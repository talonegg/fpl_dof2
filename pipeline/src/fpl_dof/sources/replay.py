"""Deterministic replay of price and ownership history from bronze snapshots.

PIPE-06, DP-11: Given retained bronze bootstrap snapshots, reconstructs
price_history.parquet deterministically with canonical sorting.
Placed in sources/ per Invariant 1: only sources/ may know about source names
and endpoint structures.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from fpl_dof.silver.store import read_table_optional, write_table
from fpl_dof.silver.tables import Table
from fpl_dof.sources.bronze import META_SUFFIX, SNAPSHOT_SUFFIX, SnapshotMeta


def extract_price_history_rows(
    bootstrap: dict[str, Any], observed_at: pd.Timestamp
) -> list[dict[str, Any]]:
    """Extract price and ownership history rows for all active elements."""
    game_settings = bootstrap.get("game_settings") or {}
    multiplier = game_settings.get("ui_currency_multiplier") or 10.0
    divisor = float(multiplier)
    elements = bootstrap.get("elements") or []
    return [
        {
            "observed_at": observed_at,
            "player_id": int(element["id"]),
            "player_code": int(element["code"]),
            "price": float(element["now_cost"]) / divisor,
            "selected_by_percent": float(element.get("selected_by_percent") or 0.0),
            "transfers_in_event": int(element.get("transfers_in_event") or 0),
            "transfers_out_event": int(element.get("transfers_out_event") or 0),
            "cost_change_event": float(element.get("cost_change_event") or 0) / divisor,
            "cost_change_start": float(element.get("cost_change_start") or 0) / divisor,
        }
        for element in elements
        if not element.get("removed")
    ]


def season_from_bootstrap(bootstrap: dict[str, Any]) -> str | None:
    events = bootstrap.get("events") or []
    if not events:
        return None
    start = pd.Timestamp(events[0]["deadline_time"]).tz_convert("UTC")
    year = int(start.year) if int(start.month) >= 7 else int(start.year) - 1
    return f"{year}/{str(year + 1)[-2:]}"


def replay_prices(
    bronze_root: Path,
    silver_root: Path,
    *,
    clean: bool = False,
) -> dict[str, int]:
    """Iterate through all retained bootstrap snapshots in chronological order
    and rebuild price_history.parquet deterministically (DP-11)."""
    bootstrap_dir = bronze_root / "fpl" / "bootstrap_static"
    if not bootstrap_dir.is_dir():
        return {"snapshots_processed": 0, "rows_written": 0}

    candidates = sorted(
        p
        for p in bootstrap_dir.glob(f"*/*{SNAPSHOT_SUFFIX}")
        if not p.name.endswith(META_SUFFIX)
    )

    frames_by_season: dict[str, list[pd.DataFrame]] = defaultdict(list)
    processed_count = 0

    for path in candidates:
        meta_path = path.with_name(path.name + META_SUFFIX)
        if not meta_path.exists():
            continue
        try:
            meta = SnapshotMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
            with gzip.open(path, "rb") as handle:
                bootstrap = json.loads(handle.read().decode("utf-8"))
        except Exception:
            continue

        season = season_from_bootstrap(bootstrap)
        if not season:
            continue

        observed_at = pd.Timestamp(meta.fetched_at).tz_convert("UTC")
        rows = extract_price_history_rows(bootstrap, observed_at)
        if rows:
            frames_by_season[season].append(pd.DataFrame(rows))
            processed_count += 1

    total_rows = 0
    for season, frames in frames_by_season.items():
        combined = pd.concat(frames, ignore_index=True)
        if not clean:
            existing = read_table_optional(silver_root, season, Table.PRICE_HISTORY)
            if existing is not None and not existing.empty:
                combined = pd.concat([existing, combined], ignore_index=True)

        combined = combined.drop_duplicates(subset=["observed_at", "player_id"], keep="last")
        combined = combined.sort_values(["observed_at", "player_id"]).reset_index(drop=True)
        write_table(silver_root, season, Table.PRICE_HISTORY, combined)
        total_rows += len(combined)

    return {"snapshots_processed": processed_count, "rows_written": total_rows}
