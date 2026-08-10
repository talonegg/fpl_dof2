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
