"""Captain and vice by the price+position rule (C3) — a policy, not a forecast (DL-76, MOD-02).

The walk-forward decision backtest found the solver's own captain — the highest ``xp_next`` in the
XI — skews to goalkeepers and defenders and loses about two points a week to a far simpler rule:
fit B0 (one least-squares line from price to points per position) on history, score every starter
with it, captain the highest and vice the next. The XI and the transfers are unchanged; only the
armband moves.

B0 is fitted by the model factory, on the forecaster's own training window, and handed to this rule
as a :class:`PricePositionLine`: the fitted coefficients, validated on their own, never a column of
the forecast frame. The rule applies them to the frame's price and position. Which rule a strategy
uses is its registry ``policy.captain_rule``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pandas as pd
from pydantic import BaseModel, ConfigDict

from fpl_dof.frames import as_float, as_int
from fpl_dof.optimise.transfer import TransferOption, TransferRecommendation
from fpl_dof.rules.models import Position
from fpl_dof.squad.selection import Selection


class PricePositionLine(BaseModel):
    """B0, fitted: points as a line in price, one per position. The captain policy's input."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    intercept_by_position: dict[Position, float]
    slope_by_position: dict[Position, float]
    fallback: float
    """For a position the fit never saw, or a missing price: the training mean, as B0 predicts."""

    def scores(self, frame: pd.DataFrame) -> dict[int, float]:
        """B0's score per ``player_id``, from the frame's ``price`` and ``position``."""
        positions = frame["position"].astype(str)
        intercept = positions.map({p.value: v for p, v in self.intercept_by_position.items()})
        slope = positions.map({p.value: v for p, v in self.slope_by_position.items()})
        price = pd.to_numeric(frame["price"], errors="coerce").astype(float)
        predicted = (intercept.astype(float) + slope.astype(float) * price).fillna(self.fallback)
        return {as_int(i): float(v) for i, v in zip(frame["player_id"], predicted, strict=True)}


def pick_captains(starting: tuple[int, ...], scores: Mapping[int, float]) -> tuple[int, int]:
    """Highest score captains, next highest vices. Ties break on the lower id, for determinism."""
    ranked = sorted(starting, key=lambda i: (-scores.get(i, float("-inf")), i))
    return ranked[0], ranked[1] if len(ranked) > 1 else ranked[0]


def relabel_option(
    option: TransferOption,
    scores: Mapping[int, float],
    xp_next: Mapping[int, float],
    captain_multiplier: int,
) -> TransferOption:
    captain, vice = pick_captains(option.starting, scores)
    gross = sum(xp_next.get(i, 0.0) for i in option.starting)
    gross += xp_next.get(captain, 0.0) * (captain_multiplier - 1)
    return replace(
        option, captain_id=captain, vice_captain_id=vice, gross_expected_points=round(gross, 4)
    )


def apply_price_position_captain(
    recommendation: TransferRecommendation,
    forecast: pd.DataFrame,
    scores: Mapping[int, float],
    captain_multiplier: int,
) -> TransferRecommendation:
    """Re-pick captain/vice on every option, after the transfer choice — as the backtest did.

    The choice between options is left exactly as the engine made it (on its own captain), so the
    shipped behaviour is the one that was measured. Each option's ``gross_expected_points`` is then
    restated with the new captain so the numbers on screen match the armband shown.
    """
    xp = {as_int(r.player_id): as_float(r.xp_next) for r in forecast.itertuples()}
    chosen = recommendation.options.index(recommendation.recommended)
    options = tuple(
        relabel_option(o, scores, xp, captain_multiplier) for o in recommendation.options
    )
    return replace(recommendation, options=options, recommended=options[chosen])


def relabel_selection(
    selection: Selection,
    scores: Mapping[int, float],
    xp_next: Mapping[int, float],
    captain_multiplier: int,
) -> Selection:
    """The published XI's armband, by the same rule. The XI itself is not touched."""
    captain, vice = pick_captains(selection.starting, scores)
    expected = sum(xp_next.get(i, 0.0) for i in selection.starting)
    expected += xp_next.get(captain, 0.0) * (captain_multiplier - 1)
    return replace(
        selection, captain=captain, vice_captain=vice, expected_points=round(expected, 3)
    )
