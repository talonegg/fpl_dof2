"""The one realised-points scorer (ORC-04): ``fpl_dof.rules.realised``.

The corpus test is the arbiter: real 2026/27 entries, scored by FPL, in
``contracts/conformance/realised/`` (DL-39), and the gameweek in play constructed from one of them
(LIVE-03). The unit tests below cover what the corpus cannot yet: a double gameweek, a blank, a
Free Hit, and rules other than FPL's (Invariant 2).
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fpl_dof.config.models import RulesConfig
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.realised import (
    Lineup,
    PlayerPerformance,
    live_score,
    performances,
    score_lineup,
)
from fpl_dof.rules.underlying import underlying_points, underlying_team_points

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
    """A fixture is ``[minutes, points]``, finished, or ``[minutes, points, finished]`` in play."""
    rows = [
        {
            "player_id": p["player_id"],
            "position": p["position"],
            "minutes": f[0],
            "total_points": f[1],
            "finished": f[2] if len(f) > 2 else True,
        }
        for p in case["picks"]
        for f in p["fixtures"]
    ]
    columns = ["player_id", "position", "minutes", "total_points", "finished"]
    frame = pd.DataFrame(rows, columns=columns)
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
    if "armband" in expected:
        assert scored.captain_id == expected["armband"]


def _builder() -> Any:
    path = CORPUS.parents[3] / "scripts" / "realised_corpus.py"
    spec = importlib.util.spec_from_file_location("realised_corpus", path)
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


def test_the_corpus_is_what_the_builder_writes() -> None:
    """The hand-written constructed cases are in the builder's own layout, so a rebuild, which
    keeps them, rewrites the file byte for byte apart from what FPL changed."""
    assert _builder().render(CASES) == CORPUS.read_text(encoding="utf-8")


def test_the_corpus_builder_reads_the_transfer_rules_from_config() -> None:
    """The builder's free transfers come from the rules config: the cap, the weekly allowance and
    the chips that keep the bank (Invariant 2), so a rule change reaches the corpus input."""
    builder = _builder()
    history = {
        "chips": [{"event": 3, "name": "wildcard"}],
        "current": [{"event": gw, "event_transfers": 0} for gw in range(1, 6)],
    }
    rules = RulesConfig()
    assert builder.free_transfers(history, rules) == {1: None, 2: 1, 3: 2, 4: 3, 5: 4}
    transfers = rules.transfers.model_copy(
        update={"free_transfers_per_gameweek": 2, "max_free_transfers": 3}
    )
    other = rules.model_copy(update={"transfers": transfers})
    assert builder.free_transfers(history, other) == {1: None, 2: 2, 3: 3, 4: 3, 5: 3}


def test_the_corpus_covers_what_the_story_names() -> None:
    tags = {t for c in CASES for t in c["tags"]}
    assert {"auto-substitution", "formation-skip", "vice", "3xc", "bboost", "wildcard"} <= tags
    in_play = {
        "starter-yet-to-play",
        "captain-yet-to-play",
        "blank-in-play",
        "double-gameweek-in-play",
        "unfinished-fixture-first",
        "substitute-yet-to-play",
        "substitute-did-not-play",
        "substitute-yet-to-play-formation-skip",
        "reserve-goalkeeper-yet-to-play",
    }
    assert in_play <= tags  # LIVE-03
    gw4 = next(c for c in CASES if c["name"] == "owner-gw4")
    assert gw4["expected"]["points"] - gw4["expected"]["transfers_cost"] == 79  # D-30


def test_a_constructed_case_is_a_real_team_in_play_and_says_so() -> None:
    """The in-play cases are ours, not FPL's: each is tagged so, names the real case it rewinds,
    keeps its fifteen and armbands, and only they have a fixture yet to finish. The constructed
    case with every fixture finished must keep FPL's own answer."""
    real = {c["name"]: c for c in CASES if "constructed" not in c["tags"]}
    for case in CASES:
        unfinished = any(len(f) > 2 and not f[2] for p in case["picks"] for f in p["fixtures"])
        if "constructed" not in case["tags"]:
            assert not unfinished, case["name"]
            continue
        source = real[case["from"]]
        assert [p["player_id"] for p in case["picks"]] == [p["player_id"] for p in source["picks"]]
        assert (case["captain"], case["vice_captain"]) == (
            source["captain"],
            source["vice_captain"],
        )
        assert unfinished == ("in-play" in case["tags"]), case["name"]
        if not unfinished:
            for key in ("points", "transfers_cost", "automatic_subs"):
                assert case["expected"][key] == source["expected"][key], case["name"]


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


def test_an_unknown_or_missing_position_is_a_data_fault_not_a_midfielder() -> None:
    """DP-15 taken too far: guessing MID would decide a formation check silently."""
    rows = pd.DataFrame([{"player_id": 1, "position": "XXX", "minutes": 1, "total_points": 1}])
    with pytest.raises(ValueError, match="player 1 has no position the rules know: 'XXX'"):
        performances(rows)
    with pytest.raises(ValueError, match="player 1 has no position"):
        performances(rows.drop(columns="position"))


def test_other_rules_give_other_answers(game_rules: GameRules) -> None:
    """Invariant 2: change the configured armband and the score moves with it."""
    other = game_rules.model_copy(
        update={"chips": game_rules.chips.model_copy(update={"captain_multiplier": 5})}
    )
    assert score_lineup(_XI, _team(), other).points_before_hits == 11 * 2 + 2 * 4


# --- A gameweek in play (LIVE-03) ----------------------------------------------------------------


def _yet(pid: int, pos: Position, mins: int = 0, pts: int = 0) -> PlayerPerformance:
    """A player with a fixture still to finish, on ``mins`` and ``pts`` so far."""
    return PlayerPerformance(pid, pos, mins, pts, complete=False)


def test_a_starter_yet_to_play_keeps_his_place(game_rules: GameRules) -> None:
    scored = score_lineup(_XI, _team(p2=_yet(2, Position.DEF)), game_rules)
    assert scored.autosubs_in == () and 2 in scored.final_starting
    assert scored.points_before_hits == 10 * 2 + 2 * (game_rules.chips.captain_multiplier - 1)


def test_a_goalkeeper_yet_to_play_keeps_his_place(game_rules: GameRules) -> None:
    scored = score_lineup(_XI, _team(p1=_yet(1, Position.GKP)), game_rules)
    assert scored.autosubs_in == () and 1 in scored.final_starting


def test_a_substitute_yet_to_play_holds_the_place_against_those_below_him(
    game_rules: GameRules,
) -> None:
    """R1 of the LIVE-03 verification: projecting 14 on now would be undone if 13 then plays,
    since FPL takes the first in bench order who played. So nobody comes on until 13's gameweek
    is over, and then it is whichever FPL would choose."""
    perfs = _team(p2=_perf(2, Position.DEF, 0, 0), p13=_yet(13, Position.DEF))
    waiting = score_lineup(_XI, perfs, game_rules)
    assert waiting.autosubs_in == () and 2 in waiting.final_starting
    assert waiting.points_before_hits == 10 * 2 + 2 * (game_rules.chips.captain_multiplier - 1)
    played = score_lineup(_XI, {**perfs, 13: _perf(13, Position.DEF, 90, 2)}, game_rules)
    assert (played.autosubs_out, played.autosubs_in) == ((2,), (13,))
    missed = score_lineup(_XI, {**perfs, 13: _perf(13, Position.DEF, 0, 0)}, game_rules)
    assert (missed.autosubs_out, missed.autosubs_in) == ((2,), (14,))


def test_a_substitute_yet_to_play_with_minutes_so_far_comes_on(game_rules: GameRules) -> None:
    perfs = _team(p2=_perf(2, Position.DEF, 0, 0), p13=_yet(13, Position.DEF, 30, 1))
    scored = score_lineup(_XI, perfs, game_rules)
    assert (scored.autosubs_out, scored.autosubs_in) == ((2,), (13,))  # he has played: certain


def test_a_substitute_whose_gameweek_is_over_without_a_minute_is_passed_over(
    game_rules: GameRules,
) -> None:
    perfs = _team(p2=_perf(2, Position.DEF, 0, 0), p13=_perf(13, Position.DEF, 0, 0))
    perfs[15] = _yet(15, Position.FWD)  # below 14: holds nothing
    scored = score_lineup(_XI, perfs, game_rules)
    assert (scored.autosubs_out, scored.autosubs_in) == ((2,), (14,))


def test_a_substitute_yet_to_play_who_could_not_come_on_holds_nothing(
    game_rules: GameRules,
) -> None:
    """In a three-defender XI the midfielder first on the bench can never replace a defender, so
    his fixture to come decides nothing and the defender behind him comes on now."""
    xi = Lineup(
        starting=(1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 15),
        bench_gkp=12,
        bench_order=(14, 13, 5),
        captain=6,
        vice_captain=7,
    )
    perfs = _team(p2=_perf(2, Position.DEF, 0, 0), p14=_yet(14, Position.MID))
    scored = score_lineup(xi, perfs, game_rules)
    assert (scored.autosubs_out, scored.autosubs_in) == ((2,), (13,))


def test_a_reserve_goalkeeper_yet_to_play_holds_the_goalkeepers_place(
    game_rules: GameRules,
) -> None:
    perfs = _team(p1=_perf(1, Position.GKP, 0, 0), p12=_yet(12, Position.GKP))
    waiting = score_lineup(_XI, perfs, game_rules)
    assert waiting.autosubs_in == () and 1 in waiting.final_starting
    played = score_lineup(_XI, {**perfs, 12: _perf(12, Position.GKP, 90, 3)}, game_rules)
    assert (played.autosubs_out, played.autosubs_in) == ((1,), (12,))


def test_a_captain_yet_to_play_keeps_the_armband_on_his_points_so_far(
    game_rules: GameRules,
) -> None:
    multiplier = game_rules.chips.captain_multiplier
    waiting = score_lineup(_XI, _team(p6=_yet(6, Position.MID)), game_rules)
    assert (waiting.captain_id, waiting.vice_used, waiting.armband_points) == (6, False, 0)
    playing = score_lineup(_XI, _team(p6=_yet(6, Position.MID, 30, 5)), game_rules)
    assert (playing.captain_id, playing.armband_points) == (6, 5 * multiplier)
    assert playing.points_before_hits == 10 * 2 + 5 * multiplier


def test_the_armband_passes_once_the_captains_gameweek_is_over_without_a_minute(
    game_rules: GameRules,
) -> None:
    scored = score_lineup(_XI, _team(p6=_perf(6, Position.MID, 0, 0)), game_rules)
    assert (scored.captain_id, scored.vice_used) == (7, True)


def test_a_double_gameweek_is_complete_only_when_both_fixtures_are_finished(
    game_rules: GameRules,
) -> None:
    rows = pd.DataFrame(
        {
            "player_id": [2, 2, 6, 6, 7],
            "position": ["DEF", "DEF", "MID", "MID", "MID"],
            "minutes": [0, 0, 90, 0, 90],
            "total_points": [0, 0, 6, 0, 2],
            "finished": [True, False, True, False, True],
        }
    )
    perfs = performances(rows)
    assert (perfs[2].minutes, perfs[2].complete) == (0, False)  # missed one, one to come
    assert (perfs[6].points, perfs[6].complete) == (6, False)
    assert perfs[7].complete
    scored = score_lineup(_XI, _team(p2=perfs[2], p6=perfs[6], p7=perfs[7]), game_rules)
    assert scored.autosubs_in == () and scored.captain_id == 6
    assert scored.armband_points == 6 * game_rules.chips.captain_multiplier


@pytest.mark.parametrize(
    "flags", [[True, False], [False, True]], ids=["to-come-last", "to-come-first"]
)
def test_a_double_gameweek_is_incomplete_whichever_order_its_fixtures_come_in(
    flags: list[bool],
) -> None:
    """R3 of the LIVE-03 verification: a fixture to come in either row keeps the player
    incomplete, so taking only the last row's flag fails one of these orders."""
    rows = pd.DataFrame(
        {
            "player_id": [2, 2],
            "position": ["DEF", "DEF"],
            "minutes": [0, 0],
            "total_points": [0, 0],
            "finished": flags,
        }
    )
    assert not performances(rows)[2].complete
    assert performances(rows.assign(finished=[True, True]))[2].complete


def test_without_a_finished_column_every_row_is_finished() -> None:
    rows = pd.DataFrame([{"player_id": 1, "position": "MID", "minutes": 0, "total_points": 0}])
    assert performances(rows)[1].complete
    assert performances(rows.iloc[:0], positions={9: Position.DEF})[9].complete  # a blank


@pytest.mark.parametrize("flag", [None, float("nan")])
def test_a_missing_finished_flag_is_a_data_fault(flag: object) -> None:
    rows = pd.DataFrame(
        [{"player_id": 1, "position": "MID", "minutes": 0, "total_points": 0, "finished": flag}]
    )
    with pytest.raises(ValueError, match="player 1 has a fixture with no finished flag"):
        performances(rows)


def test_live_points_take_this_gameweeks_hit_once(game_rules: GameRules) -> None:
    """Provisional points are the score so far less the hit; the live total adds them to the total
    after the last finished gameweek, which already holds the earlier hits (LIVE-03 design 2)."""
    hit = abs(game_rules.transfers.extra_transfer_cost)
    lineup = Lineup(**{**_kwargs(_XI), "hit_points": hit})
    perfs = _team(p2=_yet(2, Position.DEF))
    live = live_score(lineup, perfs, game_rules, last_total=400)
    scored = score_lineup(lineup, perfs, game_rules)
    assert live.scored == scored
    assert live.gameweek_points == scored.points_before_hits - hit
    assert live.live_total == 400 + scored.points_before_hits - hit


@settings(max_examples=200, deadline=None)
@given(
    minutes=st.lists(st.sampled_from([0, 30, 90]), min_size=15, max_size=15),
    complete=st.lists(st.booleans(), min_size=15, max_size=15),
)
def test_nobody_goes_off_or_loses_the_armband_before_his_gameweek_is_over(
    minutes: list[int], complete: list[bool], game_rules: GameRules
) -> None:
    """DP-13, for any state of play: only a starter whose gameweek is over without a minute goes
    off, only a substitute with minutes comes on, and the armband leaves only such a captain."""
    shape = _positions()
    perfs = {
        pid: PlayerPerformance(pid, shape[pid], minutes[pid - 1], minutes[pid - 1] // 30, done)
        for pid, done in enumerate(complete, start=1)
    }
    scored = score_lineup(_XI, perfs, game_rules)
    for off in scored.autosubs_out:
        assert perfs[off].complete and perfs[off].minutes == 0
    for on in scored.autosubs_in:
        assert perfs[on].minutes > 0
    captain = perfs[_XI.captain]
    assert scored.vice_used == (
        captain.complete and captain.minutes == 0 and perfs[_XI.vice_captain].minutes > 0
    )


#: How far a player's gameweek has got: over with minutes or without, yet to play, playing, blank.
_STATES = ("played", "did_not_play", "yet_to_play", "playing", "no_fixture")
_SO_FAR = {"played": 90, "did_not_play": 0, "yet_to_play": 0, "playing": 30}


@settings(max_examples=500, deadline=None)
@given(data=st.data())
def test_a_substitution_projected_now_is_never_undone_by_the_fixtures_to_come(
    data: st.DataObject, game_rules: GameRules
) -> None:
    """DP-13, R1 of the LIVE-03 verification: for any legal XI, bench order and state of play,
    play out every fixture still to come with or without minutes, and each substitute projected
    on now is still brought on in the final scoring. Whom he replaces may change, and a fixture to
    come may bring more on, but none goes back to the bench.

    Most of an XI plays, so the draw unsettles a few starters and the whole bench: the rule is
    tried where a substitution is a near thing, not where the bench is used up regardless."""
    squad = game_rules.squad
    formation = data.draw(st.sampled_from(squad.legal_formations()), label="formation")
    xi = [pos for pos in Position for _ in range(formation[pos])]
    outfield = [p for p in Position if p != Position.GKP]
    spare = [p for p in outfield for _ in range(squad.composition[p] - formation[p])]
    shape = [*xi, Position.GKP, *data.draw(st.permutations(spare), label="bench")]
    size = len(shape)
    unsettled = data.draw(st.sets(st.sampled_from(range(1, len(xi) + 1)), max_size=4))
    states = data.draw(st.lists(st.sampled_from(_STATES), min_size=size, max_size=size))
    plays_later = data.draw(st.lists(st.booleans(), min_size=size, max_size=size))
    now: dict[int, PlayerPerformance] = {}
    final: dict[int, PlayerPerformance] = {}
    for pid, pos in enumerate(shape, start=1):
        state = states[pid - 1] if pid in unsettled or pid > len(xi) else "played"
        if state == "no_fixture":
            continue
        complete = state in ("played", "did_not_play")
        minutes = _SO_FAR[state]
        now[pid] = PlayerPerformance(pid, pos, minutes, minutes // 30, complete)
        if not complete and plays_later[pid - 1]:
            minutes += 90
        final[pid] = PlayerPerformance(pid, pos, minutes, minutes // 30)
    lineup = Lineup(
        starting=tuple(range(1, len(xi) + 1)),
        bench_gkp=len(xi) + 1,
        bench_order=tuple(range(len(xi) + 2, size + 1)),
        captain=2,
        vice_captain=3,
    )
    projected = score_lineup(lineup, now, game_rules)
    played_out = score_lineup(lineup, final, game_rules)
    assert set(projected.autosubs_in) <= set(played_out.autosubs_in)


def _positions() -> dict[int, Position]:
    return {i: perf.position for i, perf in _team().items()}


def _kwargs(lineup: Lineup) -> dict[str, Any]:
    return {f: getattr(lineup, f) for f in Lineup.__dataclass_fields__}


# --- Underlying expected points (ORC-12) ---------------------------------------------------------


def _row(pid: int, position: str, minutes: int, **stats: Any) -> dict[str, Any]:
    return {"player_id": pid, "position": position, "minutes": minutes, **stats}


def _units(mean: float, per: int) -> float:
    """``E[floor(N / per)]``, ``N ~ Poisson(mean)``, by brute force, apart from the module's sum."""
    return sum(math.exp(-mean) * mean**k / math.factorial(k) * (k // per) for k in range(60))


def test_one_players_underlying_xp_is_the_hand_calculation_from_the_config(
    game_rules: GameRules,
) -> None:
    """ORC-12's acceptance: a midfielder's 90 minutes on 0.4 xG, 0.2 xA and 1.0 xGC, with his real
    yellow card and bonus point (they have no expected input), scored only from the rules. His two
    real goals and three conceded do not count: the expected figures replace them."""
    s = game_rules.scoring
    rows = pd.DataFrame(
        [
            _row(
                1, "MID", 90, expected_goals=0.4, expected_assists=0.2,
                expected_goals_conceded=1.0, goals_scored=2, assists=0, clean_sheets=0,
                goals_conceded=3, yellow_cards=1, bonus=1,
            )
        ]
    )  # fmt: skip
    hand = (
        s.long_play
        + 0.4 * s.goals_scored[Position.MID]
        + 0.2 * s.assists
        + math.exp(-1.0) * s.clean_sheets[Position.MID]  # P(no goal) under Poisson(1.0)
        + _units(1.0, s.goals_conceded_per_point) * s.goals_conceded[Position.MID]
        + s.yellow_cards
        + s.bonus
    )
    assert underlying_points(rows, game_rules) == {1: pytest.approx(hand)}


def test_goals_conceded_count_whole_units_and_a_substitute_gets_no_clean_sheet(
    game_rules: GameRules,
) -> None:
    s = game_rules.scoring
    per = s.goals_conceded_per_point
    # E[floor(N/2)] = (mean - P(N odd)) / 2: a closed form the brute force must meet.
    assert _units(2.0, 2) == pytest.approx((2.0 - (1 - math.exp(-4.0)) / 2) / 2)
    rows = pd.DataFrame(
        [
            _row(1, "DEF", 90, expected_goals_conceded=2.0, saves=0),
            _row(2, "DEF", s.long_play_minutes - 1, expected_goals_conceded=0.1),
            _row(3, "DEF", 0, expected_goals=0.5),
        ]
    )
    got = underlying_points(rows, game_rules)
    assert got[1] == pytest.approx(
        s.long_play
        + math.exp(-2.0) * s.clean_sheets[Position.DEF]
        + _units(2.0, per) * s.goals_conceded[Position.DEF]
    )
    assert got[2] == pytest.approx(s.short_play + _units(0.1, per) * s.goals_conceded[Position.DEF])
    assert got[3] == 0.0


def test_a_match_without_expected_figures_scores_the_actual_and_doubles_are_summed(
    game_rules: GameRules,
) -> None:
    s = game_rules.scoring
    actual = {"goals_scored": 1, "assists": 1, "clean_sheets": 1, "goals_conceded": 0}
    rows = pd.DataFrame(
        [
            _row(1, "FWD", 90, expected_goals=None, expected_assists=None,
                 expected_goals_conceded=None, **actual),
            _row(1, "FWD", 90, expected_goals=0.5, expected_assists=0.0,
                 expected_goals_conceded=0.0, **actual),
        ]
    )  # fmt: skip
    once = s.long_play + s.goals_scored[Position.FWD] + s.assists + s.clean_sheets[Position.FWD]
    again = s.long_play + 0.5 * s.goals_scored[Position.FWD] + s.clean_sheets[Position.FWD]
    assert underlying_points(rows, game_rules) == {1: pytest.approx(once + again)}


@pytest.mark.parametrize("chip", [None, "bboost", "3xc"])
def test_a_teams_underlying_is_its_final_xi_and_armband(
    chip: str | None, game_rules: GameRules
) -> None:
    """The players and the armband the realised scorer fielded, at their underlying points."""
    perfs = _team(p6=_perf(6, Position.MID, 0, 0))  # the captain did not play: 13 comes on
    lineup = Lineup(**{**_kwargs(_XI), "chip": chip})
    scored = score_lineup(lineup, perfs, game_rules)
    underlying = {pid: float(pid) for pid in range(1, 16)} | {6: 0.0}
    fielded = range(1, 16) if chip == "bboost" else [*range(1, 6), 13, *range(7, 12)]
    extra = game_rules.chips.armband(chip) - 1
    want = sum(underlying[p] for p in fielded) + underlying[7] * extra  # the vice's armband
    assert underlying_team_points(lineup, scored, underlying, game_rules) == pytest.approx(want)
