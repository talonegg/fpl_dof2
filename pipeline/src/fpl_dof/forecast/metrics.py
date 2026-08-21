"""Tier-2 metrics, all expressed relative to a baseline (DL-13).

The charter originally carried absolute thresholds. They were replaced because they would have
passed a model with no edge: ``MAE <= 2.1`` is achievable by predicting a constant, and a Spearman
of 0.30 across all positions is roughly what price alone gives you. An absolute number cannot tell
you whether a forecast is good; it can only tell you whether the problem is easy.

So every accuracy metric here answers *"compared to what?"*, and the skill score makes that
explicit: **1.0 is perfect, 0.0 is exactly as good as the baseline, and negative is worse than the
baseline.** A negative skill score is not a bug to tune away — it is the finding.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fpl_dof.frames import as_float
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MetricSet:
    """Everything measured for one model over one evaluation set."""

    name: str
    observations: int
    mae: float
    rmse: float
    mae_skill_score: float
    """1 - (model MAE / baseline MAE). Zero means the baseline was just as good."""

    spearman: float
    spearman_by_position: dict[str, float] = field(default_factory=dict)
    spearman_by_price_band: dict[str, float] = field(default_factory=dict)
    spearman_by_fixture_band: dict[str, float] = field(default_factory=dict)
    """Rank correlation split by how hard the fixture was. The axis E11 is graded on (E9-S2)."""

    calibration_by_fixture_band: dict[str, float] = field(default_factory=dict)
    """Calibration slope on the same split. A fixture model can rank well and still be scaled
    wrongly in the fixtures it is supposed to help, and only the slope shows that."""

    top_n_precision: float = 0.0
    """**Per gameweek, then averaged** — see :func:`top_n_precision` (E10-S2, DL-49)."""

    top_n_precision_by_position: dict[str, float] = field(default_factory=dict)
    """The same measure inside each position, at that position's own head. E10 grades every metric
    per position, because a gain confined to forwards is not a gain (E10 §0)."""

    captaincy_hit_rate: float = 0.0
    calibration_slope: float = float("nan")
    """Regression of actual on predicted. 1.0 is calibrated; below 1 means over-confident spread."""

    calibration_slope_by_position: dict[str, float] = field(default_factory=dict)
    """Compression is not uniform across positions, and the slope is what measures compression, so
    an aggregate slope can hide one position being badly scaled while another is fine."""

    minutes_brier: float = float("nan")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "observations": self.observations,
            "mae": _clean(self.mae),
            "rmse": _clean(self.rmse),
            "mae_skill_score": _clean(self.mae_skill_score),
            "spearman": _clean(self.spearman),
            "spearman_by_position": {k: _clean(v) for k, v in self.spearman_by_position.items()},
            "spearman_by_price_band": {
                k: _clean(v) for k, v in self.spearman_by_price_band.items()
            },
            "spearman_by_fixture_band": {
                k: _clean(v) for k, v in self.spearman_by_fixture_band.items()
            },
            "calibration_by_fixture_band": {
                k: _clean(v) for k, v in self.calibration_by_fixture_band.items()
            },
            "top_n_precision": _clean(self.top_n_precision),
            "top_n_precision_by_position": {
                k: _clean(v) for k, v in self.top_n_precision_by_position.items()
            },
            "captaincy_hit_rate": _clean(self.captaincy_hit_rate),
            "calibration_slope": _clean(self.calibration_slope),
            "calibration_slope_by_position": {
                k: _clean(v) for k, v in self.calibration_slope_by_position.items()
            },
            "minutes_brier": _clean(self.minutes_brier),
        }


def _clean(value: float) -> float | None:
    return (
        None
        if value is None or (isinstance(value, float) and np.isnan(value))
        else round(float(value), 5)
    )


def spearman(predicted: pd.Series, actual: pd.Series) -> float:
    """Rank correlation, computed directly so the metric has no hidden dependency.

    Returns NaN rather than 0.0 when it is undefined — fewer than two observations, or no variation
    in one of the series. Zero would read as "no relationship", which is a claim; NaN is the
    absence of one.
    """
    pair = pd.DataFrame({"p": predicted, "a": actual}).dropna()
    if len(pair) < 2:
        return float("nan")
    ranked_p = pair["p"].rank()
    ranked_a = pair["a"].rank()
    if ranked_p.std() == 0 or ranked_a.std() == 0:
        return float("nan")
    return float(ranked_p.corr(ranked_a))


def calibration_slope(predicted: pd.Series, actual: pd.Series) -> float:
    """Least-squares slope of actual on predicted.

    Below 1 means the forecast's spread is too wide — it is confidently distinguishing players it
    cannot actually distinguish, which in FPL terms means it will recommend differentials that are
    not differentiated.
    """
    pair = pd.DataFrame({"p": predicted, "a": actual}).dropna()
    if len(pair) < 2 or float(pair["p"].std()) == 0.0:
        return float("nan")
    design = np.vstack([np.ones(len(pair)), pair["p"].to_numpy(dtype=float)]).T
    solution, *_ = np.linalg.lstsq(design, pair["a"].to_numpy(dtype=float), rcond=None)
    return float(solution[1])


def top_n_precision(frame: pd.DataFrame, *, n: int, predicted: str, actual: str) -> float:
    """Share of the top-N predicted who were genuinely in the top N, **within one frame**.

    The metric closest to how the tool is actually used: nobody acts on the whole ranking, they act
    on the head of it. "The ranking" is therefore *one gameweek's* ranking — the object a manager
    is looking at when they choose a captain — which is why the harness reaches this through
    :func:`per_gameweek_mean` rather than calling it on a pooled frame (DL-49).
    """
    usable = frame.dropna(subset=[predicted, actual])
    if len(usable) < n:
        return float("nan")
    predicted_top = set(usable.nlargest(n, predicted).index)
    actual_top = set(usable.nlargest(n, actual).index)
    return len(predicted_top & actual_top) / n


def per_gameweek_mean(
    frame: pd.DataFrame, group: Sequence[str], measure: Callable[[pd.DataFrame], float]
) -> float:
    """``measure`` applied to each gameweek separately, then averaged over the gameweeks.

    **The head-of-ranking metrics are only meaningful one gameweek at a time**, and averaging them
    afterwards is not a refinement of pooling them — pooling produces a different and degenerate
    quantity. Over 72 pooled gameweeks the twenty highest *observed* scores are twenty individual
    20-point hauls, while the highest a calibrated expectation can ever be is about six, so no
    model can overlap them and the answer is 0.00 whatever the model does. A metric that cannot
    move cannot grade anything (DL-49, DP-12).

    Gameweeks with too few rows to rank contribute NaN and are skipped rather than counted as
    zero, because "not measurable here" is not the same claim as "got none of them right".
    """
    if frame.empty or not set(group) <= set(frame.columns):
        return float("nan")
    scores = [measure(rows) for _, rows in frame.groupby(list(group), sort=True)]
    usable = [value for value in scores if value == value]
    return float(np.mean(usable)) if usable else float("nan")


def captaincy_hit_rate(frame: pd.DataFrame, *, predicted: str, actual: str, pool: int = 1) -> float:
    """Did the top pick turn out to be the highest actual scorer, **within one frame**?

    Harsh by design. Captaincy doubles a single player's return, so the cost of being wrong is
    concentrated in exactly the way an averaged accuracy metric hides.

    One frame is one gameweek, for the same reason as :func:`top_n_precision`: a captaincy decision
    is taken once a week, and DP-12 already reasons about this metric as "n=38 over a season",
    which is only true if each gameweek contributes one observation. Pooled over every gameweek at
    once it contributes exactly one observation in total and is 0.0 for every model ever built.
    """
    usable = frame.dropna(subset=[predicted, actual])
    if usable.empty:
        return float("nan")
    chosen = set(usable.nlargest(pool, predicted).index)
    best = usable[actual].max()
    winners = set(usable[usable[actual] == best].index)
    return 1.0 if chosen & winners else 0.0


def brier_score(probabilities: pd.Series, outcomes: pd.Series) -> float:
    """Mean squared error of a probability. The minutes model's honesty check.

    A ranking-only minutes model can look fine and still be badly calibrated, and calibration is
    what the optimiser actually consumes — it multiplies by these numbers.
    """
    pair = pd.DataFrame({"p": probabilities, "o": outcomes}).dropna()
    if pair.empty:
        return float("nan")
    return float(((pair["p"] - pair["o"]) ** 2).mean())


#: The three minutes states, in the order the model reports them, and the same partition M1 names
#: in :data:`fpl_dof.forecast.models.MINUTES_BANDS`. Declared here rather than imported so the
#: metrics module keeps depending on nothing — but a metric that scored a *different* partition
#: from the one the model predicts would be a number that looks fine and means nothing, so the two
#: are pinned together by `test_minutes_calibration.py` rather than by an import.
MINUTES_BANDS: tuple[str, ...] = ("none", "short", "long")


def minutes_band(minutes: object, long_play_minutes: int) -> str:
    """Which of ``{0, 1-59, 60+}`` an observation fell in.

    ``long_play_minutes`` arrives as an argument because sixty is a **scoring rule**, not a
    constant this module is entitled to know (Invariant 2).
    """
    try:
        value = as_float(minutes)
    except TypeError, ValueError:
        return ""
    if value != value:
        # An unmeasured observation, banded as nothing rather than as a non-appearance: "he did not
        # play" and "nobody recorded whether he played" are different claims (DL-18).
        return ""
    if value <= 0:
        return MINUTES_BANDS[0]
    return MINUTES_BANDS[1] if value < long_play_minutes else MINUTES_BANDS[2]


def multiclass_brier(probabilities: pd.DataFrame, observed: pd.Series) -> float:
    """Brier score for a three-way distribution: mean squared error across every class.

    The multiclass form rather than three separate binary scores, because the quantity the
    optimiser consumes is the *distribution* — it multiplies every rate by the 60+ mass and adds
    appearance points on the 1-59 mass — and a model can be well calibrated on "did he play" while
    being badly wrong about how long. Zero is perfect; the worst possible score is 2.
    """
    columns = [band for band in MINUTES_BANDS if band in probabilities.columns]
    if not columns or probabilities.empty:
        return float("nan")
    frame = probabilities[columns].apply(pd.to_numeric, errors="coerce")
    labels = observed.reindex(frame.index)
    usable = frame.notna().all(axis=1) & labels.isin(MINUTES_BANDS)
    if not bool(usable.any()):
        return float("nan")
    frame, labels = frame[usable], labels[usable]
    total = sum(((frame[band] - (labels == band).astype(float)) ** 2) for band in columns)
    return float(total.mean())


@dataclass(frozen=True, slots=True)
class MinutesCalibration:
    """M1's calibration against the E0 status-flag haircut, split every way E10 grades on.

    **Reported per position and per observed minutes band**, because an aggregate here hides the
    thing that matters: a model can score well overall by being right about the 60% of rows that
    are non-appearances while being useless about which of the players who do feature lasts the
    hour — and the second is the half a captaincy decision rests on (E10 §0).
    """

    observations: int
    baseline_name: str
    brier: float
    baseline_brier: float
    by_position: dict[str, float] = field(default_factory=dict)
    baseline_by_position: dict[str, float] = field(default_factory=dict)
    by_band: dict[str, float] = field(default_factory=dict)
    baseline_by_band: dict[str, float] = field(default_factory=dict)

    @property
    def skill_score(self) -> float:
        """1 - (model / baseline). Zero means the haircut was just as good; negative means worse."""
        if self.baseline_brier != self.baseline_brier or self.baseline_brier <= 0:
            return float("nan")
        return 1.0 - (self.brier / self.baseline_brier)

    @property
    def beats_baseline(self) -> bool:
        """E3-S3's acceptance criterion, stated as a property rather than left to a reader."""
        return bool(self.brier == self.brier and self.brier < self.baseline_brier)

    def as_dict(self) -> dict[str, object]:
        return {
            "observations": self.observations,
            "baseline_name": self.baseline_name,
            "brier": _clean(self.brier),
            "baseline_brier": _clean(self.baseline_brier),
            "skill_score": _clean(self.skill_score),
            "beats_baseline": self.beats_baseline,
            "by_position": {k: _clean(v) for k, v in self.by_position.items()},
            "baseline_by_position": {k: _clean(v) for k, v in self.baseline_by_position.items()},
            "by_band": {k: _clean(v) for k, v in self.by_band.items()},
            "baseline_by_band": {k: _clean(v) for k, v in self.baseline_by_band.items()},
        }


def evaluate_minutes(
    frame: pd.DataFrame,
    *,
    model_columns: Mapping[str, str],
    baseline_columns: Mapping[str, str],
    observed_band: str,
    baseline_name: str,
    position: str = "position",
) -> MinutesCalibration:
    """The minutes Brier score, overall and split by position and by what actually happened.

    ``model_columns`` and ``baseline_columns`` map each of :data:`MINUTES_BANDS` onto the column
    holding its probability, so the caller names the columns once and this function never guesses.
    """
    needed = [*model_columns.values(), *baseline_columns.values(), observed_band]
    if frame.empty or not set(needed) <= set(frame.columns):
        return MinutesCalibration(
            observations=0,
            baseline_name=baseline_name,
            brier=float("nan"),
            baseline_brier=float("nan"),
        )
    usable = frame[frame[observed_band].isin(MINUTES_BANDS)]
    if usable.empty:
        return MinutesCalibration(
            observations=0,
            baseline_name=baseline_name,
            brier=float("nan"),
            baseline_brier=float("nan"),
        )

    def score(rows: pd.DataFrame, columns: Mapping[str, str]) -> float:
        renamed = rows[[columns[band] for band in MINUTES_BANDS]]
        renamed.columns = pd.Index(list(MINUTES_BANDS))
        return multiclass_brier(renamed, rows[observed_band])

    def split(column: str, columns: Mapping[str, str]) -> dict[str, float]:
        if column not in usable.columns:
            return {}
        return {str(key): score(group, columns) for key, group in usable.groupby(column)}

    return MinutesCalibration(
        observations=len(usable),
        baseline_name=baseline_name,
        brier=score(usable, model_columns),
        baseline_brier=score(usable, baseline_columns),
        by_position=split(position, model_columns),
        baseline_by_position=split(position, baseline_columns),
        by_band=split(observed_band, model_columns),
        baseline_by_band=split(observed_band, baseline_columns),
    )


def head_size_by_position(total: int, composition: Mapping[str, int]) -> dict[str, int]:
    """Split an overall head size across positions in the proportion a squad is built from them.

    A single top-20 applied inside every position measures nothing at the two ends of the pitch:
    barely twenty goalkeepers feature in a gameweek, so "the top 20 goalkeepers" is *all* of them
    and any model scores about 1.0. The head has to be the same relative depth everywhere.

    **The proportion is the squad composition, and it arrives as an argument.** Two goalkeepers in
    fifteen is an FPL rule, not a constant this module may know (Invariant 2, DP-05), and it is
    also the honest answer to "how far down this position do I actually shop?" — a top-20 overall
    is a squad's worth of players, so each position's share of that squad is its share of the head.
    At least one, because a position nobody ranks is not a position that has been graded.
    """
    size = sum(composition.values())
    if total <= 0 or size <= 0:
        return {}
    return {
        str(position): max(1, round(total * count / size))
        for position, count in composition.items()
    }


def price_band(price: float, edges: tuple[float, ...] = (5.0, 7.5, 10.0)) -> str:
    """Coarse bands, because a per-position Spearman on 15 players is noise.

    Bands rather than quantiles so the label means the same thing across gameweeks — a quantile
    band silently changes what it contains as prices drift through the season.
    """
    for edge in edges:
        if price < edge:
            return f"<{edge:.1f}"
    return f">={edges[-1]:.1f}"


#: The label a row gets when its fixture could not be resolved. Kept in the breakdown rather than
#: dropped, so a harness silently falling back to league-average opposition shows up as a band
#: rather than as an absence nobody notices (DP-15).
UNRESOLVED_FIXTURE_BAND = "unresolved"


def fixture_difficulty_band(ratio: float, band_ratio: float) -> str:
    """Coarse bands over :meth:`TeamStrengthModel.fixture_difficulty_ratio`.

    Three bands from *one* tunable, because the easy and hard edges are the same departure from
    even in opposite directions: ``band_ratio`` and its reciprocal. Two separately configured edges
    would be one tunable and a bug waiting to happen — the same reasoning the published fixture
    ticker's steepness is derived rather than set (DL-37).

    Bands rather than quantiles so the label means the same thing across gameweeks and across runs.
    """
    if ratio is None or (isinstance(ratio, float) and np.isnan(ratio)) or pd.isna(ratio):
        return UNRESOLVED_FIXTURE_BAND
    value = float(ratio)
    if value < 1.0 / band_ratio:
        return "easy"
    if value >= band_ratio:
        return "hard"
    return "average"


def evaluate(
    frame: pd.DataFrame,
    *,
    name: str,
    predicted: str,
    actual: str,
    baseline: str | None = None,
    top_n: int = 20,
    captaincy_pool: int = 1,
    minutes_probability: str | None = None,
    played: str | None = None,
    fixture_difficulty: str | None = None,
    fixture_band_ratio: float | None = None,
    group: Sequence[str] = (),
    top_n_by_position: Mapping[str, int] | None = None,
) -> MetricSet:
    """Every tier-2 metric for one model, against one baseline column.

    ``group`` names the columns identifying a single ranking — in the harness, season and gameweek.
    The head-of-ranking metrics are computed inside each one and averaged; without it they fall
    back to the whole frame, which is only right when the frame already *is* one ranking (DL-49).

    ``top_n_by_position`` gives each position its own head size, because "the top 20" of a position
    that only fields two players a week is not a head at all.
    """
    usable = frame.dropna(subset=[predicted, actual]).copy()
    if usable.empty:
        return MetricSet(
            name=name,
            observations=0,
            mae=float("nan"),
            rmse=float("nan"),
            mae_skill_score=float("nan"),
            spearman=float("nan"),
        )

    error = (usable[predicted] - usable[actual]).abs()
    mae = float(error.mean())
    rmse = float(np.sqrt(((usable[predicted] - usable[actual]) ** 2).mean()))

    skill = float("nan")
    if baseline is not None and baseline in usable.columns:
        baseline_mae = float((usable[baseline] - usable[actual]).abs().mean())
        # A baseline that is already perfect makes skill undefined rather than infinite. It has
        # never happened and would mean the target leaked into the baseline.
        skill = 1.0 - (mae / baseline_mae) if baseline_mae > 0 else float("nan")

    positions = dict(iter(usable.groupby("position")))
    by_position = {
        str(name): spearman(rows[predicted], rows[actual]) for name, rows in positions.items()
    }
    calibration_by_position = {
        str(name): calibration_slope(rows[predicted], rows[actual])
        for name, rows in positions.items()
    }
    if "price" in usable.columns:
        usable["_band"] = usable["price"].map(price_band)
        by_band = {
            str(band): spearman(rows[predicted], rows[actual])
            for band, rows in usable.groupby("_band")
        }
    else:
        by_band = {}

    by_fixture: dict[str, float] = {}
    calibration_by_fixture: dict[str, float] = {}
    if fixture_difficulty and fixture_band_ratio and fixture_difficulty in usable.columns:
        usable["_fixture_band"] = usable[fixture_difficulty].map(
            lambda value: fixture_difficulty_band(value, fixture_band_ratio)
        )
        for band, rows in usable.groupby("_fixture_band"):
            by_fixture[str(band)] = spearman(rows[predicted], rows[actual])
            calibration_by_fixture[str(band)] = calibration_slope(rows[predicted], rows[actual])

    brier = float("nan")
    if minutes_probability and played and minutes_probability in usable.columns:
        brier = brier_score(usable[minutes_probability], usable[played])

    def head(rows: pd.DataFrame, size: int) -> float:
        """Top-``size`` precision, per ranking, averaged over the rankings."""

        def measure(one: pd.DataFrame) -> float:
            return top_n_precision(one, n=size, predicted=predicted, actual=actual)

        return per_gameweek_mean(rows, group, measure) if group else measure(rows)

    precision_by_position = {
        str(name): head(rows, top_n_by_position[str(name)])
        for name, rows in positions.items()
        if top_n_by_position and str(name) in top_n_by_position
    }

    def captaincy(rows: pd.DataFrame) -> float:
        return captaincy_hit_rate(rows, predicted=predicted, actual=actual, pool=captaincy_pool)

    return MetricSet(
        name=name,
        observations=len(usable),
        mae=mae,
        rmse=rmse,
        mae_skill_score=skill,
        spearman=spearman(usable[predicted], usable[actual]),
        spearman_by_position=by_position,
        spearman_by_price_band=by_band,
        spearman_by_fixture_band=by_fixture,
        calibration_by_fixture_band=calibration_by_fixture,
        top_n_precision=head(usable, top_n),
        top_n_precision_by_position=precision_by_position,
        captaincy_hit_rate=(
            per_gameweek_mean(usable, group, captaincy) if group else captaincy(usable)
        ),
        calibration_slope=calibration_slope(usable[predicted], usable[actual]),
        calibration_slope_by_position=calibration_by_position,
        minutes_brier=brier,
    )


__all__ = [
    "MINUTES_BANDS",
    "UNRESOLVED_FIXTURE_BAND",
    "MetricSet",
    "MinutesCalibration",
    "brier_score",
    "calibration_slope",
    "captaincy_hit_rate",
    "evaluate",
    "evaluate_minutes",
    "fixture_difficulty_band",
    "head_size_by_position",
    "minutes_band",
    "multiclass_brier",
    "per_gameweek_mean",
    "price_band",
    "spearman",
    "top_n_precision",
]
