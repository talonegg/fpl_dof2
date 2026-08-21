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

from fpl_dof.config.models import ForecastConfig
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

MEAN_BASELINE = "b_mean"
PRICE_BASELINE = "b0_price_position"
FORM_BASELINE = "b_trailing_form"

#: The minutes baseline M1 has to beat (E3-S3's acceptance, unmeasured until E10-S1 — DL-22).
STATUS_HAIRCUT_BASELINE = "b_status_haircut"


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


def status_flag_haircut_minutes(features: pd.DataFrame, config: ForecastConfig) -> pd.DataFrame:
    """E0's minutes model, such as it was — the bar M1 was always supposed to clear.

    E0 had **no minutes model** (debt D-02). What it had was a start probability shrunk from the
    player's start rate, multiplied by an availability haircut read off the FPL status flag, and a
    fixed prior that a non-starter appears at all. E3-S3's acceptance criterion was to beat that,
    and [DL-22](../../../docs/planning/00-decision-log.md) found the criterion had never actually
    been measured because ``minutes_brier`` was always null. This is the thing to measure against.

    **The availability half is 1.0 for every historical row, and that is faithful rather than a
    straw man.** The archive carries no status flag, and the flag is not the reason the haircut
    was weak: the model card has said since E0 that *"nearly every player is flagged available, so
    the availability haircut does almost nothing"*. What E0's minutes estimate really rested on was
    the start rate, and that is reproduced here in full.

    Two deliberate choices in the baseline's favour, because a baseline worth beating should be the
    strongest honest version of itself:

    * the start rate is taken **unshrunk**, so a nailed starter reads as a nailed starter rather
      than being pulled toward a group prior;
    * where starts were never recorded — before 2022/23 (``starts_recorded_from_season``) — the
      appearance rate stands in, rather than the row being dropped, so the baseline is scored on
      the same population the model is.
    """
    index = features.index
    columns = ["none", "short", "long"]
    if features.empty:
        return pd.DataFrame(columns=columns, dtype=float)

    availability = pd.Series(1.0, index=index, dtype=float)
    if "status" in features.columns:
        availability = (
            pd.to_numeric(features["status"].map(config.status_multiplier), errors="coerce")
            .fillna(1.0)
            .astype(float)
        )

    appearance = pd.to_numeric(
        features.get("appearance_rate", pd.Series(np.nan, index=index)), errors="coerce"
    ).fillna(0.0)
    starts = pd.to_numeric(
        features.get("starts_rate", pd.Series(np.nan, index=index)), errors="coerce"
    )
    start_rate = starts.where(starts.notna(), appearance).clip(0.0, 1.0)

    long = (availability * start_rate).clip(0.0, 1.0)
    short = (
        availability * (1.0 - start_rate) * config.minutes.appearance_rate_if_not_starting
    ).clip(0.0, 1.0)
    plays = (long + short).clip(0.0, 1.0)
    # Renormalise rather than let the pair exceed one. It cannot with the default prior, and a
    # distribution that silently sums past one is the kind of wrongness nothing downstream notices.
    scale = (plays / (long + short)).where(long + short > 0, 0.0)
    long, short = long * scale, short * scale
    return pd.DataFrame({"none": 1.0 - long - short, "short": short, "long": long}, index=index)[
        columns
    ]


__all__ = [
    "FORM_BASELINE",
    "MEAN_BASELINE",
    "PRICE_BASELINE",
    "STATUS_HAIRCUT_BASELINE",
    "FittedBaseline",
    "fit_b0",
    "fit_mean_baseline",
    "status_flag_haircut_minutes",
    "trailing_form_prediction",
]
