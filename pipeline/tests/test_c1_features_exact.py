"""C1's feature build equals the version with a Python lambda per group, to the last bit (ORC-09).

The player and club EWMs were ``transform(lambda x: x.ewm(...).mean())``, a Python call per
player-season, and most of every C1 fit. They are now the grouped EWM. That version is kept here,
verbatim, as the reference; every value, dtype, column and row must match it exactly, on played
rows and on rows being forecast, across a season boundary and with missing statistics. Every row's
features still read only its earlier gameweeks (Invariant 5), and equality is also that proof.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import BoostedFeatureConfig, ForecastConfig
from fpl_dof.forecast.features import season_start_year
from fpl_dof.shadow import c1
from fpl_dof.shadow.c1 import ROLL_SRC, UPCOMING
from test_backtest import make_history


def reference_build_features(
    past: pd.DataFrame,
    upcoming: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    config: BoostedFeatureConfig,
) -> pd.DataFrame:
    """The pre-ORC-09 ``c1.build_features``, unchanged."""
    rows = pd.concat(
        [past.assign(**{UPCOMING: False}), upcoming.assign(**{UPCOMING: True})],
        ignore_index=True,
    )
    year = rows["season"].map(season_start_year)
    if year.isna().any():
        unreadable = sorted(set(rows.loc[year.isna(), "season"]))
        raise ValueError(f"C1 cannot order seasons it cannot read a start year from: {unreadable}")
    d = rows.assign(
        sidx=year.astype(int),
        fixture_id=rows["fixture_id"].astype(float),
        kickoff_time=pd.to_datetime(rows["kickoff_time"], utc=True),
    )
    d["t"] = d.sidx * 100 + d.gameweek
    d["key"] = d.season + "|" + d.player_code.astype(str)
    agg: dict[str, str] = dict.fromkeys(ROLL_SRC, "sum")
    agg.update(price="last", was_home="mean", fixture_id="count", kickoff_time="max")
    agg[UPCOMING] = "max"
    keys = ["key", "season", "sidx", "gameweek", "t", "player_code", "position", "team_id"]
    g = (
        d.groupby(keys, as_index=False)
        .agg(agg)
        .rename(columns={"fixture_id": "nfix"})
        .sort_values(["key", "t"])
    )
    grouped = g.groupby("key")
    for c in ROLL_SRC:
        sh = grouped[c].shift(1)
        by_key = sh.groupby(g.key)
        for w in config.rolling_windows:
            rolled = by_key.rolling(w, min_periods=1).mean()
            g[f"{c}_l{w}"] = rolled.reset_index(0, drop=True)
        g[c + "_sea"] = by_key.expanding().mean().reset_index(0, drop=True)
        g[c + "_ewm"] = by_key.transform(
            lambda x: x.ewm(halflife=config.player_halflife, ignore_na=True).mean()
        )
    g["gp"] = grouped.cumcount()
    g["min_last"] = grouped["minutes"].shift(1)
    g["played_last"] = (g.min_last > 0).astype(float)
    prev = g.groupby(["sidx", "player_code"], as_index=False)[["total_points", "minutes"]].mean()
    prev["sidx"] += 1
    g = g.merge(
        prev.rename(columns={"total_points": "prev_pts", "minutes": "prev_min"}),
        on=["sidx", "player_code"],
        how="left",
    )
    fx = d.groupby(["season", "t", "fixture_id", "team_id"], as_index=False).expected_goals.sum()
    fx2 = fx.merge(fx, on=["season", "t", "fixture_id"], suffixes=("", "_o"))
    fx2 = fx2[fx2.team_id != fx2.team_id_o]
    tg = (
        fx2.groupby(["season", "t", "team_id"], as_index=False)
        .agg(xgf=("expected_goals", "sum"), xga=("expected_goals_o", "sum"))
        .sort_values("t")
    )
    for c in ["xgf", "xga"]:
        tg[c + "_r"] = tg.groupby(["season", "team_id"])[c].transform(
            lambda x: x.shift(1).ewm(halflife=config.team_halflife).mean()
        )
    opp = d.groupby(["season", "t", "team_id"], as_index=False).opponent_team_id.first()
    g = g.merge(opp, on=["season", "t", "team_id"], how="left")
    cols = ["season", "t", "team_id", "xgf_r", "xga_r"]
    g = g.merge(tg[cols], on=["season", "t", "team_id"], how="left")
    g = g.merge(
        tg[cols].rename(
            columns={"team_id": "opponent_team_id", "xgf_r": "opp_xgf_r", "xga_r": "opp_xga_r"}
        ),
        on=["season", "t", "opponent_team_id"],
        how="left",
    )
    g["nfix"] = g.nfix.astype(float)
    g[["prev_pts", "prev_min"]] = g[["prev_pts", "prev_min"]].fillna(-1)
    g["was_home"] = g.was_home.astype(float)
    g[UPCOMING] = g[UPCOMING].astype(bool)
    g["as_of"] = g.pop("kickoff_time").where(~g[UPCOMING], pd.Timestamp(as_of))
    return g


def two_seasons(*, seed: int = 5) -> pd.DataFrame:
    """Two seasons with real-looking xG, gaps in the statistics, and a club with no xG at all."""
    rng = np.random.default_rng(seed)
    history = pd.concat(
        [
            make_history(players=36, gameweeks=20, seed=seed, season="2024/25"),
            make_history(players=40, gameweeks=8, seed=seed + 1, season="2025/26").assign(
                kickoff_time=lambda f: f["kickoff_time"] + pd.Timedelta(days=365)
            ),
        ],
        ignore_index=True,
    )
    n = len(history)
    history["expected_goals"] = rng.gamma(0.4, 0.3, n)
    history["expected_assists"] = np.where(rng.random(n) < 0.2, np.nan, rng.random(n) / 7.0)
    history.loc[history["team_id"] == 3, "expected_goals"] = np.nan
    history["bonus"] = rng.integers(0, 4, n)
    history["total_points"] = history["total_points"].round(1)
    return history


def _upcoming(history: pd.DataFrame, season: str, gameweek: int) -> pd.DataFrame:
    rows = history[(history["season"] == season) & (history["gameweek"] == gameweek)]
    return rows[
        ["player_code", "position", "team_id", "opponent_team_id", "fixture_id", "was_home"]
    ].assign(season=season, gameweek=gameweek, price=5.0, **dict.fromkeys(ROLL_SRC, np.nan))


@pytest.mark.parametrize("gameweek", [1, 4, 8])
def test_c1_features_equal_the_lambda_version(gameweek: int) -> None:
    history = two_seasons()
    deadline = pd.Timestamp(
        history.loc[
            (history["season"] == "2025/26") & (history["gameweek"] == gameweek), "kickoff_time"
        ].min()
    ) - pd.Timedelta(hours=2)
    past = history[history["kickoff_time"] < deadline]
    upcoming = _upcoming(history, "2025/26", gameweek)
    config = ForecastConfig().c1
    for ahead in (past.iloc[:0], upcoming):  # the fit's frame, then the predict's
        expected = reference_build_features(past, ahead, as_of=deadline, config=config)
        actual = c1.build_features(past, ahead, as_of=deadline, config=config)
        assert actual["xgf_r"].notna().any() and actual["total_points_ewm"].notna().any()
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_a_reads_the_same_c1_features() -> None:
    """A builds on C1's frame; its own rolling counts were already grouped and are unchanged."""
    history = two_seasons()
    deadline = pd.Timestamp("2026-09-01T00:00:00Z")
    past = history[history["kickoff_time"] < deadline]
    expected = reference_build_features(
        past, past.iloc[:0], as_of=deadline, config=ForecastConfig().a
    )
    actual = c1.build_features(past, past.iloc[:0], as_of=deadline, config=ForecastConfig().a)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
