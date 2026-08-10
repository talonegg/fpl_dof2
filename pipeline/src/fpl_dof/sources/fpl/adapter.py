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

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import ApiRules, ApiScoring, ApiSquad, Position
from fpl_dof.silver.tables import Table
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

    # --- conform -------------------------------------------------------------------------

    def _position_by_element_type(self, bootstrap: dict[str, Any]) -> dict[int, str]:
        """FPL's own position codes, read from the API rather than assumed.

        The mapping 1=GKP, 2=DEF, 3=MID, 4=FWD is stable, but it is published, so there is no
        reason to encode it.
        """
        mapping = {
            int(entry["id"]): str(entry["singular_name_short"])
            for entry in bootstrap["element_types"]
        }
        unknown = set(mapping.values()) - {p.value for p in Position}
        if unknown:
            raise SourceContractError(
                f"element_types contains unrecognised position codes: {sorted(unknown)}",
                source=self.name,
                resource="bootstrap_static",
                key="all",
            )
        return mapping

    def _currency_divisor(self, bootstrap: dict[str, Any]) -> float:
        """Prices arrive in tenths. Convert once, here, and never again downstream."""
        multiplier = bootstrap["game_settings"].get("ui_currency_multiplier")
        if not multiplier:
            raise SourceContractError(
                "game_settings has no ui_currency_multiplier, so prices cannot be converted",
                source=self.name,
                resource="bootstrap_static",
                key="all",
            )
        return float(multiplier)

    def extract_rules(self, bootstrap: dict[str, Any]) -> ApiRules:
        """Read the game's own rules out of the snapshot. The basis of Invariant 2."""
        config = bootstrap.get("game_config") or {}
        scoring = config.get("scoring")
        if not scoring:
            raise SourceContractError(
                "game_config.scoring is absent; the scoring table cannot be derived and must "
                "not be guessed",
                source=self.name,
                resource="bootstrap_static",
                key="all",
            )
        settings = bootstrap["game_settings"]
        divisor = self._currency_divisor(bootstrap)
        by_position = {
            str(entry["singular_name_short"]): entry for entry in bootstrap["element_types"]
        }

        def per_position(field: str) -> dict[str, int]:
            value = scoring[field]
            if not isinstance(value, dict):
                raise SourceContractError(
                    f"scoring.{field} is not a per-position map",
                    source=self.name,
                    resource="bootstrap_static",
                    key="all",
                )
            return {str(k): int(v) for k, v in value.items()}

        api_scoring = ApiScoring(
            long_play=int(scoring["long_play"]),
            short_play=int(scoring["short_play"]),
            goals_scored=per_position("goals_scored"),
            assists=int(scoring["assists"]),
            clean_sheets=per_position("clean_sheets"),
            goals_conceded=per_position("goals_conceded"),
            saves=int(scoring["saves"]),
            penalties_saved=int(scoring["penalties_saved"]),
            penalties_missed=int(scoring["penalties_missed"]),
            yellow_cards=int(scoring["yellow_cards"]),
            red_cards=int(scoring["red_cards"]),
            own_goals=int(scoring["own_goals"]),
            defensive_contribution=per_position("defensive_contribution"),
            bonus=int(scoring["bonus"]),
        )

        api_squad = ApiSquad(
            size=int(settings["squad_squadsize"]),
            starting_size=int(settings["squad_squadplay"]),
            budget=float(settings["squad_total_spend"]) / divisor,
            club_limit=int(settings["squad_team_limit"]),
            composition={code: int(entry["squad_select"]) for code, entry in by_position.items()},
            formation_min={
                code: int(entry["squad_min_play"]) for code, entry in by_position.items()
            },
            formation_max={
                code: int(entry["squad_max_play"]) for code, entry in by_position.items()
            },
            sell_on_fee=float(settings["transfers_sell_on_fee"]),
            sell_at_purchase_price=bool(settings["element_sell_at_purchase_price"]),
        )
        return ApiRules(scoring=api_scoring, squad=api_squad)

    def _teams(self, bootstrap: dict[str, Any]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "team_id": int(team["id"]),
                    "name": str(team["name"]),
                    "short_name": str(team["short_name"]),
                    "strength_overall_home": int(team.get("strength_overall_home") or 0),
                    "strength_overall_away": int(team.get("strength_overall_away") or 0),
                }
                for team in bootstrap["teams"]
            ]
        )

    def _players(self, bootstrap: dict[str, Any]) -> pd.DataFrame:
        positions = self._position_by_element_type(bootstrap)
        divisor = self._currency_divisor(bootstrap)
        rows = []
        for element in bootstrap["elements"]:
            if element.get("removed"):
                continue
            first, second = str(element["first_name"]), str(element["second_name"])
            rows.append(
                {
                    "player_id": int(element["id"]),
                    "code": int(element["code"]),
                    "web_name": str(element["web_name"]),
                    "full_name": f"{first} {second}".strip(),
                    "position": positions[int(element["element_type"])],
                    "team_id": int(element["team"]),
                    "price": float(element["now_cost"]) / divisor,
                    "status": str(element["status"]),
                    "chance_of_playing_next_round": element.get("chance_of_playing_next_round"),
                    "selected_by_percent": float(element.get("selected_by_percent") or 0.0),
                    "news": str(element.get("news") or ""),
                }
            )
        return pd.DataFrame(rows)

    def _gameweeks(self, bootstrap: dict[str, Any]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "gameweek": int(event["id"]),
                    "name": str(event["name"]),
                    # UTC at the boundary; local time is a rendering concern only (DL-11).
                    "deadline_time": pd.Timestamp(event["deadline_time"]).tz_convert("UTC"),
                    "finished": bool(event["finished"]),
                    "is_next": bool(event["is_next"]),
                }
                for event in bootstrap["events"]
            ]
        )

    def _fixtures(self, fixtures: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for fixture in fixtures:
            kickoff = fixture.get("kickoff_time")
            rows.append(
                {
                    "fixture_id": int(fixture["id"]),
                    "gameweek": fixture.get("event"),
                    "kickoff_time": (
                        pd.Timestamp(kickoff).tz_convert("UTC") if kickoff else pd.NaT
                    ),
                    "home_team_id": int(fixture["team_h"]),
                    "away_team_id": int(fixture["team_a"]),
                    "home_difficulty": int(fixture["team_h_difficulty"]),
                    "away_difficulty": int(fixture["team_a_difficulty"]),
                    "finished": bool(fixture["finished"]),
                }
            )
        frame = pd.DataFrame(rows)
        frame["kickoff_time"] = pd.to_datetime(frame["kickoff_time"], utc=True)
        return frame

    def _season_history(
        self, bootstrap: dict[str, Any], request: IngestRequest, warnings: list[str]
    ) -> pd.DataFrame:
        rows = []
        for element in bootstrap["elements"]:
            player_id = int(element["id"])
            try:
                summary = self.fetch_element_summary(player_id, request)
            except SourceNotFoundError, OfflineWithoutSnapshotError:
                warnings.append(f"no element-summary snapshot for player {player_id}")
                continue
            for season in summary["history_past"]:
                rows.append(
                    {
                        "player_id": player_id,
                        "season_name": str(season["season_name"]),
                        "minutes": int(season["minutes"]),
                        "starts": int(season.get("starts") or 0),
                        "goals_scored": int(season["goals_scored"]),
                        "assists": int(season["assists"]),
                        "clean_sheets": int(season["clean_sheets"]),
                        "goals_conceded": int(season["goals_conceded"]),
                        "own_goals": int(season["own_goals"]),
                        "penalties_saved": int(season["penalties_saved"]),
                        "penalties_missed": int(season["penalties_missed"]),
                        "yellow_cards": int(season["yellow_cards"]),
                        "red_cards": int(season["red_cards"]),
                        "saves": int(season["saves"]),
                        "bonus": int(season["bonus"]),
                        "bps": int(season["bps"]),
                        # Zero for any season before Defensive Contribution existed. That is an
                        # absence of measurement, not an absence of defending, and the forecast
                        # must not read it as the latter — see the model card.
                        "defensive_contribution": int(season.get("defensive_contribution") or 0),
                        "tackles": int(season.get("tackles") or 0),
                        "recoveries": int(season.get("recoveries") or 0),
                        "clearances_blocks_interceptions": int(
                            season.get("clearances_blocks_interceptions") or 0
                        ),
                        "expected_goals": float(season.get("expected_goals") or 0.0),
                        "expected_assists": float(season.get("expected_assists") or 0.0),
                        "start_cost": float(season["start_cost"]),
                        "end_cost": float(season["end_cost"]),
                        "total_points": int(season["total_points"]),
                    }
                )
        frame = pd.DataFrame(rows)
        if not frame.empty:
            divisor = self._currency_divisor(bootstrap)
            frame["start_cost"] = frame["start_cost"] / divisor
            frame["end_cost"] = frame["end_cost"] / divisor
        return frame

    def conform(self, request: IngestRequest) -> Conformed:
        warnings: list[str] = []
        bootstrap = self.fetch_bootstrap(request)
        fixtures = self.fetch_fixtures(request)

        snapshot = self.fetcher.bronze.latest(self.name, "bootstrap_static", "all")
        return Conformed(
            tables={
                Table.PLAYER.value: self._players(bootstrap),
                Table.TEAM.value: self._teams(bootstrap),
                Table.FIXTURE.value: self._fixtures(fixtures),
                Table.GAMEWEEK.value: self._gameweeks(bootstrap),
                Table.PLAYER_SEASON_HISTORY.value: self._season_history(
                    bootstrap, request, warnings
                ),
            },
            rules=self.extract_rules(bootstrap),
            rules_snapshot_sha256=snapshot.meta.sha256 if snapshot else None,
            warnings=warnings,
        )

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
