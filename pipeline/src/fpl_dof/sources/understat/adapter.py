"""Understat — expected goals from a shot-level model (E5-S2, FR-02).

**What it adds.** xG, non-penalty xG, xA, shots and key passes per player, from a model fitted on
shot locations rather than on outcomes. The official feed publishes expected goals too, but
Understat's is the longer-running series and is the one most public analysis is calibrated against,
which matters when a number has to be arguable (DP-10).

**Why extraction is brittle, and what is done about it.** This is not an API. The league page ships
its data as a JSON literal inside an inline ``<script>``, escaped byte by byte. A layout change
breaks extraction (R-06), so: the shape is contract-tested against a recorded page, the failure
mode is a source warning rather than a crash (DP-15), and the TTL is long because a season total
that moved by one shot is not worth a second request.

**Posture.** Personal, non-commercial use. One request per season per run, through the shared
:class:`~fpl_dof.sources.fetch.Fetcher` so the project's single rate limit and User-Agent apply,
cached hard, off the fast path, and credited in the published attribution (NFR-10).

**Season-to-date, not per gameweek.** The league page carries running totals. They are conformed
with ``scope="season"`` and no gameweek, because labelling a running total as a gameweek
observation would leak the rest of the season into every backtest before it (Invariant 5). Rates
derived from it are only ever knowable at the moment it was captured.
"""

from __future__ import annotations

import codecs
import json
import re
from typing import Any, ClassVar

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.silver.tables import Table, columns_for
from fpl_dof.sources.base import (
    Conformed,
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
)
from fpl_dof.sources.errors import SourceContractError, SourceError
from fpl_dof.sources.registry import register
from fpl_dof.sources.resolve import REF_COLUMNS

log = get_logger(__name__)

_DAY = 24 * 3600
HTML_SUFFIX = ".html.gz"

#: The inline script assignment the page's data lives in. Anchored on the variable name rather than
#: on position, because the page's ordering is the part most likely to change.
_PLAYERS_SCRIPT = re.compile(
    r"var\s+playersData\s*=\s*JSON\.parse\(\s*'(?P<payload>.*?)'\s*\)\s*;",
    re.DOTALL,
)

#: Keys downstream conformance depends on. Their absence is a contract breach, not a missing value.
REQUIRED_PLAYER_KEYS: tuple[str, ...] = (
    "id",
    "player_name",
    "team_title",
    "time",
    "games",
    "xG",
    "npxG",
    "xA",
    "shots",
    "key_passes",
)

#: Understat's positional shorthand, mapped onto the game's four codes. Anything else — and the
#: page carries composites like "D M S" for a player who has filled several roles — resolves to
#: nothing, and resolution then matches on name and club alone rather than on a guess.
_POSITIONS = {"GK": "GKP", "D": "DEF", "M": "MID", "F": "FWD", "S": "FWD", "AM": "MID", "DM": "MID"}


@register
class UnderstatAdapter(SourceAdapter):
    name: ClassVar[str] = "understat"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "Shot-model expected goals and assists, per player and season"
    base_url: ClassVar[str] = "https://understat.com"
    # Off unless asked for. A scraped source should be a deliberate choice in configuration, not
    # something a fresh clone starts doing to somebody else's website by default.
    enabled_by_default: ClassVar[bool] = False
    essential: ClassVar[bool] = False
    attribution: ClassVar[str] = "Expected-goals data via Understat"
    contributes: ClassVar[tuple[str, ...]] = (
        "expected_goals",
        "non_penalty_expected_goals",
        "expected_assists",
        "shots",
        "key_passes",
        "minutes_played",
        "matches",
    )
    resources: ClassVar[tuple[Resource, ...]] = (
        Resource(
            name="league_players",
            summary="Season-to-date expected goals for every player in the competition",
            # A day. The underlying model is refitted after matches, not continuously, and this is
            # somebody else's website being read for personal use.
            cache_ttl_seconds=_DAY,
            fast_path=False,
        ),
    )

    #: The competition slug. Configuration would be misleading — nothing else in this project has
    #: any use for another league's data.
    LEAGUE: ClassVar[str] = "EPL"

    # --- fetch ---------------------------------------------------------------------------

    @staticmethod
    def season_year(season: str) -> str:
        """``2026/27`` -> ``2026``. Understat labels a season by the year it starts."""
        head = season.split("/")[0].strip()
        if not head.isdigit():
            raise ValueError(f"season {season!r} is not in the expected 'YYYY/YY' form")
        return head

    def fetch_players(self, season: str, request: IngestRequest) -> list[dict[str, Any]]:
        resource = self.resource("league_players")
        year = self.season_year(season)
        fetched = self.fetcher.fetch(
            self.url_for(f"league/{self.LEAGUE}/{year}"),
            source=self.name,
            source_version=self.version,
            resource=resource.name,
            key=year,
            cache_ttl_seconds=resource.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            offline=request.offline,
            now=request.now,
            suffix=HTML_SUFFIX,
        )
        return self.parse_players(fetched.payload, key=year)

    def parse_players(self, payload: bytes, *, key: str) -> list[dict[str, Any]]:
        """Pull the embedded JSON out of the page.

        Separated from fetching so the fragile half is testable against a recorded page without any
        transport involved — which is the only way a scraper's breakage shows up in CI rather than
        at a deadline.
        """
        text = payload.decode("utf-8", errors="replace")
        match = _PLAYERS_SCRIPT.search(text)
        if match is None:
            raise SourceContractError(
                "the league page no longer carries a playersData script; extraction has broken "
                "and the numbers must not be guessed at",
                source=self.name,
                resource="league_players",
                key=key,
            )
        try:
            data = json.loads(_unescape(match.group("payload")))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceContractError(
                f"the embedded playersData was not decodable JSON: {exc}",
                source=self.name,
                resource="league_players",
                key=key,
            ) from exc
        if not isinstance(data, list) or not data:
            raise SourceContractError(
                "the embedded playersData held no players",
                source=self.name,
                resource="league_players",
                key=key,
            )
        missing = [name for name in REQUIRED_PLAYER_KEYS if name not in data[0]]
        if missing:
            raise SourceContractError(
                f"playersData is missing required keys: {', '.join(missing)}",
                source=self.name,
                resource="league_players",
                key=key,
            )
        return [record for record in data if isinstance(record, dict)]

    # --- conform -------------------------------------------------------------------------

    def _seasons(self, request: IngestRequest) -> tuple[str, ...]:
        """The current season **and** any configured backfill.

        The league page is one request per season and the URL is season-shaped, so a historical
        season costs exactly one more page — which is why a backfill here is polite in a way the
        page-per-statistic sources are not.
        """
        return request.seasons_with_current()

    def _refs(self, season: str, players: list[dict[str, Any]]) -> pd.DataFrame:
        rows = [
            {
                "season": season,
                "source": self.name,
                "source_player_id": str(record["id"]),
                "source_name": str(record["player_name"]),
                "source_team": _first_team(str(record.get("team_title") or "")),
                "source_position": _POSITIONS.get(str(record.get("position") or "").strip()),
            }
            for record in players
        ]
        return pd.DataFrame(rows, columns=list(REF_COLUMNS))

    def _advanced(self, season: str, players: list[dict[str, Any]]) -> pd.DataFrame:
        rows = [
            {
                "season": season,
                "source": self.name,
                "source_player_id": str(record["id"]),
                "player_id": None,
                "player_code": None,
                "scope": "season",
                "gameweek": None,
                "minutes_played": _number(record.get("time")),
                "matches": _number(record.get("games")),
                "expected_goals": _number(record.get("xG")),
                "non_penalty_expected_goals": _number(record.get("npxG")),
                "expected_assists": _number(record.get("xA")),
                "shots": _number(record.get("shots")),
                "shots_on_target": None,
                "key_passes": _number(record.get("key_passes")),
                "shot_creating_actions": None,
                "goal_creating_actions": None,
                "progressive_carries": None,
                "progressive_passes": None,
                "touches_attacking_penalty_area": None,
                "tackles": None,
                "interceptions": None,
                "blocks": None,
                "clearances": None,
                "recoveries": None,
            }
            for record in players
        ]
        return pd.DataFrame(rows, columns=columns_for(Table.PLAYER_ADVANCED))

    def conform(self, request: IngestRequest) -> Conformed:
        warnings: list[str] = []
        refs: list[pd.DataFrame] = []
        advanced: list[pd.DataFrame] = []

        for season in self._seasons(request):
            try:
                players = self.fetch_players(season, request)
            except SourceError as exc:
                warnings.append(f"no usable page for {season}: {exc}")
                continue
            refs.append(self._refs(season, players))
            advanced.append(self._advanced(season, players))

        if not refs:
            return Conformed(tables={}, warnings=warnings)
        return Conformed(
            tables={
                Table.PLAYER_CROSSWALK.value: pd.concat(refs, ignore_index=True),
                Table.PLAYER_ADVANCED.value: pd.concat(advanced, ignore_index=True),
            },
            warnings=warnings,
        )

    # --- ingest --------------------------------------------------------------------------

    def ingest(self, request: IngestRequest) -> IngestReport:
        report = IngestReport(source=self.name)
        before_calls = self.fetcher.network_calls
        before_hits = self.fetcher.cache_hits

        fetched = 0
        for season in self._seasons(request):
            try:
                players = self.fetch_players(season, request)
            except SourceError as exc:
                report.warnings.append(f"{season}: {exc}")
                continue
            fetched += 1
            log.info("understat.players", extra={"season": season, "count": len(players)})

        report.resources["league_players"] = fetched
        report.network_calls = self.fetcher.network_calls - before_calls
        report.cache_hits = self.fetcher.cache_hits - before_hits
        return report


def _unescape(payload: str) -> str:
    """Undo the page's ``\\xNN`` byte escaping.

    The escapes are UTF-8 *bytes*, not code points, so the round trip has to go back through
    latin-1 to recover them. Skipping that step silently mangles every accented name — and an
    accented name that does not match is an unmatched player, which is the thing this project is
    most careful about.
    """
    decoded = codecs.decode(payload, "unicode_escape")
    return decoded.encode("latin-1", errors="replace").decode("utf-8", errors="replace")


def _first_team(value: str) -> str | None:
    """A mid-season transfer leaves two clubs in one field. The last is the current one."""
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts[-1] if parts else None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


__all__ = ["REQUIRED_PLAYER_KEYS", "UnderstatAdapter"]
