"""One forecast-fitting interface (PIPE-13).

Keeps prediction and decision apart (DP-02):
- ``fit_as_of(history, deadline, config, rules) -> FittedForecastModel`` with ``.predict(window)``
- Produces identical predictions across live, backtest and replay.
- B0 is fitted on the same training window and kept on the fitted model (``b0``); the factory
  hands it to the captain policy as its own input, never as a forecast column (DL-76, MOD-02).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast import baselines
from fpl_dof.forecast.backtest import deadlines_for, fold_rows, training_rows
from fpl_dof.forecast.baselines import FittedBaseline
from fpl_dof.forecast.features import TARGET, build_features
from fpl_dof.forecast.horizon import (
    fixture_index_from_fixtures,
    fixture_index_from_history,
    horizon_frame,
)
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.models import (
    ComponentModels,
    fit_components,
)
from fpl_dof.forecast.xp_v0 import confidence_tier
from fpl_dof.forecast.xp_v1 import (
    MODEL_NAME,
    league_average_opposition,
    row_opposition,
    score_player,
    team_matches,
)
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import GameRules

log = get_logger(__name__)

#: Columns copied from the published player record onto every forecast row.
IDENTITY_COLUMNS = (
    "player_id",
    "web_name",
    "full_name",
    "position",
    "team_id",
    "price",
    "status",
    "news",
    "selected_by_percent",
    "chance_of_playing_next_round",
)


class ColdStartError(RuntimeError):
    """Too little current-season history for the component chain to be fitted."""


def training_set(
    history: pd.DataFrame, deadline: pd.Timestamp, config: ForecastConfig
) -> pd.DataFrame:
    """Every (player, gameweek) outcome knowable at the deadline, with its features."""
    cache: dict[pd.Timestamp, pd.DataFrame] = {}
    for season, gameweek, moment in deadlines_for(history):
        if moment >= deadline:
            continue
        cache[moment] = fold_rows(history, season, gameweek, moment, config)
    training = training_rows(cache, before=deadline)
    if training.empty:
        raise ColdStartError(
            "no completed gameweek has both features and outcomes before the deadline"
        )
    return training


def availability(players: pd.DataFrame, config: ForecastConfig) -> pd.Series:
    """Each player's availability this week: the stated chance of playing, else the status flag's
    multiplier. What scales P(play) in every forecaster, so the news reaches each the same way."""
    flagged = pd.to_numeric(players["status"].map(config.status_multiplier), errors="coerce")
    stated = pd.to_numeric(players["chance_of_playing_next_round"], errors="coerce") / 100.0
    return stated.where(stated.notna(), flagged.fillna(0.0)).astype(float).clip(0.0, 1.0)


def _identity(players: pd.DataFrame, config: ForecastConfig) -> pd.DataFrame:
    """The published player record, indexed by ``player_code``, plus availability and confidence."""
    frame = players.copy()
    frame["player_code"] = frame["code"].map(as_int)
    frame["availability"] = availability(frame, config)

    columns = [column for column in IDENTITY_COLUMNS if column in frame.columns]
    identity = frame[["player_code", *columns, "availability"]].drop_duplicates("player_code")
    return identity.set_index("player_code")


def _unseen_players(
    features: pd.DataFrame,
    identity: pd.DataFrame,
    *,
    deadline: pd.Timestamp,
    config: ForecastConfig,
) -> pd.DataFrame:
    """Empty feature rows for players with no minutes yet, so each model returns its prior."""
    seen = set(features["player_code"])
    missing = [code for code in identity.index if as_int(code) not in seen]
    if not missing:
        return pd.DataFrame()
    rows = [
        {
            "player_code": as_int(code),
            "as_of": deadline,
            "position": str(identity.loc[code, "position"]),
            "matches_observed": 0,
            "appearance_rate": 0.0,
            "evidence_minutes": 0.0,
            **{f"minutes_mean_last{window}": 0.0 for window in config.features.rolling_windows},
        }
        for code in missing
    ]
    return pd.DataFrame(rows)


def _features(
    past: pd.DataFrame,
    identity: pd.DataFrame,
    *,
    deadline: pd.Timestamp,
    season: str,
    inputs: ForecastInputs,
    config: ForecastConfig,
) -> pd.DataFrame:
    """The feature store's view of every player, including those it has never seen."""
    features = build_features(
        past,
        as_of=deadline,
        config=config.features,
        positions=past[["player_code", "position"]],
        metrics=inputs.metrics,
        season=season,
    )
    if features.empty:
        raise ColdStartError(f"no feature row could be built at {deadline:%Y-%m-%d}")

    minutes = past.groupby("player_code")["minutes"].sum()
    features["evidence_minutes"] = features["player_code"].map(minutes).astype(float).fillna(0.0)
    completed = _unseen_players(features, identity, deadline=deadline, config=config)
    if not completed.empty:
        features = pd.concat([features, completed], ignore_index=True)
    features["confidence"] = confidence_tier(features["evidence_minutes"], config)
    return features


@dataclass(frozen=True, slots=True)
class FittedForecastModel:
    """The fitted component chain and baselines as of a specific deadline."""

    models: ComponentModels
    b0: FittedBaseline
    b_mean: FittedBaseline
    config: ForecastConfig
    rules: GameRules
    deadline: pd.Timestamp
    training: pd.DataFrame
    past: pd.DataFrame

    def predict(
        self,
        window: Sequence[int] | pd.DataFrame | int,
        *,
        inputs: ForecastInputs | None = None,
        history: pd.DataFrame | None = None,
        season: str | None = None,
    ) -> Any:
        """Predict expected points across the requested window or feature set."""
        if isinstance(window, pd.DataFrame):
            return self._predict_features(window)
        if inputs is not None:
            return self._predict_live(window, inputs)
        if history is not None:
            return self._predict_replay(window, history, season)
        raise ValueError(
            "predict() requires either a DataFrame of visible features, "
            "inputs=ForecastInputs, or history=DataFrame"
        )

    def _predict_features(self, features: pd.DataFrame) -> pd.Series:
        default = league_average_opposition(self.models)
        predictions = []
        unresolved = 0
        for _, row in features.iterrows():
            opposition = row_opposition(self.models, row)
            if opposition is None:
                unresolved += 1
                opposition = default
            forecast = score_player(
                row,
                self.models,
                self.rules,
                self.config,
                opposition=opposition,
            )
            predictions.append(forecast.expected_points)
        if unresolved:
            log.info(
                "xp_v1.league_average_fallback",
                extra={"rows": len(features), "unresolved": unresolved},
            )
        return pd.Series(predictions, index=features.index, dtype=float)

    def _predict_live(self, window: Sequence[int] | int, inputs: ForecastInputs) -> pd.DataFrame:
        horizon = [window] if isinstance(window, int) else list(window)
        identity = _identity(inputs.players, self.config)
        features = _features(
            self.past,
            identity,
            deadline=self.deadline,
            season=self.rules.season,
            inputs=inputs,
            config=self.config,
        )
        identity["confidence"] = (
            features.set_index("player_code")["confidence"].reindex(identity.index).fillna("none")
        )

        frame = horizon_frame(
            features,
            identity=identity,
            horizon=horizon,
            fixtures=fixture_index_from_fixtures(inputs.fixtures, horizon),
            models=self.models,
            rules=self.rules,
            config=self.config,
            status_multipliers=dict(identity["availability"]),
            discount=self.config.horizon_discount,
        )
        if frame.empty:
            raise ColdStartError("no player could be scored from the component chain")

        frame["start_probability"] = (
            1.0 - frame["p_no_appearance"].astype(float).clip(0.0, 1.0)
        ).clip(0.0, 1.0)
        frame["next_gameweek"] = horizon[0]
        frame["horizon_gameweeks"] = len(horizon)
        frame.attrs["component_description"] = self.models.describe()

        log.info(
            "forecast.built",
            extra={
                "model": MODEL_NAME,
                "players": len(frame),
                "next_gameweek": horizon[0],
                "horizon": len(horizon),
                "mean_xp_next": round(float(frame["xp_next"].mean()), 3),
            },
        )
        return frame

    def _predict_replay(
        self,
        window: Sequence[int] | int,
        history: pd.DataFrame,
        season: str | None,
    ) -> pd.DataFrame:
        horizon = [window] if isinstance(window, int) else list(window)
        target_season = season or self.rules.season
        # One season only: the replayed pool and its rolling features never span a season break.
        past = self.past[self.past["season"] == target_season]
        identity = (
            past.sort_values("kickoff_time")
            .groupby("player_code")
            .last()[["web_name", "position", "team_id", "price"]]
        )
        identity = identity.assign(
            player_id=identity.index,
            status="a",
            chance_of_playing_next_round=None,
            news="",
            selected_by_percent=0.0,
            start_probability=1.0,
            start_floor=0.0,
            confidence="medium",
        )
        features = build_features(
            past,
            as_of=self.deadline,
            config=self.config.features,
            positions=past[["player_code", "position"]],
        )
        if features.empty:
            raise ColdStartError(f"no features could be built at {self.deadline}")

        frame = horizon_frame(
            features,
            identity=identity,
            horizon=horizon,
            fixtures=fixture_index_from_history(history, target_season, horizon),
            models=self.models,
            rules=self.rules,
            config=self.config,
        )
        if frame.empty:
            raise ColdStartError(f"no player could be forecast at {self.deadline}")
        frame["start_probability"] = (
            1.0 - frame["p_no_appearance"].astype(float).clip(0.0, 1.0)
        ).clip(0.0, 1.0)
        frame["next_gameweek"] = horizon[0]
        frame["horizon_gameweeks"] = len(horizon)
        return frame


def fit_as_of(
    history: pd.DataFrame | None,
    deadline: pd.Timestamp | dt.datetime,
    config: ForecastConfig,
    rules: GameRules,
    *,
    training: pd.DataFrame | None = None,
    season: str | None = None,
) -> FittedForecastModel:
    """Fit the component models and baselines on history knowable strictly before deadline.

    ``season`` is the season being forecast: the current one live, the replayed or backtested one
    otherwise. Its own rows are the only ones team strength is fitted on (see below).
    """
    if history is None or history.empty:
        raise ColdStartError("no per-gameweek history: the component chain has nothing to fit")

    deadline_ts = pd.Timestamp(deadline)
    if deadline_ts.tzinfo is None:
        deadline_ts = deadline_ts.tz_localize("UTC")
    else:
        deadline_ts = deadline_ts.tz_convert("UTC")

    past = history[history["kickoff_time"] < deadline_ts]
    if past.empty:
        raise ColdStartError(f"no gameweek has kicked off before {deadline_ts:%Y-%m-%d}")

    if training is None:
        training = training_set(history, deadline_ts, config)

    # Team strength is fitted on the forecast season only, and deliberately (REM-08). Club ids
    # come in two spaces: the live feed's season-local id and the archive's stable club code
    # (D-26). Within one season they agree; across the boundary a number names a different club,
    # so pooling would rate this season's clubs on another club's results. Before a season's first
    # kickoff that leaves no matches, and team strength is league average, as it always was.
    # Widening M2 to prior seasons is a model change, and needs DP-08's evidence.
    season_past = past[past["season"] == (season or rules.season)]
    matches = team_matches(season_past, use_xg=config.expected_goals.team_strength_from_xg)

    models = fit_components(training, matches, config, rules)
    b0 = baselines.fit_b0(training, TARGET)
    b_mean = baselines.fit_mean_baseline(training, TARGET)

    return FittedForecastModel(
        models=models,
        b0=b0,
        b_mean=b_mean,
        config=config,
        rules=rules,
        deadline=deadline_ts,
        training=training,
        past=past,
    )
