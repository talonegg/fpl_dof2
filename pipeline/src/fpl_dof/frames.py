"""Narrowing helpers for pandas values.

``pandas-stubs`` types scalar access — ``df.loc[i, c]``, ``series.max()``, a groupby key — as a
very wide union covering timestamps, bytes and complex numbers. That is correct in general and
useless here, where the value is always a number we are about to do arithmetic on.

Rather than scatter a ``# type: ignore`` at every call site, the narrowing happens once, here,
where it is visible and can be reasoned about.
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd


def as_int(value: Any) -> int:
    """Read a pandas scalar as an int."""
    return int(cast(int, value))


def as_float(value: Any) -> float:
    """Read a pandas scalar as a float."""
    return float(cast(float, value))


def cell(frame: pd.DataFrame, row: int, column: str) -> float:
    """Read one numeric cell as a float."""
    return as_float(frame.loc[row, column])


def series_map(result: Any) -> pd.Series:
    """Treat a groupby-apply result as the Series it is."""
    return cast(pd.Series, result)


GAMEWEEK_COLUMN_PREFIX = "xp_gw_"
GAMEWEEK_SD_COLUMN_SUFFIX = "_sd"


def gameweek_column(gameweek: int) -> str:
    """Column carrying expected points for one gameweek: ``μ[p,w]`` in Design §6.2.

    Named in one place because the forecast writes it and the multi-gameweek optimiser reads it,
    and a string literal agreed by coincidence in two packages is a contract nobody can see.
    """
    return f"{GAMEWEEK_COLUMN_PREFIX}{gameweek}"


def gameweek_sd_column(gameweek: int) -> str:
    """Column carrying the standard deviation for one gameweek: ``sigma[p,w]`` (Invariant 6)."""
    return f"{gameweek_column(gameweek)}{GAMEWEEK_SD_COLUMN_SUFFIX}"


def horizon_gameweeks(frame: pd.DataFrame) -> tuple[int, ...]:
    """Gameweeks the frame carries per-gameweek expected points for, in order."""
    found = []
    for column in frame.columns:
        name = str(column)
        if not name.startswith(GAMEWEEK_COLUMN_PREFIX) or name.endswith(GAMEWEEK_SD_COLUMN_SUFFIX):
            continue
        suffix = name.removeprefix(GAMEWEEK_COLUMN_PREFIX)
        if suffix.isdigit():
            found.append(int(suffix))
    return tuple(sorted(found))
