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
from fpl_dof.forecast.features import (
    FIXTURE_AT_HOME,
    FIXTURE_OPPONENT,
    FIXTURE_TEAM,
    TARGET,
    LeakageError,
    assert_no_look_ahead,
    build_features,
)
from fpl_dof.forecast.metrics import MetricSet, evaluate
from fpl_dof.forecast.models import RATE_COMPONENTS, TeamStrengthModel
from fpl_dof.forecast.xp_v1 import team_matches
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

MODEL_COLUMN = "predicted"
B0_COLUMN = "b0"
MEAN_COLUMN = "b_mean"
FORM_COLUMN = "b_form"

#: How hard each scored observation's fixture was, as a ratio to an even fixture (E9-S2).
#:
#: Attached **after** the predictions, from a team-strength model the harness fits for itself on the
#: same pre-deadline window. Deliberately not read off the graded predictor's own M2: a conditioning
#: variable taken from the model under test changes meaning whenever the model does, and the whole
#: purpose of the breakdown is to compare a fixture change against what came before it.
FIXTURE_DIFFICULTY_COLUMN = "fixture_difficulty_ratio"

#: What actually happened in the gameweek a fold predicts. **Available to ``fit``, never to
#: ``predict``.**
#:
#: The distinction is the whole safety property. A component model is fitted on outcomes by
#: construction — that is what fitting is — and it must never see the outcome of the row it is
#: predicting. Naming the set once, here, is what lets ``walk_forward`` strip exactly it before
#: handing a frame to a predictor; the previous code stripped only the target and the minutes, and
#: the consequence was not a leak but its mirror image: the fold frame carried no raw statistic at
#: all, so ``RateModel.fit`` found none of its columns and every scoring rate in the backtest was
#: shrunk toward zero instead of toward a fitted position prior (D-24).
OUTCOME_COLUMNS: tuple[str, ...] = (
    TARGET,
    "minutes",
    "kickoff_time",
    "fixture_id",
    "team_id",
    "goals_conceded",
    # Expected goals are an outcome of the gameweek being predicted just as its actual goals are:
    # a component may be *fitted* on them but must never *see* the row it is predicting, so they
    # are carried into the fold frame and stripped from the predictor's view alongside everything
    # else here (ExpectedGoalsConfig, D-25). The rolling per-90 *features* built from earlier weeks
    # keep their own names and are unaffected by this strip.
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    *RATE_COMPONENTS,
)


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
    fixture_coverage: float = float("nan")
    """Share of scored observations whose fixture the harness could resolve. Anything below 1.0 is
    a population scored against league-average opposition, and it is reported rather than assumed
    away (DP-15)."""

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
            "fixture_coverage": (
                None if self.fixture_coverage != self.fixture_coverage else self.fixture_coverage
            ),
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
    metrics: pd.DataFrame | None = None,
) -> BacktestResult:
    """Replay the seasons one deadline at a time, refitting everything at each step.

    ``metrics`` is the conformed advanced table, passed straight through to the feature store. The
    harness does not filter it and must not: which of its rows are knowable at a deadline is a
    feature-store question, and answering it twice is how the two answers diverge.
    """
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
        merged = fold_rows(frame, season, gameweek, deadline, forecast_config, metrics=metrics)
        cache[deadline] = merged
        assert_no_look_ahead(merged, past, as_of=deadline)

        played_gameweeks = past.groupby(["season", "gameweek"]).ngroups
        if played_gameweeks < backtest_config.minimum_training_matches:
            # Predicting from almost nothing measures the prior, not the model.
            continue

        training = training_rows(cache, before=deadline)
        if merged.empty or training.empty:
            continue

        # **The outcome must never reach a predictor.** ``merged`` carries everything that
        # happened in the gameweek, because the harness needs it to score with and the component
        # models need it to fit on; handing that frame to a model would let it read the answer. A
        # model doing so by accident — through a merge that pulled one column too many — would
        # produce a superb backtest and a worthless season, and nothing in the metrics would look
        # wrong. So predictors see inputs only.
        visible = merged.drop(columns=list(OUTCOME_COLUMNS), errors="ignore")

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
        # Added after the prediction and after the rebinding merge above, so it reaches neither the
        # predictor's view nor the cached frame later folds train on. It conditions the report, it
        # is not an input to anything.
        merged[FIXTURE_DIFFICULTY_COLUMN] = fixture_difficulty(merged, past)
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

    resolved = (
        float(scored[FIXTURE_OPPONENT].notna().mean())
        if FIXTURE_OPPONENT in scored.columns and not scored.empty
        else 0.0
    )
    if resolved < 1.0:
        # Never silent. A harness that quietly reverts to league-average opposition reports
        # perfectly ordinary-looking numbers that mean something else entirely (DP-15).
        warnings.append(
            f"{(1 - resolved) * 100:.1f}% of scored observations carried no resolvable fixture "
            "and were predicted against league-average opposition"
        )

    def measure(name: str, predicted: str, baseline: str) -> MetricSet:
        return evaluate(
            scored,
            name=name,
            predicted=predicted,
            actual=TARGET,
            baseline=baseline,
            top_n=backtest_config.top_n_precision,
            captaincy_pool=backtest_config.captaincy_pool,
            fixture_difficulty=FIXTURE_DIFFICULTY_COLUMN,
            fixture_band_ratio=backtest_config.fixture_difficulty_band_ratio,
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
        fixture_coverage=resolved,
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
            "fixture_coverage": resolved,
        },
    )
    return result


def fold_rows(
    history: pd.DataFrame,
    season: str,
    gameweek: int,
    deadline: pd.Timestamp,
    config: ForecastConfig,
    *,
    metrics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Features as of ``deadline``, joined to what that gameweek actually produced.

    The unit both the training set and the evaluation set are made of. Building them the same way
    is the point of the feature store: if training rows and scoring rows were assembled by two bits
    of code, they would eventually disagree and nobody would notice.
    """
    past = history[history["kickoff_time"] < deadline]
    if past.empty:
        return pd.DataFrame()
    features = build_features(
        past, as_of=deadline, config=config.features, metrics=metrics, season=season
    )
    if features.empty:
        return pd.DataFrame()
    wanted = ["player_code", "position", "price", *OUTCOME_COLUMNS]
    outcomes = history[
        (history["season"] == season)
        & (history["gameweek"] == gameweek)
        & (history["kickoff_time"] >= deadline)
    ][[column for column in wanted if column in history.columns]]
    if outcomes.empty:
        return pd.DataFrame()
    merged = features.drop(columns=["price"], errors="ignore").merge(
        outcomes, on="player_code", how="inner"
    )
    return attach_fixtures(merged, history, season, gameweek)


def fixture_calendar(history: pd.DataFrame, season: str, gameweek: int) -> pd.DataFrame:
    """Who plays whom, and where, in one gameweek. A projection of the published calendar.

    Built from the archive's *fixture* columns only — never from whether a given player happens to
    have a row. The calendar is published weeks ahead and is genuinely knowable at the deadline;
    who was picked is not, and reading the second while claiming the first is exactly the shape of
    look-ahead Invariant 5 exists to prevent.

    Keyed on ``(team, fixture)`` rather than on ``(team, gameweek)`` because a double gameweek is
    two fixtures for the same club and the harness scores each of them against its own outcome.
    """
    empty = pd.DataFrame(
        columns=["_team_key", "_fixture_key", FIXTURE_TEAM, FIXTURE_OPPONENT, FIXTURE_AT_HOME]
    )
    needed = {"season", "gameweek", "team_id", "fixture_id", "opponent_team_id", "was_home"}
    if history.empty or not needed <= set(history.columns):
        return empty
    window = history[(history["season"] == season) & (history["gameweek"] == gameweek)]
    fixtures = window[["team_id", "fixture_id", "opponent_team_id", "was_home"]].dropna(
        subset=["team_id", "fixture_id", "opponent_team_id"]
    )
    if fixtures.empty:
        return empty
    calendar = pd.DataFrame(
        {
            "_team_key": _as_key(fixtures["team_id"]),
            "_fixture_key": _as_key(fixtures["fixture_id"]),
            FIXTURE_OPPONENT: _as_key(fixtures["opponent_team_id"]),
            FIXTURE_AT_HOME: fixtures["was_home"].astype("boolean"),
        }
    )
    calendar[FIXTURE_TEAM] = calendar["_team_key"]
    return calendar.drop_duplicates(subset=["_team_key", "_fixture_key"]).reset_index(drop=True)


def attach_fixtures(
    merged: pd.DataFrame, history: pd.DataFrame, season: str, gameweek: int
) -> pd.DataFrame:
    """Give every fold row the fixture it was played under, or a stated absence.

    The fixture columns are aliases rather than the outcome's own ``team_id`` and ``fixture_id``.
    Those two stay in :data:`OUTCOME_COLUMNS` and stay stripped: a naive read of a fold row cannot
    tell that ``team_id`` came from the calendar rather than from the result, and the test that
    asserts no outcome column reaches a prediction is worth more than the one column it costs.
    """
    calendar = fixture_calendar(history, season, gameweek)
    if merged.empty or calendar.empty or not {"team_id", "fixture_id"} <= set(merged.columns):
        merged = merged.copy()
        merged[FIXTURE_TEAM] = pd.Series(pd.NA, index=merged.index, dtype="Int64")
        merged[FIXTURE_OPPONENT] = pd.Series(pd.NA, index=merged.index, dtype="Int64")
        merged[FIXTURE_AT_HOME] = pd.Series(pd.NA, index=merged.index, dtype="boolean")
        return merged

    keyed = merged.copy()
    keyed["_team_key"] = _as_key(keyed["team_id"])
    keyed["_fixture_key"] = _as_key(keyed["fixture_id"])
    joined = keyed.merge(calendar, on=["_team_key", "_fixture_key"], how="left")
    return joined.drop(columns=["_team_key", "_fixture_key"])


def fixture_difficulty(merged: pd.DataFrame, past: pd.DataFrame) -> pd.Series:
    """How hard each row's fixture looked *at the deadline*, from pre-deadline evidence only.

    A team-strength model fitted here rather than borrowed from the predictor. Borrowing would be
    cheaper and would make the band mean "where this model thought the fixture was hard", which
    changes with every model change and so cannot compare one to the next — which is the only thing
    a fixture-conditioned breakdown is for (E9-S2, the gate E11 rests on).

    Rows with no resolvable fixture get NaN, and :func:`~fpl_dof.forecast.metrics.evaluate` bands
    them as ``unresolved`` rather than dropping them.
    """
    if merged.empty:
        return pd.Series(dtype=float)
    if not {FIXTURE_TEAM, FIXTURE_OPPONENT, FIXTURE_AT_HOME} <= set(merged.columns):
        return pd.Series(float("nan"), index=merged.index, dtype=float)
    strength = TeamStrengthModel().fit(team_matches(past))
    values = [
        float("nan")
        if pd.isna(team) or pd.isna(opponent) or pd.isna(at_home)
        else strength.fixture_difficulty_ratio(int(team), int(opponent), at_home=bool(at_home))
        for team, opponent, at_home in zip(
            merged[FIXTURE_TEAM],
            merged[FIXTURE_OPPONENT],
            merged[FIXTURE_AT_HOME],
            strict=True,
        )
    ]
    return pd.Series(values, index=merged.index, dtype=float)


def _as_key(values: pd.Series) -> pd.Series:
    """A nullable integer join key. Merging int64 against float64 is an error, not a coercion."""
    return pd.to_numeric(values, errors="coerce").astype("Int64")


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
    "FIXTURE_DIFFICULTY_COLUMN",
    "FORM_COLUMN",
    "MEAN_COLUMN",
    "MODEL_COLUMN",
    "OUTCOME_COLUMNS",
    "BacktestResult",
    "Fold",
    "Predictor",
    "attach_fixtures",
    "deadlines_for",
    "fixture_calendar",
    "fixture_difficulty",
    "fold_rows",
    "training_rows",
    "walk_forward",
]
