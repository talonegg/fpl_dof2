"""The models history (ORC-06): each strategy's simulated season, the assembly, and its round trip
through ``ledger`` from the backtest stage to the published contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from fpl_dof.artefacts import MODELS_HISTORY_FAILURE_FILENAME
from fpl_dof.config.models import BacktestConfig, Config, ForecastConfig
from fpl_dof.factory import Graded
from fpl_dof.factory import history as factory_history
from fpl_dof.factory.history import season_histories
from fpl_dof.factory.registry import strategies
from fpl_dof.forecast.backtest import BacktestResult, Entrant, prediction_column, walk_forward
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.models_history import build_models_history
from fpl_dof.rules.models import GameRules
from fpl_dof.stages import backtest, publish
from test_backtest import SEASON, RateFromFeatures, make_history

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "backtest.yml"


def _row(gw: int, points: float, hit: float = 0.0) -> dict[str, Any]:
    return {
        "gw": gw,
        "points": points,
        "points_before_hits": points - hit,
        "hit_points": hit,
        "n_transfers": 2 if hit else 1,
        "transfers": ["A → B"],
        "captain": "Haaland",
        "vice_captain": "Salah",
        "captain_points": 8.0,
        "vice_used": False,
        "n_autosubs": 0,
    }


def _build(**over: Any) -> dict[str, Any]:
    rows = {  # legacy keys, as the offline scripts write them: resolved through the registry
        "champion": [_row(1, 50), _row(2, 40), _row(3, 60)],
        "challenger": [_row(1, 60, -4), _row(2, 40), _row(3, 50)],
        "engine": [_row(1, 40), _row(2, 30), _row(3, 70), _row(4, 99)],
    }
    args: dict[str, Any] = {
        "season": "2025/26",
        "rows": rows,
        "unavailable": {"a": "no run"},
        "provenance": {"frozen_tag": "t"},
        "contract_version": CONTRACT_VERSION,
    } | over
    return build_models_history(**args)


def test_built_payload_matches_schema() -> None:
    Contract(root=find_contracts_root()).validate("models_history", _build())


def test_only_common_gameweeks_are_compared() -> None:
    p = _build()
    assert [g["gameweek"] for g in p["gameweeks"]] == [1, 2, 3]  # engine's GW4 has no pair


def test_ranks_cumulative_and_ties() -> None:
    p = _build()
    gw1, gw2, gw3 = (g["models"] for g in p["gameweeks"])
    assert (gw1["c1"]["rank"], gw1["c3"]["rank"], gw1["engine"]["rank"]) == (1, 2, 3)
    assert gw2["c3"]["rank"] == gw2["c1"]["rank"] == 1  # tie shares the better rank
    assert gw3["engine"]["cumulative"] == 140 and gw3["c3"]["cumulative"] == 150
    assert gw3["c3"]["cumulative_rank"] == 1 and gw3["c1"]["cumulative_rank"] == 1
    assert gw1["c1"]["hit_points"] == -4


def test_summary_and_deltas() -> None:
    s = {x["model"]: x for x in _build()["summary"]}
    assert s["c3"]["delta_vs_champion"] is None
    d = s["engine"]["delta_vs_champion"]
    assert d["total"] == -10 and d["mean"] == pytest.approx(-3.33, abs=0.01)
    assert d["gameweeks_better"] == 1 and d["gameweeks_worse"] == 2
    assert d["ci_low"] <= d["mean"] <= d["ci_high"]
    assert s["c1"]["gameweeks_won"] == 2  # GW1 outright + GW2 shared
    assert s["c1"]["hit_points"] == -4


def test_unavailable_models_are_marked_not_invented() -> None:
    p = _build()
    a = next(m for m in p["models"] if m["id"] == "a")
    assert a["available"] is False and a["unavailable_reason"] == "no run"
    assert all("a" not in g["models"] for g in p["gameweeks"])
    assert p["kind"] == "backtest" and "not real play" in p["caveat"]


class Doubtful(RateFromFeatures):
    """A noisier forecaster, so two strategies pick differently."""

    def predict(self, features: pd.DataFrame, *, gameweek: int | None = None) -> pd.Series:
        base = super().predict(features, gameweek=gameweek)
        return base * (1 + (features["player_code"] % 3) * 0.5)


Simulated = tuple[pd.DataFrame, BacktestResult, tuple[dict[str, Any], dict[str, str]]]


@pytest.fixture(scope="module")
def simulated(game_rules: GameRules) -> Simulated:
    """Sixty players over eight gameweeks (fifteen a position, ten a club): enough for a squad.
    Walked and simulated once for the module, in this process."""
    history, result = _season()
    return (
        history,
        result,
        season_histories(result.predictions, history, strategies(), game_rules, _config(1)),
    )


def _season() -> tuple[pd.DataFrame, BacktestResult]:
    history = make_history(players=60, gameweeks=8)
    history["total_points"] = history["total_points"].round()
    result = walk_forward(
        history,
        [Entrant("c3", RateFromFeatures(), "current_season"), Entrant("engine", Doubtful())],
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(minimum_training_matches=3),
    )
    return history, result


def _config(workers: int) -> Config:
    backtest = BacktestConfig(training_seasons=(SEASON,), strategy_workers=workers)
    return Config().model_copy(update={"backtest": backtest})


def test_every_graded_strategy_plays_its_own_season(
    game_rules: GameRules, simulated: Simulated
) -> None:
    _, result, (by_season, failures) = simulated
    assert failures == {}
    rows = by_season[SEASON]
    assert set(rows) == {"c3", "engine"}  # only the strategies the walk graded
    graded = sorted({f.gameweek for f in result.folds})
    free, cost = 0, abs(game_rules.transfers.extra_transfer_cost)
    for row in rows["c3"]:
        assert row["points"] == row["points_before_hits"] + row["hit_points"]
        # GW1 of the squad makes no transfer; after it one a week rolls, and extras are charged.
        assert row["hit_points"] == -cost * max(0, row["n_transfers"] - free)
        free = max(1, min(game_rules.transfers.max_free_transfers, free - row["n_transfers"] + 1))
        assert row["captain"].startswith("P") and row["vice_captain"] != row["captain"]
        assert len(row["transfers"]) == row["n_transfers"]
        assert all(out.startswith("P") and into.startswith("P") for out, into in
                   (move.split(" → ") for move in row["transfers"]))  # fmt: skip
    assert [r["gw"] for r in rows["c3"]] == graded and rows["c3"][0]["n_transfers"] == 0
    assert any(row["n_transfers"] for row in rows["c3"])  # it trades, so the names are checked
    assert rows["c3"] != rows["engine"]  # their own squads, so their own seasons

    payload = build_models_history(
        season=SEASON,
        rows=rows,
        unavailable={"c1": "its fit raised at 2025/26 GW6: RuntimeError: diverged"},
        provenance={"run_id": "r"},
        contract_version=CONTRACT_VERSION,
    )
    Contract(root=find_contracts_root()).validate("models_history", payload)
    c1 = next(m for m in payload["models"] if m["id"] == "c1")
    assert c1["available"] is False and "GW6" in c1["unavailable_reason"]
    assert all(m["role"] != "retired" for m in payload["models"])


def test_each_fold_decides_on_a_spread_known_at_its_deadline(
    game_rules: GameRules, simulated: Simulated, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invariant 6 without look-ahead (Invariant 5): the week step is handed each player's spread,
    the strategy's error by position over its earlier folds, and a later fold's outcome never moves
    an earlier one's."""
    history, result, _ = simulated
    seen: dict[int, pd.DataFrame] = {}
    real = factory_history.decide

    def spy(frame: pd.DataFrame, state: Any, *args: Any) -> Any:
        seen[state.gameweek] = frame.copy()
        return real(frame, state, *args)

    monkeypatch.setattr(factory_history, "decide", spy)
    c3 = next(s for s in strategies() if s.id == "c3")
    keys = [*factory_history._PREDICTION_KEYS, prediction_column("c3")]
    frame = result.predictions[keys].dropna()
    factory_history.simulate(frame, history, c3, game_rules, _config(1))
    first, *rest = sorted(seen)
    floor = Config().forecast.uncertainty.floor
    assert all((seen[gw]["xp_next_sd"] >= floor).all() for gw in seen)
    assert (seen[rest[-1]]["xp_next_sd"] != seen[first]["xp_next_sd"]).any()  # measured by then

    before = {gw: f["xp_next_sd"].tolist() for gw, f in seen.items()}
    later = frame.assign(total_points=frame["total_points"].where(frame["gameweek"] < rest[-1], 99))
    factory_history.simulate(later, history, c3, game_rules, _config(1))
    assert all(seen[gw]["xp_next_sd"].tolist() == before[gw] for gw in [first, *rest])


def test_the_parallel_history_is_the_sequential_one(
    game_rules: GameRules, simulated: Simulated
) -> None:
    history, result, sequential = simulated
    parallel = season_histories(result.predictions, history, strategies(), game_rules, _config(2))
    assert parallel == sequential


def test_a_history_that_cannot_be_built_never_costs_the_experiments_record(
    game_rules: GameRules,
    simulated: Simulated,
    config: Config,
    layout: DataLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-32, DP-15: the history fails; the stage still writes the record, writes why beside the
    report, and backtest.yml appends the record before it fails on that, in its own step."""
    history, result, _ = simulated
    monkeypatch.setattr(backtest, "read_rules", lambda *_a: game_rules)
    monkeypatch.setattr(
        backtest,
        "read_table_optional",
        lambda _s, _y, t: history if t.value == "player_gameweek" else None,
    )
    monkeypatch.setattr(backtest, "grade", lambda *_a, **_k: Graded(result=result))

    def broken(*_a: Any) -> Any:
        raise RuntimeError("the simulator diverged")

    monkeypatch.setattr(backtest, "_models_history", broken)
    ctx = StageContext(config=config, layout=layout, run_id="r-history")
    backtest.run(ctx)
    assert (layout.ledger / "experiments" / "r-history.json").exists()
    assert not (layout.ledger / "models_history" / "r-history.json").exists()
    failure = layout.gold_for(game_rules.season) / MODELS_HISTORY_FAILURE_FILENAME
    assert "the simulator diverged" in failure.read_text("utf-8")

    monkeypatch.setattr(backtest, "_models_history", lambda *_a: [])
    backtest.run(ctx)
    assert not failure.exists()  # a run that builds one clears it

    steps = yaml.safe_load(WORKFLOW.read_text("utf-8"))["jobs"]["backtest"]["steps"]
    names = [s.get("name", "") for s in steps]
    record = names.index("Record this run on the `ledger` branch (MOD-08, ORC-06)")
    check = names.index("Check the models history was built")
    assert steps[record]["if"] == "${{ !cancelled() }}" and record < check
    assert MODELS_HISTORY_FAILURE_FILENAME in steps[check]["run"]


def test_the_backtest_records_it_and_the_pipeline_publishes_the_newest(
    game_rules: GameRules,
    simulated: Simulated,
    config: Config,
    layout: DataLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history, result, sequential = simulated
    monkeypatch.setattr(backtest, "season_histories", lambda *_a: sequential)
    ctx = StageContext(config=config, layout=layout, run_id="20261027T161700Z-b")
    graded = Graded(result=result, skipped={"c1": "its fit raised at 2025/26 GW6: diverged"})
    documents = backtest._models_history(ctx, graded, history, strategies(), game_rules)
    assert [d["season"] for d in documents] == [SEASON]  # each validated against the schema
    assert documents[0]["provenance"]["run_id"] == ctx.run_id

    directory = layout.ledger / "models_history"
    directory.mkdir(parents=True)
    (directory / "20261020T161700Z-a.json").write_text(json.dumps([{"season": "older run"}]))
    (directory / f"{ctx.run_id}.json").write_text(json.dumps(documents))
    (directory / "20261028T000000Z-c.json").write_text("[{torn")
    published = publish._models_history(ctx)
    assert published is not None and published["season"] == SEASON
    Contract(root=find_contracts_root()).validate("models_history", published)
