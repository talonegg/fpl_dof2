"""Prior-season per-gameweek data, from the community archive.

**Why this source exists.** The official API publishes no per-gameweek data for any prior season.
``element-summary`` returns ``history`` for the *current* season only, and ``history_past`` as
season totals. In preseason it therefore supplies zero per-gameweek observations, and E3's
backtest harness needs something to walk forward over. See DL-19.

**Licence posture, stated rather than assumed.** The archive repository declares no licence. The
underlying data is FPL's own public data, which this project already ingests directly under
NFR-10; the mirror is a convenience over it, not a new data right. Use is personal and
non-commercial, requests are cached hard, and the ingest runs once per season and is then treated
as static. If the mirror disappears the pipeline degrades to current-season data (DP-15) — the
backtest loses its evidence base, which is debt, not a crash.

**The join that would silently corrupt everything.** FPL reassigns element IDs every season. A
history table joined on ``element`` attributes one player's past to whoever inherited their number
the following year, which produces a model that is confidently wrong about exactly the players it
has most data on. ``players_raw.csv`` carries the stable ``code``, and that is the only key used
across seasons.

**Absence of measurement is preserved as null.** Defensive Contribution columns do not exist before
2025/26. They arrive here as null, never zero — zero would say the player did no defending, which
is the trap DL-18 records.

**The club join has the same shape as the player join, and used to be missing entirely.** This
adapter once wrote ``team_id: None`` on every row, which silently emptied the backtest's fixture
calendar and scored every historical observation against league-average opposition (D-26, DL-51).
The club is not absent from the archive — ``merged_gw.csv`` carries the club *name* on every row
and ``teams.csv`` carries the season's club list — it was simply never resolved.

**And the club key is the stable ``code``, for exactly DL-19's reason.** FPL renumbers teams every
season as well as players: between consecutive seasons **eight to ten of the twenty season-local
ids point at a different club**, because promotion and relegation reshuffle an alphabetical
ordering. ``team_id`` 11 is Liverpool in 2023/24, Leicester in 2024/25 and Leeds in 2025/26. Any
model that pools team form across seasons — and :class:`~fpl_dof.forecast.models.TeamStrengthModel`
does — would attribute one club's record to another. ``teams.csv`` carries FPL's own ``code``,
which is stable across every season the archive publishes, so that is what both ``team_id`` and
``opponent_team_id`` are expressed in here. The two must be in the same space or the fixture
self-join pairs a club with a stranger; relabelling both is a bijection within a season, so every
within-season consumer is unaffected.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
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
from fpl_dof.sources.errors import (
    OfflineWithoutSnapshotError,
    SourceContractError,
    SourceNotFoundError,
)
from fpl_dof.sources.registry import register

log = get_logger(__name__)

_YEAR = 365 * 24 * 3600
CSV_SUFFIX = ".csv.gz"

#: Seasons to backfill, newest last. Configuration overrides this; the default is what the mirror
#: actually carries with the columns the models need.
DEFAULT_SEASONS: tuple[str, ...] = ("2022/23", "2023/24", "2024/25", "2025/26")

#: FPL's own short position codes, as used in the canonical model. The archive writes ``GK``
#: where the API writes ``GKP``, and nothing else differs.
_POSITION_ALIASES = {"GK": "GKP", "GKP": "GKP", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}

#: Element types the *current* game has. The archive publishes no ``element_types`` table of its
#: own, so unlike the live adapter this mapping cannot be read — which is exactly why anything
#: outside it is dropped rather than guessed at. See ``_identity``.
_ELEMENT_TYPES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

#: Columns that only exist once the component they measure existed. Missing means *not measured*,
#: which is not the same as zero.
_MEASURED_LATER = (
    "defensive_contribution",
    "tackles",
    "recoveries",
    "clearances_blocks_interceptions",
    "starts",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
)

REQUIRED_GAMEWEEK_COLUMNS = (
    "GW",
    "element",
    "minutes",
    "total_points",
    "value",
    "kickoff_time",
    "was_home",
    "opponent_team",
    "fixture",
    # The club the row belongs to. Named as required rather than read opportunistically: a season
    # whose club column silently vanished would take the fixture calendar down with it and nothing
    # downstream would say so, which is precisely how D-26 survived unnoticed.
    "team",
)

#: The club list's own columns. ``code`` is the cross-season identity and is therefore as
#: load-bearing here as ``code`` is in ``players_raw.csv``.
REQUIRED_TEAM_COLUMNS = ("id", "code", "name", "short_name")


def season_slug(season: str) -> str:
    """``2025/26`` -> ``2025-26``. The archive's own directory naming."""
    return season.replace("/", "-")


def _normalise(name: str) -> str:
    """Club names are compared case- and whitespace-insensitively, and never fuzzily.

    ``merged_gw.csv`` and ``teams.csv`` come from the same upstream dump and agree exactly today.
    Normalising guards against a stray space; anything further would be entity resolution, and a
    fuzzy club match is R-10 with twenty candidates instead of six hundred.
    """
    return " ".join(name.split()).casefold()


@dataclass(frozen=True, slots=True)
class Clubs:
    """One season's clubs, keyed both ways, resolving to the stable cross-season ``code``."""

    season: str
    by_local_id: dict[int, int]
    by_name: dict[str, int]

    def code_for_local_id(self, local_id: int | None) -> int | None:
        return None if local_id is None else self.by_local_id.get(local_id)

    def code_for_name(self, name: str | None) -> int | None:
        return None if not name else self.by_name.get(_normalise(name))


@register
class ArchiveAdapter(SourceAdapter):
    name: ClassVar[str] = "fplarchive"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "Community archive of prior-season per-gameweek Fantasy data"
    base_url: ClassVar[str] = (
        "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
    )
    # Off unless asked for. It is a large, slow, once-per-season ingest, and a default-on source
    # would make every routine run pay for data that changes once a year.
    enabled_by_default: ClassVar[bool] = False
    # Losing the mirror costs the backtest its evidence base, which is debt rather than a crash —
    # exactly what the module docstring above says should happen (DP-15).
    essential: ClassVar[bool] = False
    attribution: ClassVar[str] = "Historical gameweek data via the community FPL archive"
    resources: ClassVar[tuple[Resource, ...]] = (
        Resource(
            name="merged_gameweeks",
            summary="Every player's per-gameweek record for one completed season",
            # A finished season is immutable. A year's TTL is not optimism; it is a statement that
            # re-fetching it could not produce a different answer.
            cache_ttl_seconds=_YEAR,
            fast_path=False,
        ),
        Resource(
            name="players",
            summary="Season player list, carrying the stable cross-season code",
            cache_ttl_seconds=_YEAR,
            fast_path=False,
        ),
        Resource(
            name="teams",
            summary="Season club list: the season-local id, the name, and the stable club code",
            cache_ttl_seconds=_YEAR,
            fast_path=False,
        ),
    )

    # --- fetch ---------------------------------------------------------------------------

    def _fetch_csv(
        self, resource_name: str, path: str, key: str, request: IngestRequest
    ) -> list[dict[str, str]]:
        resource = self.resource(resource_name)
        fetched = self.fetcher.fetch(
            self.url_for(path),
            source=self.name,
            source_version=self.version,
            resource=resource.name,
            key=key,
            cache_ttl_seconds=resource.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            offline=request.offline,
            now=request.now,
            suffix=CSV_SUFFIX,
        )
        try:
            text = fetched.payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SourceContractError(
                f"{self.name}/{resource.name}/{key} was not UTF-8 text",
                source=self.name,
                resource=resource.name,
                key=key,
            ) from exc
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            raise SourceContractError(
                f"{self.name}/{resource.name}/{key} contained no rows",
                source=self.name,
                resource=resource.name,
                key=key,
            )
        return rows

    def fetch_gameweeks(self, season: str, request: IngestRequest) -> list[dict[str, str]]:
        rows = self._fetch_csv(
            "merged_gameweeks",
            f"{season_slug(season)}/gws/merged_gw.csv",
            season_slug(season),
            request,
        )
        missing = [column for column in REQUIRED_GAMEWEEK_COLUMNS if column not in rows[0]]
        if missing:
            raise SourceContractError(
                f"{season} gameweek data is missing required columns: {', '.join(missing)}",
                source=self.name,
                resource="merged_gameweeks",
                key=season_slug(season),
            )
        return rows

    def fetch_players(self, season: str, request: IngestRequest) -> list[dict[str, str]]:
        rows = self._fetch_csv(
            "players",
            f"{season_slug(season)}/players_raw.csv",
            season_slug(season),
            request,
        )
        for column in ("id", "code", "element_type"):
            if column not in rows[0]:
                raise SourceContractError(
                    f"{season} player list has no {column!r} column, so cross-season identity "
                    "cannot be established and the history must not be used",
                    source=self.name,
                    resource="players",
                    key=season_slug(season),
                )
        return rows

    def fetch_teams(self, season: str, request: IngestRequest) -> list[dict[str, str]]:
        rows = self._fetch_csv(
            "teams",
            f"{season_slug(season)}/teams.csv",
            season_slug(season),
            request,
        )
        for column in REQUIRED_TEAM_COLUMNS:
            if column not in rows[0]:
                raise SourceContractError(
                    f"{season} club list has no {column!r} column, so the club a row belongs to "
                    "cannot be resolved to a cross-season identity and the fixture join would be "
                    "silently empty (D-26)",
                    source=self.name,
                    resource="teams",
                    key=season_slug(season),
                )
        return rows

    # --- conform -------------------------------------------------------------------------

    def _seasons(self, request: IngestRequest) -> tuple[str, ...]:
        return request.seasons or DEFAULT_SEASONS

    def _identity(
        self, players: list[dict[str, str]], warnings: list[str], season: str
    ) -> dict[int, tuple[int, str]]:
        """Season-local element id -> (stable code, position).

        The whole reason this source needs a second file. Without it, every cross-season join is
        wrong in a way no test on a single season can detect.

        **Element types that the current game does not have are dropped, not mapped.** 2024/25
        carried a fifth type — Managers, for the Assistant Manager chip — and 2026/27 publishes only
        four. A manager is not a footballer: they have no minutes, no goals and no position, and
        letting them into the training set would pollute every per-90 rate with rows that cannot
        mean what the column says. Mapping them onto a real position would be worse still.
        """
        mapping: dict[int, tuple[int, str]] = {}
        dropped = 0
        for row in players:
            element_type = int(row["element_type"])
            position = _ELEMENT_TYPES.get(element_type)
            if position is None:
                dropped += 1
                continue
            mapping[int(row["id"])] = (int(row["code"]), position)
        if dropped:
            warnings.append(
                f"{season}: dropped {dropped} element(s) whose type does not exist in the current "
                "game (2024/25 carried Managers as element_type 5); they are not players and must "
                "not enter a per-90 rate"
            )
        if not mapping:
            raise SourceContractError(
                f"{season} player list contains no recognised positions at all",
                source=self.name,
                resource="players",
                key=season_slug(season),
            )
        return mapping

    def _clubs(self, teams: list[dict[str, str]], warnings: list[str], season: str) -> Clubs:
        """Season-local id -> stable code, and club name -> stable code.

        Both directions are needed because the archive states the club two different ways: a row
        names *its own* club as a string and *its opponent* as a season-local integer. They must
        end up in one id space, and the only space that survives a promotion is the code.
        """
        by_local_id: dict[int, int] = {}
        by_name: dict[str, int] = {}
        for row in teams:
            local_id = _as_int(row.get("id"))
            code = _as_int(row.get("code"))
            if local_id is None or code is None:
                continue
            by_local_id[local_id] = code
            for alias in (row.get("name"), row.get("short_name")):
                if alias:
                    by_name[_normalise(alias)] = code
        if not by_local_id:
            raise SourceContractError(
                f"{season} club list resolved to no clubs at all",
                source=self.name,
                resource="teams",
                key=season_slug(season),
            )
        if len(set(by_local_id.values())) != len(by_local_id):
            # Two clubs sharing a code would merge two clubs' records into one, which is DL-19's
            # failure with twenty rows instead of six hundred.
            raise SourceContractError(
                f"{season} club list has duplicate club codes, so club identity is not unique",
                source=self.name,
                resource="teams",
                key=season_slug(season),
            )
        warnings.append(
            f"{season}: club identity resolved for {len(by_local_id)} clubs via the stable code"
        )
        return Clubs(season=season, by_local_id=by_local_id, by_name=by_name)

    def _season_frame(
        self,
        season: str,
        gameweeks: list[dict[str, str]],
        identity: dict[int, tuple[int, str]],
        clubs: Clubs | None,
        warnings: list[str],
    ) -> pd.DataFrame:
        rows = []
        unmatched = 0
        unresolved_team = 0
        unresolved_opponent = 0
        for record in gameweeks:
            element = _as_int(record.get("element"))
            if element is None:
                continue
            known = identity.get(element)
            if known is None:
                # A player in the gameweek file but not the player list. Dropped rather than
                # given a synthetic code: an invented identity is worse than a missing row,
                # because it silently merges two people.
                unmatched += 1
                continue
            code, position_from_list = known
            position = _POSITION_ALIASES.get(
                str(record.get("position") or "").upper(), position_from_list
            )
            # Unresolvable stays null rather than falling back to the season-local id. A row whose
            # club is null is dropped by the fixture calendar and is visibly absent; a row carrying
            # a season-local id in a code-keyed column is invisibly *wrong*, and would pool one
            # club's form into another's. Absence beats a plausible mistake (DP-15).
            team_code = None if clubs is None else clubs.code_for_name(record.get("team"))
            opponent_code = (
                None
                if clubs is None
                else clubs.code_for_local_id(_as_int(record.get("opponent_team")))
            )
            if clubs is not None:
                unresolved_team += team_code is None
                unresolved_opponent += opponent_code is None
            rows.append(
                {
                    "season": season,
                    "gameweek": _as_int(record.get("GW")),
                    "player_code": code,
                    "player_id": element,
                    "web_name": str(record.get("name") or ""),
                    "position": position,
                    "team_id": team_code,
                    "opponent_team_id": opponent_code,
                    "fixture_id": _as_int(record.get("fixture")),
                    "kickoff_time": record.get("kickoff_time") or None,
                    "was_home": str(record.get("was_home", "")).strip().lower() == "true",
                    "minutes": _as_int(record.get("minutes")) or 0,
                    "goals_scored": _as_int(record.get("goals_scored")) or 0,
                    "assists": _as_int(record.get("assists")) or 0,
                    "clean_sheets": _as_int(record.get("clean_sheets")) or 0,
                    "goals_conceded": _as_int(record.get("goals_conceded")) or 0,
                    "own_goals": _as_int(record.get("own_goals")) or 0,
                    "penalties_saved": _as_int(record.get("penalties_saved")) or 0,
                    "penalties_missed": _as_int(record.get("penalties_missed")) or 0,
                    "yellow_cards": _as_int(record.get("yellow_cards")) or 0,
                    "red_cards": _as_int(record.get("red_cards")) or 0,
                    "saves": _as_int(record.get("saves")) or 0,
                    "bonus": _as_int(record.get("bonus")) or 0,
                    "bps": _as_int(record.get("bps")) or 0,
                    # Null, never zero, for anything not measured in this season.
                    **{name: _optional(record.get(name)) for name in _MEASURED_LATER},
                    "price": (_as_float(record.get("value")) or 0.0) / 10.0,
                    "selected_by": _as_int(record.get("selected")),
                    "total_points": _as_int(record.get("total_points")) or 0,
                }
            )
        if unmatched:
            log.warning(
                "fplarchive.unmatched_elements",
                extra={"season": season, "rows": unmatched},
            )
        if unresolved_team or unresolved_opponent:
            # Loud, and counted. A club column that half-resolves produces a fixture calendar that
            # half-exists, and a backtest quietly measured on the other half.
            log.warning(
                "fplarchive.unresolved_clubs",
                extra={
                    "season": season,
                    "team_rows": unresolved_team,
                    "opponent_rows": unresolved_opponent,
                },
            )
            warnings.append(
                f"{season}: {unresolved_team} row(s) name a club the season's club list does not "
                f"contain and {unresolved_opponent} name an unknown opponent; their fixtures do "
                "not enter the backtest"
            )
        frame = pd.DataFrame(rows, columns=columns_for(Table.PLAYER_GAMEWEEK))
        frame["kickoff_time"] = pd.to_datetime(frame["kickoff_time"], utc=True, format="mixed")
        return frame

    def conform(self, request: IngestRequest) -> Conformed:
        warnings: list[str] = []
        frames: list[pd.DataFrame] = []

        for season in self._seasons(request):
            try:
                gameweeks = self.fetch_gameweeks(season, request)
                players = self.fetch_players(season, request)
            except SourceNotFoundError, OfflineWithoutSnapshotError:
                warnings.append(f"no archive snapshot for {season}; skipping it")
                continue
            try:
                teams = self.fetch_teams(season, request)
            except SourceNotFoundError, OfflineWithoutSnapshotError:
                # DP-15: the season's player rows are still worth having for per-90 rates. What it
                # loses is every fixture, and that is said rather than left to be inferred from a
                # backtest that quietly scores against league-average opposition (D-26).
                teams = None
                warnings.append(
                    f"{season}: no club list, so team_id and opponent_team_id stay null and this "
                    "season contributes no fixture to the backtest"
                )
            clubs = None if teams is None else self._clubs(teams, warnings, season)
            identity = self._identity(players, warnings, season)
            frames.append(self._season_frame(season, gameweeks, identity, clubs, warnings))

        if not frames:
            return Conformed(tables={}, warnings=warnings)
        return Conformed(
            tables={Table.PLAYER_GAMEWEEK.value: pd.concat(frames, ignore_index=True)},
            warnings=warnings,
        )

    # --- ingest --------------------------------------------------------------------------

    def ingest(self, request: IngestRequest) -> IngestReport:
        report = IngestReport(source=self.name)
        before_calls = self.fetcher.network_calls
        before_hits = self.fetcher.cache_hits

        seasons = 0
        clubs = 0
        for season in self._seasons(request):
            try:
                self.fetch_gameweeks(season, request)
                self.fetch_players(season, request)
            except SourceNotFoundError:
                report.warnings.append(f"archive has no data for {season}")
                continue
            except OfflineWithoutSnapshotError:
                report.warnings.append(f"no snapshot for {season}; run without --offline once")
                continue
            seasons += 1
            # Snapshotted in the same pass so an offline conform has it, but its absence costs the
            # season its fixtures rather than the season itself.
            try:
                self.fetch_teams(season, request)
            except SourceNotFoundError:
                report.warnings.append(
                    f"archive has no club list for {season}; no fixtures from it"
                )
                continue
            except OfflineWithoutSnapshotError:
                report.warnings.append(f"no club-list snapshot for {season}; no fixtures from it")
                continue
            clubs += 1

        report.resources["merged_gameweeks"] = seasons
        report.resources["players"] = seasons
        report.resources["teams"] = clubs
        report.network_calls = self.fetcher.network_calls - before_calls
        report.cache_hits = self.fetcher.cache_hits - before_hits
        log.info("fplarchive.ingest.done", extra={"seasons": seasons, "club_lists": clubs})
        return report


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except TypeError, ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _optional(value: Any) -> float | None:
    """A column that may not exist this season. Absent stays absent."""
    return _as_float(value)


__all__ = [
    "DEFAULT_SEASONS",
    "REQUIRED_TEAM_COLUMNS",
    "ArchiveAdapter",
    "Clubs",
    "season_slug",
]
