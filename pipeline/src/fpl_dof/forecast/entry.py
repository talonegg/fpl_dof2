"""The factory's forecast entry point: :func:`publishable` (MOD-02, 03 §12 P6).

**Which model runs.** ``xp_v1`` — the component chain the walk-forward backtest grades — publishes,
and ``xp_v0`` is the cold-start fallback and nothing else (DL-46, closing D-25). The fallback fires
only when the current season is too young for M1-M8 to be fitted, and when it fires it says so: in
the log, in the stage metrics, in the model card, and in the ``model`` column of the frame. A silent
fallback would be a season spent looking at a model nobody chose (DP-15).

The choice lives here, not in the stage, so "which model is the app showing" is answerable without
a pipeline context (DP-03); the forecast stage only calls this and writes what it returns.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast import live, xp_v0
from fpl_dof.forecast.baselines import FittedBaseline
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.captain import PricePositionLine
from fpl_dof.optimise.frame import validate_forecast_frame
from fpl_dof.rules.models import GameRules, Position

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Forecast:
    """The frame, the provenance of which model produced it, and the captain policy's input."""

    frame: pd.DataFrame
    model: str
    fallback_reason: str | None
    component_description: dict[str, object] | None = None
    """The fitted component chain's own account of itself (``ComponentModels.describe()``),
    carried off ``frame.attrs``. ``None`` for ``xp_v0``, which has no component chain to describe —
    a cold-start fallback's card should not imply one (DP-15)."""
    captain_line: PricePositionLine | None = None
    """B0 fitted on the same window as the model, for the price-and-position captain rule (DL-76).
    ``None`` when nothing has been played to fit it on."""


def publishable(inputs: ForecastInputs, rules: GameRules, config: ForecastConfig) -> Forecast:
    """Run ``xp_v1``, or ``xp_v0`` and a stated reason; the frame is validated before it leaves."""
    reason = _cold_start_reason(inputs, config)
    if reason is None:
        try:
            frame, b0 = live.build(inputs, rules, config)
        except live.ColdStartError as exc:
            reason = str(exc)
        else:
            description = frame.attrs.get("component_description")
            frame["model"] = live.MODEL_NAME
            return Forecast(
                frame=validate_forecast_frame(frame),
                model=live.MODEL_NAME,
                fallback_reason=None,
                component_description=description if isinstance(description, dict) else None,
                captain_line=_captain_line(b0),
            )

    log.warning(
        "forecast.cold_start_fallback",
        extra={"model": xp_v0.MODEL_NAME, "instead_of": live.MODEL_NAME, "reason": reason},
    )
    frame = xp_v0.build_forecast(inputs, rules, config)
    frame["model"] = xp_v0.MODEL_NAME
    return Forecast(
        frame=validate_forecast_frame(frame),
        model=xp_v0.MODEL_NAME,
        fallback_reason=reason,
        captain_line=_captain_line(xp_v0.fit_captain_line(inputs)),
    )


def _captain_line(b0: FittedBaseline | None) -> PricePositionLine | None:
    if b0 is None:
        return None
    return PricePositionLine(
        intercept_by_position={Position(p): v for p, v in b0.intercept_by_position.items()},
        slope_by_position={Position(p): v for p, v in b0.slope_by_position.items()},
        fallback=b0.global_mean,
    )


def _cold_start_reason(inputs: ForecastInputs, config: ForecastConfig) -> str | None:
    """Why the component chain cannot be trusted yet, or ``None`` if it can."""
    minimum = config.published.cold_start_minimum_gameweeks
    try:
        _, deadline, _ = live.next_deadline(inputs.gameweeks, config, as_of=inputs.as_of)
    except live.ColdStartError as exc:
        return str(exc)
    played = live.completed_gameweeks(inputs.player_gameweek, before=deadline)
    if played >= minimum:
        return None
    return (
        f"{played} completed gameweek(s) of 2026/27 history, below the {minimum} the component "
        "chain needs before its fitted rates say more than its priors do"
    )


__all__ = ["Forecast", "publishable"]
