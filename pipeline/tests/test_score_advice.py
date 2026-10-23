"""Ranking strategies' advice by realised points (E14-S2). The scorer is ``rules.realised``."""

from __future__ import annotations

from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.realised import Lineup, PlayerPerformance, score_lineup
from fpl_dof.week.score_advice import lineup_from_advice, score_model_recommendations


def _perf(pid: int, pos: Position, mins: int, pts: int) -> PlayerPerformance:
    return PlayerPerformance(player_id=pid, position=pos, minutes=mins, points=pts)


def test_score_model_recommendations_ranks_properly(game_rules: GameRules) -> None:
    perfs = {i: _perf(i, Position.MID, 90, 2) for i in range(1, 16)}
    perfs[1] = _perf(1, Position.GKP, 90, 2)
    for d in (2, 3, 4, 5):
        perfs[d] = _perf(d, Position.DEF, 90, 2)
    perfs[10] = _perf(10, Position.FWD, 90, 2)
    perfs[11] = _perf(11, Position.FWD, 90, 2)

    # Model A: captain on player 6 (2 pts) -> 24 pts
    model_a = Lineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=6,
        vice_captain=7,
        expected_points=25.0,
    )
    # Model B: captain on player 10 who scored 10 pts -> 32 pts
    perfs[10] = _perf(10, Position.FWD, 90, 10)
    model_b = Lineup(
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


def test_recorded_hit_is_preferred_and_the_fallback_reads_the_rules(game_rules: GameRules) -> None:
    advised = {"starting": list(range(1, 12)), "captain": 1}
    perfs = {i: _perf(i, Position.MID if i > 1 else Position.GKP, 90, 1) for i in range(1, 12)}
    rec = lineup_from_advice(
        advised, transfers_made=3, free_transfers=1, recommendation={"hit_points": -8}
    )
    assert rec is not None and score_lineup(rec, perfs, game_rules).hit_points == 8
    fallback = lineup_from_advice(advised, transfers_made=3, free_transfers=1)
    assert fallback is not None
    assert score_lineup(fallback, perfs, game_rules).hit_points == 2 * abs(
        game_rules.transfers.extra_transfer_cost
    )
    zero = lineup_from_advice(advised, transfers_made=3, free_transfers=None)
    assert zero is not None and score_lineup(zero, perfs, game_rules).hit_points == 0
