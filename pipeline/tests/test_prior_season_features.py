"""D-22 — the prior-season prior, and above all the boundary it must not cross.

**The knowability test is the reason this file exists.** Every other test here checks that a ratio
is computed the way it is described; the boundary tests check that the number is allowed to exist at
all. A season total leaking into a deadline inside its own season would make the backtest look
*better* while being worthless, and nothing in the metrics would say so — the exact failure
Invariant 5 and DP-13 exist for, and the one this feature is most able to cause because its inputs
carry no timestamp of their own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fpl_dof.config.models import FeatureConfig, ForecastConfig, PriorSeasonConfig
from fpl_dof.forecast.features import (
    PRIOR_SEASON_MINUTES,
    build_features,
    input_features,
    prior_season_feature_names,
    prior_season_ratios,
    season_start_year,
    specs,
)
from fpl_dof.forecast.models import RateModel
from fpl_dof.forecast.xp_v1 import _prior_season

PRIOR = "2025/26"
CURRENT = "2026/27"
NPXG_RATIO = "prior_season_non_penalty_expected_goals_ratio"
DEFENSIVE_RATIO = "prior_season_defensive_actions_ratio"


def enabled_config(**overrides: object) -> FeatureConfig:
    return FeatureConfig(prior_season=PriorSeasonConfig(enabled=True, **overrides))


def metrics_frame(
    *,
    season: str = PRIOR,
    players: int = 8,
    minutes: float = 2500.0,
) -> pd.DataFrame:
    """A season-scope advanced table, one row per player, shaped like ``player_metric``."""
    rows = []
    for player in range(1, players + 1):
        rows.append(
            {
                "season": season,
                "player_id": player,
                "player_code": 100_000 + player,
                "scope": "season",
                "gameweek": None,
                "sources": "a-source",
                "minutes_played": minutes,
                "matches": 30.0,
                "expected_goals": float(player),
                "non_penalty_expected_goals": float(player),
                "expected_assists": float(player) / 2.0,
                "tackles": float(player) * 3.0,
                "interceptions": float(player),
                "blocks": float(player),
                "clearances": float(player),
                "recoveries": float(player) * 2.0,
            }
        )
    return pd.DataFrame(rows)


def history_frame(
    seasons: tuple[str, ...] = ("2024/25", PRIOR, CURRENT), gameweeks: int = 38
) -> pd.DataFrame:
    """Three seasons of per-gameweek rows, one match per player per gameweek.

    Three rather than two so that even the first deadline of the middle season has history behind
    it: a feature frame that is empty for want of any past at all would pass the boundary tests
    below for the wrong reason.
    """
    rows = []
    for index, season in enumerate(seasons):
        start = pd.Timestamp(f"{season_start_year(season)}-08-15T18:00:00Z")
        for player in range(1, 9):
            for gameweek in range(1, gameweeks + 1):
                rows.append(
                    {
                        "season": season,
                        "gameweek": gameweek,
                        "player_code": 100_000 + player,
                        "position": ("GKP", "DEF", "MID", "FWD")[player % 4],
                        "kickoff_time": start + pd.Timedelta(days=7 * (gameweek - 1)),
                        "minutes": 90,
                        "starts": 1,
                        "price": 5.0,
                        "was_home": bool(index),
                        "goals_scored": 0,
                        "assists": 0,
                        "total_points": 2.0,
                    }
                )
    return pd.DataFrame(rows)


# --- the boundary ------------------------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(gameweek=st.integers(min_value=1, max_value=38))
def test_a_season_total_is_invisible_at_every_deadline_inside_its_own_season(
    gameweek: int,
) -> None:
    """No deadline of the season a total was accumulated in may see it — including the last.

    Property-tested across every gameweek because the failure mode is an off-by-one at one end of
    the season, and a single hand-picked deadline is exactly the shape of test that misses it.
    """
    history = history_frame()
    deadline = history[(history["season"] == PRIOR) & (history["gameweek"] == gameweek)][
        "kickoff_time"
    ].min()

    features = build_features(
        history,
        as_of=deadline,
        config=enabled_config(),
        metrics=metrics_frame(),
        season=PRIOR,
    )

    assert not features.empty
    assert features[NPXG_RATIO].isna().all()
    assert features[PRIOR_SEASON_MINUTES].isna().all()


@settings(max_examples=40, deadline=None)
@given(gameweek=st.integers(min_value=1, max_value=38))
def test_the_same_total_is_visible_at_every_deadline_of_the_following_season(
    gameweek: int,
) -> None:
    """A completed season is knowable from the first deadline of the next one onward."""
    history = history_frame()
    deadline = history[(history["season"] == CURRENT) & (history["gameweek"] == gameweek)][
        "kickoff_time"
    ].min()

    features = build_features(
        history,
        as_of=deadline,
        config=enabled_config(),
        metrics=metrics_frame(),
        season=CURRENT,
    )

    assert features[NPXG_RATIO].notna().all()
    assert (features[PRIOR_SEASON_MINUTES] == 2500.0).all()


def test_the_boundary_is_the_season_label_not_the_last_kickoff() -> None:
    """A deadline after the prior season's final match still sees nothing of its *own* season.

    The distinction matters because a fixture list is not a knowability rule: a postponement, a
    rearranged final round or a missing row would move a timestamp-based boundary, and this one
    cannot be moved by any of them.
    """
    history = history_frame()
    after_the_last_match = history[history["season"] == PRIOR]["kickoff_time"].max() + pd.Timedelta(
        days=1
    )

    features = build_features(
        history,
        as_of=after_the_last_match,
        config=enabled_config(),
        metrics=metrics_frame(),
        season=PRIOR,
    )

    assert features[NPXG_RATIO].isna().all()


def test_a_season_two_years_back_loses_to_the_most_recent_completed_one() -> None:
    older = metrics_frame(season="2024/25", minutes=3000.0)
    recent = metrics_frame(season=PRIOR, minutes=2500.0)

    ratios = prior_season_ratios(
        pd.concat([older, recent], ignore_index=True),
        season=CURRENT,
        positions={},
        config=PriorSeasonConfig(enabled=True),
    )

    assert (ratios[PRIOR_SEASON_MINUTES] == 2500.0).all()


def test_a_gameweek_scoped_row_is_never_a_prior_season_feature() -> None:
    """Only season totals are in scope. A per-gameweek row is the other table's business."""
    metrics = metrics_frame()
    metrics["scope"] = "gameweek"
    metrics["gameweek"] = 5

    ratios = prior_season_ratios(
        metrics, season=CURRENT, positions={}, config=PriorSeasonConfig(enabled=True)
    )

    assert ratios.empty


# --- the ratio ---------------------------------------------------------------------------


def test_the_ratio_is_relative_to_the_players_own_position() -> None:
    """Otherwise the position prior it scales would count position twice."""
    metrics = metrics_frame(players=4)
    positions = {100_001: "MID", 100_002: "MID", 100_003: "DEF", 100_004: "DEF"}

    ratios = prior_season_ratios(
        metrics, season=CURRENT, positions=positions, config=PriorSeasonConfig(enabled=True)
    ).set_index("player_code")

    # Players 1 and 2 are the midfielders, with npxG of 1 and 2 against a positional mean of 1.5.
    assert ratios.loc[100_001, NPXG_RATIO] == pytest.approx(1.0 / 1.5)
    assert ratios.loc[100_002, NPXG_RATIO] == pytest.approx(2.0 / 1.5)
    # Players 3 and 4 are the defenders, with a mean of 3.5: the same figure ranks differently.
    assert ratios.loc[100_003, NPXG_RATIO] == pytest.approx(3.0 / 3.5)


def test_the_ratio_is_bounded_at_both_ends() -> None:
    metrics = metrics_frame(players=2)
    metrics.loc[metrics["player_code"] == 100_002, "non_penalty_expected_goals"] = 100.0

    ratios = prior_season_ratios(
        metrics,
        season=CURRENT,
        positions={},
        config=PriorSeasonConfig(enabled=True, minimum_ratio=0.5, maximum_ratio=2.0),
    )

    assert ratios[NPXG_RATIO].min() >= 0.5
    assert ratios[NPXG_RATIO].max() <= 2.0


def test_a_thin_prior_season_is_dropped_rather_than_believed() -> None:
    ratios = prior_season_ratios(
        metrics_frame(minutes=200.0),
        season=CURRENT,
        positions={},
        config=PriorSeasonConfig(enabled=True, minimum_minutes=450.0),
    )

    assert ratios.empty


def test_a_statistic_no_source_supplied_is_null_not_zero() -> None:
    """The distinction between "did not do it" and "we could not have seen it" (DL-18)."""
    metrics = metrics_frame()
    for column in ("tackles", "interceptions", "blocks", "clearances", "recoveries"):
        metrics[column] = np.nan

    ratios = prior_season_ratios(
        metrics, season=CURRENT, positions={}, config=PriorSeasonConfig(enabled=True)
    )

    assert ratios[DEFENSIVE_RATIO].isna().all()
    assert ratios[NPXG_RATIO].notna().all()


def test_a_player_with_no_prior_season_gets_a_null_rather_than_a_row() -> None:
    metrics = metrics_frame(players=2)
    features = build_features(
        history_frame(),
        as_of=pd.Timestamp("2026-09-01T18:00:00Z"),
        config=enabled_config(),
        metrics=metrics,
        season=CURRENT,
    ).set_index("player_code")

    assert features.loc[100_001, NPXG_RATIO] == pytest.approx(features.loc[100_001, NPXG_RATIO])
    assert pd.isna(features.loc[100_005, NPXG_RATIO])


# --- the wiring --------------------------------------------------------------------------


def test_the_feature_does_not_exist_at_all_while_it_ships_dark() -> None:
    """DP-08: off by default, and off means absent rather than present-and-null."""
    assert prior_season_feature_names(FeatureConfig()) == ()
    assert not [name for name in input_features(FeatureConfig()) if name.startswith("prior_season")]
    assert PRIOR_SEASON_MINUTES in input_features(enabled_config())


def test_every_prior_season_feature_declares_when_it_became_knowable() -> None:
    declared = {spec.name for spec in specs(enabled_config()) if spec.knowability is not None}
    for name in prior_season_feature_names(enabled_config()):
        assert name in declared


def test_the_columns_exist_even_when_no_source_supplied_a_single_row() -> None:
    features = build_features(
        history_frame(),
        as_of=pd.Timestamp("2026-09-01T18:00:00Z"),
        config=enabled_config(),
        metrics=None,
        season=CURRENT,
    )

    for name in prior_season_feature_names(enabled_config()):
        assert name in features.columns
        assert features[name].isna().all()


def test_the_prior_is_ignored_without_a_season_to_compare_against() -> None:
    """No target season, no answer to "is this in the past". The safe answer is taken."""
    features = build_features(
        history_frame(),
        as_of=pd.Timestamp("2026-09-01T18:00:00Z"),
        config=enabled_config(),
        metrics=metrics_frame(),
        season=None,
    )

    assert features[NPXG_RATIO].isna().all()


def test_the_component_map_decides_which_rate_the_signal_reaches() -> None:
    config = ForecastConfig(features=enabled_config())
    row = pd.Series({NPXG_RATIO: 1.5, PRIOR_SEASON_MINUTES: 2700.0})

    assert _prior_season(row, "goals_scored", config) == (1.5, 2700.0)
    # Saves are not in the map: nothing an xG-shaped source measures says anything about them.
    ratio, minutes = _prior_season(row, "saves", config)
    assert np.isnan(ratio)
    assert minutes == 0.0


def test_a_missing_prior_leaves_the_position_prior_exactly_where_it_was() -> None:
    """The no-evidence path must be byte-identical to the behaviour before this feature existed."""
    model = RateModel(column="goals_scored", prior_by_position={"MID": 0.4}, prior_minutes=900.0)

    assert model.predict("MID", float("nan"), 0.0) == pytest.approx(0.4)
    assert model.predict(
        "MID", float("nan"), 0.0, prior_ratio=float("nan"), prior_ratio_minutes=3000.0
    ) == pytest.approx(0.4)


def test_the_prior_moves_toward_the_ratio_as_prior_season_minutes_accumulate() -> None:
    model = RateModel(
        column="goals_scored",
        prior_by_position={"MID": 0.4},
        prior_minutes=900.0,
        prior_season_minutes=900.0,
    )

    thin = model.predict("MID", float("nan"), 0.0, prior_ratio=2.0, prior_ratio_minutes=100.0)
    full = model.predict("MID", float("nan"), 0.0, prior_ratio=2.0, prior_ratio_minutes=2700.0)

    assert 0.4 < thin < full < 0.8
    assert full == pytest.approx(0.4 * (0.75 * 2.0 + 0.25))


def test_this_seasons_own_evidence_still_outweighs_last_seasons_as_it_arrives() -> None:
    """The prior is a starting point, not a thumb on the scale that never lifts."""
    model = RateModel(
        column="goals_scored",
        prior_by_position={"MID": 0.4},
        prior_minutes=900.0,
        prior_season_minutes=900.0,
    )

    early = model.predict("MID", 0.1, 90.0, prior_ratio=2.0, prior_ratio_minutes=2700.0)
    late = model.predict("MID", 0.1, 3000.0, prior_ratio=2.0, prior_ratio_minutes=2700.0)

    assert abs(late - 0.1) < abs(early - 0.1)
