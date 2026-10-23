"""The vectorised feature store equals the per-player loop it replaced, to the last bit (ORC-09).

``build_features`` was a Python loop over players; it is now array arithmetic over the whole frame,
because the loop was most of every backtest walk. The loop is kept here, verbatim, as the
reference: every feature value, dtype, column and row must match it exactly, and the inputs below
are chosen to reach the places an exact-output rewrite usually slips — float sums long enough for
numpy's pairwise summation, nulls in every kind of column, players with fewer matches than a
window, unsorted input with tied kickoffs, and deadlines at second and nanosecond resolution.
Neither implementation may read a match at or after the deadline (Invariant 5); the reference's
filter is the original's, so equality is also the look-ahead proof.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import FeatureConfig, PriorSeasonConfig
from fpl_dof.forecast import features as store
from fpl_dof.forecast.features import (
    PRIOR_SEASON_MINUTES,
    _attach_prior_season,
    absence_feature_name,
    build_features,
    congestion_feature_name,
    input_features,
)
from fpl_dof.frames import as_int
from test_backtest import make_history


def reference_build_features(
    history: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    config: FeatureConfig,
    positions: pd.DataFrame | None = None,
    metrics: pd.DataFrame | None = None,
    season: str | None = None,
) -> pd.DataFrame:
    """The pre-ORC-09 ``build_features``, unchanged. Slow, and obviously per player."""
    if history.empty:
        return pd.DataFrame(columns=["player_code", "as_of", *input_features(config)])

    moment = pd.Timestamp(as_of).tz_convert("UTC")
    known = history[history["kickoff_time"] < moment].copy()
    if known.empty:
        return pd.DataFrame(columns=["player_code", "as_of", *input_features(config)])

    known = known.sort_values(["player_code", "kickoff_time"])
    rows: list[dict[str, object]] = []

    for code, group in known.groupby("player_code", sort=True):
        row: dict[str, object] = {"player_code": as_int(code), "as_of": moment}
        for window in config.rolling_windows:
            recent = group.tail(window)
            minutes = float(recent["minutes"].sum())
            row[f"minutes_mean_last{window}"] = float(recent["minutes"].mean())
            for stat in config.rolling_statistics:
                if stat not in recent.columns:
                    row[f"{stat}_per90_last{window}"] = np.nan
                    continue
                values = pd.to_numeric(recent[stat], errors="coerce")
                if values.isna().all() or minutes <= 0:
                    row[f"{stat}_per90_last{window}"] = np.nan
                else:
                    row[f"{stat}_per90_last{window}"] = float(values.sum()) / minutes * 90.0

        last = group.iloc[-1]
        row["matches_observed"] = len(group)
        row["appearance_rate"] = float((group["minutes"] > 0).mean())
        starts = pd.to_numeric(group["starts"], errors="coerce")
        row["starts_rate"] = float(starts.mean()) if not starts.isna().all() else np.nan
        row["days_since_last_match"] = float(
            (moment - pd.Timestamp(last["kickoff_time"])).total_seconds() / 86400.0
        )
        window_start = moment - pd.Timedelta(days=config.congestion_window_days)
        row[congestion_feature_name(config)] = float((group["kickoff_time"] >= window_start).sum())
        returning = group.tail(config.return_window_matches)
        row[absence_feature_name(config)] = float((returning["minutes"] <= 0).mean())
        row["price"] = float(last["price"])
        row["was_home"] = bool(last["was_home"])
        rows.append(row)

    frame = pd.DataFrame(rows)
    frame = _attach_prior_season(frame, known, config=config, metrics=metrics, season=season)
    if positions is not None and not positions.empty:
        frame = frame.merge(
            positions[["player_code", "position"]].drop_duplicates("player_code"),
            on="player_code",
            how="left",
        )
    return frame


def messy_history(*, seed: int = 3) -> pd.DataFrame:
    """Two seasons of awkward rows: real-looking floats, nulls of every kind, ties, no order."""
    rng = np.random.default_rng(seed)
    history = pd.concat(
        [
            make_history(players=40, gameweeks=38, seed=seed, season="2024/25"),
            make_history(players=45, gameweeks=10, seed=seed + 1, season="2025/26").assign(
                kickoff_time=lambda f: f["kickoff_time"] + pd.Timedelta(days=365)
            ),
        ],
        ignore_index=True,
    )
    n = len(history)
    history["expected_goals"] = rng.gamma(0.4, 0.3, n)
    history["expected_assists"] = rng.random(n) / 7.0
    history.loc[rng.random(n) < 0.15, "expected_assists"] = np.nan
    history["starts"] = history["starts"].astype("Int64")
    history.loc[rng.random(n) < 0.1, "starts"] = pd.NA
    history["defensive_contribution"] = history["defensive_contribution"].astype("Int64")
    history.loc[rng.random(n) < 0.3, "defensive_contribution"] = pd.NA
    history["saves"] = np.where(rng.random(n) < 0.2, "n/a", history["saves"].astype(str))
    history.loc[history["player_code"] % 7 == 0, "minutes"] = 0  # never plays
    history["price"] = history["price"] + rng.random(n) / 10.0
    history["was_home"] = history["was_home"].astype(object)
    history.loc[rng.random(n) < 0.05, "was_home"] = np.nan
    # A duplicated row: a tied kickoff, which the sort must keep in input order.
    history = pd.concat([history, history.iloc[[5, 400]]], ignore_index=True)
    single = history.iloc[[0]].assign(player_code=999_999)  # one match only
    history = pd.concat([history, single], ignore_index=True)
    return history.sample(frac=1.0, random_state=seed).reset_index(drop=True)


CONFIGS = {
    "default": FeatureConfig(),
    # A window past numpy's pairwise block of eight, and statistics the history does not carry.
    "wide": FeatureConfig(
        rolling_windows=(1, 9, 20, 40),
        rolling_statistics=(*FeatureConfig().rolling_statistics, "not_a_column", "minutes"),
        congestion_window_days=30,
        return_window_matches=11,
    ),
}

DEADLINES = (
    pd.Timestamp("2025-08-20T10:00:00Z"),  # second resolution, one match in
    pd.Timestamp("2026-02-01T18:30:00.000000001Z"),  # nanosecond resolution, mid-season
    pd.Timestamp("2026-09-01T10:00:00", tz="Europe/London").as_unit("us"),  # the next season
    pd.Timestamp("2027-12-01T00:00:00Z"),  # after everything
)


@pytest.mark.parametrize("deadline", DEADLINES, ids=str)
@pytest.mark.parametrize("name", sorted(CONFIGS))
def test_the_vectorised_store_equals_the_per_player_loop(name: str, deadline: pd.Timestamp) -> None:
    history = messy_history()
    config = CONFIGS[name]
    positions = history[["player_code", "position"]]
    expected = reference_build_features(history, as_of=deadline, config=config, positions=positions)
    actual = build_features(history, as_of=deadline, config=config, positions=positions)
    assert len(actual) > 0
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_the_harness_fixture_is_unchanged_at_every_deadline() -> None:
    """The backtest fixture, at each of its deadlines, as the harness's folds build it."""
    history = make_history(players=30, gameweeks=12)
    for deadline in sorted(history["kickoff_time"].unique()):
        moment = pd.Timestamp(deadline) - pd.Timedelta(hours=1)
        expected = reference_build_features(history, as_of=moment, config=FeatureConfig())
        actual = build_features(history, as_of=moment, config=FeatureConfig())
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_the_prior_season_path_is_unchanged() -> None:
    history = messy_history()
    codes = history["player_code"].drop_duplicates()
    metrics = pd.DataFrame(
        {
            "player_code": codes,
            "season": "2023/24",
            "scope": "season",
            "minutes_played": 1000.0 + codes.to_numpy() % 13 * 97.0,
            "non_penalty_expected_goals": codes.to_numpy() % 5 / 3.0,
            "expected_assists": codes.to_numpy() % 4 / 7.0,
            "tackles": 30.0,
            "recoveries": 41.0,
        }
    )
    config = FeatureConfig(prior_season=PriorSeasonConfig(enabled=True))
    deadline = pd.Timestamp("2026-01-01T00:00:00Z")
    expected = reference_build_features(
        history, as_of=deadline, config=config, metrics=metrics, season="2024/25"
    )
    actual = build_features(
        history, as_of=deadline, config=config, metrics=metrics, season="2024/25"
    )
    assert actual[PRIOR_SEASON_MINUTES].notna().any()
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_an_empty_or_unplayed_history_is_unchanged() -> None:
    history = make_history(players=3, gameweeks=2)
    before = pd.Timestamp("2025-01-01T00:00:00Z")
    for frame in (history.iloc[:0], history):
        pd.testing.assert_frame_equal(
            build_features(frame, as_of=before, config=FeatureConfig()),
            reference_build_features(frame, as_of=before, config=FeatureConfig()),
            check_exact=True,
        )
    assert store.build_features is build_features
