"""MOD-05 — A_odds ported behind the frame contract, reading silver odds (DL-89 item 7).

A_odds must produce a valid frame and a full decision on a fixture snapshot, refuse a history row
kicked off after the deadline, be deterministic, price every event from the rules config, use the
market's club layer where every fixture of a club's gameweek is priced and A's estimate elsewhere,
ignore a capture after the deadline, and record "no advice" without odds while every other
strategy still runs (DL-87).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from decisions import fixture_table, pool, state
from fpl_dof.decision import decide
from fpl_dof.factory.registry import ForecastInputs, load_strategy, published_strategies
from fpl_dof.forecast.backtest import OUTCOME_COLUMNS, fold_rows
from fpl_dof.forecast.features import LeakageError
from fpl_dof.optimise.frame import validate_forecast_frame
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.shadow import a_odds
from fpl_dof.silver.tables import Table
from test_decide import (
    HORIZON,
    _advise_all,
    _config,
    _forecast_config,
    _orchestration,
    _snapshot,
    match_odds,
)


def _frame(inputs: ForecastInputs, rules: GameRules, strategy: str = "a_odds") -> pd.DataFrame:
    frame = load_strategy(strategy).forecast(inputs, rules, _forecast_config()).frame
    return frame.set_index("player_id")


def _deadline(inputs: ForecastInputs, gameweek: int) -> pd.Timestamp:
    gameweeks = inputs.gameweeks
    return pd.Timestamp(gameweeks.loc[gameweeks["gameweek"] == gameweek, "deadline_time"].min())


def _upcoming(inputs: ForecastInputs) -> pd.DataFrame:
    return inputs.fixtures[inputs.fixtures["gameweek"] == HORIZON[0]]


def test_a_odds_is_a_published_recipe_that_requires_the_odds() -> None:
    strategy = load_strategy("a_odds")
    assert strategy.published and strategy.forecaster.type == "recipe"
    assert strategy.forecaster.model == a_odds.MODEL_NAME
    assert strategy.forecaster.training_window == "all_seasons"
    assert Table.TEAM_MATCH_EXPECTATION in strategy.requires
    assert strategy.policy.captain_rule == "price_position" and not strategy.policy.plan


def test_a_odds_produces_a_valid_frame_and_a_full_decision(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    got = load_strategy("a_odds").forecast(inputs, game_rules, _forecast_config())
    frame = validate_forecast_frame(got.frame)
    assert set(frame["model"]) == {a_odds.MODEL_NAME} and set(frame["strategy"]) == {"a_odds"}
    assert (frame["xp_next_sd"] > 0).any() and got.captain_line is not None
    decision = decide(
        frame,
        state(game_rules, pool(), gameweek=HORIZON[0]),
        game_rules,
        load_strategy("a_odds").decision_policy(_config(), got.captain_line),
        fixtures=fixture_table(pool(), HORIZON),
        last_gameweek=HORIZON[-1],
    )
    assert len(decision.selection.starting) == 11
    assert decision.selection.captain in decision.selection.starting


def test_the_market_layer_applies_where_priced_and_a_stands_elsewhere(
    game_rules: GameRules,
) -> None:
    inputs, _ = _snapshot(game_rules)
    upcoming = _upcoming(inputs)
    priced = upcoming.iloc[1:]  # the first fixture's two clubs have no odds
    partial = dataclasses.replace(
        inputs, match_odds=match_odds(priced, game_rules.season, pd.Timestamp(inputs.as_of))
    )
    got, model_a = _frame(partial, game_rules), _frame(partial, game_rules, "a")
    unpriced = set(upcoming.iloc[0][["home_team_id", "away_team_id"]])
    fallback = got["team_id"].isin(unpriced)
    pd.testing.assert_series_equal(got.loc[fallback, "xp_next"], model_a.loc[fallback, "xp_next"])
    assert not got.loc[~fallback, "xp_next"].equals(model_a.loc[~fallback, "xp_next"])


def test_higher_clean_sheet_odds_raise_a_defenders_xp(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    upcoming = _upcoming(inputs)
    captured = pd.Timestamp(inputs.as_of) - pd.Timedelta(days=1)
    # The away sides expected to score less: the home clubs' clean sheets more likely.
    tighter = dataclasses.replace(
        inputs, match_odds=match_odds(upcoming, game_rules.season, captured, away_goals=0.4)
    )
    base, better = _frame(inputs, game_rules), _frame(tighter, game_rules)
    home = base["team_id"].isin(set(upcoming["home_team_id"]))
    defence = base["position"].isin([Position.GKP.value, Position.DEF.value]) & home
    assert (better.loc[defence, "xp_next"] >= base.loc[defence, "xp_next"]).all()
    assert (better.loc[defence, "xp_next"] > base.loc[defence, "xp_next"]).any()


def test_a_capture_after_the_deadline_is_ignored(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    assert inputs.match_odds is not None
    deadline = _deadline(inputs, HORIZON[0])
    late = match_odds(
        _upcoming(inputs), game_rules.season, deadline + pd.Timedelta(hours=1), home_goals=4.0
    )
    with_late = dataclasses.replace(
        inputs, match_odds=pd.concat([inputs.match_odds, late], ignore_index=True)
    )
    # Decided before the deadline, a capture after it (in a replay's silver) is never read.
    pd.testing.assert_frame_equal(_frame(with_late, game_rules), _frame(inputs, game_rules))
    # Read after the deadline, gameweek 5's odds are still the capture taken before it.
    later = dataclasses.replace(with_late, as_of=(deadline + pd.Timedelta(hours=2)).to_pydatetime())
    odds = a_odds.team_odds(later, game_rules.season)
    assert set(odds.loc[odds["gameweek"] == HORIZON[0], "goals_for"]) == {1.5, 1.1}


def test_points_come_from_the_rules_config(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    clean = dict(game_rules.scoring.clean_sheets)
    clean[Position.DEF] += 2
    rules = game_rules.model_copy(
        update={"scoring": game_rules.scoring.model_copy(update={"clean_sheets": clean})}
    )
    base, richer = _frame(inputs, game_rules), _frame(inputs, rules)
    defenders = base["position"] == Position.DEF.value
    assert (richer.loc[defenders, "xp_next"] > base.loc[defenders, "xp_next"]).any()
    forwards = base["position"] == Position.FWD.value
    pd.testing.assert_series_equal(richer.loc[forwards, "xp_next"], base.loc[forwards, "xp_next"])


def test_a_history_row_kicked_off_after_the_deadline_raises(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    planted = history.copy()
    planted.loc[planted.index[0], "kickoff_time"] = pd.Timestamp(inputs.as_of) + pd.Timedelta(
        days=2
    )
    with pytest.raises(LeakageError, match="stamped after the deadline"):
        _frame(dataclasses.replace(inputs, player_gameweek=planted), game_rules)


def test_two_fits_on_the_same_data_give_identical_frames(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    pd.testing.assert_frame_equal(_frame(inputs, game_rules), _frame(inputs, game_rules))


def test_no_odds_for_the_gameweek_is_an_error_not_a_quiet_fallback(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    # Only last week's odds, captured before last week's deadline.
    last = HORIZON[0] - 1
    deadline = _deadline(inputs, last)
    last_week = inputs.fixtures[inputs.fixtures["gameweek"] == last]
    stale = dataclasses.replace(
        inputs,
        match_odds=match_odds(last_week, game_rules.season, deadline - pd.Timedelta(days=1)),
    )
    with pytest.raises(a_odds.MissingOddsError, match="gameweek 5"):
        _frame(stale, game_rules)


def test_no_odds_records_no_advice_and_every_other_strategy_runs(
    game_rules: GameRules, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _orchestration(game_rules)
    bare = dataclasses.replace(
        snapshot, inputs=dataclasses.replace(snapshot.inputs, match_odds=None)
    )
    monkeypatch.setattr("test_decide._orchestration", lambda rules: bare)
    advice = _advise_all(game_rules, tmp_path)
    week, _ = advice["a_odds"]
    assert week["skipped"] and Table.TEAM_MATCH_EXPECTATION.value in week["skipped_reason"]
    others = [s.id for s in published_strategies() if s.id != "a_odds"]
    assert others and all(not advice[s][0]["skipped"] for s in others)


def test_the_a_odds_predictor_needs_the_odds_and_scores_a_fold(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    strategy = load_strategy("a_odds")
    with pytest.raises(ValueError, match=Table.TEAM_MATCH_EXPECTATION.value):
        strategy.predictor(game_rules, _forecast_config())
    history = inputs.player_gameweek
    assert history is not None
    deadline = pd.Timestamp(history.loc[history["gameweek"] == 4, "kickoff_time"].min())
    fold = fold_rows(history, game_rules.season, 4, deadline, _forecast_config().forecast)
    visible = fold.drop(columns=list(OUTCOME_COLUMNS), errors="ignore")
    predictor = strategy.predictor(game_rules, _forecast_config(), inputs=inputs)
    assert isinstance(predictor, a_odds.AOddsPredictor)
    predictor.fit_as_of(history, deadline, season=game_rules.season)
    got = predictor.predict(visible, gameweek=4)
    assert got.index.equals(visible.index) and got.notna().all() and (got != 0).any()
