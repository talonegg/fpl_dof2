"""The live season as if each model had played it (ORC-13, DL-95 item 4)."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest
import yaml

from fpl_dof.config.models import BacktestConfig, Config
from fpl_dof.decision import decide
from fpl_dof.factory import Graded, experiments
from fpl_dof.factory.history import as_if_played
from fpl_dof.factory.registry import strategies
from fpl_dof.forecast.backtest import Entrant
from fpl_dof.frames import as_float, as_int
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.models_history import build_models_history, label_as_played
from fpl_dof.rules.legality import Squad, SquadPlayer, validate_squad
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.stages import backtest, publish
from test_backtest import SEASON, RateFromFeatures, make_history
from test_models_history import WORKFLOW, Doubtful, _season

FINISHED = (1, 2, 3, 4, 5)  # GW6 is still being played


def _history(live: str) -> pd.DataFrame:
    """Eight archive gameweeks, then six of the live season a year later (fifteen a position)."""
    archive = make_history(players=60, gameweeks=8)
    current = make_history(players=60, gameweeks=6, seed=11, season=live)
    current["kickoff_time"] += pd.Timedelta(days=365)
    history = pd.concat([archive, current], ignore_index=True)
    history["total_points"] = history["total_points"].round()
    return history


def _config() -> Config:
    backtest_config = BacktestConfig(
        training_seasons=(SEASON,), minimum_training_matches=3, strategy_workers=1
    )
    return Config().model_copy(update={"backtest": backtest_config})


@pytest.fixture
def entrants(monkeypatch: pytest.MonkeyPatch) -> None:
    """c3 on the live season only, as registered; engine on every season, with its own forecast."""
    pair = [Entrant("c3", RateFromFeatures(), "current_season"), Entrant("engine", Doubtful())]
    monkeypatch.setattr(experiments, "entrants", lambda *_a: (pair, {"c1": "not in this test"}))


def _replay(history: pd.DataFrame, rules: GameRules) -> tuple[dict[str, Any], dict[str, str]]:
    return as_if_played(history, strategies(), rules, _config(), finished=FINISHED)


@pytest.mark.usefixtures("entrants")
def test_each_model_plays_the_finished_live_gameweeks_with_legal_squads(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    fielded: list[tuple[pd.DataFrame, Any, Any]] = []

    def spy(frame: pd.DataFrame, state: Any, rules: GameRules, policy: Any) -> Any:
        decision = decide(frame, state, rules, policy)
        fielded.append((frame, state, decision))
        return decision

    monkeypatch.setattr("fpl_dof.factory.history.decide", spy)
    rows, failures = _replay(_history(game_rules.season), game_rules)
    assert failures == {"c1": "not in this test"}
    assert set(rows) == {"c3", "engine"}
    # c3 sees only the live season, so its first fold is after three live gameweeks; GW6 is open.
    assert [r["gw"] for r in rows["c3"]] == [4, 5] == [r["gw"] for r in rows["engine"]]
    assert rows["c3"][0]["n_transfers"] == 0  # a fresh squad, picked under the budget
    assert rows["c3"] != rows["engine"]

    assert len(fielded) == 4
    for frame, state, decision in fielded:
        by_id = frame.set_index("player_id")
        selection = decision.selection
        squad = Squad(
            players=tuple(
                SquadPlayer(
                    pid,
                    Position(str(by_id.at[pid, "position"])),
                    as_int(by_id.at[pid, "team_id"]),
                    as_float(by_id.at[pid, "price"]),
                )
                for pid in decision.recommendation.recommended.squad_after
            ),
            starting=selection.starting,
            captain=selection.captain,
            vice_captain=selection.vice_captain,
        )
        value = sum(p.current_price for p in state.players) + state.bank
        assert validate_squad(squad, game_rules, budget=round(value, 1)) == []


@pytest.mark.usefixtures("entrants")
def test_a_gameweeks_decision_cannot_see_its_own_outcome(game_rules: GameRules) -> None:
    """Invariant 5: rewriting GW5's points changes what GW5 scored, never what was decided."""
    history = _history(game_rules.season)
    before, _ = _replay(history, game_rules)
    live = history["season"] == game_rules.season
    rewritten = history.assign(
        total_points=history["total_points"].where(~(live & (history["gameweek"] == 5)), 20.0)
    )
    after, _ = _replay(rewritten, game_rules)
    decided = ("n_transfers", "transfers", "captain", "vice_captain")
    for sid in before:
        assert before[sid][0] == after[sid][0]  # GW4 untouched
        assert {k: before[sid][1][k] for k in decided} == {k: after[sid][1][k] for k in decided}
        assert before[sid][1]["points"] != after[sid][1]["points"]


def test_nothing_is_replayed_before_a_live_gameweek_can_be_fitted(game_rules: GameRules) -> None:
    rows = as_if_played(
        _history(game_rules.season), strategies(), game_rules, _config(), finished=(1, 2, 3)
    )
    assert rows == ({}, {})


def _document(season: str) -> dict[str, Any]:
    def row(gw: int) -> dict[str, Any]:
        return {
            **{"gw": gw, "points": 50.0, "points_before_hits": 50.0, "hit_points": 0.0},
            **{"n_transfers": 0, "transfers": [], "captain": "P1", "vice_captain": "P2"},
            **{"captain_points": 8.0, "vice_used": False, "n_autosubs": 0},
        }

    return build_models_history(
        season=season,
        rows={"c3": [row(5), row(6), row(7)], "engine": [row(5), row(6), row(7)]},
        unavailable={},
        provenance={"run_id": "r"},
        contract_version=CONTRACT_VERSION,
        kind="as_if_played",
    )


def test_gameweeks_before_a_model_went_live_are_labelled_replayed() -> None:
    """A model is live from the first gameweek the live ledger holds its advice (models.json)."""
    models = {
        "gameweeks": [
            {"gameweek": 5, "record": "frozen", "advice": {"c3": {}, "engine": {}}},
            {"gameweek": 6, "record": "live", "advice": {"c3": {}}},
            {"gameweek": 7, "record": "live", "advice": {"c3": {}, "engine": {}}},
        ]
    }
    labelled = label_as_played(_document("2026/27"), models)
    Contract(root=find_contracts_root()).validate("as_if_played", labelled)
    records = {
        g["gameweek"]: {m: e["record"] for m, e in g["models"].items()}
        for g in labelled["gameweeks"]
    }
    assert records == {
        5: {"c3": "replayed", "engine": "replayed"},
        6: {"c3": "live", "engine": "replayed"},
        7: {"c3": "live", "engine": "live"},
    }
    live_from = {m["id"]: m.get("live_from") for m in labelled["models"]}
    assert live_from["c3"] == 6 and live_from["engine"] == 7 and live_from["a"] is None
    assert labelled["kind"] == "as_if_played" and "as if" in labelled["caveat"]
    # Without a live record nothing is live.
    unlabelled = label_as_played(_document("2026/27"), None)
    assert {e["record"] for g in unlabelled["gameweeks"] for e in g["models"].values()} == {
        "replayed"
    }


def test_the_backtest_records_the_live_replay_and_publish_labels_it(
    game_rules: GameRules,
    config: Config,
    layout: DataLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The weekly backtest writes ``ledger/as_if_played/<run_id>.json``; the pipeline publishes the
    newest as ``as_if_played.json``, labelled from the live record, beside the archive history."""
    _, result = _season()
    gameweeks = pd.DataFrame(
        {
            "gameweek": [1, 2, 3, 4, 5, 6],
            "deadline_time": pd.date_range("2026-08-14T17:30:00Z", periods=6, freq="7D"),
            "finished": [True] * 5 + [False],
            "data_checked": [True] * 5 + [False],
        }
    )
    tables = {"player_gameweek": _history(game_rules.season), "gameweek": gameweeks}
    monkeypatch.setattr(backtest, "read_rules", lambda *_a: game_rules)
    monkeypatch.setattr(backtest, "read_table_optional", lambda _s, _y, t: tables.get(t.value))
    monkeypatch.setattr(backtest, "grade", lambda *_a, **_k: Graded(result=result))
    monkeypatch.setattr(backtest, "_models_history", lambda *_a: [])
    row = {
        **{"points_before_hits": 44.0, "hit_points": 0.0, "n_transfers": 0, "transfers": []},
        **{"captain": "P1", "vice_captain": "P2", "captain_points": 6.0, "vice_used": False},
        **{"points": 44.0, "n_autosubs": 0},
    }
    rows = {sid: [{**row, "gw": 4}, {**row, "gw": 5}] for sid in ("c3", "engine")}
    seen: dict[str, Any] = {}

    def replay(*_a: Any, finished: Any, **_k: Any) -> Any:
        seen["finished"] = sorted(finished)
        return rows, {"c1": "its fit raised"}

    monkeypatch.setattr(backtest, "as_if_played", replay)
    ctx = StageContext(config=config, layout=layout, run_id="20261027T161700Z-b")
    backtest.run(ctx)
    assert seen["finished"] == list(FINISHED)  # the gameweek still being played is left out
    recorded = layout.ledger / "as_if_played" / f"{ctx.run_id}.json"
    documents = json.loads(recorded.read_text("utf-8"))
    assert [d["season"] for d in documents] == [game_rules.season]

    published = publish._as_if_played(
        ctx, {"gameweeks": [{"gameweek": 5, "record": "live", "advice": {"c3": {}}}]}
    )
    assert published is not None
    Contract(root=find_contracts_root()).validate("as_if_played", published)
    assert published["gameweeks"][0]["models"]["c3"]["record"] == "replayed"
    assert published["gameweeks"][1]["models"]["c3"]["record"] == "live"
    c1 = next(m for m in published["models"] if m["id"] == "c1")
    assert c1["available"] is False and "its fit raised" in c1["unavailable_reason"]


def test_the_weekly_job_records_and_the_pipeline_restores_the_live_replay() -> None:
    steps = yaml.safe_load(WORKFLOW.read_text("utf-8"))["jobs"]["backtest"]["steps"]
    record = next(s for s in steps if s.get("name", "").startswith("Record this run"))
    assert "as_if_played" in record["run"]
    pipeline = WORKFLOW.with_name("pipeline.yml").read_text("utf-8")
    assert "experiments models_history as_if_played" in pipeline
