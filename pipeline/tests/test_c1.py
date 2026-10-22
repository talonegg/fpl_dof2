"""MOD-05 — C1 rebuilt behind the frame contract: its own variance, knowable features, config.

C1 must pass ``assert_no_look_ahead`` (a history row kicked off after the deadline raises, never
trains), be deterministic across two fits, take every hyperparameter, window and half-life from
``forecast.c1``, key players by ``player_code`` across seasons, and be fittable by the walk-forward
harness through ``Strategy.predictor``.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import Config, ForecastConfig
from fpl_dof.factory.registry import ForecastInputs, load_strategy
from fpl_dof.forecast.backtest import OUTCOME_COLUMNS, fold_rows
from fpl_dof.forecast.features import LeakageError
from fpl_dof.forecast.xp_v1 import ComponentPredictor
from fpl_dof.optimise.frame import ForecastFrameError
from fpl_dof.rules.models import GameRules
from fpl_dof.shadow import c1
from test_decide import _forecast_config, _snapshot

PRIOR = "2025/26"


def _cfg() -> Config:
    return _forecast_config()


def _with_prior(inputs: ForecastInputs, player_ids: pd.Series | None = None) -> ForecastInputs:
    """``inputs`` with last season's rows: the same players, a different points pattern."""
    history = inputs.player_gameweek
    assert history is not None
    prior = history.assign(
        season=PRIOR,
        kickoff_time=history["kickoff_time"] - pd.Timedelta(days=364),
        total_points=(history["player_code"] % 5).astype(float),
    )
    if player_ids is not None:
        prior = prior.assign(player_id=player_ids.to_numpy())
    return dataclasses.replace(inputs, player_gameweek=pd.concat([prior, history]))


def _forecast(inputs: ForecastInputs, rules: GameRules) -> pd.DataFrame:
    return load_strategy("c1").forecast(inputs, rules, _cfg()).frame


def test_c1_trains_on_every_season_silver_holds() -> None:
    assert load_strategy("c1").forecaster.training_window == "all_seasons"


def test_a_history_row_kicked_off_after_the_deadline_raises(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    planted = history.copy()
    # Labelled as played (gameweek 1) but kicked off after the deadline being forecast.
    late = pd.Timestamp(inputs.as_of) + pd.Timedelta(days=2)
    planted.loc[planted.index[0], "kickoff_time"] = late
    with pytest.raises(LeakageError, match="stamped after the deadline"):
        c1.forecast(
            dataclasses.replace(inputs, player_gameweek=planted), game_rules, _cfg().forecast
        )


def test_two_fits_on_the_same_data_give_identical_frames(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    inputs = _with_prior(inputs)
    pd.testing.assert_frame_equal(_forecast(inputs, game_rules), _forecast(inputs, game_rules))


def test_the_seed_reaches_every_fit(game_rules: GameRules) -> None:
    history = _with_prior(_snapshot(game_rules)[0]).player_gameweek
    assert history is not None
    fitted = c1.fit_as_of(history, pd.Timestamp("2027-01-01", tz="UTC"), ForecastConfig().c1)
    for clf, reg, _ in fitted.models.values():
        for model in (clf, reg):
            if model is not None:
                assert model.random_state == ForecastConfig().c1.seed


def test_the_frame_is_c1s_own_with_variance_and_no_champion_columns(game_rules: GameRules) -> None:
    inputs, champ = _snapshot(game_rules)
    got = load_strategy("c1").forecast(inputs, game_rules, _cfg())
    frame = got.frame
    assert set(frame["model"]) == {c1.MODEL_NAME} and set(frame["strategy"]) == {"c1"}
    borrowed = {c for c in frame.columns if c.startswith("component_")} | {"confidence"}
    assert not borrowed & set(frame.columns)
    assert (frame["xp_next_sd"] > 0).any()
    assert not frame["xp_next_sd"].equals(champ.frame["xp_next_sd"])
    # One gameweek: the decided one, and the horizon is that gameweek.
    assert [c for c in frame.columns if c.startswith("xp_gw_")] == ["xp_gw_5", "xp_gw_5_sd"]
    assert frame["xp_horizon"].equals(frame["xp_next"]) and set(frame["horizon_gameweeks"]) == {1}
    # Var = p*sd^2 + p(1-p)*mu^2, mu the mean if he plays: never below the between-state term.
    p = frame["start_probability"]
    mu = frame["xp_next"] / p.where(p > 0)
    assert (frame["xp_next_sd"] ** 2 + 1e-9 >= (p * (1 - p) * mu**2).fillna(0)).all()
    assert got.captain_line is not None and got.captain_line != champ.captain_line


def test_availability_news_scales_p_play(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    players = inputs.players.assign(status="a")
    players.loc[0, "status"] = "i"  # injured: the status multiplier is 0
    frame = _forecast(dataclasses.replace(inputs, players=players), game_rules)
    row = frame[frame["player_id"] == players.loc[0, "player_id"]].iloc[0]
    assert row["start_probability"] == 0.0 and row["xp_next"] == 0.0


@pytest.mark.filterwarnings("ignore:invalid value encountered in sqrt")
def test_a_broken_variance_is_refused_by_the_frame_contract(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, _ = _snapshot(game_rules)
    monkeypatch.setattr(c1, "mixture_moments", lambda states: (1.0, -1.0))
    with pytest.raises(ForecastFrameError, match="xp_next_sd"):
        c1.forecast(inputs, game_rules, _cfg().forecast)


# --- seasons --------------------------------------------------------------------------------------


def test_reused_player_ids_in_a_prior_season_change_nothing(game_rules: GameRules) -> None:
    """FPL reassigns player_id every season: C1 keys history by player_code, so a prior season
    whose ids collide with this season's (each id moved onto another player) is the same input."""
    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    shifted = history["player_id"] % history["player_id"].max() + 1
    pd.testing.assert_frame_equal(
        _forecast(_with_prior(inputs), game_rules),
        _forecast(_with_prior(inputs, shifted), game_rules),
    )


def test_features_never_cross_a_season_boundary(game_rules: GameRules) -> None:
    history = _with_prior(_snapshot(game_rules)[0]).player_gameweek
    assert history is not None
    cfg = ForecastConfig().c1
    g = c1.build_features(
        history, history.iloc[:0], as_of=pd.Timestamp("2027-01-01", tz="UTC"), config=cfg
    )
    first = g[(g["season"] == game_rules.season) & (g["gameweek"] == 1)]
    assert (first["gp"] == 0).all()  # the count restarts
    assert first[[f"total_points_l{w}" for w in cfg.rolling_windows]].isna().all().all()
    # prev_pts is the player's own previous-season mean, found by player_code.
    prior = history[history["season"] == PRIOR]
    per_gw = prior.groupby(["player_code", "gameweek"])["total_points"].sum()
    expected = per_gw.groupby("player_code").mean()
    assert np.allclose(
        first.set_index("player_code")["prev_pts"], expected.reindex(first["player_code"])
    )


# --- DP-06 ----------------------------------------------------------------------------------------

_TUNED_CALLS = {
    "HistGradientBoostingClassifier",
    "HistGradientBoostingRegressor",
    "ewm",
    "rolling",
}


def test_no_hyperparameter_window_or_half_life_is_a_literal_in_c1() -> None:
    """Every argument to a fit, a rolling window or a half-life comes from ``forecast.c1``: the
    estimator keywords are config attributes, and no tuned call takes a number (``min_periods=1``,
    use whatever history exists, is structural; flags such as ``ignore_na`` are not numbers)."""
    tree = ast.parse(inspect.getsource(c1))
    keywords = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "kw"
    ]
    assert len(keywords) == 1 and isinstance(keywords[0], ast.Dict)
    assert all(isinstance(v, ast.Attribute) for v in keywords[0].values), ast.unparse(keywords[0])
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _TUNED_CALLS:
            continue
        values = [*node.args, *(k.value for k in node.keywords if k.arg != "min_periods")]
        numbers = [
            v for v in values if isinstance(v, ast.Constant) and type(v.value) in (int, float)
        ]
        assert not numbers, ast.unparse(node)


# --- the walk-forward harness's interface ---------------------------------------------------------


def test_each_live_strategy_offers_the_harness_a_predictor(game_rules: GameRules) -> None:
    cfg = _cfg()
    engine = load_strategy("engine").predictor(game_rules, cfg)
    assert isinstance(engine, ComponentPredictor)
    assert engine.config.discrimination.minutes_v2 is False  # the entry's override applies
    assert isinstance(load_strategy("c3").predictor(game_rules, cfg), ComponentPredictor)
    assert isinstance(load_strategy("c1").predictor(game_rules, cfg), c1.C1Predictor)
    with pytest.raises(NotImplementedError):
        load_strategy("a").predictor(game_rules, cfg)


def test_the_c1_predictor_scores_a_fold_as_the_harness_hands_it(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    deadline = pd.Timestamp(history.loc[history["gameweek"] == 4, "kickoff_time"].min())
    fold = fold_rows(history, game_rules.season, 4, deadline, ForecastConfig())
    visible = fold.drop(columns=list(OUTCOME_COLUMNS), errors="ignore")  # as walk_forward does
    predictor = load_strategy("c1").predictor(game_rules, _cfg())
    predictor.fit_as_of(history, deadline, season=game_rules.season)
    got = predictor.predict(visible)
    assert got.index.equals(visible.index) and got.notna().all() and (got != 0).any()
    pd.testing.assert_series_equal(got, predictor.predict(visible))
