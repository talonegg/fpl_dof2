"""Tests for pipeline/src/fpl_dof/week/score_advice.py (E14-S2).

Verifies realized points calculation with FPL auto-subs, vice-captain promotion,
hit deductions, and multi-model ranking.
"""

from __future__ import annotations

from fpl_dof.rules.models import GameRules, Position
from fpl_dof.week.score_advice import (
    AdvisedLineup,
    PlayerPerformance,
    score_lineup,
    score_model_recommendations,
)


def _perf(pid: int, pos: Position, mins: int, pts: int) -> PlayerPerformance:
    return PlayerPerformance(player_id=pid, position=pos, minutes=mins, points=pts)


def test_basic_scoring_no_autosubs(game_rules: GameRules) -> None:
    # 1 GKP, 4 DEF, 4 MID, 2 FWD = 11 starters
    perfs = {
        1: _perf(1, Position.GKP, 90, 6),
        2: _perf(2, Position.DEF, 90, 6),
        3: _perf(3, Position.DEF, 90, 6),
        4: _perf(4, Position.DEF, 90, 2),
        5: _perf(5, Position.DEF, 90, 1),
        6: _perf(6, Position.MID, 90, 10),  # Captain -> 20 pts
        7: _perf(7, Position.MID, 90, 3),
        8: _perf(8, Position.MID, 90, 2),
        9: _perf(9, Position.MID, 90, 2),
        10: _perf(10, Position.FWD, 90, 8),
        11: _perf(11, Position.FWD, 90, 5),
        12: _perf(12, Position.GKP, 0, 0),
        13: _perf(13, Position.DEF, 90, 4),
        14: _perf(14, Position.MID, 90, 3),
        15: _perf(15, Position.FWD, 90, 2),
    }
    advised = AdvisedLineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=6,
        vice_captain=10,
        transfers_made=1,
        free_transfers=1,
        expected_points=50.0,
    )

    scored = score_lineup(advised, perfs, game_rules)
    # Sum of 11 starters = 6+6+6+2+1+10+3+2+2+8+5 = 51. Captain bonus +10 = 61.
    assert scored.points_before_hits == 61
    assert scored.hit_points == 0
    assert scored.net_points == 61
    assert scored.vice_used is False
    assert scored.captain_id == 6
    assert scored.armband_points == 20
    assert scored.autosubs_in == ()
    assert scored.autosubs_out == ()
    assert scored.prediction_delta == 11.0


def test_gkp_autosub(game_rules: GameRules) -> None:
    perfs = {
        1: _perf(1, Position.GKP, 0, 0),  # Starter 0 mins
        12: _perf(12, Position.GKP, 90, 7),  # Sub played
        2: _perf(2, Position.DEF, 90, 2),
        3: _perf(3, Position.DEF, 90, 2),
        4: _perf(4, Position.DEF, 90, 2),
        5: _perf(5, Position.DEF, 90, 2),
        6: _perf(6, Position.MID, 90, 2),
        7: _perf(7, Position.MID, 90, 2),
        8: _perf(8, Position.MID, 90, 2),
        9: _perf(9, Position.MID, 90, 2),
        10: _perf(10, Position.FWD, 90, 2),
        11: _perf(11, Position.FWD, 90, 2),
    }
    advised = AdvisedLineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(),
        bench_gkp=12,
        captain=2,
        vice_captain=3,
    )
    scored = score_lineup(advised, perfs, game_rules)
    assert scored.autosubs_out == (1,)
    assert scored.autosubs_in == (12,)
    assert 12 in scored.final_starting
    assert 1 not in scored.final_starting
    # 7 (sub gkp) + 10 outfielders @ 2 pts = 27 + captain bonus 2 pts = 29
    assert scored.points_before_hits == 29


def test_formation_preserving_outfield_autosub(game_rules: GameRules) -> None:
    # 3-4-3 formation. Minimum DEF is 3.
    # DEF 2 plays 0 mins.
    # Bench order: MID 13 (played), DEF 14 (played).
    # MID 13 cannot sub for DEF 2 because remaining DEFs would be 2 (illegal formation).
    # DEF 14 must sub in instead.
    perfs = {
        1: _perf(1, Position.GKP, 90, 2),
        2: _perf(2, Position.DEF, 0, 0),  # 0 mins starter DEF
        3: _perf(3, Position.DEF, 90, 4),
        4: _perf(4, Position.DEF, 90, 4),
        5: _perf(5, Position.MID, 90, 3),
        6: _perf(6, Position.MID, 90, 3),
        7: _perf(7, Position.MID, 90, 3),
        8: _perf(8, Position.MID, 90, 3),
        9: _perf(9, Position.FWD, 90, 5),
        10: _perf(10, Position.FWD, 90, 5),
        11: _perf(11, Position.FWD, 90, 5),
        12: _perf(12, Position.GKP, 0, 0),
        13: _perf(13, Position.MID, 90, 10),  # 1st on bench, but cannot come on
        14: _perf(14, Position.DEF, 90, 6),  # 2nd on bench, can maintain 3 DEF formation
        15: _perf(15, Position.FWD, 90, 2),
    }
    advised = AdvisedLineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=9,
        vice_captain=10,
    )
    scored = score_lineup(advised, perfs, game_rules)
    assert scored.autosubs_out == (2,)
    assert scored.autosubs_in == (14,)
    assert 14 in scored.final_starting
    assert 13 not in scored.final_starting


def test_captain_vice_fallback(game_rules: GameRules) -> None:
    # Captain 6 played 0 mins. Vice 10 played 90 mins (8 pts).
    perfs = {
        1: _perf(1, Position.GKP, 90, 2),
        2: _perf(2, Position.DEF, 90, 2),
        3: _perf(3, Position.DEF, 90, 2),
        4: _perf(4, Position.DEF, 90, 2),
        5: _perf(5, Position.DEF, 90, 2),
        6: _perf(6, Position.MID, 0, 0),  # Captain blanks
        7: _perf(7, Position.MID, 90, 2),
        8: _perf(8, Position.MID, 90, 2),
        9: _perf(9, Position.MID, 90, 2),
        10: _perf(10, Position.FWD, 90, 8),  # Vice hauls
        11: _perf(11, Position.FWD, 90, 2),
        12: _perf(12, Position.GKP, 0, 0),
        13: _perf(13, Position.MID, 90, 4),  # Comes on for 6
        14: _perf(14, Position.DEF, 0, 0),
        15: _perf(15, Position.FWD, 0, 0),
    }
    advised = AdvisedLineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=6,
        vice_captain=10,
    )
    scored = score_lineup(advised, perfs, game_rules)
    assert scored.vice_used is True
    assert scored.captain_id == 10
    assert scored.armband_points == 16  # 8 * 2


def test_transfer_hits_deduction(game_rules: GameRules) -> None:
    perfs = {i: _perf(i, Position.MID, 90, 2) for i in range(1, 16)}
    perfs[1] = _perf(1, Position.GKP, 90, 2)
    for d in (2, 3, 4, 5):
        perfs[d] = _perf(d, Position.DEF, 90, 2)
    perfs[10] = _perf(10, Position.FWD, 90, 2)
    perfs[11] = _perf(11, Position.FWD, 90, 2)

    advised = AdvisedLineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=6,
        vice_captain=7,
        transfers_made=3,
        free_transfers=1,  # 2 extra transfers -> -8 hit points
    )
    scored = score_lineup(advised, perfs, game_rules)
    # 11 players * 2 = 22 + captain bonus 2 = 24 points before hits.
    assert scored.points_before_hits == 24
    assert scored.hit_points == 8
    assert scored.net_points == 16


def test_score_model_recommendations_ranks_properly(game_rules: GameRules) -> None:
    perfs = {i: _perf(i, Position.MID, 90, 2) for i in range(1, 16)}
    perfs[1] = _perf(1, Position.GKP, 90, 2)
    for d in (2, 3, 4, 5):
        perfs[d] = _perf(d, Position.DEF, 90, 2)
    perfs[10] = _perf(10, Position.FWD, 90, 2)
    perfs[11] = _perf(11, Position.FWD, 90, 2)

    # Model A: captain on player 6 (2 pts) -> 24 pts
    model_a = AdvisedLineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=6,
        vice_captain=7,
        expected_points=25.0,
    )
    # Model B: captain on player 10 who scored 10 pts -> 32 pts
    perfs[10] = _perf(10, Position.FWD, 90, 10)
    model_b = AdvisedLineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=10,
        vice_captain=7,
        expected_points=30.0,
    )

    ranked = score_model_recommendations(
        {"xp_v1": model_a, "c1": model_b},
        perfs,
        game_rules,
    )
    assert len(ranked) == 2
    assert ranked[0].model_name == "c1"
    assert ranked[0].rank == 1
    assert ranked[1].model_name == "xp_v1"
    assert ranked[1].rank == 2
