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

import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from fpl_dof.config.models import BacktestConfig, FeatureConfig, ForecastConfig
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
from fpl_dof.forecast.metrics import (
    MINUTES_BANDS,
    MetricSet,
    MinutesCalibration,
    PairedDelta,
    evaluate,
    evaluate_minutes,
    head_size_by_position,
    minutes_band,
    paired_deltas,
)
from fpl_dof.forecast.models import RATE_COMPONENTS, TeamStrengthModel
from fpl_dof.forecast.monolith import MonolithPredictor, gap_by_position, gap_statement, head_gap
from fpl_dof.forecast.xp_v1 import team_matches
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

MODEL_COLUMN = "predicted"
B0_COLUMN = "b0"
MEAN_COLUMN = "b_mean"
FORM_COLUMN = "b_form"

#: The shadow monolith's prediction (E10-S5, DL-53). A benchmark column and never an input to
#: anything: it is fitted, scored and reported, and no other stage of this project reads it.
MONOLITH_COLUMN = "monolith"

#: How hard each scored observation's fixture was, as a ratio to an even fixture (E9-S2).
#:
#: Attached **after** the predictions, from a team-strength model the harness fits for itself on the
#: same pre-deadline window. Deliberately not read off the graded predictor's own M2: a conditioning
#: variable taken from the model under test changes meaning whenever the model does, and the whole
#: purpose of the breakdown is to compare a fixture change against what came before it.
FIXTURE_DIFFICULTY_COLUMN = "fixture_difficulty_ratio"

#: M1's predicted probability of each minutes state, and the E0 haircut's, and what happened
#: (E10-S1, closing D-14). Named as a prefix per side so the two distributions can never be read
#: out of the wrong columns by a metric that takes them positionally.
MINUTES_PREFIX = "p_minutes_"
HAIRCUT_MINUTES_PREFIX = "p_minutes_haircut_"
OBSERVED_MINUTES_BAND = "observed_minutes_band"

#: What identifies *one ranking*: a season and a gameweek. The head-of-ranking metrics are computed
#: inside one of these and averaged across them, because the ranking a manager acts on is a single
#: gameweek's (E10-S2, DL-49).
RANKING_IDENTITY = ("season", "gameweek")


def minutes_columns(prefix: str) -> dict[str, str]:
    """Band -> the column holding its probability, for one side of the comparison."""
    return {band: f"{prefix}{band}" for band in MINUTES_BANDS}


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
    # Not an outcome and not a feature — an *identifier*, carried here because it is the only
    # list that reaches ``fit`` and not ``predict``. ``fixture_id`` runs 1..380 within a season, so
    # a training set spanning two seasons contains each fixture number twice, and the team-strength
    # model's per-match reconstruction needs the season to tell them apart (D-26). Stripped from
    # the predictor's view alongside everything else here, which is where it belongs: what a model
    # may learn from a season label is that 2024/25 scored differently, and that is a rule change,
    # not a footballer.
    "season",
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
    monolith: MetricSet
    """The shadow monolith (E10-S5). **A required field, not an optional extra**, because it always
    runs: a benchmark that a caller could omit is one that quietly stops being reported on the day
    somebody finds it inconvenient, and its whole purpose is to be reported on that day."""

    monolith_description: dict[str, object] = field(default_factory=dict)
    """What the monolith actually was — library, feature list, training rows, and whether it
    degraded. An inert benchmark reports a gap of zero, which reads as *no cost to explainability*
    and means *nothing was measured* (DP-15)."""

    top_n: int = 20
    """How deep the head is, carried so the report can say ``top-20`` in words rather than each
    reader having to look the configuration up beside the number."""

    warnings: tuple[str, ...] = field(default=())
    fixture_coverage: float = float("nan")
    """Share of scored observations whose fixture the harness could resolve. Anything below 1.0 is
    a population scored against league-average opposition, and it is reported rather than assumed
    away (DP-15)."""

    minutes_calibration: MinutesCalibration | None = None
    """M1 against the E0 status-flag haircut (E10-S1, closes D-14). ``None`` when the predictor has
    no minutes model to calibrate, which is an absence rather than a failure."""

    champion: str = "model"
    """The first entrant's id: what ``model`` measures and every pair is taken against."""

    strategies: Mapping[str, MetricSet] = field(default_factory=dict)
    """Every entrant, champion first, each measured against B0 on the same scored rows (MOD-08)."""

    training_windows: Mapping[str, str] = field(default_factory=dict)

    paired: Mapping[str, Mapping[str, PairedDelta]] = field(default_factory=dict)
    """Each challenger minus the champion, per gameweek, with a seeded bootstrap CI (MOD-08)."""

    not_graded: Mapping[str, str] = field(default_factory=dict)
    """Challenger id -> why it is not graded: its fit or prediction raised at a fold (D-32)."""

    def data_window(self) -> dict[str, object]:
        """The seasons and gameweeks graded: the same folds for every entrant."""
        first, last = self.folds[0], self.folds[-1]
        return {
            "seasons": sorted({fold.season for fold in self.folds}),
            "first": {"season": first.season, "gameweek": first.gameweek},
            "last": {"season": last.season, "gameweek": last.gameweek},
            "folds": len(self.folds),
        }

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

    @property
    def explainability_gap(self) -> float:
        """How much top-N precision the chain gives up to the monolith (E10-S5, DL-53).

        **Positive means the monolith is better and the chain is paying for its interpretability.**
        The sign is the finding, so it is defined in exactly one place —
        :func:`~fpl_dof.forecast.monolith.head_gap` — and read from there by everything that
        reports it.
        """
        return head_gap(self.model.top_n_precision, self.monolith.top_n_precision)

    @property
    def explainability_gap_by_position(self) -> dict[str, float]:
        """The same gap inside each position. E10 §0: a gap confined to forwards is not a gap."""
        return gap_by_position(
            self.model.top_n_precision_by_position, self.monolith.top_n_precision_by_position
        )

    def gap_statement(self) -> str:
        """The explainability trade in a sentence, for a human rather than for a JSON field."""
        return gap_statement(
            chain_precision=self.model.top_n_precision,
            monolith_precision=self.monolith.top_n_precision,
            chain_spearman=self.model.spearman,
            monolith_spearman=self.monolith.spearman,
            top_n=self.top_n,
            by_position=self.explainability_gap_by_position,
        )

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
            # E10-S5. Reported at the same level as the other benchmarks rather than nested under a
            # diagnostics key, because it is one: the question "what is this feature set worth to a
            # model nobody can interrogate" is asked of every run, permanently.
            "monolith": self.monolith.as_dict(),
            "explainability_gap": {
                "top_n_precision": (
                    None
                    if self.explainability_gap != self.explainability_gap
                    else round(self.explainability_gap, 5)
                ),
                "top_n_precision_by_position": {
                    position: (None if value != value else round(value, 5))
                    for position, value in self.explainability_gap_by_position.items()
                },
                "statement": self.gap_statement(),
                "monolith_model": dict(self.monolith_description),
                "never_promoted": (
                    "The monolith is a shadow benchmark. It does not reach optimise, the decision "
                    "layer or the published ranking, and never will without an explicit DP-10 "
                    "decision (E10-S5, DL-53)."
                ),
            },
            "beats_b0": self.beats_b0,
            "beats_model_free": self.beats_model_free,
            "fixture_coverage": (
                None if self.fixture_coverage != self.fixture_coverage else self.fixture_coverage
            ),
            "minutes_calibration": (
                None if self.minutes_calibration is None else self.minutes_calibration.as_dict()
            ),
            "verdict": self.verdict(),
            "warnings": list(self.warnings),
            "champion": self.champion,
            "data_window": self.data_window(),
            "strategies": {
                sid: {
                    "training_window": self.training_windows.get(sid),
                    "metrics": metrics.as_dict(),
                    "paired_vs_champion": (
                        None
                        if sid == self.champion
                        else {m: d.as_dict() for m, d in self.paired.get(sid, {}).items()}
                    ),
                }
                for sid, metrics in self.strategies.items()
            },
        }


class StrategyPredictor(Protocol):
    """What the harness needs from a strategy's forecaster (``Strategy.predictor``), and no more.

    A Protocol rather than a base class on purpose: the harness must be able to score anything,
    including a model that does not exist yet, without that model having to import the harness. It
    also means a two-method stub is a valid predictor, which is what makes the leakage tests
    possible.

    ``fit_as_of`` gets the entrant's history (already cut to its training window), the fold's
    deadline, the harness's training rows built from that same history and the season being
    predicted, so a forecaster that builds its own features (C1) fits on what the live run fits on.
    ``predict`` then scores the fold's visible rows, from which every outcome is stripped, for
    the fold's ``gameweek``: a fit is reused for ``backtest.refit_every_gameweeks`` folds, so the
    gameweek cannot be read off the fitted history.
    """

    def fit_as_of(
        self,
        history: pd.DataFrame,
        deadline: pd.Timestamp,
        *,
        training: pd.DataFrame | None = None,
        season: str,
    ) -> None: ...

    def predict(self, features: pd.DataFrame, *, gameweek: int) -> pd.Series: ...


#: Which seasons a strategy is fitted on and featured from (DL-89 item 4), as its registry entry
#: declares it.
TrainingWindow = Literal["current_season", "all_seasons"]


@dataclass(frozen=True, slots=True)
class Entrant:
    """One strategy the harness grades: its id, its forecaster and its training window."""

    id: str
    predictor: StrategyPredictor
    training_window: TrainingWindow = "all_seasons"
    features: FeatureConfig | None = None
    """Its own feature-store config, when a registry override changes the features it reads (F1);
    ``None`` reads the harness's. Without this an override on ``forecast.features`` would reach the
    predictor's fit but never the rows it is fitted and scored on."""


#: What a set of fold rows is built from: a training window and the JSON of the feature config
#: behind them (a config holds a dict, so it cannot key a mapping itself).
View = tuple[TrainingWindow, str]


def prediction_column(entrant_id: str) -> str:
    """The fold-frame column holding one entrant's prediction."""
    return f"{MODEL_COLUMN}_{entrant_id}"


def _place(
    values: pd.Series,
    rows: Mapping[View, pd.DataFrame],
    view: View,
    *,
    into: pd.DataFrame,
) -> np.ndarray:
    """``view``'s per-row values onto ``into`` (the harness's own rows), matched by player and
    fixture; a row the view lacks is NaN."""
    own = rows[view]
    if own is into:
        return values.to_numpy(dtype=float)
    keys = [key for key in ("player_code", "fixture_id") if key in own.columns]
    keyed = own[keys].assign(_value=values.to_numpy(dtype=float))
    return into[keys].merge(keyed, on=keys, how="left")["_value"].to_numpy(dtype=float)


def _window(frame: pd.DataFrame, window: TrainingWindow, season: str) -> pd.DataFrame:
    """``frame`` cut to what a strategy with ``window`` sees when it forecasts ``season``: live, a
    ``current_season`` strategy's per-gameweek history is the current season's alone."""
    return frame[frame["season"] == season] if window == "current_season" else frame


@runtime_checkable
class MinutesReporting(Protocol):
    """What a predictor must expose for its minutes model to be *calibrated* as well as scored.

    Separate from :class:`Predictor` and checked at runtime, because not every predictor has a
    minutes model — a baseline or a two-line leakage stub has none, and demanding one would make
    the harness unable to score exactly the objects it exists to score. A predictor that offers
    this gets a Brier score; one that does not gets silence rather than an invented number.

    ``long_play_minutes`` is here rather than in the harness's configuration because sixty is a
    **scoring rule**: the predictor already holds the rules it was built with, and the harness is
    not entitled to a second opinion about them (Invariant 2).
    """

    long_play_minutes: int

    def minutes_probabilities(self, features: pd.DataFrame) -> pd.DataFrame: ...


@runtime_checkable
class SquadShapeReporting(Protocol):
    """What a predictor must expose for its head-of-ranking metrics to be split per position.

    Same reasoning as :class:`MinutesReporting`: the squad composition is a **rule** the predictor
    already holds, and the harness is not entitled to a second opinion about it (Invariant 2). The
    harness decides what to do with it — how deep each position's head goes is a *metric* policy
    and lives in :func:`~fpl_dof.forecast.metrics.head_size_by_position` — but it is told the shape
    rather than assuming one. A predictor that has no squad rules gets an aggregate figure and no
    per-position split, which is an absence rather than an invented number.
    """

    squad_composition: Mapping[str, int]


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
    entrants: Sequence[Entrant],
    *,
    forecast_config: ForecastConfig,
    backtest_config: BacktestConfig,
    seasons: Sequence[str] | None = None,
    metrics: pd.DataFrame | None = None,
    workers: int = 1,
) -> BacktestResult:
    """Replay the seasons one deadline at a time, refitting at each step, for every entrant.

    **The first entrant is the champion**: ``model`` measures it against the harness's baselines
    (DL-21's verdict), and every other entrant is paired against it gameweek by gameweek (MOD-08).
    Every entrant is graded on the same folds and the same rows, so the pairs are paired.

    Each entrant walks in its own process, up to ``workers`` at once (ORC-09, ORC-06): its own
    folds, fits and predictions, and the champion's walk also fits the harness's benchmarks. The
    walks share nothing, so the result is the one ``workers=1`` gives in this process. A
    challenger whose fit or prediction raises at any fold is recorded in ``not_graded`` with the
    reason and the others are graded without it (D-32); the champion's failure raises
    :class:`ChampionNotGradedError`, naming why each was not graded, as there is nothing to pair
    against.

    Each entrant sees only its training window: a ``current_season`` strategy's features, training
    rows and fit are built from the fold's own season, as they are live (F3). A fold is graded only
    when every window holds ``minimum_training_matches`` played gameweeks, and only on the rows
    every entrant predicted.

    ``metrics`` is the conformed advanced table, passed straight through to the feature store. The
    harness does not filter it and must not: which of its rows are knowable at a deadline is a
    feature-store question, and answering it twice is how the two answers diverge.
    """
    if not entrants:
        raise ValueError("walk_forward needs at least one entrant: the champion")
    if len({entrant.id for entrant in entrants}) != len(entrants):
        raise ValueError(f"entrant ids repeat: {[entrant.id for entrant in entrants]}")
    if history.empty:
        raise ValueError("cannot backtest an empty history")

    frame = history.copy()
    if seasons:
        frame = frame[frame["season"].isin(seasons)]
    if frame.empty:
        raise ValueError(f"no history for seasons {list(seasons or ())}")

    champion = entrants[0]
    warnings: list[str] = []
    windows: frozenset[TrainingWindow] = frozenset(
        {"all_seasons", *(entrant.training_window for entrant in entrants)}
    )
    walks = _walks(
        frame,
        entrants,
        windows=windows,
        forecast_config=forecast_config,
        backtest_config=backtest_config,
        metrics=metrics,
        workers=workers,
    )
    champion_walk = walks[champion.id]
    if champion_walk.failure is not None:
        # Every metric is graded against the champion's folds and benchmarks, so nothing is.
        lost = f"no champion to compare against: {champion.id} {champion_walk.failure}"
        raise ChampionNotGradedError(
            {
                champion.id: champion_walk.failure,
                **{sid: w.failure or lost for sid, w in walks.items() if sid != champion.id},
            }
        )
    not_graded = {sid: walk.failure for sid, walk in walks.items() if walk.failure is not None}
    for sid, reason in not_graded.items():
        log.warning("backtest.not_graded", extra={"strategy": sid, "reason": reason})
    graded_entrants = [e for e in entrants if e.id not in not_graded]
    columns = {entrant.id: prediction_column(entrant.id) for entrant in graded_entrants}

    # The champion's fold frames carry the harness's columns; each challenger's predictions join
    # them by player and fixture, and only rows every entrant predicted are graded.
    joins = {entrant.id: walks[entrant.id].by_deadline for entrant in graded_entrants[1:]}
    folds: list[Fold] = []
    for fold in champion_walk.folds:
        merged = fold.predictions
        for entrant in graded_entrants[1:]:
            own = joins[entrant.id].get(fold.deadline)
            if own is None:
                merged = merged.assign(**{columns[entrant.id]: np.nan})
                continue
            keys = [key for key in own.columns if key != columns[entrant.id]]
            merged = merged.merge(own, on=keys, how="left")
        merged = merged.dropna(subset=list(columns.values())).reset_index(drop=True)
        if not merged.empty:
            folds.append(replace(fold, predictions=merged))

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

    degraded = champion_walk.monolith.get("degraded")
    if degraded is not None:
        # The last fold's monolith fell back to a constant, so the gap below is a statement about a
        # constant. Never silent: an inert benchmark reports *no cost to explainability*, which is
        # the most reassuring possible way to have measured nothing (DP-15, E10-S5).
        warnings.append(f"the shadow monolith degraded on the final fold: {degraded}")

    # Each position's head goes as deep as that position goes into a squad, when the predictor can
    # say what a squad is made of. Without it the aggregate still reports and the split is absent.
    predictor = champion.predictor
    head_sizes = (
        head_size_by_position(backtest_config.top_n_precision, predictor.squad_composition)
        if isinstance(predictor, SquadShapeReporting)
        else None
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
            # One gameweek is one ranking, and the head metrics are only meaningful inside one
            # (DL-49). Pooled across 72 folds they are pinned at zero for every model ever built.
            group=RANKING_IDENTITY,
            top_n_by_position=head_sizes,
        )

    # **Deliberately measured on every prediction, not on the scored subset.** The accuracy metrics
    # drop players who did not feature, because scoring a points forecast against a non-appearance
    # measures the minutes model twice. Minutes calibration is the exact opposite case: the rows
    # that were dropped are 60% of the population and they are *the* thing being calibrated. Score
    # M1 only where somebody played and every model looks superb, because the answer is always yes.
    measured = evaluate_minutes(
        predictions,
        model_columns=minutes_columns(MINUTES_PREFIX),
        baseline_columns=minutes_columns(HAIRCUT_MINUTES_PREFIX),
        observed_band=OBSERVED_MINUTES_BAND,
        baseline_name=baselines.STATUS_HAIRCUT_BASELINE,
    )
    calibration: MinutesCalibration | None = measured
    if measured.observations == 0:
        calibration = None
        warnings.append(
            "the predictor exposes no minutes distribution, so M1 calibration was not measured "
            "and `minutes_brier` stays null (D-14)"
        )

    # Each model is measured against the next-simpler thing, so the chain reads as a ladder:
    # the mean is the floor, B0 has to beat the mean, and the model has to beat B0.
    model_metrics = measure("model", MODEL_COLUMN, B0_COLUMN)
    if calibration is not None:
        # The field D-14 names, populated at last — with the three-way Brier over the whole
        # population rather than the appearance-only one, and said so here so nobody compares it
        # against a number computed the other way.
        model_metrics = replace(model_metrics, minutes_brier=calibration.brier)

    result = BacktestResult(
        folds=tuple(folds),
        predictions=predictions,
        model=model_metrics,
        b0=measure("B0 (price + position)", B0_COLUMN, MEAN_COLUMN),
        mean_baseline=measure("mean", MEAN_COLUMN, MEAN_COLUMN),
        model_free=measure("model-free (trailing 6)", FORM_COLUMN, B0_COLUMN),
        # Measured **against the chain**, so its MAE skill score reads directly as "how much better
        # than what we ship" rather than needing a subtraction the reader has to do themselves.
        # Every other row in the ladder is graded against the next-simpler thing; this one is graded
        # against the thing whose interpretability it exists to price.
        monolith=measure("monolith (shadow, GBM)", MONOLITH_COLUMN, MODEL_COLUMN),
        monolith_description=champion_walk.monolith,
        top_n=backtest_config.top_n_precision,
        warnings=tuple(warnings),
        fixture_coverage=resolved,
        minutes_calibration=calibration,
        champion=champion.id,
        not_graded=not_graded,
        strategies={
            champion.id: model_metrics,
            **{e.id: measure(e.id, columns[e.id], B0_COLUMN) for e in graded_entrants[1:]},
        },
        training_windows={e.id: e.training_window for e in graded_entrants},
        paired={
            e.id: paired_deltas(
                scored,
                champion=columns[champion.id],
                challenger=columns[e.id],
                actual=TARGET,
                top_n=backtest_config.top_n_precision,
                group=RANKING_IDENTITY,
                draws=backtest_config.bootstrap_draws,
                seed=backtest_config.bootstrap_seed,
            )
            for e in graded_entrants[1:]
        },
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
            "monolith_spearman": result.monolith.spearman,
            "explainability_gap": result.explainability_gap,
        },
    )
    return result


class ChampionNotGradedError(RuntimeError):
    """The champion's walk failed, so no strategy could be graded against it (D-32).

    ``reasons`` is strategy id -> why it was not graded, the champion's own first; the backtest
    stage still records them before it fails.
    """

    def __init__(self, reasons: Mapping[str, str]) -> None:
        self.reasons = dict(reasons)
        super().__init__("; ".join(f"{sid}: {why}" for sid, why in self.reasons.items()))


@dataclass(frozen=True, slots=True)
class _Walk:
    """One entrant's walk: its graded folds, or why it stopped."""

    folds: tuple[Fold, ...] = ()
    """The champion's carry every harness column; a challenger's only the keys and its own."""
    failure: str | None = None
    monolith: dict[str, object] = field(default_factory=dict)
    """The champion's: what the shadow monolith was on the last fold (E10-S5)."""

    @property
    def by_deadline(self) -> dict[pd.Timestamp, pd.DataFrame]:
        return {fold.deadline: fold.predictions for fold in self.folds}


def _walks(
    frame: pd.DataFrame,
    entrants: Sequence[Entrant],
    *,
    workers: int,
    **common: Any,
) -> dict[str, _Walk]:
    """Every entrant's walk, champion first, across up to ``workers`` processes (ORC-09 item 4).

    A walk shares nothing with another, so the walks are the ones a single process gives; an
    entrant whose walk raises, the champion included, is recorded with why (D-32), and one lost
    to a crashed worker is walked again here (:func:`run_isolated`).
    """
    calls = [
        partial(_walk_one, frame, entrant, harness=index == 0, **common)
        for index, entrant in enumerate(entrants)
    ]
    return {
        entrant.id: outcome
        if isinstance(outcome, _Walk)
        else _Walk(failure=f"its walk failed: {type(outcome).__name__}: {outcome}")
        for entrant, outcome in zip(entrants, run_isolated(calls, workers), strict=True)
    }


def run_isolated[T](calls: Sequence[Callable[[], T]], workers: int) -> list[T | Exception]:
    """Each call's result, or the exception it raised, in order, across up to ``workers``
    processes (ORC-09 item 4).

    A worker that dies outright (``BrokenProcessPool``: killed for memory, a native crash) breaks
    the pool, and every future still pending in it is lost, not only its own. Those calls are run
    again in this process, one at a time and once, so a crash costs no other job and never marks
    the champion failed blindly. With one worker everything runs here.
    """
    count = min(workers, os.process_cpu_count() or 1, len(calls))
    outcomes: dict[int, T | Exception] = {}
    if count > 1:
        with ProcessPoolExecutor(count) as pool:
            futures = [pool.submit(call) for call in calls]
            for index, future in enumerate(futures):
                try:
                    outcomes[index] = future.result()
                except BrokenProcessPool:
                    continue  # lost with the pool: run again below
                except Exception as exc:
                    outcomes[index] = exc
        if len(outcomes) < len(calls):
            log.warning("workers.lost", extra={"jobs": len(calls) - len(outcomes)})
    for index, call in enumerate(calls):
        if index not in outcomes:
            try:
                outcomes[index] = call()
            except Exception as exc:
                outcomes[index] = exc
    return [outcomes[index] for index in range(len(calls))]


def _walk_one(
    frame: pd.DataFrame,
    entrant: Entrant,
    *,
    harness: bool,
    windows: frozenset[TrainingWindow],
    forecast_config: ForecastConfig,
    backtest_config: BacktestConfig,
    metrics: pd.DataFrame | None,
) -> _Walk:
    """Walk one entrant over every deadline; with ``harness`` also fit the benchmarks on its folds.

    ``windows`` are every entrant's training windows: a fold is graded only when each holds
    ``minimum_training_matches`` played gameweeks, so every walk grades the same folds.
    """
    column = prediction_column(entrant.id)
    base: View = ("all_seasons", forecast_config.features.model_dump_json())
    features = entrant.features or forecast_config.features
    view: View = (entrant.training_window, features.model_dump_json())
    # ``all_seasons`` is always built: it is what is scored, and what the baselines are fitted on.
    feature_configs = {base: forecast_config.features, view: features}
    #: view -> deadline -> that deadline's feature/outcome rows. Built once, in order, and only ever
    #: read by folds strictly later than the key.
    caches: dict[View, dict[pd.Timestamp, pd.DataFrame]] = {v: {} for v in feature_configs}
    # E10-S5. Constructed here rather than passed in, for the same reason the baselines are: it is
    # not a model under test, it is part of what the harness reports, and a caller who could leave
    # it out is a caller who eventually does.
    monolith = MonolithPredictor(config=backtest_config.monolith, features=forecast_config.features)
    folds: list[Fold] = []
    graded = 0
    fitted_season: str | None = None

    for season, gameweek, deadline in deadlines_for(frame):
        past = frame[frame["kickoff_time"] < deadline]

        # Built and cached first, before any decision about whether this fold can be *scored*. An
        # early gameweek is not scoreable — there is nothing to have learned from — but it is still
        # evidence for every later fold, and skipping the cache would throw it away.
        rows: dict[View, pd.DataFrame] = {}
        for own, cache in caches.items():
            rows[own] = fold_rows(
                _window(frame, own[0], season),
                season,
                gameweek,
                deadline,
                forecast_config.model_copy(update={"features": feature_configs[own]}),
                metrics=metrics,
            )
            cache[deadline] = rows[own]
            assert_no_look_ahead(rows[own], past, as_of=deadline)
        # A copy, so the cached rows later folds train on carry no prediction of this one.
        merged = rows[base].copy()

        played = min(
            _window(past, window, season).groupby(["season", "gameweek"]).ngroups
            for window in windows
        )
        if played < backtest_config.minimum_training_matches:
            # Predicting from almost nothing measures the prior, not the model.
            continue

        training = {
            own: _window(training_rows(cache, before=deadline), own[0], season)
            for own, cache in caches.items()
        }
        if any(rows[v].empty or training[v].empty for v in caches):
            continue

        # Refitted every ``refit_every_gameweeks`` graded folds, and always at a new season, so a
        # ``current_season`` fit never predicts the next season.
        refit = graded % backtest_config.refit_every_gameweeks == 0 or season != fitted_season
        graded += 1
        fitted_season = season

        # **The outcome must never reach a predictor.** A fold frame carries everything that
        # happened in the gameweek, because the harness needs it to score with and the component
        # models need it to fit on; handing that frame to a model would let it read the answer. A
        # model doing so by accident — through a merge that pulled one column too many — would
        # produce a superb backtest and a worthless season, and nothing in the metrics would look
        # wrong. So predictors see inputs only.
        visible = {
            own: rows[own].drop(columns=list(OUTCOME_COLUMNS), errors="ignore") for own in rows
        }
        try:
            if refit:
                entrant.predictor.fit_as_of(
                    _window(frame, view[0], season),
                    deadline,
                    training=training[view],
                    season=season,
                )
            predicted = entrant.predictor.predict(visible[view], gameweek=gameweek)
        except Exception as exc:
            # D-32: one strategy's failure is its own; the others are graded without it.
            reason = f"its fit raised at {season} GW{gameweek}: {type(exc).__name__}: {exc}"
            return _Walk(failure=reason)
        merged[column] = _place(predicted, rows, view, into=merged)
        if not harness:
            keys = [key for key in ("player_code", "fixture_id") if key in merged.columns]
            fold = Fold(season, gameweek, deadline, len(training[view]), merged[[*keys, column]])
            folds.append(fold)
            continue
        merged[MODEL_COLUMN] = merged[column]

        # Refitted every fold on the same frame the chain was fitted on, and predicting on the same
        # stripped frame the chain saw. **Reusing the harness's own assembly is the look-ahead
        # guarantee** — a monolith with its own training-set construction would be a second chance
        # to leak, and a leaking benchmark reports a gap that is entirely its own (Invariant 5).
        all_training, all_visible = training[base], visible[base]
        monolith.fit(all_training)
        merged[MONOLITH_COLUMN] = monolith.predict(all_visible).to_numpy()

        b0 = baselines.fit_b0(all_training, TARGET)
        mean = baselines.fit_mean_baseline(all_training, TARGET)
        merged[B0_COLUMN] = b0.predict(all_visible).to_numpy()
        merged[MEAN_COLUMN] = mean.predict(all_visible).to_numpy()

        # Minutes calibration (E10-S1). Both distributions are computed from the champion's
        # *visible* frame, so the calibrated model is exactly the one that produced the prediction
        # above, and the observed band is attached afterwards from an outcome column the predictor
        # never saw.
        predictor = entrant.predictor
        if isinstance(predictor, MinutesReporting):
            predicted_minutes = predictor.minutes_probabilities(visible[view])
            haircut = baselines.status_flag_haircut_minutes(visible[view], forecast_config)
            for band in MINUTES_BANDS:
                merged[f"{MINUTES_PREFIX}{band}"] = _place(
                    predicted_minutes[band], rows, view, into=merged
                )
                merged[f"{HAIRCUT_MINUTES_PREFIX}{band}"] = _place(
                    haircut[band], rows, view, into=merged
                )
            merged[OBSERVED_MINUTES_BAND] = [
                minutes_band(value, predictor.long_play_minutes) for value in merged["minutes"]
            ]

        # Only rows the champion predicted here; each challenger's unpredicted rows drop as it
        # joins. Rebinds rather than mutates, so the cached frame later folds train on is untouched.
        merged = merged.dropna(subset=[column])
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
                training_rows=len(training[view]),
                predictions=merged,
            )
        )
    return _Walk(folds=tuple(folds), monolith=monolith.describe() if harness else {})


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
    "HAIRCUT_MINUTES_PREFIX",
    "MEAN_COLUMN",
    "MINUTES_PREFIX",
    "MODEL_COLUMN",
    "MONOLITH_COLUMN",
    "OBSERVED_MINUTES_BAND",
    "OUTCOME_COLUMNS",
    "RANKING_IDENTITY",
    "BacktestResult",
    "ChampionNotGradedError",
    "Entrant",
    "Fold",
    "MinutesReporting",
    "PairedDelta",
    "SquadShapeReporting",
    "StrategyPredictor",
    "TrainingWindow",
    "attach_fixtures",
    "deadlines_for",
    "fixture_calendar",
    "fixture_difficulty",
    "fold_rows",
    "minutes_columns",
    "prediction_column",
    "run_isolated",
    "training_rows",
    "walk_forward",
]
