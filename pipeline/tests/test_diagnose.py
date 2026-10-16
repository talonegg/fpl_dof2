"""Tests for pipeline/src/fpl_dof/week/diagnose.py (E14-S4).

Verifies diagnosis of the gap between the hindsight oracle and pre-deadline models:
- Distinguishes genuine model blindspots from high-variance black swans;
- Flags captaincy traps where models backed an underperforming asset over an obvious captain.
"""

from __future__ import annotations

from fpl_dof.week.diagnose import (
    DiagnosticCategory,
    diagnose_oracle_gap,
)
from fpl_dof.week.oracle import HindsightMove, HindsightOptimalPlan


def test_diagnose_captaincy_trap() -> None:
    # Oracle picked Haaland as captain (16 pts actual)
    optimal = HindsightOptimalPlan(
        transfers_count=0,
        moves=(),
        starting=(13,),
        captain_id=13,
        captain_name="Haaland",
        points_before_hits=32,
        hit_points=0,
        net_points=32,
        gain_over_roll=0.0,
    )
    # Primary model chose Fernandes (pid 6) with 1 pt actual, while Haaland had 16 pts
    actual_pts = {13: 16, 6: 1}
    models_xp = {
        "xp_v1": {13: 7.5, 6: 6.8},
        "c1": {13: 8.2, 6: 5.5},
    }
    models_captains = {
        "xp_v1": 6,  # Picked Fernandes
        "c1": 13,  # Picked Haaland
    }

    diags = diagnose_oracle_gap(
        optimal=optimal,
        player_actuals=actual_pts,
        models_xp=models_xp,
        models_captains=models_captains,
    )

    cap_diags = [d for d in diags if d.category == DiagnosticCategory.CAPTAINCY_TRAP]
    assert len(cap_diags) >= 1
    assert cap_diags[0].player_id == 13
    assert "xp_v1" in cap_diags[0].models_trapped


def test_diagnose_blindspot_vs_outlier() -> None:
    # Optimal transfer in: Mbeumo (pid 16, 15 pts) and Henderson (pid 18, 14 pts)
    optimal = HindsightOptimalPlan(
        transfers_count=2,
        moves=(
            HindsightMove(10, "Rogers", 16, "Mbeumo", 5.0, 7.0),
            HindsightMove(11, "Smith Rowe", 18, "Henderson", 5.5, 4.5),
        ),
        starting=(16, 18),
        captain_id=13,
        captain_name="Haaland",
        points_before_hits=50,
        hit_points=0,
        net_points=50,
        gain_over_roll=15.0,
    )
    actual_pts = {16: 15, 18: 14, 10: 2, 11: 2}
    # For Mbeumo: xp_v1 had only 3.0 xP, but c1 had 6.5 xP -> Blindspot for xp_v1
    # For Henderson: all models had < 2.5 xP -> High variance outlier
    models_xp = {
        "xp_v1": {16: 3.0, 18: 1.8},
        "c1": {16: 6.5, 18: 2.0},
        "b0": {16: 4.0, 18: 1.5},
    }
    models_captains = {"xp_v1": 13, "c1": 13, "b0": 13}

    diags = diagnose_oracle_gap(
        optimal=optimal,
        player_actuals=actual_pts,
        models_xp=models_xp,
        models_captains=models_captains,
    )

    mbeumo_diag = next(d for d in diags if d.player_id == 16)
    henderson_diag = next(d for d in diags if d.player_id == 18)

    assert mbeumo_diag.category == DiagnosticCategory.MODEL_BLINDSPOT
    assert henderson_diag.category == DiagnosticCategory.HIGH_VARIANCE_OUTLIER
