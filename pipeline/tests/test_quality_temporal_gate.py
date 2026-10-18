"""Tests for PIPE-10: Automated temporal non-leakage quality gate."""

from __future__ import annotations

import pandas as pd

from fpl_dof.quality.gates import GateOutcome, GateSeverity, run_gates
from fpl_dof.quality.rules import GATES, _temporal_monotonicity_and_containment
from fpl_dof.silver.tables import Table


def _gameweek_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "gameweek": 1,
                "name": "Gameweek 1",
                "deadline_time": pd.Timestamp("2026-08-15T10:00:00Z"),
                "finished": True,
                "is_next": False,
            },
            {
                "gameweek": 2,
                "name": "Gameweek 2",
                "deadline_time": pd.Timestamp("2026-08-22T10:00:00Z"),
                "finished": False,
                "is_next": True,
            },
        ]
    )


def test_temporal_gate_passes_on_clean_data() -> None:
    gw_df = _gameweek_table()
    now = pd.Timestamp("2026-08-20T12:00:00Z")
    price_df = pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-08-14T08:00:00Z"),
                "player_id": 1,
                "player_code": 1001,
                "price": 10.0,
                "selected_by_percent": 15.0,
                "transfers_in_event": 0,
                "transfers_out_event": 0,
                "cost_change_event": 0.0,
                "cost_change_start": 0.0,
            },
            {
                "observed_at": pd.Timestamp("2026-08-15T08:00:00Z"),
                "player_id": 1,
                "player_code": 1001,
                "price": 10.1,
                "selected_by_percent": 15.5,
                "transfers_in_event": 1000,
                "transfers_out_event": 0,
                "cost_change_event": 0.1,
                "cost_change_start": 0.1,
            },
        ]
    )
    metric_df = pd.DataFrame(
        [
            {
                "season": "2026/27",
                "as_of_gameweek": 1,
                "player_code": 1001,
                "timestamp": pd.Timestamp("2026-08-15T09:30:00Z"),
            }
        ]
    )
    tables = {
        Table.GAMEWEEK.value: gw_df,
        Table.PRICE_HISTORY.value: price_df,
        Table.PLAYER_METRIC.value: metric_df,
    }
    context = {"now": now, "tables": tables}
    ok, msg, _details = _temporal_monotonicity_and_containment(gw_df, context)
    assert ok
    assert "respect gameweek deadlines" in msg


def test_temporal_gate_catches_future_dated_price_history() -> None:
    gw_df = _gameweek_table()
    now = pd.Timestamp("2026-08-20T12:00:00Z")
    future_price_df = pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-08-25T08:00:00Z"),  # In the future!
                "player_id": 42,
                "player_code": 1042,
                "price": 8.0,
            }
        ]
    )
    tables = {
        Table.GAMEWEEK.value: gw_df,
        Table.PRICE_HISTORY.value: future_price_df,
    }
    context = {"now": now, "tables": tables}
    ok, msg, details = _temporal_monotonicity_and_containment(gw_df, context)
    assert not ok
    assert "future-dated observation" in msg
    assert details["violating_entity"] == "player_id=42"
    assert "2026-08-25" in str(details["timestamp"])
    assert "2026-08-20" in str(details["deadline"])


def test_temporal_gate_catches_non_monotonic_price_history() -> None:
    gw_df = _gameweek_table()
    now = pd.Timestamp("2026-08-20T12:00:00Z")
    non_monotonic_df = pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-08-15T08:00:00Z"),
                "player_id": 7,
            },
            {
                "observed_at": pd.Timestamp("2026-08-14T08:00:00Z"),  # Goes backwards!
                "player_id": 7,
            },
        ]
    )
    tables = {
        Table.GAMEWEEK.value: gw_df,
        Table.PRICE_HISTORY.value: non_monotonic_df,
    }
    context = {"now": now, "tables": tables}
    ok, msg, details = _temporal_monotonicity_and_containment(gw_df, context)
    assert not ok
    assert "not strictly monotonic" in msg
    assert details["violating_entity"] == "player_id=7"


def test_temporal_gate_catches_post_deadline_observation_leakage() -> None:
    gw_df = _gameweek_table()
    now = pd.Timestamp("2026-08-20T12:00:00Z")
    leaked_metric_df = pd.DataFrame(
        [
            {
                "season": "2026/27",
                "as_of_gameweek": 1,  # GW1 deadline is 2026-08-15T10:00:00Z
                "player_code": 999,
                "timestamp": pd.Timestamp("2026-08-15T16:00:00Z"),  # 6 hours after deadline!
            }
        ]
    )
    tables = {
        Table.GAMEWEEK.value: gw_df,
        Table.PLAYER_METRIC.value: leaked_metric_df,
    }
    context = {"now": now, "tables": tables}
    ok, msg, details = _temporal_monotonicity_and_containment(gw_df, context)
    assert not ok
    assert "after GW1 deadline" in msg
    assert details["violating_entity"] == "player_code=999"
    assert "2026-08-15 16:00:00" in str(details["timestamp"])
    assert "2026-08-15 10:00:00" in str(details["deadline"])


def test_temporal_gate_blocks_publication_via_run_gates() -> None:
    gw_df = _gameweek_table()
    now = pd.Timestamp("2026-08-20T12:00:00Z")
    leaked_metric_df = pd.DataFrame(
        [
            {
                "season": "2026/27",
                "as_of_gameweek": 1,
                "player_code": 55,
                "timestamp": pd.Timestamp("2026-08-15T18:00:00Z"),
            }
        ]
    )
    tables = {
        Table.GAMEWEEK.value: gw_df,
        Table.PLAYER_METRIC.value: leaked_metric_df,
    }
    context = {"now": now, "tables": tables}
    report = run_gates(GATES, tables, context)
    # The gate is blocking because severity is ERROR
    temporal_results = [
        r for r in report.results if r.gate == "temporal_monotonicity_and_containment"
    ]
    assert len(temporal_results) == 1
    assert temporal_results[0].outcome == GateOutcome.FAILED
    assert temporal_results[0].severity == GateSeverity.ERROR
    assert temporal_results[0].blocks_publication
    assert not report.passed
