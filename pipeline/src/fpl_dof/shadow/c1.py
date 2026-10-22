"""C1 — per-position boosted xG model with a minutes head, P(play) x pts|play.

Port of ``backtest/vector_models.py`` (kind ``xg2``), the candidate that scored +6.70 [3.21, 9.96]
XI pts/GW over the engine in the walk-forward backtest, concentrated in 2025/26 and with 24 hits.
It is the ``c1`` challenger's forecaster: the registry's ``Strategy.forecast`` calls
:func:`forecast`, and its advice comes from the one decision engine like every strategy's (MOD-04).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast import live
from fpl_dof.forecast.entry import Forecast
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.frames import as_int, gameweek_column
from fpl_dof.optimise.frame import validate_forecast_frame
from fpl_dof.rules.models import GameRules

MODEL_NAME = "c1_gbm_xg_minutes"

ROLL_SRC = [
    "total_points",
    "minutes",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "starts",
    "bonus",
    "bps",
]
BASE = [
    "price",
    "was_home",
    "gp",
    "nfix",
    "min_last",
    "played_last",
    "prev_pts",
    "prev_min",
    "xgf_r",
    "xga_r",
    "opp_xgf_r",
    "opp_xga_r",
]
POSITIONS = ("GKP", "DEF", "MID", "FWD")


def build_features(history: pd.DataFrame) -> pd.DataFrame:
    """Vector's features, verbatim in substance. Every rolling value is shifted one GW."""
    d = history.copy()
    seasons = sorted(d.season.unique())
    d["sidx"] = d.season.map({s: i for i, s in enumerate(seasons)})
    d["t"] = d.sidx * 100 + d.gameweek
    d["key"] = d.season + "|" + d.player_code.astype(str)
    agg: dict[str, str] = dict.fromkeys(ROLL_SRC, "sum")
    agg.update(price="last", was_home="mean", fixture_id="count")
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
        g[c + "_l3"] = sh.groupby(g.key).rolling(3, min_periods=1).mean().reset_index(0, drop=True)
        g[c + "_l6"] = sh.groupby(g.key).rolling(6, min_periods=1).mean().reset_index(0, drop=True)
        g[c + "_sea"] = sh.groupby(g.key).expanding().mean().reset_index(0, drop=True)
        g[c + "_ewm"] = sh.groupby(g.key).transform(
            lambda x: x.ewm(halflife=4, ignore_na=True).mean()
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
            lambda x: x.shift(1).ewm(halflife=6).mean()
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
    return g


def upcoming_rows(
    players: pd.DataFrame, fixtures: pd.DataFrame, season: str, gameweek: int
) -> pd.DataFrame:
    """One outcome-less row per player per fixture in ``gameweek``: the rows to predict."""
    fx = fixtures[fixtures["gameweek"] == gameweek]
    sides = pd.concat(
        [
            fx.assign(team_id=fx.home_team_id, opponent_team_id=fx.away_team_id, was_home=True),
            fx.assign(team_id=fx.away_team_id, opponent_team_id=fx.home_team_id, was_home=False),
        ]
    )[["fixture_id", "team_id", "opponent_team_id", "was_home"]]
    roster = players.rename(columns={"code": "player_code"})[
        ["player_id", "player_code", "web_name", "position", "team_id", "price"]
    ]
    rows = roster.merge(sides, on="team_id", how="inner")
    rows["season"] = season
    rows["gameweek"] = gameweek
    for c in ROLL_SRC:
        rows[c] = np.nan
    return rows


class C1Model:
    """Per-position HistGBM classifier (plays?) x regressor (points | plays)."""

    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self.features: list[str] = []

    def fit_predict(self, g: pd.DataFrame, t_next: int) -> pd.Series:
        from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

        roll = [c for c in g.columns if any(c.endswith(s) for s in ("_l3", "_l6", "_sea", "_ewm"))]
        self.features = BASE + roll
        train = g[(g.t < t_next) & (g.gp > 0)]
        test = g[g.t == t_next]
        out = pd.Series(0.0, index=test.index)
        kw: dict[str, Any] = {"max_iter": 200, "learning_rate": 0.05, "min_samples_leaf": 50}
        for pos in POSITIONS:
            p = train[train.position == pos]
            played = p[p.minutes > 0]
            e = test[test.position == pos]
            if e.empty or p.empty or played.empty:
                continue
            clf = HistGradientBoostingClassifier(**kw).fit(
                p[self.features], (p.minutes > 0).astype(int)
            )
            reg = HistGradientBoostingRegressor(**kw).fit(
                played[self.features], played.total_points
            )
            self.models[pos] = (clf, reg)
            out.loc[e.index] = clf.predict_proba(e[self.features])[:, 1] * reg.predict(
                e[self.features]
            )
        return pd.Series(out.to_numpy(), index=test.player_code.to_numpy())


def predict_next(
    history: pd.DataFrame, players: pd.DataFrame, fixtures: pd.DataFrame, season: str, gameweek: int
) -> dict[int, float]:
    """C1 xPts for ``gameweek`` per ``player_code``, trained on history strictly before it."""
    past = history[(history["season"] != season) | (history["gameweek"] < gameweek)]
    future = upcoming_rows(players, fixtures, season, gameweek)
    columns = [c for c in past.columns if c in future.columns]
    frame = pd.concat([past, future[columns]], ignore_index=True)
    frame["fixture_id"] = frame["fixture_id"].astype(float)
    g = build_features(frame)
    t_next = int(g[(g.season == season) & (g.gameweek == gameweek)].t.iloc[0])
    return {as_int(k): float(v) for k, v in C1Model().fit_predict(g, t_next).items()}


def forecast(
    inputs: ForecastInputs, rules: GameRules, config: ForecastConfig, variance_from: Forecast
) -> Forecast:
    """C1's forecast frame: its own next-gameweek mean, fitted on history strictly before it.

    C1 forecasts one gameweek and has no variance of its own yet, so it **borrows** from
    ``variance_from`` (the champion's forecast): every sd column, the per-gameweek means beyond the
    next gameweek (which the plan reads), and B0's line for the price-and-position captain rule.
    MOD-05 gives C1 its own variance and horizon; until then the borrowing is this signature.
    """
    validate_forecast_frame(variance_from.frame)
    gameweek, _, _ = live.next_deadline(inputs.gameweeks, config, as_of=inputs.as_of)
    history = inputs.player_gameweek if inputs.player_gameweek is not None else pd.DataFrame()
    players = inputs.players
    xp_by_code = predict_next(history, players, inputs.fixtures, rules.season, gameweek)
    code_of = dict(zip(players["player_id"].astype(int), players["code"].astype(int), strict=True))
    frame = variance_from.frame.copy()
    frame["xp_next"] = [xp_by_code.get(code_of.get(as_int(i), -1), 0.0) for i in frame["player_id"]]
    frame["xp_horizon"] = frame["xp_next"]
    if gameweek_column(gameweek) in frame.columns:
        frame[gameweek_column(gameweek)] = frame["xp_next"]
    frame["model"] = MODEL_NAME
    return Forecast(
        frame=validate_forecast_frame(frame),
        model=MODEL_NAME,
        fallback_reason=None,
        captain_line=variance_from.captain_line,
    )
