"""The diagnostic that decides whether the forecast is a forecast.

FPL's own price is one of the model's inputs, and the optimiser then maximises expected points
*subject to a budget*. If expected points turns out to be largely a function of price, the
objective is nearly flat across every affordable squad and the solver is selecting on residual
noise — an expensive random number generator with a budget constraint. That is risk R-15.

The check costs an hour and is on E0's "never drop" list:

    Regress xP on (price, position). Report the R-squared and the within-price-tier spread of xP.

The response is decided here, in advance, rather than in the moment when the number is known and
the temptation to tune it is strongest:

=========  ============================================  =================================
R-squared  Meaning                                       Response
=========  ============================================  =================================
< 0.7      Real information beyond price                 Proceed
0.7 - 0.9  Thin, but signal in the residuals             Proceed; weight the review heavily
> 0.9      A repricing of FPL's own prices               Say so: this is budget allocation,
                                                         not a forecast
=========  ============================================  =================================

This is a finding to report, not a number to tune until it looks better.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import numpy as np
import pandas as pd

from fpl_dof.frames import as_float
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

THIN_SIGNAL_THRESHOLD = 0.7
REPRICING_THRESHOLD = 0.9


class PriceDependence(StrEnum):
    INFORMATIVE = "informative"
    THIN = "thin"
    REPRICING = "repricing"


@dataclass(frozen=True, slots=True)
class PriceRegression:
    """How much of xP is explained by price and position alone."""

    r_squared: float
    verdict: PriceDependence
    n: int
    within_tier_spread: dict[str, float]
    """Standard deviation of xP inside each position/price-tier bucket."""

    @property
    def message(self) -> str:
        if self.verdict is PriceDependence.INFORMATIVE:
            return (
                f"xP is only {self.r_squared:.1%} explained by price and position: the model is "
                "adding real information beyond price."
            )
        if self.verdict is PriceDependence.THIN:
            return (
                f"xP is {self.r_squared:.1%} explained by price and position. Thin, but there is "
                "signal in the residuals. Weight the human review gate more heavily."
            )
        return (
            f"xP is {self.r_squared:.1%} explained by price and position. THE FORECAST IS "
            "LARGELY A REPRICING OF FPL'S OWN PRICES. The squad that comes out of this is a "
            "budget-allocation exercise, not a forecast, and should be reviewed as one."
        )


def regress_xp_on_price(
    forecast: pd.DataFrame, *, value_column: str = "xp_horizon"
) -> PriceRegression:
    """Ordinary least squares of xP on price, with a per-position intercept and slope.

    Solved with ``numpy.linalg.lstsq`` on a small design matrix rather than pulling in a stats
    dependency: the model is four intercepts and four slopes, and the R-squared is the only number
    wanted out of it.
    """
    frame = forecast[[value_column, "price", "position"]].dropna()
    if len(frame) < 10:
        raise ValueError(f"only {len(frame)} rows: too few to regress")

    dummies = pd.get_dummies(frame["position"], prefix="pos", dtype=float)
    design = pd.concat([dummies, dummies.mul(frame["price"], axis=0).add_suffix("_price")], axis=1)
    x = design.to_numpy(dtype=float)
    y = frame[value_column].to_numpy(dtype=float)

    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ coefficients
    total = float(((y - y.mean()) ** 2).sum())
    r_squared = 1.0 - float((residual**2).sum()) / total if total > 0 else 0.0
    r_squared = max(0.0, min(1.0, r_squared))

    if r_squared > REPRICING_THRESHOLD:
        verdict = PriceDependence.REPRICING
    elif r_squared > THIN_SIGNAL_THRESHOLD:
        verdict = PriceDependence.THIN
    else:
        verdict = PriceDependence.INFORMATIVE

    spread: dict[str, float] = {}
    if "price_tier" in forecast.columns:
        grouped = forecast.groupby(
            [forecast["position"].astype(str), forecast["price_tier"].astype(int)], observed=True
        )[value_column].std()
        for key, value in grouped.items():
            position, tier = cast(tuple[str, int], key)
            spread[f"{position}|{tier}"] = as_float(value)

    result = PriceRegression(
        r_squared=r_squared, verdict=verdict, n=len(frame), within_tier_spread=spread
    )
    log.info(
        "diagnostics.price_regression",
        extra={"r_squared": round(r_squared, 4), "verdict": verdict.value, "n": len(frame)},
    )
    return result


def top_by_xp(
    forecast: pd.DataFrame, n: int = 20, *, value_column: str = "xp_horizon"
) -> pd.DataFrame:
    """The sanity check a human actually performs: are the top 20 recognisably plausible?"""
    columns = ["web_name", "position", "price", value_column, "start_probability", "confidence"]
    available = [column for column in columns if column in forecast.columns]
    return forecast.nlargest(n, value_column)[available].reset_index(drop=True)
