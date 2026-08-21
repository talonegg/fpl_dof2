"""The shadow monolith: what this feature set is worth to a model you cannot argue with.

E10-S5. **A benchmark, permanently, and never a candidate.** Nothing here may reach `optimise`, the
decision layer or the published ranking — not pending a gate, not behind a flag that a future
promotion review could flip. There is no flag. The epic is explicit that a monolith is *"never
promoted over the chain without an explicit DP-10 decision"*, and a switch that exists is a switch
somebody eventually throws.

**Why it exists at all.** [DP-10](../../../../docs/DESIGN-PRINCIPLES.md) says to prefer the
formulation you can argue with *where two designs are close in expected quality* — and it says so in
the same breath as "unless the monolith is materially better, and if it is, that trade-off is a
recorded decision (Q-04)". Both halves of that sentence require a number. Without one, "the
component chain is interpretable and about as accurate" is an article of faith: a thing the project
believes because it would be inconvenient not to. This module makes it a measurement that is taken
again on every backtest run, and that can therefore change its mind.

**What makes the comparison fair, and what makes it a ceiling rather than a rival.**

* **The same feature set.** The monolith reads exactly the columns
  :func:`~fpl_dof.forecast.features.input_features` declares, and nothing else. Not a richer
  hand-engineered set: the question is what is achievable *on this data*, so a monolith that won by
  being given more would answer a different and much less useful one — it would measure the feature
  store, not the formulation.
* **The same folds, the same training assembly, the same strip.** It is fitted by the same
  ``walk_forward`` loop on the same ``training_rows`` frame the chain gets, and predicts on the same
  outcome-stripped ``visible`` frame. A second, hand-rolled training split would be a second chance
  to leak, and a leaked benchmark would report a gap that is entirely its own dishonesty
  ([DL-28](../../../../docs/planning/00-decision-log.md#dl-28), Invariant 5, DP-13).
* **Ordinary, unswept hyperparameters.** See :class:`~fpl_dof.config.models.MonolithConfig`. A
  monolith tuned against the folds it is graded on would report its own overfitting as the chain's
  deficit.

**The one place the "same features" rule bites, stated rather than hidden** (DP-09). The chain does
not consume ``fixture_opponent_team_id`` as an identifier — it turns it into M2's fitted attack and
defence ratings, which pool a club's evidence across every match it has played. The monolith gets
the raw club, as a *categorical* so that at least nothing reads an arbitrary id as an ordinal, and
has to rediscover that pooling from splits. So the gap this module reports is a lower bound on what
a monolith could do with a fixture-difficulty feature, and an honest measure of what one can do with
what the chain is actually handed. Handing it M2's output instead would make it a hybrid of the
thing it is supposed to be benchmarking.

**Why scikit-learn's histogram gradient boosting and not LightGBM or XGBoost.** It is free, open
source and installable as a wheel on every platform the scheduled runner uses (Invariant 3,
NFR-01); it handles missing values natively, which matters because much of this feature store is
legitimately null — a per-90 rate over a window in which nobody played is *unmeasured*, and the
alternative to native support is imputing a number, which is exactly the invented fact
[DL-18](../../../../docs/planning/00-decision-log.md#dl-18) warns about; it takes categorical
features without a one-hot expansion of twenty-five club codes; and it is the same library
[DL-04](../../../../docs/planning/00-decision-log.md#dl-04) already named as this project's intended
stack for anything of the kind. LightGBM would be marginally faster on a dataset a thousand times
this size and brings a compiled dependency for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from fpl_dof.config.models import FeatureConfig, MonolithConfig
from fpl_dof.forecast.features import (
    FIXTURE_OPPONENT,
    FIXTURE_TEAM,
    TARGET,
    LeakageError,
    input_features,
)
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

#: What this benchmark calls itself wherever a report has to say which model a row belongs to.
MODEL_NAME = "monolith"

#: The player's position, which the feature store does not declare because nothing *computes* it —
#: it is an attribute of the footballer, not a rolling window over his matches. The component chain
#: conditions on it in every single component (every rate has a position prior, every scoring value
#: is looked up by position), so withholding it would make this a floor rather than a ceiling and
#: the comparison would flatter the chain. Named here, once, so the exception is visible.
POSITION = "position"

#: Columns handed over as categories rather than as numbers. A club code is a label: the club whose
#: code is 43 is not "more" than the club whose code is 21, and a tree given the raw integer would
#: split on an ordering that means nothing. Treating them as categorical is not a feature the chain
#: lacks — it is the minimum honest encoding of a column the chain already reads.
CATEGORICAL: tuple[str, ...] = (POSITION, FIXTURE_TEAM, FIXTURE_OPPONENT)


@dataclass(frozen=True, slots=True)
class Encoding:
    """How one frame becomes a matrix: which columns, in which order, and which are categories.

    Learned once at ``fit`` and reused at ``predict`` unchanged. The alternative — deciding the
    column list from whatever frame is in front of it — is the classic training/inference skew the
    feature store's whole docstring is about, and it would be undetectable here: the monolith would
    still predict, and every number would be slightly wrong.
    """

    columns: tuple[str, ...]
    categories: Mapping[str, Mapping[object, int]]

    @property
    def categorical_indices(self) -> list[int]:
        return [index for index, column in enumerate(self.columns) if column in self.categories]

    def matrix(self, frame: pd.DataFrame) -> np.ndarray:
        """``frame`` as a float matrix, with unknowns as NaN for the library to handle natively."""
        rows = len(frame)
        matrix = np.full((rows, len(self.columns)), np.nan, dtype=float)
        for index, column in enumerate(self.columns):
            if column not in frame.columns:
                # A column the fit had and this frame does not. Left as NaN — "not measured here" —
                # rather than filled, which would be a claim about a value nobody observed.
                continue
            series = frame[column]
            if column in self.categories:
                codes = series.map(self.categories[column])
                matrix[:, index] = pd.to_numeric(codes, errors="coerce").to_numpy(
                    dtype=float, na_value=np.nan
                )
                continue
            matrix[:, index] = pd.to_numeric(series, errors="coerce").to_numpy(
                dtype=float, na_value=np.nan
            )
        return matrix


def encoding_for(frame: pd.DataFrame, config: FeatureConfig) -> Encoding:
    """The allow-list, applied to one training frame.

    **Allow-list rather than deny-list, and that is the look-ahead guarantee.** The columns the
    monolith may read are the ones :func:`~fpl_dof.forecast.features.specs` declares as inputs —
    every one of them stamped ``BEFORE_DEADLINE`` or ``AT_DEADLINE`` — so a new outcome column
    appearing in the fold frame cannot reach the model by default. A deny-list would let exactly
    that happen, silently, and the backtest would improve.

    **A declared column with no observed value in this window is dropped**, not passed through as a
    column of nulls. It carries no information either way, so nothing is lost — and it is what a
    harness run against an archive with no resolvable fixture actually produces (the D-26
    condition), where all three fixture columns are null on every row. Left in, the boosting
    library has no distinct value to place a bin edge between and raises rather than shrugging.
    """
    declared = [
        column
        for column in (*input_features(config), POSITION)
        if column in frame.columns and column != TARGET and bool(frame[column].notna().any())
    ]
    if TARGET in declared:  # pragma: no cover - the comprehension above already forbids it
        raise LeakageError("the target reached the monolith's feature list")

    categories: dict[str, Mapping[object, int]] = {}
    for column in CATEGORICAL:
        if column not in declared:
            continue
        # Sorted by the string form so the encoding is stable across runs whatever pandas hands
        # back, which is what makes two runs on one archive report one number (DP-11).
        seen = sorted(set(frame[column].dropna().tolist()), key=repr)
        categories[column] = {value: code for code, value in enumerate(seen)}
    return Encoding(columns=tuple(declared), categories=categories)


class MonolithPredictor:
    """A gradient-boosted regressor wearing the harness's predictor interface.

    Deliberately the same ``fit``/``predict`` shape as
    :class:`~fpl_dof.forecast.xp_v1.ComponentPredictor` and nothing more. It exposes no minutes
    distribution and no squad composition, so the harness gives it an aggregate figure and no
    minutes calibration — which is correct: it does not model minutes, it models points, and
    inventing a distribution for it would be a number with no model behind it.
    """

    name = MODEL_NAME

    def __init__(self, *, config: MonolithConfig, features: FeatureConfig) -> None:
        self.config = config
        self.features = features
        self.encoding: Encoding | None = None
        self.model: HistGradientBoostingRegressor | None = None
        self.fallback = 0.0
        self.training_rows = 0
        self.degraded: str | None = None
        self.fitted = False

    def fit(self, training: pd.DataFrame) -> None:
        self.encoding = None
        self.model = None
        self.degraded = None
        self.fitted = True

        # An absent target is a training frame this benchmark cannot be fitted on at all, which is
        # a degradation rather than an error: the harness's early folds and its two-line leakage
        # stubs both arrive here legitimately.
        target = (
            pd.to_numeric(training[TARGET], errors="coerce")
            if TARGET in training.columns
            else pd.Series(dtype=float)
        )
        usable = training[target.notna()] if len(target) else training.iloc[:0]
        self.training_rows = len(usable)
        self.fallback = float(target.dropna().mean()) if target.notna().any() else 0.0

        encoding = encoding_for(usable, self.features) if self.training_rows else None
        if encoding is None or not encoding.columns:
            self.degraded = "no declared input feature was present in the training frame"
        elif self.training_rows < self.config.minimum_training_rows:
            self.degraded = (
                f"{self.training_rows} training rows is below the "
                f"{self.config.minimum_training_rows} a boosted fit needs to be measuring "
                "anything but noise"
            )
        if self.degraded is not None:
            # Never silent: a benchmark that has quietly become a constant reports a gap that is a
            # statement about the constant (DP-15). Early folds legitimately land here.
            log.info(
                "monolith.degraded", extra={"reason": self.degraded, "rows": self.training_rows}
            )
            return

        assert encoding is not None
        model = HistGradientBoostingRegressor(
            learning_rate=self.config.learning_rate,
            max_iter=self.config.max_iterations,
            max_leaf_nodes=self.config.max_leaf_nodes,
            min_samples_leaf=self.config.min_samples_leaf,
            l2_regularization=self.config.l2_regularisation,
            categorical_features=encoding.categorical_indices,
            # Off deliberately: early stopping holds out a random slice of the training window, so
            # every fold would stop at a different capacity and the benchmark's own strength would
            # drift with the calendar rather than with the model.
            early_stopping=False,
            random_state=self.config.random_seed,
        )
        model.fit(encoding.matrix(usable), pd.to_numeric(usable[TARGET], errors="coerce"))
        self.encoding, self.model = encoding, model

    def predict(self, features: pd.DataFrame) -> pd.Series:
        if not self.fitted:
            # Distinguished from a degraded fit, which is thin evidence and legitimate. This is
            # `predict` before `fit`, which is a programming error.
            raise RuntimeError("predict() called before fit(); the harness always fits first")
        if self.model is None or self.encoding is None:
            return pd.Series(self.fallback, index=features.index, dtype=float)
        predicted = self.model.predict(self.encoding.matrix(features))
        return pd.Series(np.asarray(predicted, dtype=float), index=features.index, dtype=float)

    def describe(self) -> dict[str, object]:
        """What the report says about the benchmark, so an inert one is visible as inert."""
        return {
            "name": self.name,
            "library": "sklearn.ensemble.HistGradientBoostingRegressor",
            "training_rows": self.training_rows,
            "features": list(self.encoding.columns) if self.encoding else [],
            "categorical": sorted(self.encoding.categories) if self.encoding else [],
            "degraded": self.degraded,
        }


def head_gap(chain: float, monolith: float) -> float:
    """How much better the monolith is at the head. Positive means the chain is paying for DP-10.

    A named function for a subtraction, because the sign of this number is the entire finding and
    two call sites subtracting in opposite orders is a way to report the opposite of the truth.
    """
    if chain != chain or monolith != monolith:
        return float("nan")
    return float(monolith - chain)


def gap_statement(
    *,
    chain_precision: float,
    monolith_precision: float,
    chain_spearman: float,
    monolith_spearman: float,
    top_n: int,
    by_position: Mapping[str, float] | None = None,
) -> str:
    """The explainability trade, in a sentence, for the model card and the backtest report.

    Written once and read by both, because DP-10's requirement is that the trade is *visible* — and
    a number in a JSON field nobody opens is not visible. Two independently worded versions of it
    would be two chances to word one of them reassuringly.
    """
    gap = head_gap(chain_precision, monolith_precision)
    rank_gap = head_gap(chain_spearman, monolith_spearman)
    if gap != gap:
        return (
            "The monolith shadow benchmark did not produce a comparable head-of-ranking figure "
            "this run, so the explainability trade is **not measured** — which is an absence, not "
            "a finding of no gap (E10-S5)."
        )

    direction = (
        "a gradient-boosted model on exactly the same features scores "
        f"**{monolith_precision:.3f}** against the chain's **{chain_precision:.3f}**"
    )
    sentences = [
        "**The explainability trade, measured (E10-S5).** At the head of the ranking — "
        f"top-{top_n} precision within a gameweek — {direction}, a gap of **{gap:+.3f}**. "
        "On overall rank "
        f"correlation the same comparison is {monolith_spearman:.3f} against {chain_spearman:.3f}, "
        f"{rank_gap:+.3f}."
    ]
    if gap > 0:
        sentences.append(
            "So the interpretable chain is **not** free at the head: this is what the project pays "
            "for a forecast whose every number decomposes into components a human can challenge. "
            "The monolith is a benchmark and never a candidate — it does not reach `optimise`, the "
            "decision layer or the published ranking, and promoting it would be an explicit DP-10 "
            "decision weighing that gap against losing the decomposition entirely."
        )
    else:
        sentences.append(
            "So the chain's explainability is **free at the head**: an opaque model with the same "
            "information does no better there, and DP-10's preference for the formulation you can "
            "argue with costs nothing on the metric this project is actually graded on."
        )
    if by_position:
        worst = max(by_position.items(), key=lambda item: item[1] if item[1] == item[1] else -1e9)
        if worst[1] == worst[1]:
            sentences.append(
                f"Per position the gap is widest at **{worst[0]}** ({worst[1]:+.3f}). A gap "
                "concentrated in one position is a statement about that position's formulation, "
                "not about interpretability in general (E10 §0)."
            )
    return " ".join(sentences)


def gap_by_position(chain: Mapping[str, float], monolith: Mapping[str, float]) -> dict[str, float]:
    """The same subtraction, per position, over the positions both sides measured."""
    return {
        position: head_gap(chain[position], monolith[position])
        for position in sorted(set(chain) & set(monolith))
    }


__all__ = [
    "CATEGORICAL",
    "MODEL_NAME",
    "POSITION",
    "Encoding",
    "MonolithPredictor",
    "encoding_for",
    "gap_by_position",
    "gap_statement",
    "head_gap",
]
