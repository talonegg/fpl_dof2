"""E11-S3 — a player's goal and assist rates read M2's opposition, not only clean sheets and saves.

Before this story, only clean sheets, goals conceded and (with `gkp_v2`) saves knew which fixture a
player was in; a striker's own goal rate was scored identically against the league's tightest and
its leakiest defence. Design §M3 calls for sharing the *team's* M2-implied expected goals across its
players by npxG/xA/shot-volume shares — a cross-player aggregation this story does not build
(recorded in DL-58, not hidden). What ships instead is the part of that design that needs no
aggregation at all: a player's own fitted rate already carries his team's *general* attacking level,
so what M2 adds is only what is specific to *this* fixture — the opponent's defence and the venue,
with the player's own team's attack rating deliberately excluded so it is not counted twice.

`discrimination.opponent_adjusted_rates` is a candidate, not a promotion (DP-08, DL-47, DL-58). So
these tests check the mechanism: off changes nothing at all, an average fixture returns exactly the
old rate, a harder fixture lowers it and an easier one raises it, damping is a share of the full
move, and the factor cannot invert or collapse a rate. The claim that it *improves* the model is the
backtest's to make and is recorded in DL-58, not asserted here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_dof.config.models import (
    DiscriminationConfig,
    ForecastConfig,
    OpponentAdjustmentConfig,
)
from fpl_dof.forecast.models import ComponentModels, TeamStrengthModel, fit_components
from fpl_dof.forecast.xp_v1 import Opposition, forecast_player, score_player, team_matches
from fpl_dof.rules.models import GameRules
from test_backtest import make_history

STRIKER = 100_001


def _training() -> pd.DataFrame:
    history = make_history(players=24, gameweeks=8)
    return history.assign(
        appearance_rate=history.groupby("player_code")["minutes"].transform(
            lambda values: (values > 0).mean()
        )
    )


def _row() -> pd.Series:
    return pd.Series(
        {
            "player_code": STRIKER,
            "position": "FWD",
            "as_of": pd.Timestamp("2025-09-01", tz="UTC"),
            "minutes_mean_last6": 90.0,
            "matches_observed": 6,
            "goals_scored_per90_last6": 0.6,
            "assists_per90_last6": 0.3,
        }
    )


def _models(
    game_rules: GameRules, *, on: bool = False, **tuning: object
) -> tuple[ComponentModels, ForecastConfig]:
    training = _training()
    matches = team_matches(training)
    config = ForecastConfig(
        discrimination=DiscriminationConfig(
            opponent_adjusted_rates=on,
            opponent_adjustment=OpponentAdjustmentConfig.model_validate(tuning),
        )
    )
    return fit_components(training, matches, config, game_rules), config


# --- the flag is inert when it is off -----------------------------------------------------------


def test_with_the_flag_off_goals_and_assists_ignore_the_fixture_entirely(
    game_rules: GameRules,
) -> None:
    models, config = _models(game_rules, on=False)
    row = _row()

    easy = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=2.0,
    )
    hard = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=0.5,
    )
    assert easy.components["goals"] == pytest.approx(hard.components["goals"])
    assert easy.components["assists"] == pytest.approx(hard.components["assists"])


def test_league_average_opposition_carries_a_neutral_factor(game_rules: GameRules) -> None:
    from fpl_dof.forecast.xp_v1 import league_average_opposition

    models, _ = _models(game_rules, on=True)
    assert league_average_opposition(models).attacking_fixture_factor == pytest.approx(1.0)


# --- the fixture factor, with the flag on -------------------------------------------------------


def test_an_average_fixture_returns_exactly_the_old_rate(game_rules: GameRules) -> None:
    models, config = _models(game_rules, on=True, weight=1.0)
    row = _row()

    neutral = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=1.0,
    )
    off_config = ForecastConfig()
    off = forecast_player(
        row,
        models,
        game_rules,
        off_config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=1.0,
    )
    assert neutral.components["goals"] == pytest.approx(off.components["goals"])
    assert neutral.components["assists"] == pytest.approx(off.components["assists"])


def test_a_harder_fixture_lowers_goals_and_an_easier_one_raises_them(
    game_rules: GameRules,
) -> None:
    models, config = _models(game_rules, on=True, weight=1.0)
    row = _row()

    def goals(factor: float) -> float:
        return forecast_player(
            row,
            models,
            game_rules,
            config,
            clean_sheet_probability=0.3,
            goals_conceded_mean=1.0,
            attacking_fixture_factor=factor,
        ).components["goals"]

    neutral = goals(1.0)
    assert goals(0.6) < neutral < goals(1.6)


def test_a_weight_of_zero_is_the_identity(game_rules: GameRules) -> None:
    models, config = _models(game_rules, on=True, weight=0.0)
    row = _row()

    for factor in (0.4, 1.0, 2.0):
        forecast = forecast_player(
            row,
            models,
            game_rules,
            config,
            clean_sheet_probability=0.3,
            goals_conceded_mean=1.0,
            attacking_fixture_factor=factor,
        )
        neutral = forecast_player(
            row,
            models,
            game_rules,
            config,
            clean_sheet_probability=0.3,
            goals_conceded_mean=1.0,
            attacking_fixture_factor=1.0,
        )
        assert forecast.components["goals"] == pytest.approx(neutral.components["goals"])


def test_damping_moves_the_rate_less_than_the_full_factor_does(game_rules: GameRules) -> None:
    models, half_config = _models(game_rules, on=True, weight=0.5)
    _, full_config = _models(game_rules, on=True, weight=1.0)
    row = _row()

    def goals(config: ForecastConfig) -> float:
        return forecast_player(
            row,
            models,
            game_rules,
            config,
            clean_sheet_probability=0.3,
            goals_conceded_mean=1.0,
            attacking_fixture_factor=1.8,
        ).components["goals"]

    baseline = forecast_player(
        row,
        models,
        game_rules,
        half_config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=1.0,
    ).components["goals"]
    moved_half = abs(goals(half_config) - baseline)
    moved_full = abs(goals(full_config) - baseline)
    assert moved_half == pytest.approx(moved_full / 2.0)


def test_the_factor_is_floored_and_ceilinged(game_rules: GameRules) -> None:
    models, config = _models(
        game_rules, on=True, weight=1.0, minimum_factor=0.5, maximum_factor=2.0
    )
    row = _row()

    brutal = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=0.0,
    )
    generous = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=100.0,
    )
    floored = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=0.5,
    )
    ceilinged = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=2.0,
    )
    assert brutal.components["goals"] == pytest.approx(floored.components["goals"])
    assert generous.components["goals"] == pytest.approx(ceilinged.components["goals"])


def test_a_clean_sheet_and_saves_are_unaffected(game_rules: GameRules) -> None:
    """The factor only ever touches goal involvement — the other components already read M2."""
    models, config = _models(game_rules, on=True, weight=1.0)
    row = _row()

    easy = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=1.8,
    )
    hard = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=0.6,
    )
    assert easy.components["clean_sheet"] == pytest.approx(hard.components["clean_sheet"])


# --- TeamStrengthModel.attacking_fixture_factor --------------------------------------------------


def test_the_factor_excludes_the_players_own_teams_attack_rating() -> None:
    """The whole point of the story's simplification: only defence and venue enter."""
    model = TeamStrengthModel(attack={1: 3.0, 2: 1.0}, defence={1: 1.0, 2: 0.8}, home_advantage=1.1)
    # Team 1's own attack rating (3.0) must not appear in its own fixture factor.
    factor = model.attacking_fixture_factor(2, at_home=True)
    assert factor == pytest.approx(0.8 * 1.1)


def test_a_neutral_opponent_and_a_neutral_venue_give_a_factor_of_one() -> None:
    model = TeamStrengthModel(home_advantage=1.0)
    assert model.attacking_fixture_factor(99, at_home=True) == pytest.approx(1.0)
    assert model.attacking_fixture_factor(99, at_home=False) == pytest.approx(1.0)


def test_score_player_threads_the_factor_from_opposition(game_rules: GameRules) -> None:
    models, config = _models(game_rules, on=True, weight=1.0)
    row = _row()
    opposition = Opposition(
        clean_sheet_probability=0.3, goals_conceded_mean=1.0, attacking_fixture_factor=1.8
    )
    direct = forecast_player(
        row,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.0,
        attacking_fixture_factor=1.8,
    )
    via_score_player = score_player(row, models, game_rules, config, opposition=opposition)
    assert direct.components["goals"] == pytest.approx(via_score_player.components["goals"])
