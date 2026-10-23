"""The one realised-points scorer (ORC-04): ``fpl_dof.rules.realised``.

The corpus test is the arbiter: real 2026/27 entries, scored by FPL, in
``contracts/conformance/realised/`` (DL-39). The unit tests below cover what the corpus cannot yet:
a double gameweek, a blank, a Free Hit, and rules other than FPL's (Invariant 2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.realised import Lineup, PlayerPerformance, performances, score_lineup

CORPUS = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "conformance"
    / "realised"
    / "realised-corpus.json"
)
CASES: list[dict[str, Any]] = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]


def _perf(pid: int, pos: Position, mins: int, pts: int) -> PlayerPerformance:
    return PlayerPerformance(player_id=pid, position=pos, minutes=mins, points=pts)


def _corpus_score(case: dict[str, Any], rules: GameRules) -> Any:
    rows = [
        {"player_id": p["player_id"], "position": p["position"], "minutes": m, "total_points": pts}
        for p in case["picks"]
        for m, pts in p["fixtures"]
    ]
    frame = pd.DataFrame(rows, columns=["player_id", "position", "minutes", "total_points"])
    positions = {p["player_id"]: Position(p["position"]) for p in case["picks"]}
    ids = [p["player_id"] for p in case["picks"]]
    lineup = Lineup(
        starting=tuple(ids[:11]),
        bench_gkp=ids[11],
        bench_order=tuple(ids[12:]),
        captain=case["captain"],
        vice_captain=case["vice_captain"],
        chip=case["chip"],
        transfers_made=case["transfers"],
        free_transfers=case["free_transfers"],
    )
    return score_lineup(lineup, performances(frame, positions=positions), rules)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_scorer_reproduces_fpl(case: dict[str, Any], game_rules: GameRules) -> None:
    scored = _corpus_score(case, game_rules)
    expected = case["expected"]
    assert scored.points_before_hits == expected["points"]
    assert scored.hit_points == expected["transfers_cost"]
    assert [list(pair) for pair in zip(scored.autosubs_out, scored.autosubs_in, strict=True)] == (
        expected["automatic_subs"]
    )


def test_the_corpus_covers_what_the_story_names() -> None:
    tags = {t for c in CASES for t in c["tags"]}
    assert {"auto-substitution", "formation-skip", "vice", "3xc", "bboost", "wildcard"} <= tags
    gw4 = next(c for c in CASES if c["name"] == "owner-gw4")
    assert gw4["expected"]["points"] - gw4["expected"]["transfers_cost"] == 79  # D-30


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
    advised = Lineup(
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
    advised = Lineup(
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
    advised = Lineup(
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
    advised = Lineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=6,
        vice_captain=10,
    )
    scored = score_lineup(advised, perfs, game_rules)
    assert scored.vice_used is True
    assert scored.captain_id == 10
    assert scored.armband_points == 8 * game_rules.chips.captain_multiplier


def test_transfer_hits_deduction(game_rules: GameRules) -> None:
    perfs = {i: _perf(i, Position.MID, 90, 2) for i in range(1, 16)}
    perfs[1] = _perf(1, Position.GKP, 90, 2)
    for d in (2, 3, 4, 5):
        perfs[d] = _perf(d, Position.DEF, 90, 2)
    perfs[10] = _perf(10, Position.FWD, 90, 2)
    perfs[11] = _perf(11, Position.FWD, 90, 2)

    advised = Lineup(
        starting=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
        bench_order=(13, 14, 15),
        bench_gkp=12,
        captain=6,
        vice_captain=7,
        transfers_made=3,
        free_transfers=1,  # 2 extra transfers -> -8 hit points
    )
    scored = score_lineup(advised, perfs, game_rules)
    # Eleven players score 2 each, the armband adds the captain's 2 again per extra multiple.
    before = 11 * 2 + 2 * (game_rules.chips.captain_multiplier - 1)
    hit = 2 * abs(game_rules.transfers.extra_transfer_cost)
    assert scored.points_before_hits == before
    assert scored.hit_points == hit
    assert scored.net_points == before - hit


def test_double_gameweek_rows_are_summed_per_player() -> None:
    rows = pd.DataFrame(
        {
            "player_id": [1, 1, 2],
            "position": ["MID", "MID", "DEF"],
            "minutes": [90, 0, 0],
            "total_points": [6, 2, 0],
        }
    )
    perfs = performances(rows)
    assert (perfs[1].points, perfs[1].minutes) == (8, 90)  # a 0-minute last row must not sub him
    assert perfs[2].minutes == 0


def _team(**overrides: PlayerPerformance) -> dict[int, PlayerPerformance]:
    """A 4-4-2 of ids 1..11 who all played for 2, and a bench 12 (GKP), 13 DEF, 14 MID, 15 FWD."""
    shape = [Position.GKP, *[Position.DEF] * 4, *[Position.MID] * 4, *[Position.FWD] * 2]
    bench = [Position.GKP, Position.DEF, Position.MID, Position.FWD]
    perfs = {i: _perf(i, p, 90, 2) for i, p in enumerate([*shape, *bench], start=1)}
    perfs.update({int(k[1:]): v for k, v in overrides.items()})
    return perfs


_XI = Lineup(
    starting=tuple(range(1, 12)), bench_gkp=12, bench_order=(13, 14, 15), captain=6, vice_captain=7
)


def test_bench_boost_scores_all_fifteen_and_substitutes_nobody(game_rules: GameRules) -> None:
    perfs = _team(p6=_perf(6, Position.MID, 0, 0))
    scored = score_lineup(Lineup(**{**_kwargs(_XI), "chip": "bboost"}), perfs, game_rules)
    assert scored.autosubs_in == ()
    assert scored.vice_used and scored.captain_id == 7
    multiplier = game_rules.chips.captain_multiplier
    assert scored.points_before_hits == 14 * 2 + 2 * (multiplier - 1)


def test_triple_captain_takes_its_multiplier_from_the_rules(game_rules: GameRules) -> None:
    scored = score_lineup(Lineup(**{**_kwargs(_XI), "chip": "3xc"}), _team(), game_rules)
    multiplier = game_rules.chips.captain_multiplier_by_chip["3xc"]
    assert scored.armband_points == 2 * multiplier
    assert scored.points_before_hits == 11 * 2 + 2 * (multiplier - 1)


@pytest.mark.parametrize("chip", ["freehit", "wildcard"])
def test_a_transfer_chip_charges_no_hit(chip: str, game_rules: GameRules) -> None:
    lineup = Lineup(**{**_kwargs(_XI), "chip": chip, "transfers_made": 6, "free_transfers": 1})
    assert score_lineup(lineup, _team(), game_rules).hit_points == 0


def test_no_armband_when_neither_captain_nor_vice_played(game_rules: GameRules) -> None:
    perfs = _team(p6=_perf(6, Position.MID, 0, 0), p7=_perf(7, Position.MID, 0, 0))
    perfs[13] = _perf(13, Position.DEF, 0, 0)
    perfs[14] = _perf(14, Position.MID, 0, 0)
    perfs[15] = _perf(15, Position.FWD, 0, 0)
    scored = score_lineup(_XI, perfs, game_rules)
    assert scored.armband_points == 0 and not scored.vice_used
    assert scored.points_before_hits == 9 * 2


def test_a_player_with_no_fixture_is_substituted_and_keeps_his_position(
    game_rules: GameRules,
) -> None:
    """A blank: no row at all. ``positions`` keeps him a defender, so the bench midfielder cannot
    replace him in a three-defender XI, and the second-choice defender does."""
    rows = pd.DataFrame(
        [
            {"player_id": i, "position": p.value, "minutes": 90, "total_points": 2}
            for i, p in _positions().items()
            if i != 2
        ]
    )
    xi = Lineup(
        starting=(1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 15),  # 3-4-3 with defender 2 blanking
        bench_gkp=12,
        bench_order=(14, 13, 5),
        captain=6,
        vice_captain=7,
    )
    scored = score_lineup(xi, performances(rows, positions=_positions()), game_rules)
    assert (scored.autosubs_out, scored.autosubs_in) == ((2,), (13,))


def test_a_goalkeeper_stays_when_the_reserve_did_not_play_either(game_rules: GameRules) -> None:
    perfs = _team(p1=_perf(1, Position.GKP, 0, 0), p12=_perf(12, Position.GKP, 0, 0))
    scored = score_lineup(_XI, perfs, game_rules)
    assert scored.autosubs_in == () and 1 in scored.final_starting


def test_a_recorded_hit_is_charged_as_recorded(game_rules: GameRules) -> None:
    lineup = Lineup(**{**_kwargs(_XI), "hit_points": 4, "transfers_made": 9, "free_transfers": 1})
    scored = score_lineup(lineup, _team(), game_rules)
    assert (scored.hit_points, scored.net_points) == (4, scored.points_before_hits - 4)
    assert scored.as_dict()["hit_points"] == 4


def test_an_unknown_position_is_read_as_a_midfielder() -> None:
    rows = pd.DataFrame([{"player_id": 1, "position": "XXX", "minutes": 1, "total_points": 1}])
    assert performances(rows)[1].position == Position.MID


def test_other_rules_give_other_answers(game_rules: GameRules) -> None:
    """Invariant 2: change the configured armband and the score moves with it."""
    other = game_rules.model_copy(
        update={"chips": game_rules.chips.model_copy(update={"captain_multiplier": 5})}
    )
    assert score_lineup(_XI, _team(), other).points_before_hits == 11 * 2 + 2 * 4


def _positions() -> dict[int, Position]:
    return {i: perf.position for i, perf in _team().items()}


def _kwargs(lineup: Lineup) -> dict[str, Any]:
    return {f: getattr(lineup, f) for f in Lineup.__dataclass_fields__}
