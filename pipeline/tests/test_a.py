"""MOD-05 — A ported from the frozen bundle behind the frame contract (DL-89 item 7).

A must produce a valid frame and a full decision on a fixture snapshot, refuse a history row
kicked off after the deadline, be deterministic across two fits, price every event from the rules
config (a rules change moves its xP), and be fittable by the walk-forward harness.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from decisions import fixture_table, pool, state
from fpl_dof.decision import decide
from fpl_dof.factory.registry import ForecastInputs, load_strategy
from fpl_dof.forecast.backtest import OUTCOME_COLUMNS, fold_rows
from fpl_dof.forecast.features import LeakageError
from fpl_dof.optimise.frame import validate_forecast_frame
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.shadow import a
from test_c1 import _with_prior
from test_decide import HORIZON, _config, _forecast_config, _snapshot


def _forecast(inputs: ForecastInputs, rules: GameRules) -> pd.DataFrame:
    return load_strategy("a").forecast(inputs, rules, _forecast_config()).frame


def test_a_is_a_published_recipe_on_every_season() -> None:
    strategy = load_strategy("a")
    assert strategy.published and strategy.forecaster.type == "recipe"
    assert strategy.forecaster.model == a.MODEL_NAME
    assert strategy.forecaster.training_window == "all_seasons"
    assert strategy.policy.captain_rule == "price_position" and not strategy.policy.plan


def test_a_produces_a_valid_frame_and_a_full_decision(game_rules: GameRules) -> None:
    inputs, champ = _snapshot(game_rules)
    got = load_strategy("a").forecast(inputs, game_rules, _forecast_config())
    frame = validate_forecast_frame(got.frame)
    assert set(frame["model"]) == {a.MODEL_NAME} and set(frame["strategy"]) == {"a"}
    assert (frame["xp_next_sd"] > 0).any() and (frame["xp_next"] > 0).any()
    assert not frame["xp_next"].equals(champ.frame["xp_next"])
    assert got.captain_line is not None

    held = state(game_rules, pool(), gameweek=HORIZON[0])
    policy = load_strategy("a").decision_policy(_config(), got.captain_line)
    decision = decide(
        frame,
        held,
        game_rules,
        policy,
        fixtures=fixture_table(pool(), HORIZON),
        last_gameweek=HORIZON[-1],
    )
    assert len(decision.selection.starting) == 11
    assert decision.selection.captain in decision.selection.starting


def test_a_history_row_kicked_off_after_the_deadline_raises(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    planted = history.copy()
    planted.loc[planted.index[0], "kickoff_time"] = pd.Timestamp(inputs.as_of) + pd.Timedelta(
        days=2
    )
    with pytest.raises(LeakageError, match="stamped after the deadline"):
        _forecast(dataclasses.replace(inputs, player_gameweek=planted), game_rules)


def test_two_fits_on_the_same_data_give_identical_frames(game_rules: GameRules) -> None:
    inputs = _with_prior(_snapshot(game_rules)[0])
    pd.testing.assert_frame_equal(_forecast(inputs, game_rules), _forecast(inputs, game_rules))


def _scoring(rules: GameRules, **update: object) -> GameRules:
    return rules.model_copy(update={"scoring": rules.scoring.model_copy(update=update)})


def test_points_come_from_the_rules_config(game_rules: GameRules) -> None:
    """Invariant 2: a forward's goal worth more moves forwards' xP and no goalkeeper's."""
    inputs, _ = _snapshot(game_rules)
    base = _forecast(inputs, game_rules).set_index("player_id")
    goals = dict(game_rules.scoring.goals_scored)
    goals[Position.FWD] += 3
    richer = _forecast(inputs, _scoring(game_rules, goals_scored=goals)).set_index("player_id")
    forwards = base["position"] == Position.FWD.value
    keepers = base["position"] == Position.GKP.value
    assert (richer.loc[forwards, "xp_next"] >= base.loc[forwards, "xp_next"]).all()
    assert (richer.loc[forwards, "xp_next"] > base.loc[forwards, "xp_next"]).any()
    pd.testing.assert_series_equal(richer.loc[keepers, "xp_next"], base.loc[keepers, "xp_next"])


def test_the_award_is_gated_on_recorded_data_not_a_season(game_rules: GameRules) -> None:
    """No defensive contribution recorded anywhere: no award model, so no award points."""
    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    blank = history.assign(defensive_contribution=float("nan"))
    fitted = a.fit_as_of(
        blank, pd.Timestamp(inputs.as_of), _forecast_config().forecast.a, game_rules
    )
    assert all(a.AWARD not in models for models in fitted.models.values())
    cfg = _forecast_config().forecast.a.model_copy(
        update={"defensive_contribution_minimum_rows": 0}
    )
    recorded = a.fit_as_of(history, pd.Timestamp(inputs.as_of), cfg, game_rules)
    assert a.AWARD in recorded.models[Position.DEF.value]
    assert a.AWARD not in recorded.models[Position.GKP.value]  # the rules give keepers no award


def test_floor_moments_match_a_direct_sum() -> None:
    import math

    first, second = a.floor_moments(pd.Series([1.5]).to_numpy(), 3, 40)
    pmf = [math.exp(-1.5) * 1.5**n / math.factorial(n) for n in range(40)]
    assert first[0] == pytest.approx(sum(p * (n // 3) for n, p in enumerate(pmf)))
    assert second[0] == pytest.approx(sum(p * (n // 3) ** 2 for n, p in enumerate(pmf)))


def test_the_a_predictor_scores_a_fold_as_the_harness_hands_it(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    deadline = pd.Timestamp(history.loc[history["gameweek"] == 4, "kickoff_time"].min())
    fold = fold_rows(history, game_rules.season, 4, deadline, _forecast_config().forecast)
    visible = fold.drop(columns=list(OUTCOME_COLUMNS), errors="ignore")
    predictor = load_strategy("a").predictor(game_rules, _forecast_config())
    assert isinstance(predictor, a.APredictor)
    predictor.fit_as_of(history, deadline, season=game_rules.season)
    got = predictor.predict(visible, gameweek=4)
    assert got.index.equals(visible.index) and got.notna().all() and (got != 0).any()
