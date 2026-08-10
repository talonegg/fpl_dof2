"""Reading and writing the silver tier.

Parquet, one file per canonical table, partitioned by season. Validation happens on the way in and
on the way out: a table that was written correctly can still be read back by code that expects a
column that has since been renamed, and finding that out at read time is much cheaper than finding
it out in a squad.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fpl_dof.silver.tables import SCHEMAS, Table, validate


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


def append_table(root: Path, season: str, table: Table, frame: pd.DataFrame) -> Path:
    """Append rows, keeping the last occurrence of each unique key.

    Used by tables that accumulate rather than being rebuilt — price and ownership history most of
    all, where the whole point is the days that have already gone by. Overwriting would silently
    destroy the only copy of them.
    """
    if frame.empty:
        return table_path(root, season, table)
    path = table_path(root, season, table)
    combined = frame
    if path.exists():
        combined = pd.concat([read_table(root, season, table), frame], ignore_index=True)
        keys = getattr(SCHEMAS[table].Config, "unique", None)
        if keys:
            combined = combined.drop_duplicates(subset=list(keys), keep="last")
    return write_table(root, season, table, combined)


def read_table_optional(root: Path, season: str, table: Table) -> pd.DataFrame | None:
    """``None`` when the table has never been written.

    Distinct from an empty frame on purpose: "no team ID is configured" and "the team has no picks"
    are different situations, and only the caller knows which of them is a problem.
    """
    if not table_path(root, season, table).exists():
        return None
    return read_table(root, season, table)


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
