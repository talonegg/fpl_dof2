"""The evaluation step: a Finished gameweek judged once, on the owner's real squad (ORC-05).

The fixture is a 15-player squad held from GW1 into GW2, built so the real deadline state and the
old placeholders (every held player £5.0m at club 1, clubs and prices read today) choose different
hindsight optima: player 8 was bought for £4.5m and is worth £6.0m at the GW2 deadline, so he sells
for £5.2m, exactly the price of player 16; and player 18 was at club 1 at the deadline, where the
owner already held three (3, 13 and 14), though he has since moved to club 9 (D-31).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from typing import Any

import pandas as pd
import pytest

from fpl_dof.config.models import Config
from fpl_dof.gameweek import Due, SilverTables, season_states
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.publish.benchmark import build_live_xp_accuracy
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.season_log import build_log
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.silver.tables import Table
from fpl_dof.squad.state import HeldPlayer, Provenance, SquadState
from fpl_dof.stages import week
from fpl_dof.week import evaluation
from fpl_dof.week.evaluation import Evidence, build_evaluation, evaluation_path, unready
from fpl_dof.week.ledger import advice_path, predictions_path
from fpl_dof.week.oracle import solve_hindsight_optimal

ENTRY = 7
SEASON = "2026/27"
AS_OF = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
POSITIONS = {
    **dict.fromkeys((1, 2), "GKP"),
    **dict.fromkeys(range(3, 8), "DEF"),
    **dict.fromkeys((*range(8, 13), 16, 17), "MID"),
    **dict.fromkeys((13, 14, 15, 18), "FWD"),
}
#: Clubs at the GW2 deadline. Club 1 holds 3, 13 and 14, and 18 at the deadline.
CLUB_THEN = {1: 2, 2: 3, 3: 1, 4: 4, 5: 5, 6: 6, 7: 7, 8: 2, 9: 3, 10: 4, 11: 5, 12: 6}
CLUB_THEN |= {13: 1, 14: 1, 15: 8, 16: 7, 17: 8, 18: 1}
POINTS = dict.fromkeys(POSITIONS, 2) | {8: 0, 13: 1, 14: 2, 15: 0, 16: 20, 17: 12, 18: 25}


def _price(gameweek: int, pid: int) -> float:
    if pid == 8:
        return 4.5 if gameweek == 1 else 6.0
    return 5.2 if pid == 16 else 5.0


def _evidence(*, gw2_rows: bool = True) -> Evidence:
    rows = [
        {
            "season": SEASON,
            "gameweek": gw,
            "player_id": pid,
            "web_name": f"P{pid}",
            "position": pos,
            "team_id": CLUB_THEN[pid],
            "kickoff_time": pd.Timestamp("2026-08-30T14:00:00Z"),
            "minutes": 90,
            "total_points": POINTS[pid] if gw == 2 else 2,
            "price": _price(gw, pid),
        }
        for gw in ((1, 2) if gw2_rows else (1,))
        for pid, pos in POSITIONS.items()
    ]
    players = pd.DataFrame(
        [
            {
                "player_id": pid,
                "web_name": f"P{pid}",
                "position": pos,
                "team_id": 9 if pid == 18 else CLUB_THEN[pid],  # 18 has moved since
                "price": {8: 6.5, 16: 5.2}.get(pid, 5.0),
            }
            for pid, pos in POSITIONS.items()
        ]
    )
    picks = pd.DataFrame(
        [
            {
                "entry_id": ENTRY,
                "gameweek": gw,
                "player_id": pid,
                "slot": pid,
                "multiplier": 2 if pid == 9 else 1,
                "is_captain": pid == 9,
                "is_vice_captain": pid == 10,
                "purchase_price": None,
                "selling_price": None,
            }
            for gw in (1, 2)
            for pid in range(1, 16)
        ]
    )
    scores = pd.DataFrame(
        [
            {
                "entry_id": ENTRY,
                "gameweek": gw,
                "points": 40 + gw,
                "total_points": 40 * gw,
                "rank": None,
                "overall_rank": None,
                "bank": 0.0,
                "points_on_bench": 0,
                "transfers": 0,
                "transfers_cost": 0,
            }
            for gw in (1, 2)
        ]
    )
    fixtures = pd.DataFrame(
        [
            {"gameweek": gw, "home_team_id": h, "away_team_id": a, "finished": True}
            for gw in (1, 2)
            for h, a in ((1, 2), (3, 4), (5, 6), (7, 8))
        ]
    )
    return Evidence(
        season=SEASON,
        player_gameweek=pd.DataFrame(rows),
        players=players,
        fixtures=fixtures,
        picks=picks,
        entry_gameweeks=scores,
        chips=None,
        transfers=None,
    )


def _advice() -> dict[str, Any]:
    advised = {
        "gameweek": 2,
        "squad": list(range(1, 16)),
        "starting": [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15],
        "bench_order": [6, 7, 12],
        "reserve_goalkeeper": 2,
        "captain": 9,
        "vice_captain": 10,
        "expected_points": 50.0,
    }
    return {
        "gameweek": 2,
        "run_id": "run-gw2",
        "recorded_at": "2026-08-28T08:00:00Z",
        "advised": advised,
        "recommendation": {"transfers": 0, "hit_points": 0, "moves": []},
        "squad_state": {"bank": 0.0, "free_transfers": 1},
    }


def _predictions() -> dict[str, pd.DataFrame]:
    def frame(xp: float) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"player_id": p, "xp_next": xp, "xp_next_sd": 1.0, "start_probability": 1.0}
                for p in POSITIONS
            ]
        )

    return {"c3": frame(2.0), "c1": frame(3.0)}


def _evaluate(rules: GameRules, evidence: Evidence | None = None) -> dict[str, Any]:
    return build_evaluation(
        2,
        evidence=evidence or _evidence(),
        advice=_advice(),
        predictions=_predictions(),
        rules=rules,
        entry_id=ENTRY,
        as_of=AS_OF,
        run_id="run-eval",
    )


def test_the_hindsight_optimum_honours_the_deadline_clubs_and_selling_prices(
    game_rules: GameRules,
) -> None:
    rules = game_rules.model_copy(update={"season": SEASON})
    optimal = _evaluate(rules)["log"]["hindsight"]["optimal"]["optimal_overall"]
    moves = {(m["player_out_id"], m["player_in_id"]): m for m in optimal["moves"]}
    # 8 sells for £5.2m and buys 16; 18 comes in for a club-1 player, never for 15 (club 8).
    assert set(moves) == {(8, 16), (13, 18)}
    assert moves[(8, 16)]["selling_price"] == pytest.approx(5.2)
    assert moves[(8, 16)]["player_out_name"] == "P8"
    # GW2 starts on one free transfer (D-36), so the second move costs a hit, and is worth it.
    assert optimal["hit_points"] == game_rules.transfers.extra_transfer_cost

    # The placeholders this replaces choose otherwise: £5.0m buys 17, not 16, and 18's club today
    # lets 15 make way for him.
    placeholder = SquadState(
        entry_id=None,
        gameweek=2,
        players=tuple(
            HeldPlayer(pid, Position(POSITIONS[pid]), 1, 5.0, 5.0) for pid in range(1, 16)
        ),
        bank=0.0,
        free_transfers=1,
        chips_used=(),
        provenance=Provenance.RECONSTRUCTED,
    )
    pool = _evidence().players.assign(now_cost=lambda f: f["price"])  # type: ignore[union-attr]
    pool["xp_next"] = pool["player_id"].map(POINTS).astype(float)
    old = solve_hindsight_optimal(gameweek=2, state=placeholder, pool=pool, rules=rules)
    assert {(m.player_out_id, m.player_in_id) for m in old.optimal_overall.moves} != set(moves)
    assert 16 not in {m.player_in_id for m in old.optimal_overall.moves}


def test_the_captains_belief_is_divided_by_the_rules_armband(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The diagnostics read a strategy's captain xP off its lineup's xP, by the armband the rules
    set for the chip in force, never a literal (Invariant 2)."""
    chips = game_rules.chips.model_copy(update={"captain_multiplier": 4})
    rules = game_rules.model_copy(update={"season": SEASON, "chips": chips})
    seen: dict[str, Any] = {}

    def spy(**kwargs: Any) -> list[Any]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(evaluation, "diagnose_oracle_gap", spy)
    _evaluate(rules)
    assert seen["models_xp"]["c3"] == {9: 50.0 / 4}


def test_the_evaluation_scores_each_strategy_and_its_xp(game_rules: GameRules) -> None:
    rules = game_rules.model_copy(update={"season": SEASON})
    result = _evaluate(rules)
    assert result["scorer_version"] == evaluation.SCORER_VERSION
    c3 = result["strategies"]["c3"]
    # The XI scores 2 each but 8 (0), 13 (1), 15 (0); the captain, 9, doubles his 2.
    assert c3["actual"]["points"] == 2 * 8 + 1 + 2
    # c3 forecast 2.0 for all: 2 off for 8 and 15, 1 for 13, 18 for 16, 10 for 17, 23 for 18.
    assert c3["xp_accuracy"] == {
        "mae": round((2 + 2 + 1 + 18 + 10 + 23) / 18, 4),
        "bias": round((2 + 2 + 1 - 18 - 10 - 23) / 18, 4),
        "players": 18,
    }
    assert result["strategies"]["c1"]["actual"] is None  # predicted, but advised nothing
    log = build_log(
        entry_id=ENTRY, season=SEASON, evaluations={2: result}, contract_version=CONTRACT_VERSION
    )
    assert log is not None and log["gameweeks"][0]["advised"]["run_id"] == "run-gw2"
    assert build_log(entry_id=8, season=SEASON, evaluations={2: result}, contract_version=1) is None
    Contract(root=find_contracts_root()).validate("log", log)
    accuracy = build_live_xp_accuracy(SEASON, {2: result})
    assert accuracy is not None
    Contract(root=find_contracts_root()).validate("xp_accuracy", accuracy)
    assert accuracy["seasons"][0]["pooled_mae"]["c3"] == c3["xp_accuracy"]["mae"]


def test_a_gameweek_waits_for_complete_evidence() -> None:
    assert unready(2, _evidence(), entry_id=ENTRY, lagging_share=0.02) is None
    assert "no player_gameweek rows" in str(
        unready(2, _evidence(gw2_rows=False), entry_id=ENTRY, lagging_share=0.02)
    )
    complete = _evidence()
    scores = complete.entry_gameweeks
    assert scores is not None
    late = dataclasses.replace(complete, entry_gameweeks=scores[scores["gameweek"] == 1])
    assert "not scored" in str(unready(2, late, entry_id=ENTRY, lagging_share=0.02))


def test_a_finished_gameweek_is_evaluated_once_and_again_for_a_new_scorer(
    config: Config, layout: DataLayout, game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules = game_rules.model_copy(update={"season": SEASON})
    evidence = _evidence()
    tables = {
        Table.PLAYER_GAMEWEEK: evidence.player_gameweek,
        Table.PLAYER: evidence.players,
        Table.FIXTURE: evidence.fixtures,
        Table.ENTRY_PICK: evidence.picks,
        Table.ENTRY_GAMEWEEK: evidence.entry_gameweeks,
    }
    monkeypatch.setattr(week, "read_table_optional", lambda _root, _season, t: tables.get(t))
    advice_path(layout, 2).parent.mkdir(parents=True)
    advice_path(layout, 2).write_text(json.dumps(_advice()), encoding="utf-8")
    for sid, frame in _predictions().items():
        predictions_path(layout, 2, sid).parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(predictions_path(layout, 2, sid), index=False)
    gameweeks = pd.DataFrame(
        [
            {
                "gameweek": gw,
                "name": f"Gameweek {gw}",
                "deadline_time": pd.Timestamp(f"2026-08-{14 * gw:02d}T17:30:00Z"),
                "finished": True,
                "is_next": False,
                "data_checked": True,
            }
            for gw in (1, 2)
        ]
    )
    config = config.model_copy(update={"entry": config.entry.model_copy(update={"team_id": ENTRY})})
    ctx = StageContext(config=config, layout=layout, run_id="r", as_of=AS_OF)

    def run() -> list[int]:
        states = season_states(SilverTables(gameweeks), evaluation.evaluated(layout), AS_OF)
        due = [s.gameweek for s in states if s.due is Due.EVALUATE]
        week.evaluate(ctx, rules, due)
        return due

    assert run() == [1, 2]
    written = evaluation_path(layout, 2).read_bytes()
    assert run() == []  # Evaluated: nothing is due, nothing is rewritten
    assert evaluation_path(layout, 2).read_bytes() == written

    monkeypatch.setattr(evaluation, "SCORER_VERSION", "next")
    assert run() == [1, 2]
    assert json.loads(evaluation_path(layout, 2).read_text("utf-8"))["scorer_version"] == "next"
