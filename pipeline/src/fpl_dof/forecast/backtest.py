"""Walk-forward backtesting. E3-S1, and the story E3 says to do first.

**Measurement before modelling.** Building the harness first means every subsequent change is
evaluated rather than assumed, and it forecloses the most common failure in a project like this: a
season spent improving a model that was never better than the simple thing it replaced.

How the walk works. For each historical deadline, in order:

1. Build features from matches that **finished strictly before** that deadline.
2. Fit the model and every baseline on that same window — refitting each time, because a model
   fitted once on everything and evaluated on part of it has seen the future.
3. Predict the gameweek.
4. Compare against what happened.

The refit is the expensive part and it is not optional. Fitting once and slicing is faster, gives
better-looking numbers, and measures nothing.

**This repays D-01**, the knowingly unvalidated GW1 model. Until it runs, nobody knows whether the
forecast has any edge, which means no expensive decision — an -8 hit, a chip, a wildcard — is safe
to base on it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from fpl_dof.config.models import BacktestConfig, ForecastConfig
from fpl_dof.forecast import baselines
from fpl_dof.forecast.features import TARGET, LeakageError, assert_no_look_ahead, build_features
from fpl_dof.forecast.metrics import MetricSet, evaluate
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

MODEL_COLUMN = "predicted"
B0_COLUMN = "b0"
MEAN_COLUMN = "b_mean"
FORM_COLUMN = "b_form"


@dataclass(frozen=True, slots=True)
class Fold:
    """One deadline's worth of walk-forward evidence."""

    season: str
    gameweek: int
    deadline: pd.Timestamp
    training_rows: int
    predictions: pd.DataFrame


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Everything the backtest measured, and the verdict it implies."""

    folds: tuple[Fold, ...]
    predictions: pd.DataFrame
    model: MetricSet
    b0: MetricSet
    mean_baseline: MetricSet
    model_free: MetricSet
    warnings: tuple[str, ...] = field(default=())

    @property
    def beats_b0(self) -> bool:
        """Does the forecast add anything beyond price and position?"""
        return bool(self.model.mae_skill_score > 0 and self.model.spearman > self.b0.spearman)

    @property
    def beats_model_free(self) -> bool:
        """The bar that matters: better than what an unaided manager does.

        Compared on rank correlation rather than MAE, because the model-free benchmark predicts a
        *rate* rather than a points total — comparing their absolute errors would penalise it for
        being on a different scale rather than for being less informative.
        """
        return bool(self.model.spearman > self.model_free.spearman)

    def verdict(self) -> str:
        """The headline, written to be reportable as a finding rather than tuned away."""
        if not self.beats_b0:
            return (
                "The forecast does not beat B0. It is an expensive restatement of price and "
                "position, and no decision should be based on it that price alone would not "
                "justify."
            )
        if not self.beats_model_free:
            return (
                "The forecast beats B0 but not the model-free benchmark. It knows more than "
                "price, and still less than picking the last six gameweeks' top scorers. This is "
                "the finding, not a number to tune."
            )
        return (
            "The forecast beats both B0 and the model-free benchmark. The margin over the "
            "model-free benchmark is the honest measure of what this project adds."
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "folds": len(self.folds),
            "observations": len(self.predictions),
            "model": self.model.as_dict(),
            "b0": self.b0.as_dict(),
            "mean_baseline": self.mean_baseline.as_dict(),
            "model_free": self.model_free.as_dict(),
            "beats_b0": self.beats_b0,
            "beats_model_free": self.beats_model_free,
            "verdict": self.verdict(),
            "warnings": list(self.warnings),
        }


class Predictor(Protocol):
    """What the harness needs from a model, and nothing more.

    A Protocol rather than a base class on purpose: the harness must be able to score anything,
    including a model that does not exist yet, without that model having to import the harness. It
    also means a two-line stub is a valid predictor, which is what makes the leakage tests possible.
    """

    def fit(self, training: pd.DataFrame) -> None: ...

    def predict(self, features: pd.DataFrame) -> pd.Series: ...


def deadlines_for(history: pd.DataFrame) -> list[tuple[str, int, pd.Timestamp]]:
    """Every (season, gameweek) with its effective deadline, ordered.

    The deadline is taken as the **earliest kickoff** in the gameweek. FPL's published deadline is
    up to ninety minutes before it, so this is a slightly conservative boundary — which is the
    right direction to be wrong in, because it can only exclude information, never admit it.
    """
    if history.empty:
        return []
    grouped = (
        history.dropna(subset=["kickoff_time"])
        .groupby(["season", "gameweek"])["kickoff_time"]
        .min()
        .reset_index()
        .sort_values("kickoff_time")
    )
    return [
        (str(row.season), as_int(row.gameweek), pd.Timestamp(str(row.kickoff_time)))
        for row in grouped.itertuples()
    ]


def walk_forward(
    history: pd.DataFrame,
    predictor: Predictor,
    *,
    forecast_config: ForecastConfig,
    backtest_config: BacktestConfig,
    seasons: Sequence[str] | None = None,
) -> BacktestResult:
    """Replay the seasons one deadline at a time, refitting everything at each step."""
    if history.empty:
        raise ValueError("cannot backtest an empty history")

    frame = history.copy()
    if seasons:
        frame = frame[frame["season"].isin(seasons)]
    if frame.empty:
        raise ValueError(f"no history for seasons {list(seasons or ())}")

    warnings: list[str] = []
    folds: list[Fold] = []
    schedule = deadlines_for(frame)
    #: deadline -> that deadline's feature/outcome rows. Built once, in order, and only ever read
    #: by folds strictly later than the key.
    cache: dict[pd.Timestamp, pd.DataFrame] = {}

    for season, gameweek, deadline in schedule:
        past = frame[frame["kickoff_time"] < deadline]

        # Built and cached first, before any decision about whether this fold can be *scored*. An
        # early gameweek is not scoreable — there is nothing to have learned from — but it is still
        # evidence for every later fold, and skipping the cache would throw it away.
        merged = fold_rows(frame, season, gameweek, deadline, forecast_config)
        cache[deadline] = merged
        assert_no_look_ahead(merged, past, as_of=deadline)

        played_gameweeks = past.groupby(["season", "gameweek"]).ngroups
        if played_gameweeks < backtest_config.minimum_training_matches:
            # Predicting from almost nothing measures the prior, not the model.
            continue

        training = training_rows(cache, before=deadline)
        if merged.empty or training.empty:
            continue

        # **The outcome must never reach a predictor.** ``merged`` carries the target and the
        # minutes actually played, because the harness needs them to score with; handing that frame
        # to a model would let it read the answer. A model doing so by accident — through a merge
        # that pulled one column too many — would produce a superb backtest and a worthless season,
        # and nothing in the metrics would look wrong. So predictors see inputs only.
        visible = merged.drop(columns=[TARGET, "minutes"], errors="ignore")

        predictor.fit(training)
        merged[MODEL_COLUMN] = predictor.predict(visible).to_numpy()

        b0 = baselines.fit_b0(training, TARGET)
        mean = baselines.fit_mean_baseline(training, TARGET)
        merged[B0_COLUMN] = b0.predict(visible).to_numpy()
        merged[MEAN_COLUMN] = mean.predict(visible).to_numpy()

        form = baselines.trailing_form_prediction(past, as_of=deadline)
        merged = merged.merge(
            form.rename(columns={"prediction": FORM_COLUMN}), on="player_code", how="left"
        )

        merged["season"] = season
        merged["gameweek"] = gameweek
        merged["played"] = (merged["minutes"] > 0).astype(float)
        folds.append(
            Fold(
                season=season,
                gameweek=gameweek,
                deadline=deadline,
                training_rows=len(training),
                predictions=merged,
            )
        )

    if not folds:
        raise ValueError(
            "no gameweek had enough prior history to score; the backtest measured nothing, which "
            "is a different situation from measuring a poor model"
        )

    predictions = pd.concat([fold.predictions for fold in folds], ignore_index=True)
    scored = predictions[predictions["minutes"] >= backtest_config.minimum_minutes_for_scoring]
    if scored.empty:
        warnings.append("no player met the minutes threshold; metrics fall back to all rows")
        scored = predictions

    def measure(name: str, predicted: str, baseline: str) -> MetricSet:
        return evaluate(
            scored,
            name=name,
            predicted=predicted,
            actual=TARGET,
            baseline=baseline,
            top_n=backtest_config.top_n_precision,
            captaincy_pool=backtest_config.captaincy_pool,
        )

    # Each model is measured against the next-simpler thing, so the chain reads as a ladder:
    # the mean is the floor, B0 has to beat the mean, and the model has to beat B0.
    result = BacktestResult(
        folds=tuple(folds),
        predictions=predictions,
        model=measure("model", MODEL_COLUMN, B0_COLUMN),
        b0=measure("B0 (price + position)", B0_COLUMN, MEAN_COLUMN),
        mean_baseline=measure("mean", MEAN_COLUMN, MEAN_COLUMN),
        model_free=measure("model-free (trailing 6)", FORM_COLUMN, B0_COLUMN),
        warnings=tuple(warnings),
    )

    log.info(
        "backtest.done",
        extra={
            "folds": len(folds),
            "observations": len(scored),
            "model_spearman": result.model.spearman,
            "b0_spearman": result.b0.spearman,
            "model_free_spearman": result.model_free.spearman,
            "beats_b0": result.beats_b0,
            "beats_model_free": result.beats_model_free,
        },
    )
    return result


def fold_rows(
    history: pd.DataFrame,
    season: str,
    gameweek: int,
    deadline: pd.Timestamp,
    config: ForecastConfig,
) -> pd.DataFrame:
    """Features as of ``deadline``, joined to what that gameweek actually produced.

    The unit both the training set and the evaluation set are made of. Building them the same way
    is the point of the feature store: if training rows and scoring rows were assembled by two bits
    of code, they would eventually disagree and nobody would notice.
    """
    past = history[history["kickoff_time"] < deadline]
    if past.empty:
        return pd.DataFrame()
    features = build_features(past, as_of=deadline, config=config.features)
    if features.empty:
        return pd.DataFrame()
    outcomes = history[
        (history["season"] == season)
        & (history["gameweek"] == gameweek)
        & (history["kickoff_time"] >= deadline)
    ][["player_code", "position", "price", TARGET, "minutes"]]
    if outcomes.empty:
        return pd.DataFrame()
    return features.drop(columns=["price"], errors="ignore").merge(
        outcomes, on="player_code", how="inner"
    )


def training_rows(
    cache: dict[pd.Timestamp, pd.DataFrame],
    *,
    before: pd.Timestamp,
) -> pd.DataFrame:
    """Every (player, gameweek) outcome that was already known at ``before``, with its features.

    Assembled from a cache **keyed on the deadline**, which is the only key that is safe: a fold's
    rows depend on nothing but its own deadline, so two folds asking for the same deadline must get
    the same answer. Rebuilding them per fold instead is O(n^2) in the number of gameweeks and, at
    four seasons, turns a minute into an hour.

    Any other cache key would be a leak waiting to happen, which is why the deadline is also what
    the assertion below re-checks.
    """
    rows = [frame for stamp, frame in cache.items() if stamp < before and not frame.empty]
    if not rows:
        return pd.DataFrame()
    training = pd.concat(rows, ignore_index=True)

    # Belt and braces: nothing in the training set may come from at or after the fold's deadline.
    if "as_of" in training.columns:
        late = training[pd.to_datetime(training["as_of"], utc=True) >= before]
        if not late.empty:
            raise LeakageError(
                f"{len(late)} training rows are stamped at or after the fold deadline {before}"
            )
    return training


__all__ = [
    "B0_COLUMN",
    "FORM_COLUMN",
    "MEAN_COLUMN",
    "MODEL_COLUMN",
    "BacktestResult",
    "Fold",
    "Predictor",
    "deadlines_for",
    "fold_rows",
    "training_rows",
    "walk_forward",
]
