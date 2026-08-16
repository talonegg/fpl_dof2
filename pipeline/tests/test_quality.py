"""E2-S2 — the quality gate framework.

E2-S2 says it explicitly: **"Testing the gate itself is the story, not an extra."** A gate that has
never been seen to fire is indistinguishable from a gate that cannot fire, and the second kind is
worse than no gate at all, because it is trusted.

So each test here *injects* the specific corruption the gate exists to catch, and the corruptions
chosen are the ones that pass every other check: a table that halved, a price in tenths, a foreign
key pointing nowhere. None of them is a type error, and none of them would fail schema validation.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from fpl_dof.config.models import QualityConfig
from fpl_dof.quality.gates import GateOutcome, GateSeverity, QualityGateError, run_gates
from fpl_dof.quality.rules import GATES, GateClass
from fpl_dof.silver.tables import Table


def _players(count: int = 500) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": range(1, count + 1),
            "code": range(100_000, 100_000 + count),
            "web_name": [f"P{i}" for i in range(count)],
            "full_name": [f"Player {i}" for i in range(count)],
            "position": ["MID"] * count,
            "team_id": [(i % 20) + 1 for i in range(count)],
            "price": [5.0] * count,
            "status": ["a"] * count,
            "chance_of_playing_next_round": [None] * count,
            "selected_by_percent": [1.0] * count,
            "news": [""] * count,
        }
    )


def _teams(count: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "team_id": range(1, count + 1),
            "name": [f"Club {i}" for i in range(count)],
            "short_name": [f"C{i:02d}" for i in range(count)],
            "strength_overall_home": [3] * count,
            "strength_overall_away": [3] * count,
        }
    )


def _fixtures(count: int = 380) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fixture_id": range(1, count + 1),
            "gameweek": [(i % 38) + 1 for i in range(count)],
            "kickoff_time": pd.to_datetime(["2026-08-21T17:30:00Z"] * count, utc=True),
            "home_team_id": [(i % 20) + 1 for i in range(count)],
            "away_team_id": [((i + 1) % 20) + 1 for i in range(count)],
            "home_difficulty": [3] * count,
            "away_difficulty": [3] * count,
            "finished": [False] * count,
        }
    )


def _gameweeks() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gameweek": range(1, 39),
            "name": [f"Gameweek {i}" for i in range(1, 39)],
            "deadline_time": pd.to_datetime(
                [f"2026-08-{min(21 + i, 31):02d}T17:30:00Z" for i in range(38)], utc=True
            ),
            "finished": [False] * 38,
            "is_next": [False] * 38,
        }
    )


def _tables(**overrides: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tables = {
        Table.PLAYER.value: _players(),
        Table.TEAM.value: _teams(),
        Table.FIXTURE.value: _fixtures(),
        Table.GAMEWEEK.value: _gameweeks(),
    }
    tables.update(overrides)
    return tables


def _context(**overrides: object) -> dict[str, object]:
    tables = overrides.pop("tables", None)
    context: dict[str, object] = {
        "quality": QualityConfig(),
        "now": dt.datetime(2026, 8, 10, tzinfo=dt.UTC),
        "team_ids": frozenset(range(1, 21)),
        "player_ids": frozenset(range(1, 501)),
    }
    context.update(overrides)
    assert tables is None
    return context


def test_clean_data_passes_every_gate() -> None:
    report = run_gates(GATES, _tables(), _context())
    assert report.passed, [r.message for r in report.failures]
    assert report.failures == ()


def test_all_four_assertion_classes_are_represented() -> None:
    """Design §3.4. Three of the four are easy; the fourth is the one that catches real outages."""
    classes = {gate.gate_class for gate in GATES}
    assert classes == set(GateClass)


def test_every_gate_names_the_requirement_it_protects() -> None:
    """DP-14. A check nobody can trace to a requirement is one nobody can argue with."""
    for gate in GATES:
        assert gate.requirement, gate.name
        assert gate.requirement.startswith(("FR-", "NFR-")), (gate.name, gate.requirement)


# --- injected corruption ------------------------------------------------------------------------


def test_a_collapsed_player_table_blocks_publication() -> None:
    """The failure nobody anticipates: a partial outage that returns 30 players instead of 700.

    Every schema, range and referential check passes on the result. The squad built from it looks
    entirely reasonable. Volume is the only thing that sees it.
    """
    report = run_gates(GATES, _tables(player=_players(30)), _context())

    assert not report.passed
    failure = next(r for r in report.failures if r.gate == "player_volume")
    assert failure.severity is GateSeverity.ERROR
    assert failure.blocks_publication


def test_a_halved_table_is_caught_even_above_the_absolute_floor() -> None:
    """450 players is above the 400 floor and is still half of what the last run saw."""
    report = run_gates(
        GATES,
        _tables(player=_players(450)),
        _context(previous_row_counts={Table.PLAYER.value: 900}),
    )

    assert not report.passed
    failure = next(r for r in report.failures if r.gate == "player_volume_stability")
    assert failure.blocks_publication
    assert failure.observed["previous"] == 900


def test_prices_left_in_tenths_are_caught() -> None:
    """The most likely silent unit bug here. £145.0m parses, validates, and buys nobody."""
    players = _players()
    players["price"] = players["price"] * 10
    report = run_gates(GATES, _tables(player=players), _context())

    assert not report.passed
    failure = next(r for r in report.failures if r.gate == "price_range")
    assert failure.gate_class == GateClass.RANGE.value
    assert failure.blocks_publication


def test_a_player_on_a_club_that_does_not_exist_is_caught() -> None:
    """A referential break is not a type error, so nothing upstream of this notices it."""
    players = _players()
    players.loc[0, "team_id"] = 47
    report = run_gates(GATES, _tables(player=players), _context())

    assert not report.passed
    failure = next(r for r in report.failures if r.gate == "player_team_reference")
    assert 47 in failure.observed["orphans"]  # type: ignore[operator]


def test_a_stale_snapshot_warns_but_does_not_block() -> None:
    """DP-15. A stale but honest recommendation beats no recommendation before a deadline.

    What must never happen is presenting it as fresh, which is why it is reported rather than
    swallowed.
    """
    report = run_gates(GATES, _tables(), _context(snapshot_age_seconds=10 * 24 * 3600))

    failure = next(r for r in report.failures if r.gate == "snapshot_freshness")
    assert failure.severity is GateSeverity.WARN
    assert not failure.blocks_publication
    assert report.passed, "a stale snapshot must not stop the run"


def test_a_missing_table_is_skipped_not_passed() -> None:
    """A gate that never ran proves nothing, and calling it a pass is how checks quietly lapse."""
    tables = _tables()
    del tables[Table.FIXTURE.value]
    report = run_gates(GATES, tables, _context())

    fixture_gates = [g.name for g in GATES if g.table == Table.FIXTURE.value]
    assert fixture_gates
    skipped = {r.gate for r in report.results if r.outcome is GateOutcome.SKIPPED}
    assert set(fixture_gates) <= skipped
    assert report.counts()["failed"] == 0, "an absent table is not a failing table"


def test_every_gate_runs_even_after_one_fails() -> None:
    """Being told about one problem per run turns a five-minute fix into five runs."""
    players = _players(30)
    players["price"] = players["price"] * 10
    players.loc[0, "team_id"] = 47

    report = run_gates(GATES, _tables(player=players), _context())

    failed = {r.gate for r in report.failures}
    assert {"player_volume", "price_range", "player_team_reference"} <= failed
    assert len(report.results) == len(GATES)


def test_the_error_says_that_the_last_good_artefact_stays_live() -> None:
    report = run_gates(GATES, _tables(player=_players(30)), _context())
    error = QualityGateError(report)

    assert "last good artefact" in str(error)
    assert error.report is report


@pytest.mark.parametrize("severity", [GateSeverity.INFO, GateSeverity.WARN])
def test_only_errors_block(severity: GateSeverity) -> None:
    from fpl_dof.quality.gates import GateResult

    result = GateResult(
        gate="x",
        gate_class="range",
        severity=severity,
        outcome=GateOutcome.FAILED,
        message="",
        requirement="FR-08",
    )
    assert not result.blocks_publication
