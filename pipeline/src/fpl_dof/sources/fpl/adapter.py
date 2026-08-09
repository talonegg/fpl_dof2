"""The official Fantasy Premier League API.

Public endpoints only. There is no authentication in this project and there never will be
(NFR-11, Invariant 4).

Three resources:

``bootstrap_static``
    Players, teams, gameweeks, chips, and — importantly — ``game_settings`` and ``game_config``,
    which carry FPL's own squad rules and the complete scoring table. Those are the seed for the
    rules module, which is how Invariant 2 is satisfied rather than merely asserted.

``fixtures``
    All 380 fixtures with per-side difficulty ratings. In preseason the team ``strength_attack_*``
    and ``strength_defence_*`` fields are all zero, so fixture difficulty must come from the
    fixture's own ``team_h_difficulty`` / ``team_a_difficulty``, not from team strength.

``element_summary``
    Per-player. ``history_past`` carries season totals for every prior season the player has PL
    history for — including ``defensive_contribution``, ``tackles``, ``recoveries``,
    ``clearances_blocks_interceptions`` and ``starts``. This is the whole evidence base for the
    cold-start model, and it is ~570 requests, so it never runs on the fast path
    (Architecture §9).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from fpl_dof.obs.logging import get_logger
from fpl_dof.sources.base import IngestReport, IngestRequest, Resource, SourceAdapter
from fpl_dof.sources.errors import SourceContractError, SourceNotFoundError
from fpl_dof.sources.registry import register

log = get_logger(__name__)

_HOUR = 3600
_WEEK = 7 * 24 * _HOUR

#: Fields downstream code depends on. Their absence is a contract breach, not a missing value.
REQUIRED_BOOTSTRAP_KEYS = ("elements", "teams", "element_types", "events", "game_settings")
REQUIRED_ELEMENT_KEYS = ("id", "element_type", "team", "now_cost", "web_name", "status")
REQUIRED_HISTORY_PAST_KEYS = (
    "season_name",
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "starts",
    "defensive_contribution",
)


@register
class FplApiAdapter(SourceAdapter):
    name: ClassVar[str] = "fpl"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "Official Fantasy Premier League public API"
    base_url: ClassVar[str] = "https://fantasy.premierleague.com/api"
    resources: ClassVar[tuple[Resource, ...]] = (
        Resource(
            name="bootstrap_static",
            summary="Players, teams, gameweeks, chips, game settings and the scoring table",
            cache_ttl_seconds=_HOUR,
            fast_path=True,
        ),
        Resource(
            name="fixtures",
            summary="All fixtures with per-side difficulty",
            cache_ttl_seconds=_HOUR,
            fast_path=True,
        ),
        Resource(
            name="element_summary",
            summary="Per-player prior-season totals and upcoming fixtures",
            # history_past is immutable for the season, so a long TTL costs nothing and saves
            # ~570 requests on every re-run.
            cache_ttl_seconds=_WEEK,
            fast_path=False,
        ),
    )

    # --- fetch helpers -------------------------------------------------------------------

    def _json(self, payload: bytes, *, resource: str, key: str) -> Any:
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SourceContractError(
                f"{self.name}/{resource}/{key} was not valid JSON: {exc}",
                source=self.name,
                resource=resource,
                key=key,
            ) from exc

    def fetch_bootstrap(self, request: IngestRequest) -> dict[str, Any]:
        resource = self.resource("bootstrap_static")
        fetched = self.fetcher.fetch(
            self.url_for("bootstrap-static/"),
            source=self.name,
            source_version=self.version,
            resource=resource.name,
            key="all",
            cache_ttl_seconds=resource.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            offline=request.offline,
            now=request.now,
        )
        data = self._json(fetched.payload, resource=resource.name, key="all")
        if not isinstance(data, dict):
            raise SourceContractError(
                "bootstrap-static did not return an object",
                source=self.name,
                resource=resource.name,
                key="all",
            )
        missing = [key for key in REQUIRED_BOOTSTRAP_KEYS if key not in data]
        if missing:
            raise SourceContractError(
                f"bootstrap-static is missing required keys: {', '.join(missing)}",
                source=self.name,
                resource=resource.name,
                key="all",
            )
        elements = data["elements"]
        if not isinstance(elements, list) or not elements:
            raise SourceContractError(
                "bootstrap-static returned no elements",
                source=self.name,
                resource=resource.name,
                key="all",
            )
        element_missing = [key for key in REQUIRED_ELEMENT_KEYS if key not in elements[0]]
        if element_missing:
            raise SourceContractError(
                f"element records are missing required keys: {', '.join(element_missing)}",
                source=self.name,
                resource=resource.name,
                key="all",
            )
        return data

    def fetch_fixtures(self, request: IngestRequest) -> list[dict[str, Any]]:
        resource = self.resource("fixtures")
        fetched = self.fetcher.fetch(
            self.url_for("fixtures/"),
            source=self.name,
            source_version=self.version,
            resource=resource.name,
            key="all",
            cache_ttl_seconds=resource.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            offline=request.offline,
            now=request.now,
        )
        data = self._json(fetched.payload, resource=resource.name, key="all")
        if not isinstance(data, list):
            raise SourceContractError(
                "fixtures did not return a list",
                source=self.name,
                resource=resource.name,
                key="all",
            )
        return data

    def fetch_element_summary(self, element_id: int, request: IngestRequest) -> dict[str, Any]:
        resource = self.resource("element_summary")
        fetched = self.fetcher.fetch(
            self.url_for(f"element-summary/{element_id}/"),
            source=self.name,
            source_version=self.version,
            resource=resource.name,
            key=str(element_id),
            cache_ttl_seconds=resource.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            offline=request.offline,
            now=request.now,
        )
        data = self._json(fetched.payload, resource=resource.name, key=str(element_id))
        if not isinstance(data, dict) or "history_past" not in data:
            raise SourceContractError(
                f"element-summary/{element_id} has no history_past",
                source=self.name,
                resource=resource.name,
                key=str(element_id),
            )
        return data

    # --- ingest --------------------------------------------------------------------------

    def ingest(self, request: IngestRequest) -> IngestReport:
        report = IngestReport(source=self.name)
        before_calls = self.fetcher.network_calls
        before_hits = self.fetcher.cache_hits

        bootstrap = self.fetch_bootstrap(request)
        report.resources["bootstrap_static"] = 1

        fixtures = self.fetch_fixtures(request)
        report.resources["fixtures"] = 1
        log.info("fpl.fixtures", extra={"count": len(fixtures)})

        element_ids = [int(element["id"]) for element in bootstrap["elements"]]
        if request.player_limit is not None:
            element_ids = element_ids[: request.player_limit]
            report.warnings.append(
                f"player_limit={request.player_limit} applied; this is a development setting "
                "and must not be used for a real run"
            )

        log.info("fpl.element_summary.start", extra={"players": len(element_ids)})
        fetched = 0
        checked_contract = False
        for element_id in element_ids:
            try:
                summary = self.fetch_element_summary(element_id, request)
            except SourceNotFoundError:
                # A removed player. Recoverable: the squad model simply will not see them.
                report.warnings.append(f"element-summary/{element_id} returned 404")
                continue
            fetched += 1
            if not checked_contract and summary["history_past"]:
                missing = [
                    key
                    for key in REQUIRED_HISTORY_PAST_KEYS
                    if key not in summary["history_past"][0]
                ]
                if missing:
                    raise SourceContractError(
                        f"history_past is missing required keys: {', '.join(missing)}",
                        source=self.name,
                        resource="element_summary",
                        key=str(element_id),
                    )
                checked_contract = True

        report.resources["element_summary"] = fetched
        report.network_calls = self.fetcher.network_calls - before_calls
        report.cache_hits = self.fetcher.cache_hits - before_hits
        log.info(
            "fpl.ingest.done",
            extra={
                "players": fetched,
                "network_calls": report.network_calls,
                "cache_hits": report.cache_hits,
            },
        )
        return report
