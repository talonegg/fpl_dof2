"""The expected-goals switch (D-25, DL-34): observe goal involvement through xG, not actual goals.

These check the *mechanism*, not the modelling verdict — that a component fitted and observed
through expected goals genuinely reads a different column, that the signal changes a forecast, and
that expected goals are treated as an outcome the predictor never sees. The claim that xG *improves*
the model is the backtest's to make, and it is recorded in DL-34, not asserted here.
"""

from __future__ import annotations

import pandas as pd

from fpl_dof.config.models import ExpectedGoalsConfig, ForecastConfig
from fpl_dof.forecast.backtest import OUTCOME_COLUMNS
from fpl_dof.forecast.features import build_features
from fpl_dof.forecast.models import fit_components
from fpl_dof.forecast.xp_v1 import _team_matches, forecast_player
from fpl_dof.rules.models import GameRules

SEASON = "2025/26"


def _xg_config(*, enabled: bool, team_xg: bool = False) -> ForecastConfig:
    return ForecastConfig(
        expected_goals=ExpectedGoalsConfig(enabled=enabled, team_strength_from_xg=team_xg)
    )


def _history(*, goals: float, xg: float) -> pd.DataFrame:
    """A single striker who scores ``goals`` a game on ``xg`` expected goals, over 10 weeks.

    Goals and xG deliberately diverge so a model reading one cannot be mistaken for one reading the
    other: the whole point of the switch is which of these two columns informs the goal rate.
    """
    start = pd.Timestamp("2025-08-15T18:00:00Z")
    rows = []
    for gameweek in range(1, 11):
        rows.append(
            {
                "season": SEASON,
                "gameweek": gameweek,
                "player_code": 100_001,
                "player_id": 1,
                "position": "FWD",
                "team_id": 1,
                "fixture_id": 100 + gameweek,
                "kickoff_time": start + pd.Timedelta(days=7 * (gameweek - 1)),
                "was_home": gameweek % 2 == 0,
                "minutes": 90,
                "starts": 1,
                "appearance_rate": 1.0,
                "goals_scored": goals,
                "assists": 0.0,
                "clean_sheets": 0,
                "goals_conceded": 1.0,
                "saves": 0,
                "bonus": 0,
                "bps": 20,
                "yellow_cards": 0,
                "defensive_contribution": 0,
                "expected_goals": xg,
                "expected_assists": 0.0,
                "expected_goals_conceded": 1.2,
                "price": 8.0,
                "total_points": 3.0,
            }
        )
    return pd.DataFrame(rows)


def test_the_default_ships_dark() -> None:
    """DP-08: the mechanism is off until the backtest promotes it. The promotion lives in the YAML
    app config, not in the model default, so a bare ForecastConfig() is the pre-promotion model."""
    assert ForecastConfig().expected_goals.enabled is False


def test_the_switch_moves_which_column_the_goal_rate_reads(game_rules: GameRules) -> None:
    history = _history(goals=1.0, xg=0.3)

    off = fit_components(history, _team_matches(history), _xg_config(enabled=False), game_rules)
    on = fit_components(history, _team_matches(history), _xg_config(enabled=True), game_rules)

    # The dict stays keyed by the scoring component; only the observed column moves (Invariant 1).
    assert off.rates["goals_scored"].column == "goals_scored"
    assert off.rates["assists"].column == "assists"
    assert on.rates["goals_scored"].column == "expected_goals"
    assert on.rates["assists"].column == "expected_assists"
    # A component not in the map is untouched either way.
    assert on.rates["defensive_contribution"].column == "defensive_contribution"


def test_the_signal_actually_changes_the_forecast(game_rules: GameRules) -> None:
    """A striker overperforming his xG is forecast lower once the model believes xG over goals.

    If the switch were wired but inert — reading the field without using it — this would not hold,
    which is the failure a field-level assertion would miss.
    """
    history = _history(goals=1.0, xg=0.3)
    features = build_features(
        history, as_of=pd.Timestamp("2025-11-01T00:00:00Z"), config=ForecastConfig().features
    )
    row = features.iloc[0].copy()
    row["position"] = "FWD"

    off_models = fit_components(
        history, _team_matches(history), _xg_config(enabled=False), game_rules
    )
    on_models = fit_components(
        history, _team_matches(history), _xg_config(enabled=True), game_rules
    )

    kwargs = {"clean_sheet_probability": 0.3, "goals_conceded_mean": 1.4}
    goals_off = forecast_player(
        row, off_models, game_rules, _xg_config(enabled=False), **kwargs
    ).components["goals"]
    goals_on = forecast_player(
        row, on_models, game_rules, _xg_config(enabled=True), **kwargs
    ).components["goals"]

    # He scored more than he deserved; the xG model expects less of him next time.
    assert goals_on < goals_off


def test_team_strength_from_xg_reconstructs_from_expected_goals() -> None:
    history = _history(goals=2.0, xg=0.5)
    # Two players in one fixture so the team's expected goals is a genuine sum, not one row.
    second = history.copy()
    second["player_code"] = 100_002
    second["player_id"] = 2
    both = pd.concat([history, second], ignore_index=True)

    actual = _team_matches(both, use_xg=False)
    xg = _team_matches(both, use_xg=True)

    one_fixture_actual = actual[actual["fixture_id"] == 101]["goals_for"].iloc[0]
    one_fixture_xg = xg[xg["fixture_id"] == 101]["goals_for"].iloc[0]
    assert one_fixture_actual == 4.0  # 2 goals x 2 players
    assert one_fixture_xg == 1.0  # 0.5 xG x 2 players
    assert one_fixture_xg != one_fixture_actual


def test_team_strength_from_xg_falls_back_when_the_column_is_absent() -> None:
    """DP-15: a partial archive without xG must still fit M2 on actual goals, not return empty."""
    history = _history(goals=2.0, xg=0.5).drop(
        columns=["expected_goals", "expected_goals_conceded"]
    )
    matches = _team_matches(history, use_xg=True)
    assert not matches.empty
    assert matches["goals_for"].iloc[0] == 2.0


def test_expected_goals_are_treated_as_an_outcome() -> None:
    """They describe the gameweek being predicted, so they are carried for fitting and stripped
    before prediction alongside the target — never a leak into ``predict`` (D-25)."""
    for column in ("expected_goals", "expected_assists", "expected_goals_conceded"):
        assert column in OUTCOME_COLUMNS
