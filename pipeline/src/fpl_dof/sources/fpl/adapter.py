"""The official Fantasy Premier League API.

Public endpoints only. There is no authentication in this project and there never will be
(NFR-11, Invariant 4).

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
    (Architecture §9). ``history`` carries the current season per gameweek and is empty until the
    season starts. No prior season is available at that granularity from this source at all —
    see DL-19.

``event_live``, ``set_piece_notes``, ``league_standings``
    Added in E2-S1. All three are empty or trivial in preseason, which is normal.

``entry``, ``entry_history``, ``entry_picks``, ``entry_transfers``
    The owner's own team, fetched only when a team ID is configured. Public endpoints, like
    everything else here — the authenticated ``my-team`` endpoint carries purchase prices and is
    deliberately not used (Invariant 4), so purchase prices are reconstructed instead.

**Two paths in this file are not where the catalogue said they were.** Set-piece notes live at
``team/set-piece-notes/``; a bare ``set-piece-notes/`` returns 404. ``element-status/`` no longer
exists at all.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, ClassVar, cast

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.rules.models import ApiRules, ApiScoring, ApiSquad, Position
from fpl_dof.silver.tables import Table, columns_for
from fpl_dof.sources.base import (
    Conformed,
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
    Window,
)
from fpl_dof.sources.errors import (
    OfflineWithoutSnapshotError,
    SourceContractError,
    SourceError,
    SourceNotFoundError,
)
from fpl_dof.sources.registry import register
from fpl_dof.sources.replay import extract_price_history_rows

log = get_logger(__name__)

_HOUR = 3600
_WEEK = 7 * 24 * _HOUR

#: Fields downstream code depends on. Their absence is a contract breach, not a missing value.
REQUIRED_BOOTSTRAP_KEYS = ("elements", "teams", "element_types", "events", "game_settings")
REQUIRED_ELEMENT_KEYS = ("id", "element_type", "team", "now_cost", "web_name", "status")
REQUIRED_FIXTURE_KEYS = (
    "id",
    "team_h",
    "team_a",
    "team_h_difficulty",
    "team_a_difficulty",
    "finished",
)
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


def _standings_results(standings: dict[str, Any]) -> list[dict[str, Any]]:
    """The first page of a classic league's table, in the order the API returned it.

    **One page only, deliberately.** The endpoint paginates at 50 and this project reads the top of
    the table, not the whole of it; following `has_next` would turn a configured league into an
    unbounded crawl of a stranger's server for rows nothing renders.
    """
    results = (standings.get("standings") or {}).get("results")
    return [result for result in results if isinstance(result, dict)] if results else []


def _league_entry_ids(standings: dict[str, Any], limit: int) -> list[int]:
    """Entry IDs to fetch squads for: the top `limit` of the table, best rank first."""
    if limit <= 0:
        return []
    ordered = sorted(
        (r for r in _standings_results(standings) if r.get("entry") and r.get("rank")),
        key=lambda r: int(r["rank"]),
    )
    return [int(result["entry"]) for result in ordered[:limit]]


def _latest_finished_gameweek(bootstrap: dict[str, Any]) -> int | None:
    """The most recent gameweek with a final score, or None when none has been played.

    None is the normal preseason state, not an error (DL-20): before GW1 there are no picks to read
    for anybody, so there is nothing a caller could usefully do with a number here.
    """
    finished = [int(event["id"]) for event in bootstrap["events"] if event.get("finished")]
    return max(finished) if finished else None


def _latest_checked_gameweek(bootstrap: dict[str, Any]) -> int | None:
    """The most recent gameweek FPL has finished *and* checked: its per-player rows are final."""
    checked = [
        int(event["id"])
        for event in bootstrap["events"]
        if event.get("finished") and event.get("data_checked")
    ]
    return max(checked) if checked else None


@register
class FplApiAdapter(SourceAdapter):
    name: ClassVar[str] = "fpl"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "Official Fantasy Premier League public API"
    health_label: ClassVar[str] = "Official FPL data"
    health_description: ClassVar[str] = (
        "Player, team and gameweek data from the official Fantasy Premier League game. It's the "
        "core feed that everything else builds on."
    )
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
            summary="Per-player prior-season totals, this season's gameweeks and upcoming fixtures",
            # history_past is fixed for the season, but `history` gains a row per player every
            # gameweek and is where player_gameweek comes from. So the week-long TTL (~670
            # requests a sweep) holds only until a gameweek is checked: ingest then treats every
            # summary fetched before that as stale (`_summaries_stale_before`).
            cache_ttl_seconds=_WEEK,
            fast_path=False,
        ),
        Resource(
            name="event_live",
            summary="Per-gameweek actuals for every player, including BPS",
            # A finished gameweek never changes. An in-progress one changes constantly, which the
            # fetcher handles by TTL rather than by the adapter guessing which state it is in.
            cache_ttl_seconds=_HOUR,
            fast_path=False,
        ),
        Resource(
            name="set_piece_notes",
            summary="Editorial notes on penalty, free-kick and corner takers, per club",
            cache_ttl_seconds=6 * _HOUR,
            fast_path=True,
        ),
        Resource(
            name="league_standings",
            summary="Classic league standings, for rival analysis",
            cache_ttl_seconds=_HOUR,
            fast_path=False,
        ),
        Resource(
            name="entry",
            summary="The owner's team: bank, value, chips and league memberships",
            cache_ttl_seconds=_HOUR,
            fast_path=True,
        ),
        Resource(
            name="entry_history",
            summary="The owner's per-gameweek history and chips played",
            cache_ttl_seconds=_HOUR,
            fast_path=True,
        ),
        Resource(
            name="entry_picks",
            summary="The owner's picks for a finished gameweek, with purchase and selling prices",
            cache_ttl_seconds=_HOUR,
            fast_path=True,
        ),
        Resource(
            name="entry_transfers",
            summary="Every transfer the owner has made, with the prices they were made at",
            cache_ttl_seconds=_HOUR,
            fast_path=True,
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

    def _drift(
        self, what: str, required: tuple[str, ...], record: dict[str, Any], resource: str
    ) -> None:
        """Raise when ``record`` lacks a required key: a contract breach, not a missing value."""
        if not isinstance(record, dict):
            raise SourceContractError(
                f"{what} carried a record that is not an object",
                source=self.name,
                resource=resource,
                key="all",
            )
        missing = [key for key in required if key not in record]
        if not missing:
            return
        diff = {"missing": missing, "received": sorted(record.keys())}
        log.error("ingest.schema_drift", extra={"source": self.name, "resource": resource, **diff})
        raise SourceContractError(
            f"{what} schema drift; missing required keys: {', '.join(missing)}",
            source=self.name,
            resource=resource,
            key="all",
            expected=list(required),
            received=list(record.keys()),
            diff=diff,
        )

    #: The one key each smaller resource's payload must carry, and the type it must be.
    _SHAPES: ClassVar[dict[str, tuple[type, str | None]]] = {
        "element_summary": (dict, "history_past"),
        "event_live": (dict, "elements"),
        "set_piece_notes": (dict, "teams"),
        "league_standings": (dict, "standings"),
        "entry": (dict, "id"),
        "entry_history": (dict, "chips"),
        "entry_picks": (dict, "picks"),
        "entry_transfers": (list, None),
    }

    def check(self, resource: str, key: str, payload: bytes) -> None:
        self._parse(resource, key, payload)

    watched: ClassVar[tuple[tuple[str, str], ...]] = (
        ("bootstrap_static", "all"),
        ("fixtures", "all"),
    )

    def changes(self, resource: str, before: bytes, after: bytes, window: Window) -> set[str]:
        """Prices, status or news per player; kick-off or gameweek per fixture (ORC-02). A player
        or fixture in only one capture is not a change of either."""
        old, new = json.loads(before), json.loads(after)
        if resource == "fixtures":
            was = {f["id"]: (f.get("kickoff_time"), f.get("event")) for f in old}
            now = {f["id"]: (f.get("kickoff_time"), f.get("event")) for f in new}
            return {"fixtures"} if any(was.get(i, at) != at for i, at in now.items()) else set()
        kinds: set[str] = set()
        players = {e["id"]: e for e in old["elements"]}
        for element in new["elements"]:
            prior = players.get(element["id"])
            if prior is None:
                continue
            if prior.get("now_cost") != element.get("now_cost"):
                kinds.add("prices")
            if (prior.get("status"), prior.get("news")) != (
                element.get("status"),
                element.get("news"),
            ):
                kinds.add("status")
        return kinds

    def _parse(self, resource: str, key: str, payload: bytes) -> Any:
        """Decode one capture and check it against this source's contract (ORC-10).

        The same check whether the capture was just fetched or read back from bronze, so a
        capture that ingest kept is one conformance can read. Every record of a list is checked,
        not the first: one malformed row makes the whole capture malformed (DL-94).
        """
        data = self._json(payload, resource=resource, key=key)
        if resource == "bootstrap_static":
            if not isinstance(data, dict):
                raise SourceContractError(
                    "bootstrap-static did not return an object",
                    source=self.name,
                    resource=resource,
                    key=key,
                )
            self._drift("bootstrap-static", REQUIRED_BOOTSTRAP_KEYS, data, resource)
            elements = data["elements"]
            if not isinstance(elements, list) or not elements:
                raise SourceContractError(
                    "bootstrap-static returned no elements",
                    source=self.name,
                    resource=resource,
                    key=key,
                )
            for element in elements:
                self._drift("element records", REQUIRED_ELEMENT_KEYS, element, resource)
        elif resource == "fixtures":
            if not isinstance(data, list):
                raise SourceContractError(
                    "fixtures did not return a list",
                    source=self.name,
                    resource=resource,
                    key=key,
                )
            for fixture in data:
                self._drift("fixtures", REQUIRED_FIXTURE_KEYS, fixture, resource)
        elif resource in self._SHAPES:
            kind, required = self._SHAPES[resource]
            if not isinstance(data, kind) or (
                required is not None and required not in cast(dict[str, Any], data)
            ):
                expected = f"a {kind.__name__}" + (f" with a {required} key" if required else "")
                raise SourceContractError(
                    f"{resource}/{key} is not {expected}",
                    source=self.name,
                    resource=resource,
                    key=key,
                )
        return data

    def _fetch_resource(
        self,
        resource_name: str,
        path: str,
        key: str,
        request: IngestRequest,
        *,
        stale_before: dt.datetime | None = None,
    ) -> Any:
        """Fetch, snapshot and parse one resource, checked against its contract (:meth:`_parse`).

        Only the shape is checked here. Every endpoint added in E2-S1 is optional in a way the
        original three are not: a gameweek that has not been played, a club with no set-piece
        notes and a team ID that is not configured are all normal, so whether emptiness is
        expected is decided at conformance.
        """
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
            stale_before=stale_before,
        )
        return self._parse(resource.name, key, fetched.payload)

    def fetch_bootstrap(self, request: IngestRequest) -> dict[str, Any]:
        data: dict[str, Any] = self._fetch_resource(
            "bootstrap_static", "bootstrap-static/", "all", request
        )
        return data

    def fetch_fixtures(self, request: IngestRequest) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = self._fetch_resource("fixtures", "fixtures/", "all", request)
        return data

    def fetch_element_summary(
        self,
        element_id: int,
        request: IngestRequest,
        *,
        stale_before: dt.datetime | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = self._fetch_resource(
            "element_summary",
            f"element-summary/{element_id}/",
            str(element_id),
            request,
            stale_before=stale_before,
        )
        return data

    def _summaries_stale_before(
        self, bootstrap: dict[str, Any], request: IngestRequest
    ) -> dt.datetime | None:
        """When bronze first saw the latest checked gameweek as checked, or None.

        An element-summary fetched before then lacks that gameweek's final rows, however young it
        is. FPL publishes no finish time, so the moment is the fetch time of the oldest bootstrap
        snapshot still showing it checked — never file mtime, which CI's restore resets (F2). The
        walk stops a TTL back: a summary older than that is refetched anyway.
        """
        latest = _latest_checked_gameweek(bootstrap)
        if latest is None:
            return None
        moment = request.now or utcnow()
        ttl = self.resource("element_summary").cache_ttl_seconds or _WEEK
        horizon = moment - dt.timedelta(seconds=ttl)
        bronze = self.fetcher.bronze
        seen: dt.datetime | None = None
        snapshot = bronze.latest(self.name, "bootstrap_static", "all", as_of=moment)
        while snapshot is not None:
            if snapshot.meta.fetched_at < horizon:
                return None  # checked before any cached summary could have been fetched
            then = self._json(snapshot.read_bytes(), resource="bootstrap_static", key="all")
            if (_latest_checked_gameweek(then) or 0) < latest:
                break
            seen = snapshot.meta.fetched_at
            snapshot = bronze.latest(
                self.name, "bootstrap_static", "all", as_of=seen - dt.timedelta(microseconds=1)
            )
        return seen

    def fetch_event_live(self, gameweek: int, request: IngestRequest) -> dict[str, Any]:
        data: dict[str, Any] = self._fetch_resource(
            "event_live", f"event/{gameweek}/live/", str(gameweek), request
        )
        return data

    def fetch_set_piece_notes(self, request: IngestRequest) -> dict[str, Any]:
        # The path is `team/set-piece-notes/`. A bare `set-piece-notes/` returns 404 — it is the
        # path the endpoint catalogue carried, and it has moved.
        data: dict[str, Any] = self._fetch_resource(
            "set_piece_notes", "team/set-piece-notes/", "all", request
        )
        return data

    def fetch_league_standings(self, league_id: int, request: IngestRequest) -> dict[str, Any]:
        data: dict[str, Any] = self._fetch_resource(
            "league_standings", f"leagues-classic/{league_id}/standings/", str(league_id), request
        )
        return data

    def fetch_entry(self, entry_id: int, request: IngestRequest) -> dict[str, Any]:
        data: dict[str, Any] = self._fetch_resource(
            "entry", f"entry/{entry_id}/", str(entry_id), request
        )
        return data

    def fetch_entry_history(self, entry_id: int, request: IngestRequest) -> dict[str, Any]:
        data: dict[str, Any] = self._fetch_resource(
            "entry_history", f"entry/{entry_id}/history/", str(entry_id), request
        )
        return data

    def fetch_entry_picks(
        self, entry_id: int, gameweek: int, request: IngestRequest
    ) -> dict[str, Any] | None:
        """``None`` when the gameweek has no picks yet.

        Before a gameweek's deadline passes the endpoint 404s, which is the normal state of the
        world for most of the week and is not an error (DL-20).
        """
        try:
            data: dict[str, Any] = self._fetch_resource(
                "entry_picks",
                f"entry/{entry_id}/event/{gameweek}/picks/",
                f"{entry_id}-{gameweek}",
                request,
            )
        except SourceNotFoundError:
            return None
        return data

    def fetch_entry_transfers(self, entry_id: int, request: IngestRequest) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = self._fetch_resource(
            "entry_transfers", f"entry/{entry_id}/transfers/", str(entry_id), request
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
                    "code": int(team["code"]),
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
                    "data_checked": bool(event.get("data_checked", False)),
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

    def _chips(self, bootstrap: dict[str, Any]) -> pd.DataFrame:
        """Chip windows as published. The GW19 expiry is read, not written down (Invariant 2)."""
        return pd.DataFrame(
            [
                {
                    "chip_id": int(chip["id"]),
                    "name": str(chip["name"]),
                    "chip_type": str(chip.get("chip_type") or "unknown"),
                    "start_event": int(chip["start_event"]),
                    "stop_event": int(chip["stop_event"]),
                }
                for chip in bootstrap.get("chips") or []
            ],
            columns=["chip_id", "name", "chip_type", "start_event", "stop_event"],
        )

    def _set_piece_notes(self, payload: dict[str, Any]) -> pd.DataFrame:
        rows = [
            {
                "team_id": int(team["id"]),
                "info_message": str(note.get("info_message") or ""),
                "source_link": str(note.get("source_link") or ""),
                "external_link": bool(note.get("external_link")),
            }
            for team in payload.get("teams") or []
            for note in team.get("notes") or []
        ]
        return pd.DataFrame(
            rows, columns=["team_id", "info_message", "source_link", "external_link"]
        )

    def _price_history(self, bootstrap: dict[str, Any], now: pd.Timestamp) -> pd.DataFrame:
        """One observation of every player's price and ownership, stamped with its fetch time.

        The API publishes only the present. This row is the only record that will ever exist of
        what today looked like, which is why the store appends rather than overwrites.
        """
        rows = extract_price_history_rows(bootstrap, now)
        return pd.DataFrame(rows)

    def _entry(self, entry: dict[str, Any], bootstrap: dict[str, Any]) -> pd.DataFrame:
        divisor = self._currency_divisor(bootstrap)

        def money(value: Any) -> float | None:
            return None if value is None else float(value) / divisor

        return pd.DataFrame(
            [
                {
                    "entry_id": int(entry["id"]),
                    "name": str(entry.get("name") or ""),
                    "started_event": entry.get("started_event"),
                    "current_event": entry.get("current_event"),
                    "bank": money(entry.get("last_deadline_bank")),
                    "squad_value": money(entry.get("last_deadline_value")),
                    "total_transfers": int(entry.get("last_deadline_total_transfers") or 0),
                    "summary_overall_points": entry.get("summary_overall_points"),
                    "summary_overall_rank": entry.get("summary_overall_rank"),
                }
            ]
        )

    def _entry_picks(
        self, entry_id: int, picks_by_gameweek: dict[int, dict[str, Any]]
    ) -> pd.DataFrame:
        """Picks as published.

        ``purchase_price`` and ``selling_price`` are left null here on purpose: the public picks
        endpoint does not carry them — only the authenticated ``my-team`` endpoint does, and this
        project will never authenticate (Invariant 4). They are reconstructed downstream from
        transfer history and gameweek prices, which is lossless for anything actually observable.
        """
        rows = [
            {
                "entry_id": entry_id,
                "gameweek": gameweek,
                "player_id": int(pick["element"]),
                "slot": int(pick["position"]),
                "multiplier": int(pick["multiplier"]),
                "is_captain": bool(pick.get("is_captain")),
                "is_vice_captain": bool(pick.get("is_vice_captain")),
                "purchase_price": pick.get("purchase_price"),
                "selling_price": pick.get("selling_price"),
            }
            for gameweek, payload in sorted(picks_by_gameweek.items())
            for pick in payload.get("picks") or []
        ]
        return pd.DataFrame(
            rows,
            columns=[
                "entry_id",
                "gameweek",
                "player_id",
                "slot",
                "multiplier",
                "is_captain",
                "is_vice_captain",
                "purchase_price",
                "selling_price",
            ],
        )

    def _entry_transfers(
        self, entry_id: int, transfers: list[dict[str, Any]], bootstrap: dict[str, Any]
    ) -> pd.DataFrame:
        divisor = self._currency_divisor(bootstrap)
        rows = [
            {
                "entry_id": entry_id,
                "gameweek": int(transfer["event"]),
                "player_in_id": int(transfer["element_in"]),
                "player_in_cost": float(transfer["element_in_cost"]) / divisor,
                "player_out_id": int(transfer["element_out"]),
                "player_out_cost": float(transfer["element_out_cost"]) / divisor,
                "made_at": pd.Timestamp(transfer["time"]).tz_convert("UTC")
                if transfer.get("time")
                else pd.NaT,
            }
            for transfer in transfers
        ]
        frame = pd.DataFrame(
            rows,
            columns=[
                "entry_id",
                "gameweek",
                "player_in_id",
                "player_in_cost",
                "player_out_id",
                "player_out_cost",
                "made_at",
            ],
        )
        frame["made_at"] = pd.to_datetime(frame["made_at"], utc=True)
        return frame

    def _entry_gameweeks(
        self, entry_id: int, history: dict[str, Any], bootstrap: dict[str, Any]
    ) -> pd.DataFrame:
        """The owner's score per gameweek, from ``history.current`` (DL-69).

        Only gameweeks the game has finished are kept: the in-progress row changes with every
        kickoff, and the season log is a record of results, not a live ticker.
        """
        divisor = self._currency_divisor(bootstrap)
        finished = {int(e["id"]) for e in bootstrap["events"] if e.get("finished")}

        def money(value: Any) -> float | None:
            return None if value is None else float(value) / divisor

        rows = [
            {
                "entry_id": entry_id,
                "gameweek": int(row["event"]),
                "points": int(row.get("points") or 0),
                "total_points": int(row.get("total_points") or 0),
                "rank": row.get("rank"),
                "overall_rank": row.get("overall_rank"),
                "bank": money(row.get("bank")),
                "squad_value": money(row.get("value")),
                "transfers": int(row.get("event_transfers") or 0),
                "transfers_cost": int(row.get("event_transfers_cost") or 0),
                "points_on_bench": int(row.get("points_on_bench") or 0),
            }
            for row in history.get("current") or []
            if int(row["event"]) in finished
        ]
        return pd.DataFrame(
            rows,
            columns=[
                "entry_id",
                "gameweek",
                "points",
                "total_points",
                "rank",
                "overall_rank",
                "bank",
                "squad_value",
                "transfers",
                "transfers_cost",
                "points_on_bench",
            ],
        )

    def _entry_chips(self, entry_id: int, history: dict[str, Any]) -> pd.DataFrame:
        rows = [
            {
                "entry_id": entry_id,
                "name": str(chip["name"]),
                "gameweek": int(chip["event"]),
            }
            for chip in history.get("chips") or []
        ]
        return pd.DataFrame(rows, columns=["entry_id", "name", "gameweek"])

    def _player_gameweek(
        self, bootstrap: dict[str, Any], request: IngestRequest, warnings: list[str]
    ) -> pd.DataFrame:
        """Current-season per-gameweek rows, from each player's own history.

        Empty until the season starts, which is the normal preseason state and not a fault. Prior
        seasons are not available here at any granularity finer than a season total — that gap is
        what DL-19 exists to fill.
        """
        divisor = self._currency_divisor(bootstrap)
        positions = self._position_by_element_type(bootstrap)
        season = str(self.season_name(bootstrap))
        rows = []
        for element in bootstrap["elements"]:
            if element.get("removed"):
                continue
            player_id = int(element["id"])
            try:
                summary = self.fetch_element_summary(player_id, request)
            except SourceNotFoundError, OfflineWithoutSnapshotError:
                continue
            for row in summary.get("history") or []:
                rows.append(
                    {
                        "season": season,
                        "gameweek": int(row["round"]),
                        "player_code": int(element["code"]),
                        "player_id": player_id,
                        "web_name": str(element["web_name"]),
                        "position": positions[int(element["element_type"])],
                        "team_id": int(element["team"]),
                        "opponent_team_id": int(row["opponent_team"]),
                        "fixture_id": int(row["fixture"]),
                        "kickoff_time": pd.Timestamp(row["kickoff_time"]).tz_convert("UTC")
                        if row.get("kickoff_time")
                        else pd.NaT,
                        "was_home": bool(row["was_home"]),
                        "minutes": int(row["minutes"]),
                        "starts": row.get("starts"),
                        "goals_scored": int(row["goals_scored"]),
                        "assists": int(row["assists"]),
                        "clean_sheets": int(row["clean_sheets"]),
                        "goals_conceded": int(row["goals_conceded"]),
                        "own_goals": int(row["own_goals"]),
                        "penalties_saved": int(row["penalties_saved"]),
                        "penalties_missed": int(row["penalties_missed"]),
                        "yellow_cards": int(row["yellow_cards"]),
                        "red_cards": int(row["red_cards"]),
                        "saves": int(row["saves"]),
                        "bonus": int(row["bonus"]),
                        "bps": int(row["bps"]),
                        "defensive_contribution": row.get("defensive_contribution"),
                        "tackles": row.get("tackles"),
                        "recoveries": row.get("recoveries"),
                        "clearances_blocks_interceptions": row.get(
                            "clearances_blocks_interceptions"
                        ),
                        "expected_goals": row.get("expected_goals"),
                        "expected_assists": row.get("expected_assists"),
                        "expected_goals_conceded": row.get("expected_goals_conceded"),
                        "price": float(row["value"]) / divisor,
                        "selected_by": row.get("selected"),
                        "total_points": int(row["total_points"]),
                    }
                )
        if not rows:
            warnings.append("no per-gameweek rows yet; the season has not started")
        return pd.DataFrame(rows, columns=columns_for(Table.PLAYER_GAMEWEEK))

    def season_name(self, bootstrap: dict[str, Any]) -> str:
        """Derive the season label from the first deadline. Never hardcoded.

        A season that starts in August 2026 is 2026/27. Reading it from the events means a
        pipeline left running into next season labels its data correctly rather than confidently
        mislabelling it.
        """
        events = bootstrap.get("events") or []
        if not events:
            raise SourceContractError(
                "bootstrap-static has no events, so the season cannot be identified",
                source=self.name,
                resource="bootstrap_static",
                key="all",
            )
        start = pd.Timestamp(events[0]["deadline_time"]).tz_convert("UTC")
        year = int(start.year) if int(start.month) >= 7 else int(start.year) - 1
        return f"{year}/{str(year + 1)[-2:]}"

    def conform(self, request: IngestRequest) -> Conformed:
        warnings: list[str] = []
        bootstrap = self.fetch_bootstrap(request)
        fixtures = self.fetch_fixtures(request)
        snapshot = self.fetcher.bronze.latest(
            self.name, "bootstrap_static", "all", as_of=request.now
        )
        # The snapshot's own fetch time, never the run's: a re-run adds no rows, and the replay
        # (sources/replay.py) reproduces exactly what live runs wrote (DP-11).
        observed = pd.Timestamp(
            snapshot.meta.fetched_at if snapshot else (request.now or utcnow())
        ).tz_convert("UTC")

        tables: dict[str, pd.DataFrame] = {
            Table.PLAYER.value: self._players(bootstrap),
            Table.TEAM.value: self._teams(bootstrap),
            Table.FIXTURE.value: self._fixtures(fixtures),
            Table.GAMEWEEK.value: self._gameweeks(bootstrap),
            Table.CHIP.value: self._chips(bootstrap),
            Table.PRICE_HISTORY.value: self._price_history(bootstrap, observed),
            Table.PLAYER_SEASON_HISTORY.value: self._season_history(bootstrap, request, warnings),
            Table.PLAYER_GAMEWEEK.value: self._player_gameweek(bootstrap, request, warnings),
        }

        try:
            tables[Table.SET_PIECE_NOTE.value] = self._set_piece_notes(
                self.fetch_set_piece_notes(request)
            )
        except SourceNotFoundError, OfflineWithoutSnapshotError:
            warnings.append("no set-piece notes snapshot; continuing without them")

        if request.entry_id is not None:
            tables.update(self._conform_entry(request.entry_id, bootstrap, request, warnings))

        if request.league_id is not None:
            tables.update(self._conform_league(request.league_id, bootstrap, request, warnings))

        return Conformed(
            tables=tables,
            rules=self.extract_rules(bootstrap),
            rules_snapshot_sha256=snapshot.meta.sha256 if snapshot else None,
            warnings=warnings,
        )

    def _conform_league(
        self,
        league_id: int,
        bootstrap: dict[str, Any],
        request: IngestRequest,
        warnings: list[str],
    ) -> dict[str, pd.DataFrame]:
        """The mini-league table, and as many rivals' squads as the budget allowed.

        An unreadable league is a warning, never a failure: it enriches a comparison view and feeds
        no decision, so losing it must cost exactly that view (NFR-15, DP-15).
        """
        try:
            standings = self.fetch_league_standings(league_id, request)
        except SourceNotFoundError, OfflineWithoutSnapshotError:
            warnings.append(f"league {league_id} was not readable; continuing without it")
            return {}

        gameweek = _latest_finished_gameweek(bootstrap)
        picks: dict[int, dict[str, Any]] = {}
        if gameweek is not None:
            for entry_id in _league_entry_ids(standings, request.league_rival_limit):
                try:
                    payload = self.fetch_entry_picks(entry_id, gameweek, request)
                except OfflineWithoutSnapshotError:
                    warnings.append(f"no picks snapshot for league entry {entry_id}")
                    continue
                if payload is not None:
                    picks[entry_id] = payload

        moves: dict[int, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
        if gameweek is not None:
            for entry_id in _league_entry_ids(standings, request.league_rival_limit):
                try:
                    moves[entry_id] = self._rival_moves(entry_id, gameweek, request)
                except SourceError as exc:
                    # Only this team's drill-down loses its moves (NFR-15); the reason is kept.
                    warnings.append(f"no moves for league entry {entry_id}: {exc}")

        if request.league_rival_limit > 0 and not picks:
            # Says which of the two reasons applies, because "no overlap shown" has a very
            # different meaning preseason than it does in October (DP-15: visible degradation).
            warnings.append(
                f"league {league_id}: no rival squads available"
                + (" (no gameweek scored yet)" if gameweek is None else f" for gameweek {gameweek}")
            )

        return {
            Table.LEAGUE_STANDING.value: self._league_standings(league_id, standings),
            Table.LEAGUE_PICK.value: self._league_picks(gameweek, picks),
            Table.LEAGUE_GAMEWEEK.value: pd.DataFrame(
                [
                    {"entry_id": e, "gameweek": gameweek, **row}
                    for e, (row, _) in sorted(moves.items())
                ],
                columns=columns_for(Table.LEAGUE_GAMEWEEK),
            ),
            Table.LEAGUE_TRANSFER.value: pd.DataFrame(
                [
                    {"entry_id": e, "gameweek": gameweek, **t}
                    for e, (_, ts) in sorted(moves.items())
                    for t in ts
                ],
                columns=columns_for(Table.LEAGUE_TRANSFER),
            ),
        }

    def _rival_moves(
        self, entry_id: int, gameweek: int, request: IngestRequest
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """One rival's hit, chip and transfers for ``gameweek``, from the public entry endpoints."""
        history = self.fetch_entry_history(entry_id, request)
        transfers = self.fetch_entry_transfers(entry_id, request)
        current = next(
            (r for r in history.get("current") or [] if int(r["event"]) == gameweek), None
        )
        chip = next(
            (str(c["name"]) for c in history.get("chips") or [] if int(c["event"]) == gameweek),
            None,
        )
        row = {
            "transfers": int((current or {}).get("event_transfers") or 0),
            "transfers_cost": int((current or {}).get("event_transfers_cost") or 0),
            "chip": chip,
        }
        moved = [
            {"player_in_id": int(t["element_in"]), "player_out_id": int(t["element_out"])}
            for t in transfers
            if int(t["event"]) == gameweek
        ]
        return row, moved

    def _league_standings(self, league_id: int, standings: dict[str, Any]) -> pd.DataFrame:
        name = str((standings.get("league") or {}).get("name") or "")
        rows = [
            {
                "league_id": league_id,
                "league_name": name,
                "entry_id": int(result["entry"]),
                "entry_name": str(result.get("entry_name") or ""),
                "player_name": str(result.get("player_name") or ""),
                "rank": int(result["rank"]),
                "last_rank": result.get("last_rank"),
                "event_total": result.get("event_total"),
                "total": int(result.get("total") or 0),
            }
            for result in _standings_results(standings)
            if result.get("entry") is not None and result.get("rank") is not None
        ]
        return pd.DataFrame(
            rows,
            columns=[
                "league_id",
                "league_name",
                "entry_id",
                "entry_name",
                "player_name",
                "rank",
                "last_rank",
                "event_total",
                "total",
            ],
        )

    def _league_picks(
        self, gameweek: int | None, picks_by_entry: dict[int, dict[str, Any]]
    ) -> pd.DataFrame:
        rows = [
            {
                "entry_id": entry_id,
                "gameweek": gameweek,
                "player_id": int(pick["element"]),
                "slot": int(pick["position"]),
                "multiplier": int(pick["multiplier"]),
                "is_captain": bool(pick.get("is_captain")),
                "is_vice_captain": bool(pick.get("is_vice_captain")),
            }
            for entry_id, payload in sorted(picks_by_entry.items())
            for pick in payload.get("picks") or []
        ]
        return pd.DataFrame(
            rows,
            columns=[
                "entry_id",
                "gameweek",
                "player_id",
                "slot",
                "multiplier",
                "is_captain",
                "is_vice_captain",
            ],
        )

    def _conform_entry(
        self,
        entry_id: int,
        bootstrap: dict[str, Any],
        request: IngestRequest,
        warnings: list[str],
    ) -> dict[str, pd.DataFrame]:
        """Everything about the owner's team, or nothing, with a reason.

        A configured team ID that the API cannot answer for is a warning rather than a failure:
        before GW1 is scored there is genuinely nothing to read (DL-20), and failing the run would
        make the pipeline unusable in exactly the week it is needed most.
        """
        try:
            entry = self.fetch_entry(entry_id, request)
            history = self.fetch_entry_history(entry_id, request)
            transfers = self.fetch_entry_transfers(entry_id, request)
        except SourceNotFoundError:
            warnings.append(f"entry {entry_id} was not found; check the configured team ID")
            return {}
        except OfflineWithoutSnapshotError:
            warnings.append(f"no snapshot for entry {entry_id}; running without squad state")
            return {}

        picks: dict[int, dict[str, Any]] = {}
        for event in bootstrap["events"]:
            if not event.get("finished"):
                continue
            payload = self.fetch_entry_picks(entry_id, int(event["id"]), request)
            if payload is not None:
                picks[int(event["id"])] = payload
        if not picks:
            warnings.append(
                f"entry {entry_id} has no published picks yet; squad state must be declared"
            )

        return {
            Table.ENTRY.value: self._entry(entry, bootstrap),
            Table.ENTRY_PICK.value: self._entry_picks(entry_id, picks),
            Table.ENTRY_TRANSFER.value: self._entry_transfers(entry_id, transfers, bootstrap),
            Table.ENTRY_CHIP.value: self._entry_chips(entry_id, history),
            Table.ENTRY_GAMEWEEK.value: self._entry_gameweeks(entry_id, history, bootstrap),
        }

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

        # ~700 requests, several minutes. It is declared off the fast path, and the fast cadence
        # runs six times a day, so honouring that declaration is what keeps the frequent workflow
        # measured in seconds (Architecture §9).
        fetched = 0
        if not self.wants("element_summary", request):
            log.info("fpl.element_summary.skipped", extra={"reason": "off the fast path"})
        else:
            element_ids = [int(element["id"]) for element in bootstrap["elements"]]
            if request.player_limit is not None:
                element_ids = element_ids[: request.player_limit]
                report.warnings.append(
                    f"player_limit={request.player_limit} applied; this is a development setting "
                    "and must not be used for a real run"
                )

            stale_before = self._summaries_stale_before(bootstrap, request)
            log.info(
                "fpl.element_summary.start",
                extra={"players": len(element_ids), "stale_before": str(stale_before)},
            )
            checked_contract = False
            for element_id in element_ids:
                try:
                    summary = self.fetch_element_summary(
                        element_id, request, stale_before=stale_before
                    )
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

        if self.wants("set_piece_notes", request):
            try:
                self.fetch_set_piece_notes(request)
                report.resources["set_piece_notes"] = 1
            except SourceNotFoundError, OfflineWithoutSnapshotError:
                report.warnings.append("set-piece notes unavailable")

        # Only gameweeks that have actually been played. Asking for a future one returns an empty
        # payload that would then be cached as if it meant something.
        live = 0
        if self.wants("event_live", request):
            for event in bootstrap["events"]:
                if not event.get("finished"):
                    continue
                try:
                    self.fetch_event_live(int(event["id"]), request)
                    live += 1
                except SourceNotFoundError, OfflineWithoutSnapshotError:
                    report.warnings.append(f"no live data for gameweek {event['id']}")
        report.resources["event_live"] = live

        if request.league_id is not None and self.wants("league_standings", request):
            report.resources.update(
                self._ingest_league(request.league_id, bootstrap, request, report)
            )

        if request.entry_id is not None:
            report.resources.update(
                self._ingest_entry(request.entry_id, bootstrap, request, report)
            )

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

    def _ingest_league(
        self,
        league_id: int,
        bootstrap: dict[str, Any],
        request: IngestRequest,
        report: IngestReport,
    ) -> dict[str, int]:
        """The configured mini-league: its table, and the squads of the entries near the top.

        Standings are one request. Squads are one request *per entry*, which is why the number of
        entries read is a configured budget rather than "everyone in the league" — a public league
        can hold hundreds of thousands of them.
        """
        counts: dict[str, int] = {}
        try:
            standings = self.fetch_league_standings(league_id, request)
        except SourceNotFoundError, OfflineWithoutSnapshotError:
            report.warnings.append(f"league {league_id} unavailable")
            return counts
        counts["league_standings"] = 1

        gameweek = _latest_finished_gameweek(bootstrap)
        if gameweek is None:
            # Preseason. Nobody has picks yet, not even the owner (DL-20), so there is nothing to
            # fetch and the standings alone are the honest answer.
            return counts

        fetched = moves = 0
        for entry_id in _league_entry_ids(standings, request.league_rival_limit):
            try:
                if self.fetch_entry_picks(entry_id, gameweek, request) is not None:
                    fetched += 1
            except OfflineWithoutSnapshotError:
                report.warnings.append(f"no picks snapshot for league entry {entry_id}")
            try:
                self._rival_moves(entry_id, gameweek, request)
                moves += 1
            except SourceError as exc:
                report.warnings.append(f"no moves for league entry {entry_id}: {exc}")
        counts["league_entry_picks"] = fetched
        counts["league_entry_moves"] = moves
        return counts

    def _ingest_entry(
        self,
        entry_id: int,
        bootstrap: dict[str, Any],
        request: IngestRequest,
        report: IngestReport,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        try:
            self.fetch_entry(entry_id, request)
            counts["entry"] = 1
            self.fetch_entry_history(entry_id, request)
            counts["entry_history"] = 1
            self.fetch_entry_transfers(entry_id, request)
            counts["entry_transfers"] = 1
        except SourceNotFoundError:
            report.warnings.append(f"entry {entry_id} not found; check the configured team ID")
            return counts
        except OfflineWithoutSnapshotError:
            report.warnings.append(f"no snapshot for entry {entry_id}")
            return counts

        picks = 0
        for event in bootstrap["events"]:
            if not event.get("finished"):
                continue
            try:
                if self.fetch_entry_picks(entry_id, int(event["id"]), request) is not None:
                    picks += 1
            except OfflineWithoutSnapshotError:
                report.warnings.append(f"no picks snapshot for gameweek {event['id']}")
        counts["entry_picks"] = picks
        return counts
