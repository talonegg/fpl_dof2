"""FBref — the underlying actions FPL only publishes as a total (E5-S3, FR-02).

**What it adds, and why it is the highest-value part of this epic.** The official feed publishes
``defensive_contribution`` as a single number and the component counts only in part. Model M4 scores
a *threshold crossing*, so what it needs is the distribution of the components — tackles,
interceptions, blocks, clearances, recoveries — not their sum. This source supplies them, alongside
shot- and goal-creating actions, progressive carries and passes, and touches in the attacking
penalty area. The conformed columns are additive: nothing here replaces the official
``defensive_contribution``, which stays the highest-precedence source for the field it defines.

**As of 2026-08-15 this source yields nothing.** The site answers every request — ``robots.txt``
included — with a Cloudflare 403, so no permission can be read and nothing is fetched. That is the
adapter behaving correctly, not failing. See D-23.

**Posture (NFR-10).** Personal, non-commercial use. ``robots.txt`` is fetched and *evaluated*
before any statistics page is requested — a comment claiming compliance is not compliance — the
shared rate limiter applies, pages are cached for a week, every resource is off the fast path, and
the source declares the attribution the UI must render.

**Why not a wrapper library.** The polite-access libraries that exist do their own HTTP: their own
session, their own throttle, their own on-disk cache. That is precisely what
:mod:`fpl_dof.sources.fetch` exists to own for the whole project, and running a second, invisible
request path alongside it would break the one rate limit, the one User-Agent and the one immutable
bronze snapshot that reproducibility depends on (DP-11). The extraction that remains is a few dozen
lines against the page's own ``data-stat`` attributes, which is a smaller surface than the
dependency would have been.

**Season-to-date, not per gameweek**, for the same reason as the other scraped source: these are
running totals, conformed with ``scope="season"``, and treating one as a gameweek observation would
be look-ahead (Invariant 5).
"""

from __future__ import annotations

import urllib.robotparser
from typing import ClassVar

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.silver.tables import ADVANCED_METRICS, Table, columns_for
from fpl_dof.sources.base import (
    Conformed,
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
)
from fpl_dof.sources.errors import SourceContractError, SourceError
from fpl_dof.sources.fbref.tables import parse_table
from fpl_dof.sources.registry import register
from fpl_dof.sources.resolve import REF_COLUMNS
from fpl_dof.sources.robots import RobotsDisallowedError, check_allowed, fetch_robots

log = get_logger(__name__)

_WEEK = 7 * 24 * 3600
HTML_SUFFIX = ".html.gz"

#: Page slug -> (table id, {site column -> canonical metric}).
#: The whole mapping between this source's vocabulary and the canonical one, in one readable place.
PAGES: dict[str, tuple[str, dict[str, str]]] = {
    "stats": (
        "stats_standard",
        {
            "xg": "expected_goals",
            "npxg": "non_penalty_expected_goals",
            "xg_assist": "expected_assists",
            "games": "matches",
            "minutes": "minutes_played",
            "progressive_carries": "progressive_carries",
            "progressive_passes": "progressive_passes",
        },
    ),
    "shooting": (
        "stats_shooting",
        {"shots": "shots", "shots_on_target": "shots_on_target"},
    ),
    "gca": (
        "stats_gca",
        {"sca": "shot_creating_actions", "gca": "goal_creating_actions"},
    ),
    "defense": (
        "stats_defense",
        {
            "tackles": "tackles",
            "interceptions": "interceptions",
            "blocks": "blocks",
            "clearances": "clearances",
        },
    ),
    "passing": (
        "stats_passing",
        {"assisted_shots": "key_passes", "progressive_passes": "progressive_passes"},
    ),
    "possession": (
        "stats_possession",
        {"touches_att_pen_area": "touches_attacking_penalty_area"},
    ),
    "misc": ("stats_misc", {"ball_recoveries": "recoveries"}),
}

#: Cells every statistics row must carry for the row to mean anything.
REQUIRED_ROW_KEYS: tuple[str, ...] = ("player_id", "player", "team")

#: The site's positional shorthand. Composites like "DF,MF" are left unmapped rather than
#: arbitrated, so resolution falls back to name and club instead of trusting a coin flip.
_POSITIONS = {"GK": "GKP", "DF": "DEF", "MF": "MID", "FW": "FWD"}


@register
class FbrefAdapter(SourceAdapter):
    name: ClassVar[str] = "fbref"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "Progressive, creation, box-touch and defensive action counts"
    base_url: ClassVar[str] = "https://fbref.com"
    enabled_by_default: ClassVar[bool] = False
    essential: ClassVar[bool] = False
    attribution: ClassVar[str] = "Advanced statistics via FBref, from Opta data"
    contributes: ClassVar[tuple[str, ...]] = (
        "expected_goals",
        "non_penalty_expected_goals",
        "expected_assists",
        "shots",
        "shots_on_target",
        "key_passes",
        "shot_creating_actions",
        "goal_creating_actions",
        "progressive_carries",
        "progressive_passes",
        "touches_attacking_penalty_area",
        "tackles",
        "interceptions",
        "blocks",
        "clearances",
        "recoveries",
        "minutes_played",
        "matches",
    )
    resources: ClassVar[tuple[Resource, ...]] = (
        Resource(
            name="robots",
            summary="The site's own crawling rules, checked before anything else is requested",
            cache_ttl_seconds=_WEEK,
            fast_path=False,
        ),
        *(
            Resource(
                name=f"league_{page}",
                summary=f"Season-to-date {page} totals for every player in the competition",
                # A week. E5-S3 sets the cadence at weekly at most, and the TTL is what actually
                # enforces it — a schedule is a promise, a TTL is a mechanism.
                cache_ttl_seconds=_WEEK,
                fast_path=False,
            )
            for page in PAGES
        ),
    )

    COMPETITION_ID: ClassVar[str] = "9"
    COMPETITION_SLUG: ClassVar[str] = "Premier-League-Stats"

    # --- politeness ----------------------------------------------------------------------

    @staticmethod
    def season_slug(season: str) -> str:
        """``2026/27`` -> ``2026-2027``. The site's own season naming."""
        head, _, tail = season.partition("/")
        if not head.strip().isdigit():
            raise ValueError(f"season {season!r} is not in the expected 'YYYY/YY' form")
        start = int(head)
        end = int(f"{start // 100}{tail.strip()}") if tail.strip().isdigit() else start + 1
        return f"{start}-{end}"

    @classmethod
    def page_path(cls, season: str, page: str) -> str:
        """Where one statistics page lives. A classmethod so a test can name a URL without
        constructing an adapter — which would otherwise need a fetcher it has no use for."""
        slug = cls.season_slug(season)
        return f"en/comps/{cls.COMPETITION_ID}/{slug}/{page}/{slug}-{cls.COMPETITION_SLUG}"

    def robots(self, request: IngestRequest) -> urllib.robotparser.RobotFileParser:
        """Fetch and parse the site's crawling rules, through the shared mechanism."""
        return fetch_robots(self, request)

    # --- fetch ---------------------------------------------------------------------------

    def fetch_page(
        self,
        season: str,
        page: str,
        request: IngestRequest,
        robots: urllib.robotparser.RobotFileParser | None = None,
    ) -> list[dict[str, str]]:
        resource = self.resource(f"league_{page}")
        path = self.page_path(season, page)
        if robots is not None:
            check_allowed(self, path, robots)
        fetched = self.fetcher.fetch(
            self.url_for(path),
            source=self.name,
            source_version=self.version,
            resource=resource.name,
            key=self.season_slug(season),
            cache_ttl_seconds=resource.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            offline=request.offline,
            now=request.now,
            suffix=HTML_SUFFIX,
        )
        return self.parse_page(fetched.payload, page=page, key=self.season_slug(season))

    def parse_page(self, payload: bytes, *, page: str, key: str) -> list[dict[str, str]]:
        """Read one statistics table. Testable against a recorded page with no transport at all."""
        table_id, _ = PAGES[page]
        rows = [
            row
            for row in parse_table(payload.decode("utf-8", errors="replace"), table_id)
            if row.get("player_id")
        ]
        if not rows:
            raise SourceContractError(
                f"the {page} page carried no rows in table {table_id!r}; the layout has changed "
                "and the numbers must not be guessed at",
                source=self.name,
                resource=f"league_{page}",
                key=key,
            )
        missing = [name for name in REQUIRED_ROW_KEYS if name not in rows[0]]
        if missing:
            raise SourceContractError(
                f"the {page} table is missing required cells: {', '.join(missing)}",
                source=self.name,
                resource=f"league_{page}",
                key=key,
            )
        return rows

    # --- conform -------------------------------------------------------------------------

    def _seasons(self, request: IngestRequest) -> tuple[str, ...]:
        """The current season **and** any configured backfill.

        Costed honestly: seven pages per season, so a four-season backfill is twenty-eight requests
        against somebody else's site. They go through the shared rate limiter and the week-long TTL
        like everything else, so the backfill is paid once and then never again — a finished
        season's totals cannot change, which is precisely what makes it safe to cache hard.
        """
        return request.seasons_with_current()

    def _collect(
        self, season: str, request: IngestRequest, warnings: list[str]
    ) -> dict[str, dict[str, object]]:
        """One record per player, filled in from whichever pages could be read.

        A page that fails removes its own columns and nothing else — the shape DP-15 asks for, at
        the granularity of a single request.
        """
        collected: dict[str, dict[str, object]] = {}
        for page, (_, mapping) in PAGES.items():
            try:
                rows = self.fetch_page(season, page, request)
            except SourceError as exc:
                warnings.append(f"{season}: {page} page unavailable ({exc})")
                continue
            for row in rows:
                record = collected.setdefault(
                    row["player_id"],
                    {
                        "source_name": row.get("player", ""),
                        "source_team": row.get("team") or None,
                        "source_position": _POSITIONS.get(str(row.get("position") or "").strip()),
                    },
                )
                for cell, canonical in mapping.items():
                    value = _number(row.get(cell))
                    if value is not None:
                        record[canonical] = value
        return collected

    def conform(self, request: IngestRequest) -> Conformed:
        warnings: list[str] = []
        refs: list[pd.DataFrame] = []
        advanced: list[pd.DataFrame] = []

        for season in self._seasons(request):
            collected = self._collect(season, request, warnings)
            if not collected:
                continue
            refs.append(
                pd.DataFrame(
                    [
                        {
                            "season": season,
                            "source": self.name,
                            "source_player_id": player_id,
                            "source_name": record["source_name"],
                            "source_team": record["source_team"],
                            "source_position": record["source_position"],
                        }
                        for player_id, record in sorted(collected.items())
                    ],
                    columns=list(REF_COLUMNS),
                )
            )
            advanced.append(
                pd.DataFrame(
                    [
                        {
                            "season": season,
                            "source": self.name,
                            "source_player_id": player_id,
                            "player_id": None,
                            "player_code": None,
                            "scope": "season",
                            "gameweek": None,
                            **{metric: record.get(metric) for metric in ADVANCED_METRICS},
                        }
                        for player_id, record in sorted(collected.items())
                    ],
                    columns=columns_for(Table.PLAYER_ADVANCED),
                )
            )

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

        try:
            robots = self.robots(request)
        except SourceError as exc:
            # No rules read means no permission established. Declining to fetch is the only honest
            # response, and it degrades the run rather than failing it.
            report.warnings.append(f"robots.txt could not be read ({exc}); nothing was fetched")
            report.network_calls = self.fetcher.network_calls - before_calls
            report.cache_hits = self.fetcher.cache_hits - before_hits
            return report
        report.resources["robots"] = 1

        for season in self._seasons(request):
            for page in PAGES:
                try:
                    rows = self.fetch_page(season, page, request, robots)
                except SourceError as exc:
                    report.warnings.append(f"{season}/{page}: {exc}")
                    continue
                report.resources[f"league_{page}"] = report.resources.get(f"league_{page}", 0) + 1
                log.info("fbref.page", extra={"season": season, "page": page, "rows": len(rows)})

        report.network_calls = self.fetcher.network_calls - before_calls
        report.cache_hits = self.fetcher.cache_hits - before_hits
        return report


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except TypeError, ValueError:
        return None


__all__ = ["PAGES", "FbrefAdapter", "RobotsDisallowedError"]
