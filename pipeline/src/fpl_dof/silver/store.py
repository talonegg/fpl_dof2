"""Reading and writing the silver tier.

Parquet, one file per canonical table, partitioned by season. Validation happens on the way in and
on the way out: a table that was written correctly can still be read back by code that expects a
column that has since been renamed, and finding that out at read time is much cheaper than finding
it out in a squad.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fpl_dof.silver.tables import Table, validate


def table_path(root: Path, season: str, table: Table) -> Path:
    """``silver/season=2026-27/player.parquet``.

    The season is slugified because ``/`` in ``2026/27`` is a path separator, which is precisely
    the sort of thing that silently creates a directory nobody expects.
    """
    return root / f"season={season.replace('/', '-')}" / f"{table.value}.parquet"


def write_table(root: Path, season: str, table: Table, frame: pd.DataFrame) -> Path:
    validated = validate(table, frame)
    path = table_path(root, season, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    validated.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
    return path


def read_table(root: Path, season: str, table: Table) -> pd.DataFrame:
    path = table_path(root, season, table)
    if not path.exists():
        raise FileNotFoundError(
            f"silver table {table.value!r} is missing for season {season!r} at {path}; "
            "run `fpl-dof transform` first"
        )
    # engine is left at "auto": pyarrow is the only engine installed, and pinning it here trips a
    # pandas-stubs overload that demands to_pandas_kwargs alongside an explicit "pyarrow".
    return validate(table, pd.read_parquet(path))
