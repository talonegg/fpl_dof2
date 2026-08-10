"""Baselines — the reason every other number means anything.

**B0** predicts from **position and current price alone**, fitted on the same training window as the
real model. It is an afternoon's work and every tier-2 threshold is expressed relative to it
(DL-13), for an uncomfortable reason worth restating rather than filing away:

    charter v1.0's absolute thresholds would have passed a model with no edge at all. ``MAE <= 2.1``
    sits in the range a *constant predictor* achieves on players who played. ``Spearman >= 0.30``
    across all positions is plausibly reachable knowing nothing but price and position — because
    price **is** FPL's own expected-value estimate, continuously updated by a million managers.

Without B0 you cannot tell a working forecast from an expensive restatement of ``now_cost``.

**The model-free benchmark** is the season-level counterpart: pick the highest trailing-six-gameweek
scorers, one transfer a week. It depends on nothing this project predicts, which is exactly what
makes it the honest bar — it is roughly what an unaided manager does.

The third benchmark the plan inherited, *"highest xP, one transfer per week"*, is **circular** and
is labelled as a diagnostic here rather than a benchmark. It runs on this project's own forecast: if
the forecast is poor, both sides of the comparison are poor, and better optimisation beats it while
both remain worse than guessing. It measures the optimiser, not the model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

MEAN_BASELINE = "b_mean"
PRICE_BASELINE = "b0_price_position"
FORM_BASELINE = "b_trailing_form"


@dataclass(frozen=True, slots=True)
class FittedBaseline:
    """A baseline, fitted. Kept as data so the model card can print what it learned."""

    name: str
    summary: str
    intercept_by_position: dict[str, float]
    slope_by_position: dict[str, float]
    global_mean: float

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        if self.name == MEAN_BASELINE:
            return pd.Series(self.global_mean, index=frame.index, dtype=float)
        positions = frame["position"].astype(str)
        intercept = positions.map(self.intercept_by_position).astype(float)
        slope = positions.map(self.slope_by_position).astype(float)
        price = pd.to_numeric(frame["price"], errors="coerce").astype(float)
        # A position never seen in training falls back to the overall mean rather than to NaN:
        # a baseline that refuses to predict cannot be beaten, which defeats the point of it.
        predicted = intercept + slope * price
        return predicted.fillna(self.global_mean)


def fit_mean_baseline(training: pd.DataFrame, target: str) -> FittedBaseline:
    """Predict the same number for everyone. The floor beneath the floor.

    Included because it is startling how well it does on the metrics the charter originally used,
    which is precisely the finding that motivated DL-13.
    """
    values = pd.to_numeric(training[target], errors="coerce").dropna()
    return FittedBaseline(
        name=MEAN_BASELINE,
        summary="Constant: the training mean, for everyone",
        intercept_by_position={},
        slope_by_position={},
        global_mean=float(values.mean()) if len(values) else 0.0,
    )


def fit_b0(training: pd.DataFrame, target: str) -> FittedBaseline:
    """B0: one least-squares line per position, from price to points.

    Per position rather than pooled because the price-to-points relationship genuinely differs by
    position — a £6.0m defender and a £6.0m forward are not comparable bets — and pooling would
    hand the real model an easy win it has not earned.
    """
    values = pd.to_numeric(training[target], errors="coerce")
    usable = training.assign(_target=values).dropna(subset=["_target", "price", "position"])
    global_mean = float(usable["_target"].mean()) if len(usable) else 0.0

    intercepts: dict[str, float] = {}
    slopes: dict[str, float] = {}
    for position, group in usable.groupby("position"):
        price = pd.to_numeric(group["price"], errors="coerce").to_numpy(dtype=float)
        points = group["_target"].to_numpy(dtype=float)
        if len(group) < 2 or float(np.ptp(price)) == 0.0:
            # Not enough spread to fit a line. A flat group mean is the honest answer, and it is
            # still a fair opponent.
            intercepts[str(position)] = float(points.mean())
            slopes[str(position)] = 0.0
            continue
        design = np.vstack([np.ones_like(price), price]).T
        solution, *_ = np.linalg.lstsq(design, points, rcond=None)
        intercepts[str(position)] = float(solution[0])
        slopes[str(position)] = float(solution[1])

    return FittedBaseline(
        name=PRICE_BASELINE,
        summary="Least squares from price to points, fitted separately within each position",
        intercept_by_position=intercepts,
        slope_by_position=slopes,
        global_mean=global_mean,
    )


def trailing_form_prediction(
    history: pd.DataFrame, *, as_of: pd.Timestamp, window: int = 6
) -> pd.DataFrame:
    """The model-free benchmark's ranking: total points over the last ``window`` matches.

    Uses no model, no fitted parameter and nothing this project predicts. That independence is the
    whole value — it is the bar a forecast has to clear to be worth running at all.
    """
    moment = pd.Timestamp(as_of).tz_convert("UTC")
    known = history[history["kickoff_time"] < moment]
    if known.empty:
        return pd.DataFrame(columns=["player_code", "prediction"])

    ordered = known.sort_values(["player_code", "kickoff_time"])
    recent = ordered.groupby("player_code").tail(window)
    totals = recent.groupby("player_code")["total_points"].sum().reset_index()
    counts = recent.groupby("player_code")["total_points"].size().reset_index(name="matches")
    merged = totals.merge(counts, on="player_code")
    # Per match, so a player with four appearances is not penalised against one with six.
    merged["prediction"] = merged["total_points"] / merged["matches"].clip(lower=1)
    return merged[["player_code", "prediction"]]


__all__ = [
    "FORM_BASELINE",
    "MEAN_BASELINE",
    "PRICE_BASELINE",
    "FittedBaseline",
    "fit_b0",
    "fit_mean_baseline",
    "trailing_form_prediction",
]
