"""LIVE-01: the gameweek being played, ingested — picks once, live scores, ``player_live``.

The recorded bootstrap and fixtures, with GW1's deadline behind the pinned clock: GW1 is the
gameweek in play. The owner is entry 9; the league's published rivals are 7 and 8.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
import respx

from conftest import isolated_environ
from fpl_dof.config import load_config
from fpl_dof.config.models import FeatureConfig, HttpConfig, RateLimitConfig, RetryConfig
from fpl_dof.factory.registry import Strategy, champion
from fpl_dof.forecast.features import LeakageError, assert_no_look_ahead, build_features
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.silver.store import read_table_optional, table_path
from fpl_dof.silver.tables import (
    PROVISIONAL,
    SchemaViolationError,
    Table,
    require_past_deadline,
    validate,
)
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fpl.adapter import FplApiAdapter
from fpl_dof.stages import transform

FIXTURES = Path(__file__).parent / "fixtures"
BASE = FplApiAdapter.base_url
OWNER, RIVALS = 9, (7, 8)
DEADLINE = pd.Timestamp("2026-08-21T17:30:00Z")


def at(stamp: str) -> dt.datetime:
    return pd.Timestamp(stamp).to_pydatetime()


AFTER_DEADLINE = at("2026-08-21T18:00:00Z")  # GW1 in play, its first match not yet kicked off
SECOND_MATCHDAY = at("2026-08-23T20:00:00Z")
CHECKED = at("2026-08-25T09:00:00Z")  # FPL has finished and data-checked GW1
LATER = at("2026-08-25T15:00:00Z")


def load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def bootstrap(*, checked: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = load("bootstrap_static")
    data["events"][0].update(finished=checked, data_checked=checked)
    return data


def fixtures(*, played: bool) -> list[dict[str, Any]]:
    """Fixture 1 (clubs 1 v 7) played to full time with bonus confirmed when ``played``; fixture 7
    (clubs 5 v 2) still to kick off."""
    data: list[dict[str, Any]] = load("fixtures")
    if played:
        first = next(f for f in data if f["id"] == 1)
        first.update(started=True, finished_provisional=True, finished=True)
    return data


#: Player 1 (club 1) played fixture 1: 90 minutes, a goal and a bonus point.
LIVE = {
    "elements": [
        {
            "id": 1,
            "stats": {"minutes": 90, "total_points": 7, "bps": 31, "bonus": 1},
            "explain": [
                {
                    "fixture": 1,
                    "stats": [
                        {"identifier": "minutes", "points": 2, "value": 90},
                        {"identifier": "goals_scored", "points": 4, "value": 1},
                        {"identifier": "bonus", "points": 1, "value": 1},
                    ],
                }
            ],
        }
    ]
}
STANDINGS = {
    "league": {"id": 42, "name": "L"},
    "standings": {
        "results": [
            {"entry": e, "entry_name": "n", "player_name": "p", "rank": r, "total": 9}
            for r, e in enumerate(RIVALS, start=1)
        ]
    },
}


def picks(entry_id: int) -> dict[str, Any]:
    return {
        "picks": [
            {
                "element": element,
                "position": slot,
                "multiplier": 2 if slot == 1 else 1,
                "is_captain": slot == 1,
                "is_vice_captain": slot == 2,
            }
            for slot, element in enumerate((1, 57, 61), start=1)
        ],
        "entry_history": {
            "event": 1,
            "points": 40 + entry_id,
            "total_points": 40 + entry_id,
            "event_transfers_cost": 4 if entry_id == 7 else 0,
        },
        "active_chip": "3xc" if entry_id == 7 else None,
    }


class Api:
    """The mocked API, with a switch for each state of the world the tests move through."""

    def __init__(self, mock: respx.MockRouter) -> None:
        self.mock = mock
        self.serve(checked=False, played=False)
        for element_id, summary in load("element_summary").items():
            mock.get(f"{BASE}/element-summary/{element_id}/").mock(
                return_value=httpx.Response(200, json=summary)
            )
        mock.get(f"{BASE}/team/set-piece-notes/").mock(
            return_value=httpx.Response(200, json={"teams": []})
        )
        mock.get(url__regex=rf"{BASE}/event/\d+/live/").mock(
            return_value=httpx.Response(200, json=LIVE)
        )
        mock.get(f"{BASE}/leagues-classic/42/standings/").mock(
            return_value=httpx.Response(200, json=STANDINGS)
        )
        mock.get(f"{BASE}/entry/{OWNER}/").mock(
            return_value=httpx.Response(200, json={"id": OWNER, "name": "Owner"})
        )
        mock.get(url__regex=rf"{BASE}/entry/\d+/history/").mock(
            return_value=httpx.Response(200, json={"current": [], "past": [], "chips": []})
        )
        mock.get(url__regex=rf"{BASE}/entry/\d+/transfers/").mock(
            return_value=httpx.Response(200, json=[])
        )
        for entry_id in (OWNER, *RIVALS):
            self.picks(entry_id, httpx.Response(200, json=picks(entry_id)))

    def serve(self, *, checked: bool, played: bool) -> None:
        self.mock.get(f"{BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap(checked=checked))
        )
        self.mock.get(f"{BASE}/fixtures/").mock(
            return_value=httpx.Response(200, json=fixtures(played=played))
        )

    def picks(self, entry_id: int, response: httpx.Response) -> None:
        self.mock.get(f"{BASE}/entry/{entry_id}/event/1/picks/").mock(return_value=response)

    def requests(self, fragment: str) -> int:
        return sum(fragment in str(call.request.url) for call in self.mock.calls)


@pytest.fixture
def api() -> Iterator[Api]:
    with respx.mock(assert_all_called=False) as mock:
        yield Api(mock)


@pytest.fixture
def adapter(tmp_path: Path) -> Iterator[FplApiAdapter]:
    config = HttpConfig(
        rate_limit=RateLimitConfig(requests_per_second=1000.0),
        retry=RetryConfig(max_attempts=1, backoff_base_seconds=0.001),
    )
    with Fetcher(
        config=config, bronze=BronzeStore(tmp_path / "bronze"), run_id="r", sleep=lambda _s: None
    ) as fetcher:
        yield FplApiAdapter(fetcher)


def request(now: dt.datetime, *, fast: bool = True, offline: bool = False) -> IngestRequest:
    return IngestRequest(
        run_id="r",
        now=now,
        fast_path_only=fast,
        offline=offline,
        entry_id=OWNER,
        league_id=42,
        league_rival_limit=5,
    )


def conform(adapter: FplApiAdapter, now: dt.datetime) -> tuple[dict[str, pd.DataFrame], list[str]]:
    conformed = adapter.conform(request(now, fast=False, offline=True))
    return conformed.tables, conformed.warnings


# --- picks once per entry --------------------------------------------------------------------


def test_the_gameweek_in_plays_picks_are_fetched_once_per_entry(
    api: Api, adapter: FplApiAdapter
) -> None:
    """A second matchday fetches no picks; the live scores and the table are fetched again."""
    adapter.ingest(request(AFTER_DEADLINE))
    assert api.requests("/event/1/picks/") == 3  # the owner and both rivals
    assert api.requests("/event/1/live/") == 1
    assert api.requests("/standings/") == 1

    api.serve(checked=False, played=True)
    report = adapter.ingest(request(SECOND_MATCHDAY))
    assert api.requests("/event/1/picks/") == 3, "a matchday costs no picks requests"
    assert api.requests("/event/1/live/") == 2, "the live scores are as fresh as the fixtures"
    assert api.requests("/standings/") == 2
    assert report.resources["league_live_picks"] == 2
    assert report.resources["entry_picks"] == 1

    # The slow ingest the same day reads the same captures: picks are still not refetched.
    adapter.ingest(request(SECOND_MATCHDAY, fast=False))
    assert api.requests("/event/1/picks/") == 3


def test_once_checked_each_teams_picks_and_the_scores_are_fetched_once_more_for_good(
    api: Api, adapter: FplApiAdapter
) -> None:
    """The game's final figures ride on the picks' own ``entry_history`` (LIVE-03's check)."""
    adapter.ingest(request(AFTER_DEADLINE))
    api.serve(checked=True, played=True)
    adapter.ingest(request(CHECKED))
    assert api.requests("/event/1/picks/") == 6
    assert api.requests("/event/1/live/") == 2
    assert api.requests("/standings/") == 2

    adapter.ingest(request(LATER))
    adapter.ingest(request(LATER, fast=False))
    assert api.requests("/event/1/picks/") == 6, "final picks are never fetched again"
    assert api.requests("/event/1/live/") == 2
    assert api.requests("/standings/") == 2


def test_preseason_fetches_nothing_for_a_gameweek_in_play(api: Api, adapter: FplApiAdapter) -> None:
    adapter.ingest(request(at("2026-08-15T12:00:00Z")))
    assert api.requests("/picks/") == 0
    assert api.requests("/live/") == 0
    assert api.requests("/standings/") == 0  # off the fast path, and nothing is in play


# --- one rival failing degrades that team only (NFR-15) -----------------------------------------


def test_one_rivals_picks_failing_degrades_that_team_only(api: Api, adapter: FplApiAdapter) -> None:
    api.picks(8, httpx.Response(500))
    report = adapter.ingest(request(AFTER_DEADLINE))

    assert report.resources["league_live_picks"] == 1
    assert any("league entry 8" in warning for warning in report.warnings)

    tables, warnings = conform(adapter, AFTER_DEADLINE)
    league = validate(Table.LEAGUE_PICK, tables[Table.LEAGUE_PICK.value])
    assert set(league["entry_id"]) == {7}
    assert set(league["gameweek"]) == {1}
    assert sorted(tables[Table.ENTRY_LIVE.value]["entry_id"]) == [7, 9]
    assert len(tables[Table.LEAGUE_STANDING.value]) == 2
    assert any("league entry 8" in warning for warning in warnings)


def test_one_rivals_malformed_picks_degrade_that_team_only(
    api: Api, adapter: FplApiAdapter
) -> None:
    broken = picks(8)
    broken["picks"][0]["element"] = None  # the shape check passes; the row does not read
    api.picks(8, httpx.Response(200, json=broken))
    adapter.ingest(request(AFTER_DEADLINE))

    tables, warnings = conform(adapter, AFTER_DEADLINE)
    assert set(tables[Table.LEAGUE_PICK.value]["entry_id"]) == {7}
    assert any("malformed picks for league entry 8" in warning for warning in warnings)


# --- silver: the in-play picks, entry_live and player_live ---------------------------------------


def test_the_in_play_picks_reach_the_existing_pick_tables_and_entry_live(
    api: Api, adapter: FplApiAdapter
) -> None:
    adapter.ingest(request(AFTER_DEADLINE))
    tables, _ = conform(adapter, AFTER_DEADLINE)

    owner = validate(Table.ENTRY_PICK, tables[Table.ENTRY_PICK.value])
    assert set(owner["gameweek"]) == {1} and len(owner) == 3
    live = validate(Table.ENTRY_LIVE, tables[Table.ENTRY_LIVE.value]).set_index("entry_id")
    assert live.loc[7, "transfers_cost"] == 4 and live.loc[7, "chip"] == "3xc"
    assert live.loc[9, "points"] == 49
    assert live["provisional"].all()

    # The season log's table is untouched: it still holds finished gameweeks only (DL-69).
    assert tables[Table.ENTRY_GAMEWEEK.value].empty


def test_player_live_holds_the_gameweek_in_play_per_player_and_fixture(
    api: Api, adapter: FplApiAdapter
) -> None:
    adapter.ingest(request(AFTER_DEADLINE))
    api.serve(checked=False, played=True)
    adapter.ingest(request(SECOND_MATCHDAY))
    tables, _ = conform(adapter, SECOND_MATCHDAY)
    live = validate(Table.PLAYER_LIVE, tables[Table.PLAYER_LIVE.value])

    assert set(live["gameweek"]) == {1}, "the gameweek in play, and no other"
    assert live[PROVISIONAL].all()
    assert (live["observed_at"] >= DEADLINE).all()
    scored = live[(live["player_id"] == 1) & (live["fixture_id"] == 1)].iloc[0].to_dict()
    assert (scored["minutes"], scored["points"], scored["bonus"], scored["bps"]) == (90, 7, 1, 31)
    assert bool(scored["finished"]) and bool(scored["bonus_confirmed"])

    # Every other player whose club plays has a row of zeros: one in fixture 1 (clubs 1 and 7),
    # played without him, and one in fixture 7 (clubs 5 and 2), still to kick off.
    players = pd.DataFrame(bootstrap()["elements"])
    clubs = players.set_index("id")["team"]
    assert len(live) == int(clubs.isin([1, 7, 5, 2]).sum())
    waiting = live[live["fixture_id"] == 7]
    assert set(clubs[waiting["player_id"]]) == {5, 2}
    assert (waiting["minutes"] == 0).all() and not waiting["finished"].any()
    idle = live[(live["fixture_id"] == 1) & (live["player_id"] != 1)]
    assert (idle["minutes"] == 0).all() and idle["finished"].all()


def test_player_live_is_final_once_captured_after_the_check(
    api: Api, adapter: FplApiAdapter
) -> None:
    adapter.ingest(request(AFTER_DEADLINE))
    api.serve(checked=True, played=True)
    adapter.ingest(request(CHECKED))
    tables, _ = conform(adapter, CHECKED)
    assert not tables[Table.PLAYER_LIVE.value][PROVISIONAL].any()
    assert not tables[Table.ENTRY_LIVE.value][PROVISIONAL].any()


def test_a_live_row_for_a_gameweek_not_past_its_deadline_is_refused() -> None:
    gameweeks = pd.DataFrame(
        {"gameweek": [1, 2], "deadline_time": [DEADLINE, pd.Timestamp("2026-08-28T17:30:00Z")]}
    )
    row = {"gameweek": 2, "observed_at": pd.Timestamp("2026-08-29T10:00:00Z")}

    require_past_deadline(
        Table.PLAYER_LIVE, pd.DataFrame([row]), gameweeks, pd.Timestamp("2026-08-29T11:00Z")
    )
    with pytest.raises(SchemaViolationError, match="gameweek 2"):  # the deadline is still ahead
        require_past_deadline(
            Table.PLAYER_LIVE, pd.DataFrame([row]), gameweeks, pd.Timestamp("2026-08-27T11:00Z")
        )
    early = {"gameweek": 2, "observed_at": pd.Timestamp("2026-08-28T17:00:00Z")}
    with pytest.raises(SchemaViolationError, match="gameweek 2"):  # captured before it
        require_past_deadline(
            Table.ENTRY_LIVE, pd.DataFrame([early]), gameweeks, pd.Timestamp("2026-08-29T11:00Z")
        )


def test_player_live_holds_one_gameweek() -> None:
    row = {
        "gameweek": 1,
        "observed_at": DEADLINE,
        PROVISIONAL: True,
        "fixture_id": 1,
        "player_id": 1,
        "minutes": 0,
        "points": 0,
        "bonus": 0,
        "bps": None,
        "finished": False,
        "bonus_confirmed": False,
    }
    with pytest.raises(SchemaViolationError):
        validate(Table.PLAYER_LIVE, pd.DataFrame([row, {**row, "gameweek": 2}]))


# --- the transform: written while live, removed when not --------------------------------------


def test_transform_writes_player_live_and_removes_it_once_no_gameweek_is_live(
    api: Api, tmp_path: Path
) -> None:
    config, _ = load_config(environ=isolated_environ(tmp_path), local_override=None)
    layout = DataLayout(root=config.runtime.data_dir)
    layout.ensure()
    preseason = at("2026-08-15T12:00:00Z")
    with Fetcher(
        config=config.http, bronze=BronzeStore(layout.bronze), run_id="r", sleep=lambda _s: None
    ) as fetcher:
        FplApiAdapter(fetcher).ingest(IngestRequest(run_id="r", now=preseason))
        api.serve(checked=False, played=True)
        FplApiAdapter(fetcher).ingest(IngestRequest(run_id="r", now=SECOND_MATCHDAY))

    transform.run(StageContext(config=config, layout=layout, run_id="r", as_of=SECOND_MATCHDAY))
    live = read_table_optional(layout.silver, "2026/27", Table.PLAYER_LIVE)
    assert live is not None and set(live["gameweek"]) == {1}

    # The same bronze read as of preseason: nothing is live, and the old copy is not left behind.
    transform.run(StageContext(config=config, layout=layout, run_id="r", as_of=preseason))
    assert not table_path(layout.silver, "2026/27", Table.PLAYER_LIVE).exists()


# --- provisional rows are never features (Invariant 5) ------------------------------------------


def _live_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gameweek": [1],
            "player_id": [1],
            "player_code": [1001],
            "kickoff_time": [DEADLINE],
            PROVISIONAL: [True],
        }
    )


def test_a_feature_build_that_reads_player_live_fails_the_look_ahead_gate() -> None:
    with pytest.raises(LeakageError, match="player_gameweek only"):
        build_features(_live_frame(), as_of=DEADLINE, config=FeatureConfig())
    features = pd.DataFrame({"player_code": [1001], "as_of": [DEADLINE]})
    with pytest.raises(LeakageError, match="player_gameweek only"):
        assert_no_look_ahead(features, _live_frame(), as_of=DEADLINE)


def test_only_the_live_scores_and_the_table_join_the_fast_path_while_in_play(
    adapter: FplApiAdapter,
) -> None:
    """One or two requests a firing, and nothing per player (Architecture §9)."""
    fast = request(AFTER_DEADLINE)
    joined = {
        r.name
        for r in FplApiAdapter.resources
        if adapter.wants(r.name, fast, in_play=True) and not adapter.wants(r.name, fast)
    }
    assert joined == {"event_live", "league_standings"}


def test_no_strategy_may_require_the_live_tables() -> None:
    entry = champion().model_dump()
    entry["requires"] = [Table.PLAYER_GAMEWEEK, Table.PLAYER_LIVE]
    with pytest.raises(ValueError, match="player_live"):
        Strategy.model_validate(entry)
