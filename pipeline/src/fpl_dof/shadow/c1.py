"""C1 — per-position boosted xG model with a minutes head: P(play) x points | play.

Port of ``backtest/vector_models.py`` (kind ``xg2``), the candidate that scored +6.70 [3.21, 9.96]
XI pts/GW over the engine in the walk-forward backtest, concentrated in 2025/26 and with 24 hits.
It is the ``c1`` challenger's forecaster: the registry's ``Strategy.forecast`` calls
:func:`forecast`, the walk-forward backtest can fit it through :class:`C1Predictor`, and its advice
comes from the one decision engine like every strategy's (MOD-04).

**Its own frame, nothing borrowed (MOD-05).** The mean is P(play) x points | play; the variance is
the two-state mixture of not playing and playing (:func:`~fpl_dof.forecast.xp_v1.mixture_moments`,
the champion's formula), with points | play spread by the regressor's per-position residuals; and
P(play) is the classifier's, scaled by availability news as the champion scales its own. B0, for
the price-and-position captain rule, is fitted on C1's own training rows.

**One gameweek.** C1 forecasts the gameweek being decided and nothing beyond it, so its frame
carries that gameweek's column and a one-gameweek horizon (``horizon_gameweeks`` = 1), and the
registry runs it with ``plan: false``. Forecasting later gameweeks needs its rolling features
carried forward without outcomes: a model extension to grade, not part of the port.

**Knowability.** Every feature is declared in :func:`specs` with the moment it becomes knowable.
Every feature row is stamped ``as_of``: a played row with its latest kickoff, an upcoming row with
the deadline it is forecast at. :func:`fit_as_of` and :meth:`FittedC1.predict` call
:func:`~fpl_dof.forecast.features.assert_no_look_ahead` on them, so a history row kicked off after
the deadline that reaches the features raises rather than trains (Invariant 5).

**Seasons.** Players are keyed by ``player_code`` (FPL reuses ``player_id`` every season), rolling
features and club xG never cross a season boundary, and seasons are ordered by start year, so the
previous season is the one that started a year earlier.

Differences from the frozen original, all deliberate: hyperparameters, windows and half-lives from
``forecast.c1`` (DP-06) and every fit seeded; seasons ordered by start year rather than by label;
the live fit stops at the first unfinished gameweek (REM-08).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd

from fpl_dof.config.models import BoostedFeatureConfig, C1Config, ForecastConfig
from fpl_dof.forecast import baselines, live
from fpl_dof.forecast.baselines import FittedBaseline
from fpl_dof.forecast.entry import Forecast, price_position_line
from fpl_dof.forecast.features import (
    FIXTURE_AT_HOME,
    FIXTURE_OPPONENT,
    FIXTURE_TEAM,
    TARGET,
    FeatureSpec,
    Knowability,
    assert_no_look_ahead,
    season_start_year,
)
from fpl_dof.forecast.fit import IDENTITY_COLUMNS, ColdStartError, availability
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.xp_v1 import mixture_moments
from fpl_dof.frames import as_int, gameweek_column, gameweek_sd_column
from fpl_dof.optimise.frame import validate_forecast_frame
from fpl_dof.rules.models import GameRules, Position

MODEL_NAME = "c1_gbm_xg_minutes"

#: Per-gameweek statistics each rolling feature is a mean of.
ROLL_SRC = (
    "total_points",
    "minutes",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "starts",
    "bonus",
    "bps",
)
#: Marks the rows being forecast, as opposed to played rows, through the feature build.
UPCOMING = "_upcoming"


def _rolling_names(config: BoostedFeatureConfig) -> tuple[str, ...]:
    suffixes = (*(f"l{w}" for w in config.rolling_windows), "sea", "ewm")
    return tuple(f"{stat}_{suffix}" for stat in ROLL_SRC for suffix in suffixes)


def specs(config: BoostedFeatureConfig) -> tuple[FeatureSpec, ...]:
    """C1's features, each declared with the moment it becomes knowable (the feature store seam)."""
    before, at = Knowability.BEFORE_DEADLINE, Knowability.AT_DEADLINE

    def spec(name: str, knowability: Knowability, summary: str, *sources: str) -> FeatureSpec:
        return FeatureSpec(name, knowability, summary, sources)

    return (
        spec("price", at, "Price at the deadline", "price"),
        spec(
            "was_home",
            at,
            "Share of the gameweek's fixtures at home, from the calendar",
            "was_home",
        ),
        spec("gp", before, "Gameweeks played this season before this one", "gameweek"),
        spec("nfix", at, "Fixtures in the gameweek, from the calendar", "fixture_id"),
        spec("min_last", before, "Minutes in the previous gameweek", "minutes"),
        spec("played_last", before, "Whether the previous gameweek had minutes", "minutes"),
        spec("prev_pts", before, "Previous season's points per gameweek", TARGET, "season"),
        spec("prev_min", before, "Previous season's minutes per gameweek", "minutes", "season"),
        spec("xgf_r", before, "Club xG for, EWM over its earlier matches", "expected_goals"),
        spec("xga_r", before, "Club xG against, EWM over its earlier matches", "expected_goals"),
        spec("opp_xgf_r", before, "Opponent's xG for, EWM", "expected_goals", "opponent_team_id"),
        spec(
            "opp_xga_r", before, "Opponent's xG against, EWM", "expected_goals", "opponent_team_id"
        ),
        *(
            spec(name, before, "Mean over the player's earlier gameweeks this season", name)
            for name in _rolling_names(config)
        ),
        spec(
            TARGET, Knowability.AFTER_KICKOFF, "What happened. The target, never an input", TARGET
        ),
    )


def input_features(config: BoostedFeatureConfig) -> tuple[str, ...]:
    return tuple(s.name for s in specs(config) if s.is_input)


def build_features(
    past: pd.DataFrame,
    upcoming: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    config: BoostedFeatureConfig,
) -> pd.DataFrame:
    """One row per player per gameweek: played rows in ``past``, forecast rows in ``upcoming``.

    Every rolling value is shifted one gameweek within ``season|player_code``, so a row's features
    read only its earlier gameweeks of the same season; ``prev_*`` read the season that started a
    year earlier, by ``player_code``. Rows are stamped ``as_of`` (see the module docstring).
    """
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


def utc_deadline(moment: pd.Timestamp | Any) -> pd.Timestamp:
    ts = pd.Timestamp(moment)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


@dataclass(frozen=True, slots=True)
class FittedC1:
    """C1 fitted on everything played before ``as_of``: per position a classifier (plays?), a
    regressor (points | plays) and that regressor's residual sd, and B0 on the same rows."""

    config: C1Config
    as_of: pd.Timestamp
    past: pd.DataFrame
    models: dict[str, tuple[Any, Any, float]]
    b0: FittedBaseline

    def predict(self, upcoming: pd.DataFrame) -> pd.DataFrame:
        """``player_code``, ``p_play``, ``mean_if_play`` and ``sd_if_play`` for each player in
        ``upcoming`` (one gameweek, a row per fixture). A position with no fitted model reads 0."""
        g = build_features(self.past, upcoming, as_of=self.as_of, config=self.config)
        assert_no_look_ahead(g, self.past, as_of=self.as_of)
        rows = g[g[UPCOMING]].reset_index(drop=True)
        out = pd.DataFrame(
            {
                "player_code": rows["player_code"],
                "p_play": 0.0,
                "mean_if_play": 0.0,
                "sd_if_play": 0.0,
            }
        )
        features = list(input_features(self.config))
        for position, (clf, reg, sd) in self.models.items():
            mask = rows["position"] == position
            if mask.any():
                x = rows.loc[mask, features]
                out.loc[mask, "p_play"] = clf.predict_proba(x)[:, 1] if clf is not None else 1.0
                out.loc[mask, "mean_if_play"] = reg.predict(x)
                out.loc[mask, "sd_if_play"] = sd
        return out


def fit_as_of(past: pd.DataFrame, as_of: pd.Timestamp, config: C1Config) -> FittedC1:
    """Fit C1 on ``past``, every row of which must have kicked off before ``as_of``."""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    moment = utc_deadline(as_of)
    g = build_features(past, past.iloc[:0], as_of=moment, config=config)
    assert_no_look_ahead(g, past, as_of=moment)
    train = g[g.gp > 0]
    if train.empty:
        raise ColdStartError("C1 has no player with an earlier gameweek to learn from")
    features = list(input_features(config))
    kw: dict[str, Any] = {
        "max_iter": config.max_iter,
        "learning_rate": config.learning_rate,
        "min_samples_leaf": config.min_samples_leaf,
        "early_stopping": config.early_stopping,
        "random_state": config.seed,
    }
    models: dict[str, tuple[Any, Any, float]] = {}
    for position in Position:
        p = train[train.position == position.value]
        played = p[p.minutes > 0]
        if played.empty:
            continue
        plays = (p.minutes > 0).astype(int)
        # Every row of the position played: nothing to classify, P(play) is the observed 1.
        clf = (
            HistGradientBoostingClassifier(**kw).fit(p[features], plays)
            if plays.nunique() > 1
            else None
        )
        reg = HistGradientBoostingRegressor(**kw).fit(played[features], played[TARGET])
        residual = played[TARGET].to_numpy(dtype=float) - reg.predict(played[features])
        sd = max(config.conditional_sd_floor, float(np.sqrt(np.mean(residual**2))))
        models[position.value] = (clf, reg, sd)
    return FittedC1(
        config=config,
        as_of=moment,
        past=past,
        models=models,
        b0=baselines.fit_b0(train, TARGET),
    )


def knowable_history(history: pd.DataFrame, season: str, *, before_gameweek: int) -> pd.DataFrame:
    """Prior seasons, and ``season`` up to ``before_gameweek``: what C1 is fitted on live.

    Selected by label, not by kickoff, so a row labelled as played but kicked off after the deadline
    reaches the feature build and fails its look-ahead check instead of being dropped unseen.
    """
    year = history["season"].map(season_start_year)
    current = season_start_year(season)
    keep = (year < current) | (
        (history["season"] == season) & (history["gameweek"] < before_gameweek)
    )
    return history[keep]


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
        ["player_code", "position", "team_id", "price"]
    ]
    rows = roster.merge(sides, on="team_id", how="inner")
    return rows.assign(season=season, gameweek=gameweek, **dict.fromkeys(ROLL_SRC, np.nan))


class Fitted(Protocol):
    """A forecaster fitted before a deadline, as :func:`forecast_with` and :class:`C1Predictor`
    use it: B0 on its training rows, the history it was fitted on, and a one-gameweek predict."""

    @property
    def past(self) -> pd.DataFrame: ...

    @property
    def b0(self) -> FittedBaseline: ...

    def predict(self, upcoming: pd.DataFrame) -> pd.DataFrame:
        """``player_code``, ``p_play``, ``mean_if_play`` and ``sd_if_play`` per player."""
        ...


def forecast(inputs: ForecastInputs, rules: GameRules, config: ForecastConfig) -> Forecast:
    """C1's forecast frame for the gameweek being decided, fitted on history before its cutoff."""
    return forecast_with(
        inputs, rules, config, MODEL_NAME, lambda past, cutoff: fit_as_of(past, cutoff, config.c1)
    )


def forecast_with(
    inputs: ForecastInputs,
    rules: GameRules,
    config: ForecastConfig,
    model: str,
    fit: Callable[[pd.DataFrame, pd.Timestamp], Fitted],
) -> Forecast:
    """The one-gameweek frame of a forecaster that predicts P(play) and points given play (C1, A,
    A_odds): fitted on the history knowable before the cutoff, scaled by availability news, with
    the two-state mixture's variance and its own B0 line."""
    gameweek, cutoff, _ = live.next_deadline(inputs.gameweeks, config, as_of=inputs.as_of)
    history = inputs.player_gameweek
    if history is None or history.empty:
        raise ColdStartError(f"{model} has no per-gameweek history to learn from")
    deadlines = inputs.gameweeks
    fit_gameweek = as_int(deadlines.loc[deadlines["deadline_time"] >= cutoff, "gameweek"].min())
    past = knowable_history(history, rules.season, before_gameweek=fit_gameweek)
    fitted = fit(past, cutoff)
    upcoming = upcoming_rows(inputs.players, inputs.fixtures, rules.season, gameweek)
    predicted = fitted.predict(upcoming).set_index("player_code")

    players = inputs.players[inputs.players["team_id"].notna()].reset_index(drop=True)
    identity = players[[c for c in IDENTITY_COLUMNS if c in players.columns]].assign(
        player_code=players["code"].map(as_int)
    )
    p_hist = identity["player_code"].map(predicted["p_play"]).fillna(0.0)  # no fixture: no play
    p = (p_hist * availability(players, config)).clip(0.0, 1.0)
    mu = identity["player_code"].map(predicted["mean_if_play"]).fillna(0.0)
    sd = identity["player_code"].map(predicted["sd_if_play"]).fillna(0.0)
    moments = [
        mixture_moments([(1.0 - pi, 0.0, 0.0), (pi, mi, si**2)])
        for pi, mi, si in zip(p, mu, sd, strict=True)
    ]
    mean = pd.Series([m for m, _ in moments], index=identity.index, dtype=float)
    spread = pd.Series([np.sqrt(v) for _, v in moments], index=identity.index, dtype=float)
    frame = identity.assign(
        xp_next=mean,
        xp_next_sd=spread,
        xp_horizon=mean,  # a one-gameweek horizon: C1 forecasts the gameweek being decided only
        xp_horizon_sd=spread,
        **{gameweek_column(gameweek): mean, gameweek_sd_column(gameweek): spread},
        start_probability=p.astype(float),
        p_no_appearance=(1.0 - p).astype(float),
        next_gameweek=gameweek,
        horizon_gameweeks=1,
        model=model,
    )
    return Forecast(
        frame=validate_forecast_frame(frame),
        model=model,
        fallback_reason=None,
        captain_line=price_position_line(fitted.b0),
    )


class C1Predictor:
    """C1 behind the walk-forward harness's interface: :meth:`fit_as_of`, then :meth:`predict`.

    ``fit_as_of`` is what the harness calls for the shipped champion today (``fit.fit_as_of``); C1
    fits on the raw history before the deadline, not the harness's feature rows, which carry no
    ``starts`` or ``bonus``. ``predict`` takes the harness's visible fold rows (one per player per
    fixture) and splits each player's gameweek forecast evenly over his fixture rows.
    """

    name = MODEL_NAME

    def __init__(self, config: ForecastConfig, rules: GameRules) -> None:
        self.config = config
        self.rules = rules
        self.fitted: Fitted | None = None
        self.season: str | None = None

    def _fit(self, past: pd.DataFrame, moment: pd.Timestamp) -> Fitted:
        return fit_as_of(past, moment, self.config.c1)

    def fit_as_of(
        self,
        history: pd.DataFrame,
        deadline: pd.Timestamp,
        *,
        training: pd.DataFrame | None = None,
        season: str,
    ) -> None:
        moment = utc_deadline(deadline)
        self.fitted = self._fit(history[history["kickoff_time"] < moment], moment)
        self.season = season

    def predict(self, features: pd.DataFrame) -> pd.Series:
        if self.fitted is None or self.season is None:
            raise RuntimeError("predict() called before fit_as_of()")
        past = self.fitted.past
        played = past.loc[past["season"] == self.season, "gameweek"]
        gameweek = as_int(played.max()) + 1 if not played.empty else 1
        team, opponent, home = (
            pd.to_numeric(features[c], errors="coerce")
            .astype("Float64")
            .to_numpy(float, na_value=np.nan)
            for c in (FIXTURE_TEAM, FIXTURE_OPPONENT, FIXTURE_AT_HOME)
        )
        upcoming = pd.DataFrame(
            {
                "player_code": features["player_code"].to_numpy(),
                "position": features["position"].to_numpy(),
                "price": features["price"].to_numpy(),
                "team_id": team,
                "opponent_team_id": opponent,
                # The harness strips fixture ids; a club pair stands in for one in the xG self-join.
                "fixture_id": np.minimum(team, opponent) * 1000 + np.maximum(team, opponent),
                "was_home": home,
                "season": self.season,
                "gameweek": gameweek,
                **dict.fromkeys(ROLL_SRC, np.nan),
            }
        )
        predicted = self.fitted.predict(upcoming).set_index("player_code")
        xp = predicted["p_play"] * predicted["mean_if_play"]
        codes = features["player_code"]
        per_fixture = codes.map(xp).fillna(0.0) / codes.map(codes.value_counts())
        return pd.Series(per_fixture.to_numpy(dtype=float), index=features.index)


__all__ = [
    "MODEL_NAME",
    "UPCOMING",
    "C1Predictor",
    "Fitted",
    "FittedC1",
    "build_features",
    "fit_as_of",
    "forecast",
    "forecast_with",
    "input_features",
    "knowable_history",
    "specs",
    "upcoming_rows",
    "utc_deadline",
]
