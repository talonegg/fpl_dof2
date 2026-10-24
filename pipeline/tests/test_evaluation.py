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
from fpl_dof.publish.benchmark import build_live_xp_accuracy, with_record
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


def test_the_optimum_prices_a_player_as_of_the_deadline_not_the_fixture(
    game_rules: GameRules, caplog: pytest.LogCaptureFixture
) -> None:
    """D-31: 16 cost £5.3m at the GW2 deadline and fell to £5.2m before kick-off, which is what his
    fixture row records. Priced at the deadline, 8's £5.2m no longer buys him."""
    rules = game_rules.model_copy(update={"season": SEASON})
    deadline = pd.Timestamp("2026-08-28T17:30:00Z")
    history = pd.DataFrame(
        {
            "observed_at": [deadline - pd.Timedelta(hours=16), deadline + pd.Timedelta(hours=8)],
            "player_id": [16, 16],
            "price": [5.3, 5.2],
        }
    )
    gameweeks = pd.DataFrame(
        {"gameweek": [1, 2], "deadline_time": [deadline - pd.Timedelta(days=14), deadline]}
    )
    evidence = dataclasses.replace(_evidence(), price_history=history, gameweeks=gameweeks)
    with caplog.at_level("WARNING"):
        optimal = _evaluate(rules, evidence)["log"]["hindsight"]["optimal"]["optimal_overall"]
    assert (8, 16) not in {(m["player_out_id"], m["player_in_id"]) for m in optimal["moves"]}
    # Every other player has no observation, so each keeps his fixture's price, said aloud.
    assert any(r.message == "evaluation.price_not_observed_at_deadline" for r in caplog.records)


def test_a_failed_optimum_and_armless_picks_are_said_not_swallowed(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DP-15 without silence: a solve that raises keeps the rankings and records why there is no
    optimum, as a squad never held does; picks with no captain are incomplete, so the gameweek is
    not judged on a guessed armband."""

    def unsolvable(**_k: Any) -> Any:
        raise RuntimeError("infeasible")

    rules = game_rules.model_copy(update={"season": SEASON})
    with monkeypatch.context() as patch:
        patch.setattr(evaluation, "solve_hindsight_optimal", unsolvable)
        hindsight = _evaluate(rules)["log"]["hindsight"]
    assert hindsight["optimal"] is None and hindsight["rankings"]
    assert hindsight["optimal_unavailable_reason"] == (
        "the hindsight optimum could not be solved: RuntimeError: infeasible"
    )

    complete = _evidence()
    assert complete.picks is not None
    armless = dataclasses.replace(complete, picks=complete.picks.assign(is_captain=False))
    with pytest.raises(ValueError, match="GW2 picks name no captain"):
        _evaluate(rules, armless)


def test_a_transfer_in_gets_each_models_own_xp_not_zero(game_rules: GameRules) -> None:
    """D-37: the diagnostics read each strategy's recorded xP for the player himself, and his
    underlying points, rather than a team's xP keyed by its own captain (0.0 for anyone else)."""
    rules = game_rules.model_copy(update={"season": SEASON})
    diagnostics = _evaluate(rules)["log"]["hindsight"]["diagnostics"]
    brought = {d["player_id"]: d for d in diagnostics if d["role"] == "transfer_in"}
    assert set(brought) == {16, 18}
    # c1 advised nothing but priced every player, so its belief is shown too.
    assert brought[16]["models_xp"] == {"c3": 2.0, "c1": 3.0}
    # 90 minutes and no expected figures recorded: the appearance alone.
    assert brought[16]["underlying_points"] == rules.scoring.long_play


def test_the_evaluation_scores_each_strategy_and_its_xp(game_rules: GameRules) -> None:
    rules = game_rules.model_copy(update={"season": SEASON})
    result = _evaluate(rules)
    assert result["evaluation_version"] == evaluation.EVALUATION_VERSION
    c3 = result["strategies"]["c3"]
    # The XI scores 2 each but 8 (0), 13 (1), 15 (0); the captain, 9, doubles his 2.
    assert c3["actual"]["points"] == 2 * 8 + 1 + 2
    # Every one of the XI played 90 minutes with no expected figures: the appearance each, the
    # captain's again. The forecast error is the advice's 50.0 xP over it; the luck, the points.
    underlying = rules.scoring.long_play * (11 + rules.chips.captain_multiplier - 1)
    assert c3["actual"]["underlying_points"] == underlying
    assert c3["actual"]["forecast_error"] == 50.0 - underlying
    assert c3["actual"]["luck"] == c3["actual"]["points_before_hits"] - underlying
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


def test_the_published_xp_accuracy_carries_the_2025_26_record_forward() -> None:
    """WEB-04: the frozen-era backtest season is in every publication, live season or not."""
    contract = Contract(root=find_contracts_root())
    alone = with_record(None)
    contract.validate("xp_accuracy", alone)
    assert [(s["season"], s["kind"]) for s in alone["seasons"]] == [("2025/26", "backtest")]
    live = {"seasons": [{**alone["seasons"][0], "season": SEASON, "kind": "prospective"}]}
    merged = with_record(live)
    contract.validate("xp_accuracy", merged)
    assert [(s["season"], s["kind"]) for s in merged["seasons"]] == [
        ("2025/26", "backtest"),
        (SEASON, "prospective"),
    ]
    # A live season of the same season and kind replaces the recorded one.
    replaced = with_record({"seasons": [{**alone["seasons"][0], "pooled_mae": {"c3": 1.0}}]})
    assert [s["pooled_mae"] for s in replaced["seasons"]] == [{"c3": 1.0}]


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


def test_a_gameweek_waits_for_the_owners_picks_and_history() -> None:
    """A degraded entry ingest must not store ``log: null`` for good (ORC-05)."""
    complete = _evidence()
    picks, scores = complete.picks, complete.entry_gameweeks
    assert picks is not None and scores is not None
    for degraded in (
        dataclasses.replace(complete, picks=None),
        dataclasses.replace(complete, picks=picks[picks["gameweek"] == 1]),
        dataclasses.replace(complete, entry_gameweeks=None),
        dataclasses.replace(complete, picks=None, entry_gameweeks=None),
    ):
        assert unready(2, degraded, entry_id=ENTRY, lagging_share=0.02) is not None
    # An entry the game shows starting at GW3 had no GW2 team: judged, with no log row.
    later = scores.assign(gameweek=3)
    joined = dataclasses.replace(
        complete, picks=picks[picks["gameweek"] > 2], entry_gameweeks=later
    )
    assert unready(2, joined, entry_id=ENTRY, lagging_share=0.02) is None
    assert (
        unready(2, dataclasses.replace(complete, picks=None), entry_id=None, lagging_share=0.02)
        is None
    )


def test_a_finished_gameweek_is_evaluated_once_and_again_for_a_new_version(
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

    def run(on: StageContext = ctx) -> list[int]:
        done = evaluation.evaluated(layout, on.config.entry.team_id)
        states = season_states(SilverTables(gameweeks), done, AS_OF)
        due = [s.gameweek for s in states if s.due is Due.EVALUATE]
        week.evaluate(on, rules, due)
        return due

    assert run() == [1, 2]
    written = evaluation_path(layout, 2, ENTRY).read_bytes()
    assert run() == []  # Evaluated: nothing is due, nothing is rewritten
    assert evaluation_path(layout, 2, ENTRY).read_bytes() == written

    # A run with team ID 1 judges for entry 1: the owner's evaluation neither counts for it nor
    # is touched by it, and the owner's gameweeks stay Evaluated.
    other = config.model_copy(update={"entry": config.entry.model_copy(update={"team_id": 1})})
    assert run(StageContext(config=other, layout=layout, run_id="r1", as_of=AS_OF)) == [1, 2]
    assert evaluation_path(layout, 2, ENTRY).read_bytes() == written
    assert run() == []

    monkeypatch.setattr(evaluation, "EVALUATION_VERSION", "next")
    assert run() == [1, 2]
    stored = json.loads(evaluation_path(layout, 2, ENTRY).read_text("utf-8"))
    assert stored["evaluation_version"] == "next"
