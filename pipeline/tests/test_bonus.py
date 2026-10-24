"""EXP-01 (D-34) — M8's bonus, with and without the player's own BPS spread.

The shipped :meth:`BonusModel.expected_bonus` holds the player's own BPS at its expectation and
asks how many of 21 random others beat it. For an average player that is ``0.5 ** 21`` for first
place, so a match's 22 players share almost none of its six bonus points: the deployed forecast
summed 5.7 bonus points over a whole gameweek in which FPL awarded about 65 (D-34).

``discrimination.bonus_v2`` integrates over the player's own spread instead. These tests pin the
mechanism — flag off changes nothing, flag on hands a match of identical players exactly the points
on offer — and leave whether it improves the forecast to the declared experiment
(``config/experiments/e1_bonus_spread.yaml``).
"""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_dof.config.models import DiscriminationConfig, ForecastConfig
from fpl_dof.forecast.models import BonusModel, fit_components
from fpl_dof.forecast.xp_v1 import team_matches
from fpl_dof.rules.models import GameRules
from test_goalkeeper import _training


def test_off_is_the_shipped_formula() -> None:
    model = BonusModel(typical_bps_mean=14.0, typical_bps_sd=9.0, own_bps_sd=6.0)
    # The point estimate against 21 independent others: an average player gets almost nothing.
    assert model.expected_bonus(14.0) == pytest.approx((3 + 2 * 21 + 210) * 0.5**21, rel=1e-9)


def test_on_a_match_of_identical_players_shares_every_bonus_point() -> None:
    """With the own spread equal to the population's, 22 exchangeable players split 3+2+1."""
    model = BonusModel(
        typical_bps_mean=14.0, typical_bps_sd=9.0, own_bps_sd=9.0, integrate_own_spread=True
    )
    assert 22 * model.expected_bonus(14.0) == pytest.approx(sum(model.bonus_points), rel=1e-3)


def test_on_more_expected_bps_never_means_less_bonus() -> None:
    model = BonusModel(
        typical_bps_mean=14.0, typical_bps_sd=9.0, own_bps_sd=6.0, integrate_own_spread=True
    )
    values = [model.expected_bonus(x) for x in (0.0, 10.0, 14.0, 20.0, 30.0, 45.0)]
    assert values == sorted(values)
    assert values[-1] < max(model.bonus_points)


def test_fit_measures_the_spread_within_a_player_not_between_players() -> None:
    history = pd.DataFrame(
        {
            "player_code": [1] * 30 + [2] * 30,
            "minutes": 90,
            # Player 1 always 10, player 2 alternates 28 and 32: within-player spread is player 2's.
            "bps": [10.0] * 30 + [28.0, 32.0] * 15,
        }
    )
    model = BonusModel().fit(history)
    assert model.typical_bps_sd > 9.0
    assert model.own_bps_sd == pytest.approx(pd.Series([0.0] * 30 + [-2.0, 2.0] * 15).std())


def test_the_flag_reaches_the_fitted_chain(game_rules: GameRules) -> None:
    history = _training()
    off = fit_components(history, team_matches(history), ForecastConfig(), game_rules)
    on = fit_components(
        history,
        team_matches(history),
        ForecastConfig(discrimination=DiscriminationConfig(bonus_v2=True)),
        game_rules,
    )
    assert not off.bonus.integrate_own_spread
    assert on.bonus.integrate_own_spread
    assert "own_bps_sd" not in str(off.describe()["M8_bonus"])
