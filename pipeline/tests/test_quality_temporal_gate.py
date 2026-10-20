"""PIPE-10, REM-09: the look-ahead gate, on frames the strict silver schemas accept.

Every frame here is validated against its schema before the gate sees it. A gate tested on columns
silver never holds passes its tests and never fires on a real run, which is how this one shipped
the first time (DL-83).
"""

from __future__ import annotations

import pandas as pd

from fpl_dof.quality.gates import GateOutcome, GateSeverity, run_gates
from fpl_dof.quality.rules import GATES, _temporal_monotonicity_and_containment
from fpl_dof.silver.tables import ADVANCED_METRICS, Table, validate

SEASON = "2026/27"
GW1_DEADLINE = pd.Timestamp("2026-08-15T10:00:00Z")
GW2_DEADLINE = pd.Timestamp("2026-08-22T10:00:00Z")
NOW = pd.Timestamp("2026-08-20T12:00:00Z")


def _gameweeks() -> pd.DataFrame:
    return validate(
        Table.GAMEWEEK,
        pd.DataFrame(
            {
                "gameweek": [1, 2],
                "name": ["Gameweek 1", "Gameweek 2"],
                "deadline_time": [GW1_DEADLINE, GW2_DEADLINE],
                "finished": [True, False],
                "is_next": [False, True],
            }
        ),
    )


def _prices(*rows: tuple[str, int]) -> pd.DataFrame:
    return validate(
        Table.PRICE_HISTORY,
        pd.DataFrame(
            [
                {
                    "observed_at": pd.Timestamp(when),
                    "player_id": player,
                    "player_code": 1000 + player,
                    "price": 10.0,
                    "selected_by_percent": 15.0,
                    "transfers_in_event": 0,
                    "transfers_out_event": 0,
                    "cost_change_event": 0.0,
                    "cost_change_start": 0.0,
                }
                for when, player in rows
            ]
        ),
    )


def _metric(as_of_gameweek: int, observed_at: str, season: str = SEASON) -> pd.DataFrame:
    return validate(
        Table.PLAYER_METRIC,
        pd.DataFrame(
            [
                {
                    **dict.fromkeys(ADVANCED_METRICS, 1.0),
                    "season": season,
                    "as_of_gameweek": as_of_gameweek,
                    "observed_at": pd.Timestamp(observed_at),
                    "player_id": 9,
                    "player_code": 999,
                    "scope": "season",
                    "gameweek": None,
                    "sources": "a",
                }
            ]
        ),
    )


def _played(gameweek: int, kickoff: str, season: str = SEASON) -> pd.DataFrame:
    counts = [
        "starts",
        "goals_scored",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "own_goals",
        "penalties_saved",
        "penalties_missed",
        "yellow_cards",
        "red_cards",
        "saves",
        "bonus",
        "bps",
        "total_points",
    ]
    return validate(
        Table.PLAYER_GAMEWEEK,
        pd.DataFrame(
            [
                {
                    **dict.fromkeys(counts, 0),
                    "season": season,
                    "gameweek": gameweek,
                    "player_code": 777,
                    "player_id": 7,
                    "web_name": "P7",
                    "position": "MID",
                    "team_id": 1,
                    "opponent_team_id": 2,
                    "fixture_id": 10 + gameweek,
                    "kickoff_time": pd.Timestamp(kickoff),
                    "was_home": True,
                    "minutes": 90,
                    "defensive_contribution": None,
                    "tackles": None,
                    "recoveries": None,
                    "clearances_blocks_interceptions": None,
                    "expected_goals": None,
                    "expected_assists": None,
                    "expected_goals_conceded": None,
                    "price": 5.0,
                    "selected_by": None,
                }
            ]
        ),
    )


def _check(**tables: pd.DataFrame) -> tuple[bool, str, dict[str, object]]:
    gameweeks = _gameweeks()
    context = {"now": NOW, "season": SEASON, "tables": {Table.GAMEWEEK.value: gameweeks, **tables}}
    ok, message, details = _temporal_monotonicity_and_containment(gameweeks, context)
    return ok, message, dict(details)


def test_temporal_gate_passes_on_clean_data() -> None:
    ok, message, _ = _check(
        price_history=_prices(("2026-08-14T08:00Z", 1), ("2026-08-15T08:00Z", 1)),
        player_metric=_metric(1, "2026-08-15T09:30Z"),
        player_advanced=pd.DataFrame(),
        player_gameweek=_played(1, "2026-08-15T14:00Z"),
    )
    assert ok, message
    assert "respect gameweek deadlines" in message


def test_temporal_gate_catches_future_dated_price_history() -> None:
    ok, message, details = _check(price_history=_prices(("2026-08-25T08:00Z", 42)))
    assert not ok
    assert "future-dated observation" in message
    assert details["violating_entity"] == "player_id=42"
    assert "2026-08-25" in str(details["timestamp"])
    assert "2026-08-20" in str(details["deadline"])


def test_temporal_gate_catches_non_monotonic_price_history() -> None:
    ok, message, details = _check(
        price_history=_prices(("2026-08-15T08:00Z", 7), ("2026-08-14T08:00Z", 7))
    )
    assert not ok
    assert "not strictly monotonic" in message
    assert details["violating_entity"] == "player_id=7"


def test_a_metric_captured_after_its_gameweeks_deadline_is_caught() -> None:
    ok, message, details = _check(player_metric=_metric(1, "2026-08-15T16:00Z"))
    assert not ok
    assert "after the GW1 deadline" in message
    assert details["violating_entity"] == "player_code=999"
    assert "2026-08-15 16:00:00" in str(details["timestamp"])
    assert "2026-08-15 10:00:00" in str(details["deadline"])


def test_a_gameweek_row_that_kicked_off_before_its_own_deadline_is_caught() -> None:
    """Its outcome was already a feature at the deadline it is meant to be predicted from."""
    ok, message, details = _check(player_gameweek=_played(2, "2026-08-21T19:00Z"))
    assert not ok
    assert "before the GW2 deadline" in message
    assert details["violating_entity"] == "player_code=777"


def test_other_seasons_are_not_held_to_this_seasons_deadlines() -> None:
    ok, message, _ = _check(
        player_metric=_metric(38, "2026-07-01T00:00Z", season="2025/26"),
        player_gameweek=_played(2, "2025-08-23T14:00Z", season="2025/26"),
    )
    assert ok, message


def test_temporal_gate_blocks_publication_via_run_gates() -> None:
    gameweeks = _gameweeks()
    tables = {
        Table.GAMEWEEK.value: gameweeks,
        Table.PLAYER_METRIC.value: _metric(1, "2026-08-15T18:00Z"),
    }
    report = run_gates(GATES, tables, {"now": NOW, "season": SEASON, "tables": tables})
    temporal = [r for r in report.results if r.gate == "temporal_monotonicity_and_containment"]
    assert len(temporal) == 1
    assert temporal[0].outcome == GateOutcome.FAILED
    assert temporal[0].severity == GateSeverity.ERROR
    assert temporal[0].blocks_publication
    assert not report.passed
