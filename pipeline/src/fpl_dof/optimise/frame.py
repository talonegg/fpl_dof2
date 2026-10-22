"""The forecast frame: what any forecaster must emit and the decision engine may read (MOD-02).

One row per player. The engine reads identity, the next-gameweek and horizon means, their standard
deviations, the per-gameweek means and deviations the horizon planner draws from, and
``start_probability``. Variance is not optional: a frame without it is refused here, before a solver
sees it, rather than read as certain (Invariant 6). Nothing is coerced — a frame that needs
coercing is a forecaster bug, and the place to find it is where it was made.

The captain rule's price-and-position line is deliberately not in the frame: captaincy is policy,
and its fitted line travels as its own input (:class:`fpl_dof.optimise.captain.PricePositionLine`,
DL-76). The strategy that produced the frame is stamped on every row by the factory
(``strategy``, ``strategy_digest``), so the stamp survives a parquet round trip.
"""

from __future__ import annotations

import pandas as pd
import pandera.errors
import pandera.pandas as pa

from fpl_dof.frames import GAMEWEEK_COLUMN_PREFIX, GAMEWEEK_SD_COLUMN_SUFFIX, horizon_gameweeks
from fpl_dof.rules.models import Position

#: Bumped when a column is removed, renamed or tightened; adding an optional column is not a bump.
FORECAST_FRAME_VERSION = 1

STRATEGY_COLUMN = "strategy"
STRATEGY_DIGEST_COLUMN = "strategy_digest"

_SD = pa.Check.ge(0)
_PROBABILITY = pa.Check.in_range(0.0, 1.0)


def _unpaired_gameweek_columns(frame: pd.DataFrame) -> list[str]:
    """Per-gameweek means without their sd, and sds without their mean."""
    means = {f"{GAMEWEEK_COLUMN_PREFIX}{week}" for week in horizon_gameweeks(frame)}
    sds = {
        str(c)
        for c in frame.columns
        if str(c).startswith(GAMEWEEK_COLUMN_PREFIX) and str(c).endswith(GAMEWEEK_SD_COLUMN_SUFFIX)
    }
    wanted = {f"{mean}{GAMEWEEK_SD_COLUMN_SUFFIX}" for mean in means}
    return sorted(
        (wanted - sds) | {sd.removesuffix(GAMEWEEK_SD_COLUMN_SUFFIX) for sd in sds - wanted}
    )


FORECAST_FRAME = pa.DataFrameSchema(
    {
        "player_id": pa.Column(checks=pa.Check.ge(1), unique=True),
        "player_code": pa.Column(required=False),
        "position": pa.Column(checks=pa.Check.isin([p.value for p in Position])),
        "team_id": pa.Column(checks=pa.Check.ge(1)),
        "price": pa.Column(checks=pa.Check.gt(0)),
        "xp_next": pa.Column(float),
        "xp_next_sd": pa.Column(float, _SD),
        "xp_horizon": pa.Column(float),
        "xp_horizon_sd": pa.Column(float, _SD),
        r"^xp_gw_\d+$": pa.Column(float, regex=True, required=False),
        r"^xp_gw_\d+_sd$": pa.Column(float, _SD, regex=True, required=False),
        "start_probability": pa.Column(float, _PROBABILITY),
        "start_floor": pa.Column(float, _PROBABILITY, required=False),
        r"^p_(no|short|long)_appearance$": pa.Column(
            float, _PROBABILITY, regex=True, required=False
        ),
        "expected_minutes": pa.Column(float, pa.Check.ge(0), required=False),
        r"^component_\w+$": pa.Column(float, regex=True, required=False),
        STRATEGY_COLUMN: pa.Column(str, pa.Check.str_length(min_value=1), required=False),
        STRATEGY_DIGEST_COLUMN: pa.Column(str, pa.Check.str_length(min_value=1), required=False),
    },
    coerce=False,
    strict=False,
)


class ForecastFrameError(ValueError):
    """The frame breaks the forecast-frame contract; the engine refuses to read it."""


def validate_forecast_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return ``frame`` untouched if it meets the contract, else raise :class:`ForecastFrameError`.

    Every failure is reported at once, each naming its column, so a broken forecaster is fixed in
    one pass rather than one column at a time.
    """
    problems = {f"missing column {column}" for column in _unpaired_gameweek_columns(frame)}
    try:
        FORECAST_FRAME.validate(frame, lazy=True)
    except pandera.errors.SchemaErrors as exc:
        cases = exc.failure_cases
        for (column, check), group in cases.groupby(["column", "check"], dropna=False):
            if check == "column_in_dataframe":
                problems.update(f"missing column {c}" for c in group["failure_case"])
            else:
                problems.add(
                    f"{column}: {check} fails on {len(group)} row(s), "
                    f"e.g. {group['failure_case'].iloc[0]}"
                )
    if problems:
        raise ForecastFrameError(
            f"forecast frame v{FORECAST_FRAME_VERSION} refused: " + "; ".join(sorted(problems))
        )
    return frame


__all__ = [
    "FORECAST_FRAME",
    "FORECAST_FRAME_VERSION",
    "STRATEGY_COLUMN",
    "STRATEGY_DIGEST_COLUMN",
    "ForecastFrameError",
    "validate_forecast_frame",
]
