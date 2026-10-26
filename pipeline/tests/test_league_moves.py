"""ORC-14: rivals' transfers, hits and chips - ingest, silver and the published ``league.json``."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
import respx

from fpl_dof.config.models import HttpConfig, RateLimitConfig, RetryConfig
from fpl_dof.publish.contract import Contract, find_contracts_root
from fpl_dof.publish.league import build_league
from fpl_dof.silver.tables import Table, validate
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fpl.adapter import FplApiAdapter

BASE = FplApiAdapter.base_url
BOOTSTRAP: dict[str, Any] = {"events": [{"id": 2, "finished": True}, {"id": 3, "finished": False}]}
STANDINGS = {
    "league": {"id": 42, "name": "L"},
    "standings": {
        "results": [
            {"entry": 7, "entry_name": "A", "player_name": "P", "rank": 1, "total": 9},
            {"entry": 8, "entry_name": "B", "player_name": "Q", "rank": 2, "total": 8},
        ]
    },
}
HISTORY = {
    "current": [
        {"event": 1, "event_transfers": 0, "event_transfers_cost": 0, "total_points": 60},
        {"event": 2, "event_transfers": 3, "event_transfers_cost": 8, "total_points": 103},
        # The gameweek in play: its row moves with every kick-off, so it is not kept.
        {"event": 3, "event_transfers": 0, "event_transfers_cost": 0, "total_points": 110},
    ],
    "chips": [{"name": "wildcard", "event": 2}],
}
TRANSFERS = [
    {"event": 1, "element_in": 9, "element_out": 8},
    {"event": 2, "element_in": 11, "element_out": 10},
    {"event": 2, "element_in": 13, "element_out": 12},
]


@pytest.fixture
def adapter(tmp_path: Path) -> Iterator[FplApiAdapter]:
    config = HttpConfig(
        rate_limit=RateLimitConfig(requests_per_second=1000.0),
        retry=RetryConfig(max_attempts=1, backoff_base_seconds=0.001),
    )
    with Fetcher(
        config=config, bronze=BronzeStore(tmp_path / "b"), run_id="r", sleep=lambda _s: None
    ) as fetcher:
        yield FplApiAdapter(fetcher)


def _mock(mock: respx.MockRouter, *, failing: int | None, malformed: int | None = None) -> None:
    mock.get(f"{BASE}/leagues-classic/42/standings/").mock(
        return_value=httpx.Response(200, json=STANDINGS)
    )
    mock.get(url__regex=rf"{BASE}/entry/\d+/event/2/picks/").mock(
        return_value=httpx.Response(200, json={"picks": []})
    )
    for entry in (7, 8):
        broken = entry == failing
        mock.get(f"{BASE}/entry/{entry}/history/").mock(
            return_value=httpx.Response(500) if broken else httpx.Response(200, json=HISTORY)
        )
        # A list of rows passes the shape check; one row with no player in is still unreadable.
        rows = [*TRANSFERS, {"event": 2, "element_in": None}] if entry == malformed else TRANSFERS
        mock.get(f"{BASE}/entry/{entry}/transfers/").mock(
            return_value=httpx.Response(200, json=rows)
        )


def _conform(
    adapter: FplApiAdapter, failing: int | None = None, malformed: int | None = None
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    warnings: list[str] = []
    with respx.mock(assert_all_called=False) as mock:
        _mock(mock, failing=failing, malformed=malformed)
        tables = adapter._conform_league(
            42, BOOTSTRAP, IngestRequest(run_id="r", league_id=42, league_rival_limit=5), warnings
        )
    return tables, warnings


def test_a_rivals_finished_gameweek_moves_are_conformed(adapter: FplApiAdapter) -> None:
    tables, warnings = _conform(adapter)

    weeks = validate(Table.LEAGUE_GAMEWEEK, tables["league_gameweek"])
    assert sorted(weeks["entry_id"]) == [7, 8]
    assert set(weeks["gameweek"]) == {2}, "finished gameweeks only"
    row = weeks.iloc[0]
    assert (row["gameweek"], row["transfers"], row["transfers_cost"], row["chip"]) == (
        2,
        3,
        8,
        "wildcard",
    )
    # The total after it, net of every hit: what the gameweek after it stands on live (LIVE-03).
    assert row["total_points"] == 103
    moved = validate(Table.LEAGUE_TRANSFER, tables["league_transfer"])
    assert len(moved) == 4  # gameweek 1's transfer is not the published gameweek's
    assert warnings == []


def test_one_failing_rival_degrades_only_that_team(adapter: FplApiAdapter) -> None:
    tables, warnings = _conform(adapter, failing=8)

    assert list(tables["league_gameweek"]["entry_id"]) == [7]
    assert list(tables["league_transfer"]["entry_id"].unique()) == [7]
    assert any("league entry 8" in w for w in warnings)
    assert len(tables["league_standing"]) == 2


def test_a_malformed_rival_row_degrades_only_that_team(adapter: FplApiAdapter) -> None:
    """DP-15: a row the fetch's shape check lets through degrades its team, with a warning."""
    tables, warnings = _conform(adapter, malformed=8)

    assert list(tables["league_gameweek"]["entry_id"]) == [7]
    assert list(tables["league_transfer"]["entry_id"].unique()) == [7]
    assert any("league entry 8" in w and "malformed" in w for w in warnings)
    assert len(tables["league_standing"]) == 2


def test_moves_publish_and_a_missing_team_is_null() -> None:
    contract = Contract(root=find_contracts_root())
    standings = pd.DataFrame(
        [
            {
                "league_id": 42,
                "league_name": "L",
                "entry_id": e,
                "entry_name": "n",
                "player_name": "p",
                "rank": e - 6,
                "last_rank": 1,
                "event_total": 1,
                "total": 5,
            }
            for e in (7, 8)
        ]
    )
    weeks = pd.DataFrame(
        [{"entry_id": 7, "gameweek": 2, "transfers": 3, "transfers_cost": 8, "chip": "3xc"}]
    )
    moved = pd.DataFrame([{"entry_id": 7, "gameweek": 2, "player_in_id": 11, "player_out_id": 10}])
    payload = build_league(
        standings=standings,
        league_picks=None,
        entry_picks=None,
        league_gameweeks=weeks,
        league_transfers=moved,
        owner_entry_id=None,
        gameweek=2,
        squad_limit=5,
        contract_version=1,
    )

    contract.validate("league", payload)
    first, second = payload["entries"]
    assert first["moves"] == {
        "gameweek": 2,
        "hit_cost": 8,
        "chip": "3xc",
        # Named as the game shows it, not by the API's id (as the plan's chip labels).
        "chip_label": "Triple Captain",
        "transfers": [{"out_id": 10, "in_id": 11}],
    }
    assert second["moves"] is None
