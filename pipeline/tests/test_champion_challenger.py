"""Champion/challenger: C1's full weekly answer published beside the engine's, in its schema."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from fpl_dof.config.loader import load_config
from fpl_dof.config.models import OptimiserConfig, TransferConfig
from fpl_dof.optimise.transfer import recommend_transfers
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.rules.models import GameRules
from fpl_dof.shadow import c1
from fpl_dof.stages import week
from fpl_dof.week.deadline import next_deadline
from squads import players as _players
from test_c3_shadow import _forecast, _state

CONFIG = OptimiserConfig(enforce_start_probability_floor=False)


def _deadline() -> Any:
    frame = pd.DataFrame(
        [
            {
                "gameweek": 2,
                "name": "Gameweek 2",
                "deadline_time": pd.Timestamp("2026-08-28T17:30:00Z"),
                "finished": False,
                "is_next": True,
            }
        ]
    )
    return next_deadline(
        frame,
        now=dt.datetime(2026, 8, 25, tzinfo=dt.UTC),
        local_zone="Australia/Sydney",
        decide_by_hours=12,
    )


def _ctx() -> Any:
    cfg, _ = load_config(environ={})
    cfg = cfg.model_copy(
        update={
            "optimiser": cfg.optimiser.model_copy(update={"enforce_start_probability_floor": False})
        }
    )
    return SimpleNamespace(config=cfg, run_id="run-cc")


def _challenger(game_rules: GameRules) -> tuple[Any, c1.Challenger, Any]:
    players = _players()
    state = _state(game_rules, players)
    # Distinct numbers so C1 and the engine can disagree.
    fc = _forecast(players, {int(p): float(i % 7) for i, p in enumerate(players["player_id"])})
    rec = recommend_transfers(fc, state, game_rules, TransferConfig(), CONFIG)
    return state, c1.Challenger(recommendation=rec, forecast=fc, captain_scores=None), fc


def _write(game_rules: GameRules, gold: Path, challenger: c1.Challenger, state: Any) -> Path | None:
    return week._write_challenger_safely(
        gold,
        challenger,
        ctx=_ctx(),
        rules=game_rules,
        state=state,
        alerts=[],
        deadline=_deadline(),
        reconciliation=None,
        form=None,
    )


def test_publish_challenger_defaults_on() -> None:
    assert OptimiserConfig().publish_challenger is True
    assert OptimiserConfig().shadow_c1 is True


def test_challenger_is_written_in_the_week_schema_with_a_model_label(
    game_rules: GameRules, tmp_path: Path
) -> None:
    state, challenger, _ = _challenger(game_rules)
    path = _write(game_rules, tmp_path, challenger, state)
    assert path is not None and path.name == week.CHALLENGER_FILENAME
    payload = json.loads(path.read_text())
    assert payload["model"] == week.CHALLENGER_MODEL
    advised = payload["advised"]
    assert len(advised["starting"]) == 11
    assert advised["captain"] in advised["starting"]
    assert advised["vice_captain"] in advised["starting"]
    assert len(advised["bench_order"]) + 1 + 11 == 15  # bench + reserve GK + XI
    assert "moves" in payload["recommendation"]
    payload["contract_version"] = CONTRACT_VERSION
    Contract(root=find_contracts_root()).validate("week", payload)


def test_champion_model_label_validates() -> None:
    schema = Contract(root=find_contracts_root()).schema("week")
    assert schema["properties"]["model"]["properties"]["role"]["enum"] == [
        "champion",
        "challenger",
    ]
    assert week.CHAMPION_MODEL["role"] == "champion"


def test_a_challenger_that_cannot_be_rendered_is_dropped_not_raised(
    game_rules: GameRules, tmp_path: Path
) -> None:
    state, challenger, fc = _challenger(game_rules)
    (tmp_path / week.CHALLENGER_FILENAME).write_text("{stale}")
    broken = c1.Challenger(
        recommendation=challenger.recommendation,
        forecast=fc.iloc[0:0],  # no rows: every lookup fails
        captain_scores=None,
    )
    assert _write(game_rules, tmp_path, broken, state) is None
    assert not (tmp_path / week.CHALLENGER_FILENAME).exists()


def test_shadow_log_reuses_a_precomputed_challenger(
    game_rules: GameRules, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, challenger, _ = _challenger(game_rules)

    def must_not_refit(**_: object) -> None:
        raise AssertionError("C1 was fitted twice")

    monkeypatch.setattr(c1, "run_shadow", must_not_refit)
    path = c1.run_shadow_safely(
        gold=tmp_path,
        run_id="r",
        gameweek=2,
        engine=challenger.recommendation,
        result=challenger,
    )
    assert path is not None
    assert json.loads(path.read_text())["status"] == "ok"


def test_shadow_log_records_a_precomputed_failure(game_rules: GameRules, tmp_path: Path) -> None:
    _, challenger, _ = _challenger(game_rules)
    path = c1.run_shadow_safely(
        gold=tmp_path,
        run_id="r",
        gameweek=2,
        engine=challenger.recommendation,
        result=RuntimeError("c1 fit failed"),
    )
    assert path is not None
    payload = json.loads(path.read_text())
    assert payload["status"] == "failed" and "c1 fit failed" in payload["error"]
