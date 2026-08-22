"""E11-S6 — M2's expected goals defer to the odds market near the deadline.

This candidate cannot be graded by the walk-forward backtest at all: the odds adapter has been
collecting data only since it started running, there is no historical archive of past lines, and
the harness trains and scores entirely on `player_gameweek` history that carries no market column
(DL-60). So unlike S1/S3/S4, there is no "measured, held dark" table here — what these tests pin is
the mechanism's edges instead: attaching market data changes nothing until something reads it,
blending degrades cleanly to the ratings-only figure whenever a fixture has no market row or the
weight is zero, the weight itself decays with horizon and floors at zero, and a `captured_at`-later
row for the same pair replaces an earlier one rather than being averaged with it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_dof.config.models import MarketBlendConfig
from fpl_dof.forecast.models import TeamStrengthModel, market_blend_weight


def _market_rows(rows: list[tuple[int, int, float, float, str]]) -> pd.DataFrame:
    """``rows``: ``(home_team_id, away_team_id, expected_goals_home, expected_goals_away,
    captured_at)``."""
    return pd.DataFrame(
        [
            {
                "home_team_id": home,
                "away_team_id": away,
                "expected_goals_home": xg_home,
                "expected_goals_away": xg_away,
                "captured_at": pd.Timestamp(captured_at),
            }
            for home, away, xg_home, xg_away, captured_at in rows
        ]
    )


def _model() -> TeamStrengthModel:
    return TeamStrengthModel(attack={1: 1.2, 2: 0.8}, defence={1: 0.9, 2: 1.1}, home_advantage=1.1)


# --- attach_market --------------------------------------------------------------------------


def test_an_unattached_model_has_no_market_data() -> None:
    model = _model()
    assert model.market_expected_goals(1, 2, at_home=True) is None


def test_attaching_market_data_makes_it_reachable_by_the_ordered_pair() -> None:
    model = _model().attach_market(_market_rows([(1, 2, 2.3, 0.9, "2026-08-20T10:00:00Z")]))
    assert model.market_expected_goals(1, 2, at_home=True) == pytest.approx(2.3)
    # Team 2 away at team 1's ground, in the same fixture: team 2's own expected goals is the
    # "away" figure from that one row, not the "home" figure looked up a second time.
    assert model.market_expected_goals(2, 1, at_home=False) == pytest.approx(0.9)


def test_an_unresolved_fixture_returns_none_even_with_other_fixtures_attached() -> None:
    model = _model().attach_market(_market_rows([(1, 2, 2.3, 0.9, "2026-08-20T10:00:00Z")]))
    assert model.market_expected_goals(1, 3, at_home=True) is None


def test_the_latest_captured_row_for_a_pair_wins() -> None:
    model = _model().attach_market(
        _market_rows(
            [
                (1, 2, 2.3, 0.9, "2026-08-18T10:00:00Z"),
                (1, 2, 1.8, 1.1, "2026-08-20T10:00:00Z"),
            ]
        )
    )
    assert model.market_expected_goals(1, 2, at_home=True) == pytest.approx(1.8)


def test_an_empty_frame_leaves_the_model_unmarketed() -> None:
    model = _model().attach_market(pd.DataFrame())
    assert model.market_expected_goals(1, 2, at_home=True) is None


def test_rows_missing_the_needed_columns_are_ignored_rather_than_raising() -> None:
    model = _model().attach_market(pd.DataFrame([{"home_team_id": 1, "away_team_id": 2}]))
    assert model.market_expected_goals(1, 2, at_home=True) is None


# --- blended_expected_goals ------------------------------------------------------------------


def test_with_no_market_attached_blending_is_the_identity() -> None:
    model = _model()
    rating_based = model.expected_goals(1, 2, at_home=True)
    assert model.blended_expected_goals(1, 2, at_home=True, weight=1.0) == pytest.approx(
        rating_based
    )


def test_a_weight_of_zero_is_the_identity_even_with_market_data_attached() -> None:
    model = _model().attach_market(_market_rows([(1, 2, 9.0, 0.1, "2026-08-20T10:00:00Z")]))
    rating_based = model.expected_goals(1, 2, at_home=True)
    assert model.blended_expected_goals(1, 2, at_home=True, weight=0.0) == pytest.approx(
        rating_based
    )


def test_a_weight_of_one_returns_the_market_figure_exactly() -> None:
    model = _model().attach_market(_market_rows([(1, 2, 2.3, 0.9, "2026-08-20T10:00:00Z")]))
    assert model.blended_expected_goals(1, 2, at_home=True, weight=1.0) == pytest.approx(2.3)


def test_a_partial_weight_is_a_linear_blend() -> None:
    model = _model().attach_market(_market_rows([(1, 2, 2.3, 0.9, "2026-08-20T10:00:00Z")]))
    rating_based = model.expected_goals(1, 2, at_home=True)
    blended = model.blended_expected_goals(1, 2, at_home=True, weight=0.4)
    assert blended == pytest.approx(0.4 * 2.3 + 0.6 * rating_based)


def test_an_unresolved_fixture_falls_back_to_ratings_even_at_full_weight() -> None:
    model = _model().attach_market(_market_rows([(1, 2, 2.3, 0.9, "2026-08-20T10:00:00Z")]))
    rating_based = model.expected_goals(1, 3, at_home=True)
    assert model.blended_expected_goals(1, 3, at_home=True, weight=1.0) == pytest.approx(
        rating_based
    )


# --- market_blend_weight ---------------------------------------------------------------------


def test_the_next_gameweek_gets_the_configured_starting_weight() -> None:
    config = MarketBlendConfig(weight_at_next_gameweek=0.6, decay_per_gameweek=0.15)
    assert market_blend_weight(0, config) == pytest.approx(0.6)


def test_the_weight_decays_linearly_with_horizon() -> None:
    config = MarketBlendConfig(weight_at_next_gameweek=0.6, decay_per_gameweek=0.15)
    assert market_blend_weight(1, config) == pytest.approx(0.45)
    assert market_blend_weight(2, config) == pytest.approx(0.30)


def test_the_weight_floors_at_zero_rather_than_going_negative() -> None:
    config = MarketBlendConfig(weight_at_next_gameweek=0.6, decay_per_gameweek=0.15)
    assert market_blend_weight(10, config) == pytest.approx(0.0)


def test_a_negative_horizon_is_clamped_rather_than_trusted() -> None:
    config = MarketBlendConfig(weight_at_next_gameweek=0.6, decay_per_gameweek=0.15)
    assert market_blend_weight(-3, config) == pytest.approx(0.6)


# --- describe ---------------------------------------------------------------------------------


def test_describe_reports_how_many_fixtures_carry_market_data() -> None:
    unmarketed = _model()
    assert unmarketed.describe()["market_fixtures"] == 0

    marketed = _model().attach_market(
        _market_rows(
            [(1, 2, 2.3, 0.9, "2026-08-20T10:00:00Z"), (2, 1, 1.1, 1.6, "2026-08-27T10:00:00Z")]
        )
    )
    assert marketed.describe()["market_fixtures"] == 2
