"""EXP-02 (D-21) — the chip-timing experiment's two seams.

``simulation.undiscounted_percentile`` takes the horizon discount out of the re-rank's draws and,
off, leaves them exactly as shipped. :func:`timing_summary` turns the replay's arms into the
declared experiment's measure. The replay itself is slow and runs in the weekly backtest
(``backtest.chip_replay.timing_experiment``); its finding is recorded in the debt register.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from fpl_dof.config.models import DecisionConfig, HorizonConfig, SimulationConfig
from fpl_dof.factory.replay import timing_summary
from fpl_dof.frames import gameweek_column, gameweek_sd_column
from fpl_dof.optimise.horizon import PlannedWeek
from fpl_dof.optimise.plan import _draws
from fpl_dof.rules.models import GameRules


def _week(gameweek: int) -> PlannedWeek:
    return PlannedWeek(
        gameweek=gameweek,
        chip=None,
        squad=(1,),
        fielded=(1,),
        starting=(1,),
        bench_order=(),
        captain_id=99,
        vice_captain_id=98,
        formation={},
        transfers_in=(),
        transfers_out=(),
        free_transfers=1,
        charged_transfers=0,
        hit_points=0,
        bank_after=0.0,
        expected_points=0.0,
    )


@pytest.mark.parametrize(("undiscounted", "expected"), [(False, 0.9**2), (True, 1.0)])
def test_the_flag_decides_whether_a_later_week_is_discounted(
    game_rules: GameRules, undiscounted: bool, expected: float
) -> None:
    decision = DecisionConfig(
        horizon=HorizonConfig(discount=0.9),
        simulation=SimulationConfig(undiscounted_percentile=undiscounted),
    )
    row = SimpleNamespace(team_id=1, **{gameweek_column(7): 5.0, gameweek_sd_column(7): 2.0})
    (draw,) = _draws(_week(7), {1: row}, game_rules, decision, (5, 6, 7))
    assert draw.multiplier == pytest.approx(expected)
    assert draw.mean == 5.0


def _fold(offsets: dict[str, int | None]) -> dict[str, Any]:
    return {
        "arms": {
            key: {"offset": o, "actual_points": 50.0, "chips": []} for key, o in offsets.items()
        }
    }


def test_the_summary_measures_the_share_of_front_loading_the_discount_explains() -> None:
    dials = ("safe", "balanced")
    # Off never front-loads; on as shipped always does; undiscounted does at one of four.
    folds = [
        _fold(
            {
                f"{d}/{arm}": offset
                for d in dials
                for arm, offset in (
                    ("off", 3),
                    ("discounted", 0),
                    ("undiscounted", 0 if (d, i) == ("safe", 0) else 2),
                )
            }
        )
        for i in range(2)
    ]
    summary = timing_summary(folds, dials, seconds=1.0)
    assert summary["arms"]["safe/discounted"]["front_loaded"] == 2
    assert summary["arms"]["safe/undiscounted"]["front_loaded"] == 1
    assert summary["discount_share_of_front_loading"] == pytest.approx(0.75)
    assert "75%" in summary["verdict"]


def test_no_excess_front_loading_is_said_rather_than_divided_by() -> None:
    folds = [_fold({f"balanced/{a}": 1 for a in ("off", "discounted", "undiscounted")})]
    summary = timing_summary(folds, ("balanced",), seconds=1.0)
    assert summary["discount_share_of_front_loading"] is None
    assert "nothing to explain" in summary["verdict"]
