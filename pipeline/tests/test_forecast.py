"""The cold-start model.

Most of these tests are about the things that are *invisible* when wrong (DP-13): an
absence-of-measurement field read as evidence, a blank gameweek quietly scoring points, a new
signing getting a confident forecast from no data at all.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.diagnostics import (
    PriceDependence,
    regress_xp_on_price,
    top_by_xp,
)
from fpl_dof.forecast.model_card import write_model_card
from fpl_dof.forecast.xp_v0 import (
    ForecastInputs,
    build_forecast,
    poisson_survival,
    summarise_history,
)
from fpl_dof.frames import cell
from fpl_dof.rules.models import GameRules

CONFIG = ForecastConfig()


# --- the Poisson threshold model -----------------------------------------------------------


def test_poisson_survival_is_a_probability() -> None:
    for mean in (0.0, 0.5, 5.0, 40.0):
        for threshold in (0, 1, 10, 12):
            value = poisson_survival(threshold, mean)
            assert 0.0 <= value <= 1.0


def test_a_zero_threshold_is_certain() -> None:
    assert poisson_survival(0, 0.0) == 1.0


def test_no_actions_means_no_award() -> None:
    assert poisson_survival(10, 0.0) == 0.0


def test_survival_rises_with_the_rate() -> None:
    values = [poisson_survival(10, mean) for mean in (2.0, 5.0, 10.0, 20.0)]
    assert values == sorted(values)
    assert values[0] < 0.01
    assert values[-1] > 0.99


def test_survival_falls_as_the_threshold_rises() -> None:
    values = [poisson_survival(threshold, 10.0) for threshold in (5, 10, 15, 20)]
    assert values == sorted(values, reverse=True)


def test_survival_matches_a_hand_computed_case() -> None:
    """P(X >= 2) for lambda = 1 is 1 - e^-1 - e^-1."""
    assert poisson_survival(2, 1.0) == pytest.approx(1 - 2 * math.exp(-1))


# --- history summarisation, and the measurement traps ----------------------------------------


def _history(**overrides: object) -> pd.DataFrame:
    base = {
        "player_id": 1,
        "season_name": "2025/26",
        "minutes": 2700,
        "starts": 30,
        "goals_scored": 10,
        "assists": 5,
        "clean_sheets": 12,
        "goals_conceded": 30,
        "own_goals": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "yellow_cards": 4,
        "red_cards": 0,
        "saves": 0,
        "bonus": 15,
        "bps": 600,
        "defensive_contribution": 300,
        "tackles": 40,
        "recoveries": 100,
        "clearances_blocks_interceptions": 160,
        "expected_goals": 9.0,
        "expected_assists": 4.0,
        "start_cost": 6.0,
        "end_cost": 6.5,
        "total_points": 180,
    }
    base.update(overrides)
    return pd.DataFrame([base])


def test_rates_are_per_ninety() -> None:
    summary = summarise_history(_history(minutes=900, goals_scored=5), CONFIG)
    assert cell(summary, 0, "goals_scored_per90") == pytest.approx(0.5)


def test_defensive_contribution_ignores_seasons_before_it_existed() -> None:
    """The trap: 2024/25 reports zero because the metric did not exist, not because of play."""
    history = pd.concat(
        [
            _history(season_name="2024/25", defensive_contribution=0, minutes=2700),
            _history(season_name="2025/26", defensive_contribution=300, minutes=2700),
        ],
        ignore_index=True,
    )
    summary = summarise_history(history, CONFIG)
    # 300 actions in 2700 minutes = 10 per 90. Including 2024/25 would halve it to 5.
    assert cell(summary, 0, "defensive_contribution_per90") == pytest.approx(10.0)
    assert cell(summary, 0, "defcon_minutes") == 2700


def test_a_player_with_no_recorded_defcon_season_has_no_rate() -> None:
    summary = summarise_history(_history(season_name="2023/24"), CONFIG)
    assert math.isnan(cell(summary, 0, "defensive_contribution_per90"))


def test_starts_ignore_seasons_before_they_were_recorded() -> None:
    history = pd.concat(
        [_history(season_name="2021/22", starts=0), _history(season_name="2025/26", starts=38)],
        ignore_index=True,
    )
    summary = summarise_history(history, CONFIG)
    assert cell(summary, 0, "start_rate") == pytest.approx(1.0)


def test_recent_seasons_count_for_more() -> None:
    history = pd.concat(
        [
            _history(season_name="2024/25", goals_scored=0, minutes=2700),
            _history(season_name="2025/26", goals_scored=20, minutes=2700),
        ],
        ignore_index=True,
    )
    summary = summarise_history(history, CONFIG)
    naive = 20 / ((2700 + 2700) / 90)
    assert cell(summary, 0, "goals_scored_per90") > naive


def test_history_beyond_the_window_is_dropped() -> None:
    history = pd.concat(
        [
            _history(season_name="2019/20", goals_scored=100),
            _history(season_name="2025/26", goals_scored=10),
        ],
        ignore_index=True,
    )
    summary = summarise_history(history, CONFIG)
    assert cell(summary, 0, "goals_scored_per90") == pytest.approx(10 / 30)


def test_empty_history_is_survivable() -> None:
    assert summarise_history(pd.DataFrame(), CONFIG).empty


def test_an_unparseable_season_does_not_crash() -> None:
    summary = summarise_history(_history(season_name="not-a-season"), CONFIG)
    assert len(summary) == 1


# --- the full model ------------------------------------------------------------------------


#: Teams 1 and 2 field identical squads at different fixture difficulties, so the fixture effect is
#: isolated. Team 3 has no fixture at all, which is how the blank-gameweek case gets exercised.
SQUAD_SHAPE = [("GKP", 5.0), ("DEF", 6.0), ("DEF", 4.5), ("MID", 9.0), ("MID", 5.0), ("FWD", 8.0)]


@pytest.fixture
def inputs() -> ForecastInputs:
    rows = []
    player_id = 0
    for team_id in (1, 2, 3):
        for position, price in SQUAD_SHAPE:
            player_id += 1
            rows.append(
                {
                    "player_id": player_id,
                    "code": 1000 + player_id,
                    "web_name": f"P{player_id}",
                    "full_name": f"Player {player_id}",
                    "position": position,
                    "team_id": team_id,
                    "price": price,
                    "status": "a",
                    "chance_of_playing_next_round": None,
                    "selected_by_percent": 5.0,
                    "news": "",
                }
            )
    # Two players with no history at all: a new signing and a promoted-club player.
    for position, price in (("MID", 6.0), ("FWD", 5.5)):
        player_id += 1
        rows.append(
            {
                "player_id": player_id,
                "code": 1000 + player_id,
                "web_name": f"New{player_id}",
                "full_name": f"Newcomer {player_id}",
                "position": position,
                "team_id": 1,
                "price": price,
                "status": "a",
                "chance_of_playing_next_round": None,
                "selected_by_percent": 1.0,
                "news": "",
            }
        )
    players = pd.DataFrame(rows)
    teams = pd.DataFrame(
        [
            {
                "team_id": t,
                "name": f"T{t}",
                "short_name": f"T{t}",
                "strength_overall_home": 3,
                "strength_overall_away": 3,
            }
            for t in (1, 2, 3)
        ]
    )
    fixtures = pd.DataFrame(
        [
            {
                "fixture_id": 1,
                "gameweek": 1,
                "kickoff_time": pd.Timestamp("2026-08-21T19:00:00Z"),
                "home_team_id": 1,
                "away_team_id": 2,
                "home_difficulty": 2,
                "away_difficulty": 4,
                "finished": False,
            },
            {
                "fixture_id": 2,
                "gameweek": 2,
                "kickoff_time": pd.Timestamp("2026-08-28T19:00:00Z"),
                "home_team_id": 2,
                "away_team_id": 1,
                "home_difficulty": 3,
                "away_difficulty": 3,
                "finished": False,
            },
        ]
    )
    gameweeks = pd.DataFrame(
        [
            {
                "gameweek": gw,
                "name": f"Gameweek {gw}",
                "deadline_time": pd.Timestamp(f"2026-08-{20 + gw}T17:30:00Z"),
                "finished": False,
                "is_next": gw == 1,
            }
            for gw in (1, 2)
        ]
    )
    # Everyone in a club squad has history; the two newcomers deliberately have none.
    history = pd.concat(
        [_history(player_id=i) for i in range(1, len(SQUAD_SHAPE) * 3 + 1)], ignore_index=True
    )
    return ForecastInputs(
        players=players, teams=teams, fixtures=fixtures, gameweeks=gameweeks, history=history
    )


def test_every_player_is_scored(inputs: ForecastInputs, game_rules: GameRules) -> None:
    result = build_forecast(inputs, game_rules, CONFIG)
    assert len(result) == len(inputs.players)
    assert result["xp_next"].notna().all()


def test_every_value_carries_uncertainty(inputs: ForecastInputs, game_rules: GameRules) -> None:
    """Invariant 6: expected points always carry variance, not just a mean."""
    result = build_forecast(inputs, game_rules, CONFIG)
    assert (result["xp_next_sd"] > 0).all()
    assert (result["xp_horizon_sd"] > 0).all()
    assert set(result["confidence"]) <= {"high", "medium", "low", "none"}


def test_uncertainty_is_wider_for_thinner_evidence(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    result = build_forecast(inputs, game_rules, CONFIG)
    with_history = result[result["confidence"] == "high"]
    without = result[result["confidence"] == "none"]
    assert not with_history.empty and not without.empty
    cv_high = CONFIG.uncertainty.coefficient_of_variation["high"]
    cv_none = CONFIG.uncertainty.coefficient_of_variation["none"]
    assert cv_none > cv_high


def test_a_player_with_no_history_gets_the_group_prior_not_a_zero(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    """New signings and promoted-club players must not be silently unselectable."""
    result = build_forecast(inputs, game_rules, CONFIG)
    newcomers = result[(result["confidence"] == "none") & (result["team_id"] != 3)]
    assert not newcomers.empty
    assert (newcomers["xp_next"] > 0).all()
    # And they are priced off their group, not off nothing.
    assert (newcomers["component_goals"] > 0).all()


def test_the_decomposition_sums_to_the_total(inputs: ForecastInputs, game_rules: GameRules) -> None:
    result = build_forecast(inputs, game_rules, CONFIG)
    components = [c for c in result.columns if c.startswith("component_")]
    assert components
    assert np.allclose(result[components].sum(axis=1), result["xp_next"])


def test_defensive_contribution_is_in_the_decomposition(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    """E0-S3 existed to make this possible; E0-S5 acceptance requires it."""
    result = build_forecast(inputs, game_rules, CONFIG)
    assert "component_defensive_contribution" in result.columns
    outfield = result[result["position"] != "GKP"]
    assert (outfield["component_defensive_contribution"] > 0).any()


def test_goalkeepers_never_score_defensive_contribution(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    result = build_forecast(inputs, game_rules, CONFIG)
    keepers = result[result["position"] == "GKP"]
    assert (keepers["component_defensive_contribution"] == 0).all()


def test_a_blank_gameweek_scores_nothing(inputs: ForecastInputs, game_rules: GameRules) -> None:
    """Team 3 has no fixture at all. It must score zero, not the average of nothing."""
    result = build_forecast(inputs, game_rules, CONFIG)
    blank = result[result["team_id"] == 3]
    assert not blank.empty
    assert (blank["xp_next"] == 0).all()


def test_an_injured_player_is_priced_at_zero(inputs: ForecastInputs, game_rules: GameRules) -> None:
    players = inputs.players.copy()
    players.loc[players["player_id"] == 1, "status"] = "i"
    result = build_forecast(
        ForecastInputs(
            players=players,
            teams=inputs.teams,
            fixtures=inputs.fixtures,
            gameweeks=inputs.gameweeks,
            history=inputs.history,
        ),
        game_rules,
        CONFIG,
    )
    injured = result[result["player_id"] == 1].iloc[0]
    assert injured["start_probability"] == 0.0
    assert injured["xp_next"] == pytest.approx(0.0, abs=1e-9)


def test_a_stated_chance_of_playing_overrides_the_flag(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    players = inputs.players.copy()
    players.loc[players["player_id"] == 1, "chance_of_playing_next_round"] = 25.0
    result = build_forecast(
        ForecastInputs(
            players=players,
            teams=inputs.teams,
            fixtures=inputs.fixtures,
            gameweeks=inputs.gameweeks,
            history=inputs.history,
        ),
        game_rules,
        CONFIG,
    )
    assert result[result["player_id"] == 1].iloc[0]["availability"] == pytest.approx(0.25)


def test_an_easier_fixture_is_worth_more(inputs: ForecastInputs, game_rules: GameRules) -> None:
    """Team 1 plays at difficulty 2, team 2 at difficulty 4, with identical histories."""
    result = build_forecast(inputs, game_rules, CONFIG)
    squads = result[result["confidence"] != "none"]
    easy = squads[squads["team_id"] == 1]["xp_next"].mean()
    hard = squads[squads["team_id"] == 2]["xp_next"].mean()
    assert easy > hard


def test_start_probability_is_a_probability(inputs: ForecastInputs, game_rules: GameRules) -> None:
    result = build_forecast(inputs, game_rules, CONFIG)
    assert result["start_probability"].between(0.0, 1.0).all()


def test_horizon_exceeds_a_single_gameweek(inputs: ForecastInputs, game_rules: GameRules) -> None:
    result = build_forecast(inputs, game_rules, CONFIG)
    playing = result[result["team_id"] != 3]
    assert (playing["xp_horizon"] >= playing["xp_next"] - 1e-9).all()


# --- diagnostics ---------------------------------------------------------------------------


def _synthetic(r_squared_target: str) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    price = rng.uniform(4.0, 14.0, 200)
    noise_scale = {"low": 0.05, "high": 8.0}[r_squared_target]
    return pd.DataFrame(
        {
            "price": price,
            "position": rng.choice(["GKP", "DEF", "MID", "FWD"], 200),
            "xp_horizon": 2.0 * price + rng.normal(0, noise_scale, 200),
            "price_tier": rng.integers(0, 4, 200),
        }
    )


def test_a_forecast_that_is_just_price_is_called_a_repricing() -> None:
    result = regress_xp_on_price(_synthetic("low"))
    assert result.verdict is PriceDependence.REPRICING
    assert result.r_squared > 0.9
    assert "REPRICING" in result.message


def test_a_forecast_with_real_residual_signal_is_called_informative() -> None:
    result = regress_xp_on_price(_synthetic("high"))
    assert result.verdict is PriceDependence.INFORMATIVE
    assert "adding real information" in result.message


def test_within_tier_spread_is_reported() -> None:
    result = regress_xp_on_price(_synthetic("high"))
    assert result.within_tier_spread


def test_too_few_rows_to_regress_is_an_error() -> None:
    with pytest.raises(ValueError, match="too few"):
        regress_xp_on_price(_synthetic("high").head(5))


def test_top_by_xp_returns_the_best(inputs: ForecastInputs, game_rules: GameRules) -> None:
    result = build_forecast(inputs, game_rules, CONFIG)
    top = top_by_xp(result, 5)
    assert len(top) == 5
    assert top["xp_horizon"].is_monotonic_decreasing


# --- the model card ------------------------------------------------------------------------


def test_the_model_card_states_the_diagnostic_and_the_weaknesses(
    inputs: ForecastInputs, game_rules: GameRules, tmp_path: Path
) -> None:
    result = build_forecast(inputs, game_rules, CONFIG)
    regression = regress_xp_on_price(result)
    path = write_model_card(
        tmp_path / "model-card.md",
        forecast=result,
        regression=regression,
        config=CONFIG,
        rules=game_rules,
        run_id="run-1",
    )
    text = path.read_text(encoding="utf-8")
    assert "R²" in text
    assert f"{regression.r_squared:.3f}" in text
    assert "Known weaknesses" in text
    assert "No backtesting" in text
    assert "D-01" in text
    assert "Tunables in force" in text
    assert "start-probability floor" in text
