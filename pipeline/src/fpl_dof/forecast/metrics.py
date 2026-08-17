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

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

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
    captaincy_hit_rate: float = 0.0
    calibration_slope: float = float("nan")
    """Regression of actual on predicted. 1.0 is calibrated; below 1 means over-confident spread."""

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
            "captaincy_hit_rate": _clean(self.captaincy_hit_rate),
            "calibration_slope": _clean(self.calibration_slope),
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
    """Share of the top-N predicted who were genuinely in the top N.

    The metric closest to how the tool is actually used: nobody acts on the whole ranking, they act
    on the head of it.
    """
    usable = frame.dropna(subset=[predicted, actual])
    if len(usable) < n:
        return float("nan")
    predicted_top = set(usable.nlargest(n, predicted).index)
    actual_top = set(usable.nlargest(n, actual).index)
    return len(predicted_top & actual_top) / n


def captaincy_hit_rate(frame: pd.DataFrame, *, predicted: str, actual: str, pool: int = 1) -> float:
    """Did the top pick turn out to be the highest actual scorer?

    Harsh by design. Captaincy doubles a single player's return, so the cost of being wrong is
    concentrated in exactly the way an averaged accuracy metric hides.
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
) -> MetricSet:
    """Every tier-2 metric for one model, against one baseline column."""
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

    by_position = {
        str(position): spearman(group[predicted], group[actual])
        for position, group in usable.groupby("position")
    }
    if "price" in usable.columns:
        usable["_band"] = usable["price"].map(price_band)
        by_band = {
            str(band): spearman(group[predicted], group[actual])
            for band, group in usable.groupby("_band")
        }
    else:
        by_band = {}

    by_fixture: dict[str, float] = {}
    calibration_by_fixture: dict[str, float] = {}
    if fixture_difficulty and fixture_band_ratio and fixture_difficulty in usable.columns:
        usable["_fixture_band"] = usable[fixture_difficulty].map(
            lambda value: fixture_difficulty_band(value, fixture_band_ratio)
        )
        for band, group in usable.groupby("_fixture_band"):
            by_fixture[str(band)] = spearman(group[predicted], group[actual])
            calibration_by_fixture[str(band)] = calibration_slope(group[predicted], group[actual])

    brier = float("nan")
    if minutes_probability and played and minutes_probability in usable.columns:
        brier = brier_score(usable[minutes_probability], usable[played])

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
        top_n_precision=top_n_precision(usable, n=top_n, predicted=predicted, actual=actual),
        captaincy_hit_rate=captaincy_hit_rate(
            usable, predicted=predicted, actual=actual, pool=captaincy_pool
        ),
        calibration_slope=calibration_slope(usable[predicted], usable[actual]),
        minutes_brier=brier,
    )


__all__ = [
    "UNRESOLVED_FIXTURE_BAND",
    "MetricSet",
    "brier_score",
    "calibration_slope",
    "captaincy_hit_rate",
    "evaluate",
    "fixture_difficulty_band",
    "price_band",
    "spearman",
    "top_n_precision",
]
