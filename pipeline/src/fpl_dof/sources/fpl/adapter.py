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
    Added in E2-S1. All three are empty or trivial in preseason, which is normal. ``event_live``
    for the gameweek in play is conformed as ``player_live``: per player and fixture, its
    ``explain`` lines carry the fixture id (LIVE-01).

``entry``, ``entry_history``, ``entry_picks``, ``entry_transfers``
    The owner's own team, fetched only when a team ID is configured. Public endpoints, like
    everything else here — the authenticated ``my-team`` endpoint carries purchase prices and is
    deliberately not used (Invariant 4), so purchase prices are reconstructed instead.

**The gameweek in play** is the latest past its deadline, until FPL data-checks it (LIVE-01). Its
picks are fixed at the deadline, so each team's are fetched once after it, and once more when the
gameweek is checked, for the game's final figures in their ``entry_history``. Its live scores and
the league table are fetched on every firing of the fast cadence while it is in play, as fresh as
the fixtures read with them.

**Two paths in this file are not where the catalogue said they were.** Set-piece notes live at
``team/set-piece-notes/``; a bare ``set-piece-notes/`` returns 404. ``element-status/`` no longer
exists at all.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, cast

import pandas as pd

from fpl_dof.config.models import SourceOverride
from fpl_dof.gameweek import matchdays_done_since
from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.rules.models import ApiRules, ApiScoring, ApiSquad, Position
from fpl_dof.silver.tables import Table, columns_for
from fpl_dof.sources.base import (
    ChangeContext,
    Conformed,
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
)
from fpl_dof.sources.bronze import Snapshot
from fpl_dof.sources.errors import (
    OfflineWithoutSnapshotError,
    SourceContractError,
    SourceError,
    SourceNotFoundError,
)
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.registry import register
from fpl_dof.sources.replay import extract_price_history_rows

log = get_logger(__name__)

_HOUR = 3600
_WEEK = 7 * 24 * _HOUR
#: The fast-path captures' TTL (LIVE-02, DL-99). The fast ingest fires hourly (ingest-fast.yml,
#: `7 * * * *`), and a capture still inside its TTL at the next firing is read, not refetched. A
#: full hour would let a firing a few seconds short of an hour after the last fetch read that
#: capture, so a done matchday or a deadline's price move would wait for the firing after. 50
#: minutes makes every hourly firing refetch, including one whose previous fetch ran up to ten
#: minutes late (a queued run). Tied to that cron: a test holds the two together.
_FAST_PATH_TTL = 50 * 60

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


def _checked(event: dict[str, Any]) -> tuple[bool, bool]:
    """A gameweek's two completion flags, as the change manifest compares them (LIVE-02)."""
    return bool(event.get("finished")), bool(event.get("data_checked"))


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


@dataclass(frozen=True, slots=True)
class _LiveGameweek:
    """The latest gameweek past its deadline: in play until FPL data-checks it (LIVE-01)."""

    gameweek: int
    deadline: dt.datetime
    checked: bool
    """FPL has marked it finished and data-checked: its figures are final."""

    @property
    def key(self) -> str:
        return str(self.gameweek)


def _live_gameweek(bootstrap: dict[str, Any], moment: dt.datetime) -> _LiveGameweek | None:
    """The latest gameweek whose deadline is at or before ``moment``, or None preseason.

    The deadline, not the first kick-off, because the picks are what it governs: they are public
    and fixed from then (CON-10). An event without a deadline is no gameweek anyone can be in.
    """
    past: list[tuple[dt.datetime, dict[str, Any]]] = []
    for event in bootstrap.get("events") or []:
        if not event.get("deadline_time"):
            continue
        deadline = pd.Timestamp(event["deadline_time"]).tz_convert("UTC").to_pydatetime()
        if deadline <= moment:
            past.append((deadline, event))
    if not past:
        return None
    deadline, event = max(past, key=lambda item: item[0])
    checked = bool(event.get("finished")) and bool(event.get("data_checked"))
    return _LiveGameweek(gameweek=int(event["id"]), deadline=deadline, checked=checked)


def _live_rows(
    element: dict[str, Any], states: dict[int, tuple[bool, bool]]
) -> list[dict[str, Any]]:
    """One row per fixture FPL explains for this player, as it explains it.

    ``explain`` is FPL's own per-fixture breakdown; a fixture's points are the sum of its lines.
    BPS is reported for the whole gameweek, so it is the fixture's only when the player has one.
    ``states`` is each fixture's (full time, bonus confirmed).
    """
    explain = element.get("explain") or []
    stats = element.get("stats") or {}
    rows = []
    for item in explain:
        lines = {str(line["identifier"]): line for line in item.get("stats") or []}
        bps = lines["bps"].get("value") if "bps" in lines else None
        if bps is None and len(explain) == 1:
            bps = stats.get("bps")
        rows.append(
            {
                "fixture_id": int(item["fixture"]),
                "player_id": int(element["id"]),
                "minutes": int((lines.get("minutes") or {}).get("value") or 0),
                "points": sum(int(line.get("points") or 0) for line in lines.values()),
                "bonus": int((lines.get("bonus") or {}).get("value") or 0),
                "bps": None if bps is None else int(bps),
                "finished": states.get(int(item["fixture"]), (False, False))[0],
                "bonus_confirmed": states.get(int(item["fixture"]), (False, False))[1],
            }
        )
    return rows


def _unexplained_rows(
    bootstrap: dict[str, Any],
    fixtures: list[dict[str, Any]],
    gameweek: int,
    explained: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    """A row of zeros for each fixture of the gameweek a player's club plays and FPL gives him no
    line in: one still to kick off, or one he has not appeared in.

    FPL's ``explain`` lists only fixtures a player has a line in, and no line means no minutes, so
    this states what it reports rather than inferring anything; without it a player yet to play
    would read as a blank, and be substituted (LIVE-03).
    """
    by_club: dict[int, list[dict[str, Any]]] = {}
    for fixture in fixtures:
        if fixture.get("event") != gameweek:
            continue
        for club in (fixture["team_h"], fixture["team_a"]):
            by_club.setdefault(int(club), []).append(fixture)
    return [
        {
            "fixture_id": int(fixture["id"]),
            "player_id": int(element["id"]),
            "minutes": 0,
            "points": 0,
            "bonus": 0,
            "bps": None,
            "finished": bool(fixture.get("finished_provisional")),
            "bonus_confirmed": bool(fixture.get("finished")),
        }
        for element in bootstrap["elements"]
        if not element.get("removed")
        for fixture in by_club.get(int(element["team"]), [])
        if (int(element["id"]), int(fixture["id"])) not in explained
    ]


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
            cache_ttl_seconds=_FAST_PATH_TTL,
            fast_path=True,
        ),
        Resource(
            name="fixtures",
            summary="All fixtures with per-side difficulty",
            cache_ttl_seconds=_FAST_PATH_TTL,
            fast_path=True,
        ),
        Resource(
            name="element_summary",
            summary="Per-player prior-season totals, this season's gameweeks and upcoming fixtures",
            # history_past is fixed for the season, but `history` gains a row per player every
            # gameweek and is where player_gameweek comes from. So the week-long TTL (~670
            # requests a sweep) holds only until a gameweek is checked: ingest then treats every
            # summary fetched before that as stale (`_summaries_stale_before`). The fast ingest
            # whose capture is the first to show a check does that sweep itself, once, so the run
            # the check starts evaluates the gameweek on its final rows (LIVE-07).
            cache_ttl_seconds=_WEEK,
            fast_path=False,
            on_check=True,
        ),
        Resource(
            name="event_live",
            summary="Per-gameweek actuals for every player, including BPS",
            # A finished gameweek never changes. The one in play changes with every match, so the
            # fast cadence fetches it too, as fresh as the fixtures read with it (LIVE-01).
            cache_ttl_seconds=_HOUR,
            fast_path=False,
            in_play=True,
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
            in_play=True,
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
            # Fixed from the deadline: the gameweek in play's are fetched once a team (LIVE-01).
            summary="A team's picks for a gameweek past its deadline, with the game's own score",
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

    def __init__(self, fetcher: Fetcher, options: SourceOverride | None = None) -> None:
        super().__init__(fetcher, options)
        self._checked_at: dict[Path, frozenset[int]] = {}
        """The gameweeks each bootstrap capture shows data-checked, read once per capture."""

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

    def changes(
        self, resource: str, before: Snapshot, after: Snapshot, context: ChangeContext
    ) -> set[str]:
        """Prices, status or news per player; kick-off or gameweek per fixture (ORC-02); results
        when a matchday becomes done or a gameweek is marked finished or data-checked (LIVE-02).
        A player, fixture or gameweek in only one capture is not a change of any. A fixture's
        start, score or provisional finish moves nothing: only its bonus-confirmed ``finished``
        counts, through the matchday rule (:func:`~fpl_dof.gameweek.matchdays_done_since`)."""
        old, new = json.loads(before.read_bytes()), json.loads(after.read_bytes())
        kinds: set[str] = set()
        if resource == "fixtures":
            was = {f["id"]: (f.get("kickoff_time"), f.get("event")) for f in old}
            now = {f["id"]: (f.get("kickoff_time"), f.get("event")) for f in new}
            if any(was.get(i, at) != at for i, at in now.items()):
                kinds.add("fixtures")
            if matchdays_done_since(
                self._fixtures(old) if old else None,
                before.meta.fetched_at,
                self._fixtures(new) if new else None,
                after.meta.fetched_at,
                zone=context.matchday_zone,
                settle=context.settle,
            ):
                kinds.add("results")
            return kinds
        flags = {e["id"]: _checked(e) for e in old.get("events") or []}
        for event in new.get("events") or []:
            prior = flags.get(event["id"])
            if prior is not None and any(
                flag and not was for was, flag in zip(prior, _checked(event), strict=True)
            ):
                kinds.add("results")  # marked finished, or data-checked
        players = {e["id"]: e for e in old["elements"]}
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
        fresh_from: dt.datetime | None = None,
    ) -> Any:
        """Fetch, snapshot and parse one resource, checked against its contract (:meth:`_parse`).

        Only the shape is checked here. Every endpoint added in E2-S1 is optional in a way the
        original three are not: a gameweek that has not been played, a club with no set-piece
        notes and a team ID that is not configured are all normal, so whether emptiness is
        expected is decided at conformance.
        """
        return self._capture(
            resource_name, path, key, request, stale_before=stale_before, fresh_from=fresh_from
        )[0]

    def _capture(
        self,
        resource_name: str,
        path: str,
        key: str,
        request: IngestRequest,
        *,
        stale_before: dt.datetime | None = None,
        fresh_from: dt.datetime | None = None,
    ) -> tuple[Any, Snapshot]:
        """:meth:`_fetch_resource`, with the capture it read: its time stamps live rows."""
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
            fresh_from=fresh_from,
        )
        return self._parse(resource.name, key, fetched.payload), fetched.snapshot

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

    def _newly_checked(self, bootstrap: dict[str, Any], capture: Snapshot) -> bool:
        """Whether ``capture`` is the first bootstrap capture to show its latest checked gameweek
        data-checked: the per-player summaries in bronze then all predate the check (LIVE-07).

        Any gameweek, not only the live one: FPL can check a gameweek after the next deadline has
        passed (a Monday match, a Tuesday deadline), when the live gameweek is already the next.
        One read of the capture before, so the firings after the first neither fetch nor walk the
        summaries. With no capture before it there is no telling when the check came, so it counts
        as new: a sweep of cached summaries is cheap, and a missed one is a wrong evaluation.
        """
        latest = _latest_checked_gameweek(bootstrap)
        if latest is None:
            return False
        before = self.fetcher.bronze.latest(
            self.name,
            "bootstrap_static",
            "all",
            as_of=capture.meta.fetched_at - dt.timedelta(microseconds=1),
        )
        if before is None:
            return True
        then = self._json(before.read_bytes(), resource="bootstrap_static", key="all")
        return (_latest_checked_gameweek(then) or 0) < latest

    def fetch_event_live(
        self, gameweek: int, request: IngestRequest, *, fresh_from: dt.datetime | None = None
    ) -> dict[str, Any]:
        data: dict[str, Any] = self._fetch_resource(
            "event_live", f"event/{gameweek}/live/", str(gameweek), request, fresh_from=fresh_from
        )
        return data

    def fetch_set_piece_notes(self, request: IngestRequest) -> dict[str, Any]:
        # The path is `team/set-piece-notes/`. A bare `set-piece-notes/` returns 404 — it is the
        # path the endpoint catalogue carried, and it has moved.
        data: dict[str, Any] = self._fetch_resource(
            "set_piece_notes", "team/set-piece-notes/", "all", request
        )
        return data

    def fetch_league_standings(
        self, league_id: int, request: IngestRequest, *, fresh_from: dt.datetime | None = None
    ) -> dict[str, Any]:
        data: dict[str, Any] = self._fetch_resource(
            "league_standings",
            f"leagues-classic/{league_id}/standings/",
            str(league_id),
            request,
            fresh_from=fresh_from,
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
        self,
        entry_id: int,
        gameweek: int,
        request: IngestRequest,
        *,
        fresh_from: dt.datetime | None = None,
    ) -> dict[str, Any] | None:
        """``None`` when the gameweek has no picks yet.

        Before a gameweek's deadline passes the endpoint 404s, which is the normal state of the
        world for most of the week and is not an error (DL-20).
        """
        captured = self._picks_capture(entry_id, gameweek, request, fresh_from=fresh_from)
        return None if captured is None else captured[0]

    def _picks_capture(
        self,
        entry_id: int,
        gameweek: int,
        request: IngestRequest,
        *,
        fresh_from: dt.datetime | None = None,
    ) -> tuple[dict[str, Any], Snapshot] | None:
        """:meth:`fetch_entry_picks`, with the capture it read."""
        try:
            data, snapshot = self._capture(
                "entry_picks",
                f"entry/{entry_id}/event/{gameweek}/picks/",
                f"{entry_id}-{gameweek}",
                request,
                fresh_from=fresh_from,
            )
        except SourceNotFoundError:
            return None
        return cast(dict[str, Any], data), snapshot

    # --- the gameweek in play (LIVE-01) ----------------------------------------------------

    def _settled(self, snapshot: Snapshot, gameweek: int) -> bool:
        """Whether ``snapshot`` was captured once FPL had data-checked ``gameweek``: final.

        Read from the bootstrap capture bronze held at that moment, because FPL publishes no time
        a gameweek was checked; so a run on any later day stamps a capture as it was (DP-11). A
        capture with no bootstrap before it cannot be shown final, and is not.
        """
        bootstrap = self.fetcher.bronze.latest(
            self.name, "bootstrap_static", "all", as_of=snapshot.meta.fetched_at
        )
        if bootstrap is None:
            return False
        checked = self._checked_at.get(bootstrap.path)
        if checked is None:
            data = self._json(bootstrap.read_bytes(), resource="bootstrap_static", key="all")
            checked = frozenset(
                int(event["id"])
                for event in data.get("events") or []
                if event.get("finished") and event.get("data_checked")
            )
            self._checked_at[bootstrap.path] = checked
        return gameweek in checked

    def _fresh_from(
        self,
        resource: str,
        key: str,
        live: _LiveGameweek,
        request: IngestRequest,
        in_play_from: dt.datetime,
    ) -> dt.datetime:
        """From when a capture of the live gameweek's ``resource`` is current.

        ``in_play_from`` while it is in play. Once it is checked, the first capture taken after
        the check is current for good and every earlier one is not: the final figures are
        fetched once, and never again.
        """
        if not live.checked:
            return in_play_from
        moment = request.now or utcnow()
        latest = self.fetcher.bronze.latest(self.name, resource, key, as_of=moment)
        if latest is not None and self._settled(latest, live.gameweek):
            return latest.meta.fetched_at
        return moment

    def _scores_from(self, live: _LiveGameweek, request: IngestRequest) -> dt.datetime:
        """From when live scores and the table are current while the gameweek is in play: the
        fixtures capture read with them, never before the deadline. So a run never reads scores
        older than the fixture states beside them."""
        fixtures = self.fetcher.bronze.latest(self.name, "fixtures", "all", as_of=request.now)
        captured = fixtures.meta.fetched_at if fixtures is not None else live.deadline
        return max(captured, live.deadline)

    def _live_picks(
        self, entry_id: int, live: _LiveGameweek, request: IngestRequest
    ) -> tuple[dict[str, Any], Snapshot] | None:
        """One team's picks for the live gameweek: once after its deadline, once when checked."""
        key = f"{entry_id}-{live.gameweek}"
        fresh = self._fresh_from("entry_picks", key, live, request, live.deadline)
        return self._picks_capture(entry_id, live.gameweek, request, fresh_from=fresh)

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
                    "finished_provisional": bool(fixture.get("finished_provisional")),
                    "started": bool(fixture.get("started")),
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
        live = _live_gameweek(bootstrap, request.now or utcnow())

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
        if live is not None:
            tables[Table.PLAYER_LIVE.value] = self._player_live(
                live, bootstrap, fixtures, request, warnings
            )

        try:
            tables[Table.SET_PIECE_NOTE.value] = self._set_piece_notes(
                self.fetch_set_piece_notes(request)
            )
        except SourceNotFoundError, OfflineWithoutSnapshotError:
            warnings.append("no set-piece notes snapshot; continuing without them")

        # The owner first, so an owner who is also a published rival keeps one row (one capture).
        entry_live: list[pd.DataFrame] = []
        for part in (
            self._conform_entry(request.entry_id, bootstrap, request, warnings, live)
            if request.entry_id is not None
            else {},
            self._conform_league(request.league_id, bootstrap, request, warnings, live)
            if request.league_id is not None
            else {},
        ):
            entry_live.append(part.pop(Table.ENTRY_LIVE.value, pd.DataFrame()))
            tables.update(part)
        frames = [frame for frame in entry_live if not frame.empty]
        if frames:
            merged = pd.concat(frames, ignore_index=True)
            tables[Table.ENTRY_LIVE.value] = merged.drop_duplicates(
                subset=["entry_id", "gameweek"], keep="first"
            ).reset_index(drop=True)

        return Conformed(
            tables=tables,
            rules=self.extract_rules(bootstrap),
            rules_snapshot_sha256=snapshot.meta.sha256 if snapshot else None,
            warnings=warnings,
        )

    def _player_live(
        self,
        live: _LiveGameweek,
        bootstrap: dict[str, Any],
        fixtures: list[dict[str, Any]],
        request: IngestRequest,
        warnings: list[str],
    ) -> pd.DataFrame:
        """The live gameweek's scores per player and fixture, stamped provisional (LIVE-01).

        Losing them costs the live view and nothing else (DP-15): no decision reads them, and the
        feature store refuses them outright (Invariant 5).
        """
        empty = pd.DataFrame(columns=columns_for(Table.PLAYER_LIVE))
        try:
            payload, snapshot = self._capture(
                "event_live", f"event/{live.key}/live/", live.key, request
            )
        except SourceNotFoundError, OfflineWithoutSnapshotError:
            warnings.append(f"no live scores for gameweek {live.gameweek} yet")
            return empty
        if snapshot.meta.fetched_at < live.deadline:
            warnings.append(f"the live scores for gameweek {live.gameweek} predate its deadline")
            return empty
        states = {
            int(f["id"]): (bool(f.get("finished_provisional")), bool(f.get("finished")))
            for f in fixtures
        }
        try:
            rows, unexplained = [], 0
            for element in payload.get("elements") or []:
                lines = _live_rows(element, states)
                total = (element.get("stats") or {}).get("total_points")
                if total is not None and sum(r["points"] for r in lines) != int(total):
                    unexplained += 1
                rows.extend(lines)
            explained = {(r["player_id"], r["fixture_id"]) for r in rows}
            rows.extend(_unexplained_rows(bootstrap, fixtures, live.gameweek, explained))
        except (KeyError, ValueError, TypeError) as exc:
            warnings.append(f"the live scores for gameweek {live.gameweek} are malformed: {exc!r}")
            return empty
        if unexplained:
            # Visible, not silent (DP-15): FPL's breakdown no longer adds up to its own totals.
            warnings.append(
                f"gameweek {live.gameweek}: {unexplained} players' explained points do not sum "
                "to their total"
            )
        frame = pd.DataFrame(rows, columns=columns_for(Table.PLAYER_LIVE))
        frame["gameweek"] = live.gameweek
        frame["observed_at"] = pd.Timestamp(snapshot.meta.fetched_at).tz_convert("UTC")
        frame["provisional"] = not self._settled(snapshot, live.gameweek)
        return frame

    def _entry_live(
        self, entry_id: int, live: _LiveGameweek, payload: dict[str, Any], snapshot: Snapshot
    ) -> dict[str, Any] | None:
        """FPL's own figures for one team in the live gameweek, from its picks; None when the
        picks carry none, which is not a score of zero (DL-18)."""
        history = payload.get("entry_history")
        if not isinstance(history, dict) or history.get("points") is None:
            return None
        return {
            "gameweek": live.gameweek,
            "observed_at": pd.Timestamp(snapshot.meta.fetched_at).tz_convert("UTC"),
            "provisional": not self._settled(snapshot, live.gameweek),
            "entry_id": entry_id,
            "points": int(history["points"]),
            "transfers_cost": int(history.get("event_transfers_cost") or 0),
            "total_points": int(history.get("total_points") or 0),
            "chip": payload.get("active_chip"),
        }

    def _conform_league(
        self,
        league_id: int,
        bootstrap: dict[str, Any],
        request: IngestRequest,
        warnings: list[str],
        live: _LiveGameweek | None = None,
    ) -> dict[str, pd.DataFrame]:
        """The mini-league table, and as many rivals' squads as the budget allowed.

        An unreadable league is a warning, never a failure: it enriches a comparison view and feeds
        no decision, so losing it must cost exactly that view (NFR-15, DP-15). So is one rival's
        unreadable picks: that team loses its squad, and no other does.
        """
        try:
            standings = self.fetch_league_standings(league_id, request)
        except SourceNotFoundError, OfflineWithoutSnapshotError:
            warnings.append(f"league {league_id} was not readable; continuing without it")
            return {}

        rivals = _league_entry_ids(standings, request.league_rival_limit)
        gameweek = _latest_finished_gameweek(bootstrap)
        picks: dict[tuple[int, int], dict[str, Any]] = {}
        if gameweek is not None and (live is None or gameweek != live.gameweek):
            for entry_id in rivals:
                try:
                    payload = self.fetch_entry_picks(entry_id, gameweek, request)
                except SourceError:
                    warnings.append(f"no picks snapshot for league entry {entry_id}")
                    continue
                if payload is not None:
                    picks[(entry_id, gameweek)] = payload

        live_rows: list[dict[str, Any]] = []
        if live is not None:
            for entry_id in rivals:
                try:
                    captured = self._live_picks(entry_id, live, request)
                except SourceError:
                    warnings.append(
                        f"no picks snapshot for league entry {entry_id} in gameweek {live.gameweek}"
                    )
                    continue
                if captured is None:
                    continue
                picks[(entry_id, live.gameweek)] = captured[0]
                row = self._entry_live(entry_id, live, *captured)
                if row is not None:
                    live_rows.append(row)

        finished = {int(e["id"]) for e in bootstrap["events"] if e.get("finished")}
        moves: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
        if gameweek is not None:
            for entry_id in rivals:
                try:
                    moves[entry_id] = self._rival_moves(entry_id, gameweek, request, finished)
                except SourceError as exc:
                    # Only this team's drill-down loses its moves (NFR-15); the reason is kept.
                    warnings.append(f"no moves for league entry {entry_id}: {exc}")

        if request.league_rival_limit > 0 and not any(gw == gameweek for _, gw in picks):
            # Says which of the two reasons applies, because "no overlap shown" has a very
            # different meaning preseason than it does in October (DP-15: visible degradation).
            warnings.append(
                f"league {league_id}: no rival squads available"
                + (" (no gameweek scored yet)" if gameweek is None else f" for gameweek {gameweek}")
            )

        return {
            Table.LEAGUE_STANDING.value: self._league_standings(league_id, standings),
            Table.LEAGUE_PICK.value: self._league_picks(picks, warnings),
            Table.LEAGUE_GAMEWEEK.value: pd.DataFrame(
                [{"entry_id": e, **row} for e, (rows, _) in sorted(moves.items()) for row in rows],
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
            Table.ENTRY_LIVE.value: pd.DataFrame(live_rows, columns=columns_for(Table.ENTRY_LIVE)),
        }

    def _rival_moves(
        self,
        entry_id: int,
        gameweek: int,
        request: IngestRequest,
        finished: frozenset[int] | set[int] = frozenset(),
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """One rival's per-gameweek history and his transfers for ``gameweek``, from the public
        entry endpoints: a row for ``gameweek`` and each of the ``finished`` ones his history has.

        The fetch checks each payload's shape, not its rows, so a malformed row is raised here as
        a contract error: the callers then degrade only this team, as for a failed fetch (DP-15).
        """
        history = self.fetch_entry_history(entry_id, request)
        transfers = self.fetch_entry_transfers(entry_id, request)
        try:
            return self._read_rival_moves(history, transfers, gameweek, finished)
        except (KeyError, ValueError, TypeError) as exc:
            raise SourceContractError(
                f"malformed history or transfers row: {exc!r}",
                source=self.name,
                resource="entry_history",
                key=str(entry_id),
            ) from exc

    @staticmethod
    def _read_rival_moves(
        history: dict[str, Any],
        transfers: list[dict[str, Any]],
        gameweek: int,
        finished: frozenset[int] | set[int] = frozenset(),
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """His row for ``gameweek`` (zeros and no total when his history has none) and for each
        finished gameweek his history has: the total after it is what the gameweek after it
        stands on live (LIVE-03). Only finished ones, as the owner's season log: the row for the
        gameweek in play moves with every kick-off."""
        current = {int(r["event"]): r for r in history.get("current") or []}
        chips = {int(c["event"]): str(c["name"]) for c in history.get("chips") or []}

        def row(event: int) -> dict[str, Any]:
            found = current.get(event) or {}
            total = found.get("total_points")
            return {
                "gameweek": event,
                "transfers": int(found.get("event_transfers") or 0),
                "transfers_cost": int(found.get("event_transfers_cost") or 0),
                "chip": chips.get(event),
                "total_points": None if total is None else int(total),
            }

        rows = [row(event) for event in sorted({gameweek} | (set(current) & set(finished)))]
        moved = [
            {"player_in_id": int(t["element_in"]), "player_out_id": int(t["element_out"])}
            for t in transfers
            if int(t["event"]) == gameweek
        ]
        return rows, moved

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
        self, picks: dict[tuple[int, int], dict[str, Any]], warnings: list[str]
    ) -> pd.DataFrame:
        """Each rival's squad for each gameweek read, keyed by ``(entry_id, gameweek)``.

        A team whose picks will not read loses its squad for that gameweek, with a warning; the
        other teams keep theirs (NFR-15).
        """
        rows: list[dict[str, Any]] = []
        for (entry_id, gameweek), payload in sorted(picks.items()):
            try:
                rows.extend(
                    {
                        "entry_id": entry_id,
                        "gameweek": gameweek,
                        "player_id": int(pick["element"]),
                        "slot": int(pick["position"]),
                        "multiplier": int(pick["multiplier"]),
                        "is_captain": bool(pick.get("is_captain")),
                        "is_vice_captain": bool(pick.get("is_vice_captain")),
                    }
                    for pick in payload.get("picks") or []
                )
            except (KeyError, ValueError, TypeError) as exc:
                rows = [r for r in rows if (r["entry_id"], r["gameweek"]) != (entry_id, gameweek)]
                warnings.append(
                    f"malformed picks for league entry {entry_id} in gameweek {gameweek}: {exc!r}"
                )
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
        live: _LiveGameweek | None = None,
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
            if not event.get("finished") or (live is not None and event["id"] == live.gameweek):
                continue
            payload = self.fetch_entry_picks(entry_id, int(event["id"]), request)
            if payload is not None:
                picks[int(event["id"])] = payload
        live_rows: list[dict[str, Any]] = []
        if live is not None:
            try:
                captured = self._live_picks(entry_id, live, request)
            except SourceError:
                # Squad state does not need them: the last finished picks and the transfers since
                # reconstruct the same squad (DP-15).
                warnings.append(f"no picks snapshot for gameweek {live.gameweek}")
                captured = None
            if captured is not None:
                picks[live.gameweek] = captured[0]
                row = self._entry_live(entry_id, live, *captured)
                if row is not None:
                    live_rows.append(row)
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
            Table.ENTRY_LIVE.value: pd.DataFrame(live_rows, columns=columns_for(Table.ENTRY_LIVE)),
        }

    # --- ingest --------------------------------------------------------------------------

    def ingest(self, request: IngestRequest) -> IngestReport:
        report = IngestReport(source=self.name)
        before_calls = self.fetcher.network_calls
        before_hits = self.fetcher.cache_hits

        bootstrap, capture = self._capture("bootstrap_static", "bootstrap-static/", "all", request)
        bootstrap = cast(dict[str, Any], bootstrap)
        report.resources["bootstrap_static"] = 1

        fixtures = self.fetch_fixtures(request)
        report.resources["fixtures"] = 1
        log.info("fpl.fixtures", extra={"count": len(fixtures)})
        live = _live_gameweek(bootstrap, request.now or utcnow())

        # ~700 requests, several minutes. It is declared off the fast path, and the fast cadence
        # fires every four hours, hourly within a day of a deadline and while a gameweek is in
        # play, so honouring that declaration is what keeps the frequent workflow measured in
        # seconds (Architecture §9). The one exception is the firing whose capture is the first to
        # show a gameweek data-checked: its rows are final only now, and the run that firing starts
        # evaluates it, so it sweeps the summaries that predate the check, and only those
        # (LIVE-07). Keyed on the gameweek checked, not the live one: a gameweek checked after the
        # next deadline has passed is no longer the live gameweek, and is still evaluated by that
        # run. Every later firing leaves the summaries alone, without walking them.
        fetched = 0
        checked = self._newly_checked(bootstrap, capture)
        if not self.wants("element_summary", request, checked=checked):
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
        played = 0
        if self.wants("event_live", request):
            for event in bootstrap["events"]:
                if not event.get("finished") or (live is not None and event["id"] == live.gameweek):
                    continue
                try:
                    self.fetch_event_live(int(event["id"]), request)
                    played += 1
                except SourceNotFoundError, OfflineWithoutSnapshotError:
                    report.warnings.append(f"no live data for gameweek {event['id']}")
        if live is not None and self.wants("event_live", request, in_play=True):
            fresh = self._fresh_from(
                "event_live", live.key, live, request, self._scores_from(live, request)
            )
            try:
                self.fetch_event_live(live.gameweek, request, fresh_from=fresh)
                played += 1
            except SourceError as exc:
                # The live view loses its scores; nothing decided reads them (DP-15).
                report.warnings.append(f"no live scores for gameweek {live.gameweek}: {exc}")
        report.resources["event_live"] = played

        if request.league_id is not None and self.wants(
            "league_standings", request, in_play=live is not None
        ):
            report.resources.update(
                self._ingest_league(request.league_id, bootstrap, request, report, live)
            )

        if request.entry_id is not None:
            report.resources.update(
                self._ingest_entry(request.entry_id, bootstrap, request, report, live)
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
        live: _LiveGameweek | None = None,
    ) -> dict[str, int]:
        """The configured mini-league: its table, and the squads of the entries near the top.

        Standings are one request. Squads are one request *per entry*, which is why the number of
        entries read is a configured budget rather than "everyone in the league" — a public league
        can hold hundreds of thousands of them. The last finished gameweek's squads and moves are
        the full cadence's; the live gameweek's squads are fetched on either cadence, once a team.
        """
        counts: dict[str, int] = {}
        fresh = (
            None
            if live is None
            else self._fresh_from(
                "league_standings", str(league_id), live, request, self._scores_from(live, request)
            )
        )
        try:
            standings = self.fetch_league_standings(league_id, request, fresh_from=fresh)
        except SourceNotFoundError, OfflineWithoutSnapshotError:
            report.warnings.append(f"league {league_id} unavailable")
            return counts
        counts["league_standings"] = 1
        rivals = _league_entry_ids(standings, request.league_rival_limit)

        if live is not None:
            picked = 0
            for entry_id in rivals:
                try:
                    if self._live_picks(entry_id, live, request) is not None:
                        picked += 1
                except SourceError as exc:
                    # This team is not live; every other one is (NFR-15).
                    report.warnings.append(
                        f"no picks for league entry {entry_id} in gameweek {live.gameweek}: {exc}"
                    )
            counts["league_live_picks"] = picked

        gameweek = _latest_finished_gameweek(bootstrap)
        if gameweek is None or not self.wants("league_standings", request):
            # Preseason, nobody has picks yet, not even the owner (DL-20), so the standings alone
            # are the honest answer; or the fast cadence, which leaves these to the full one.
            return counts

        fetched = moves = 0
        for entry_id in rivals:
            if live is None or gameweek != live.gameweek:
                try:
                    if self.fetch_entry_picks(entry_id, gameweek, request) is not None:
                        fetched += 1
                except SourceError as exc:
                    report.warnings.append(f"no picks for league entry {entry_id}: {exc}")
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
        live: _LiveGameweek | None = None,
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
            if not event.get("finished") or (live is not None and event["id"] == live.gameweek):
                continue
            try:
                if self.fetch_entry_picks(entry_id, int(event["id"]), request) is not None:
                    picks += 1
            except OfflineWithoutSnapshotError:
                report.warnings.append(f"no picks snapshot for gameweek {event['id']}")
        if live is not None:
            try:
                if self._live_picks(entry_id, live, request) is not None:
                    picks += 1
            except SourceError as exc:
                report.warnings.append(f"no picks for gameweek {live.gameweek}: {exc}")
        counts["entry_picks"] = picks
        return counts
