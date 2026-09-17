"""The advice ledger: what the pipeline advised, per gameweek, kept after the fact (DL-69).

E1-S5's reconciliation compares last week's advice with what was played. Advice used to live only
in the previous ``week.json``, which the next run overwrote and which CI never had at all — every
CI run starts from a fresh checkout, so in production the comparison had never once happened.

The ledger fixes the *persistence*, not the comparison. One file per gameweek advised, written
every time ``week`` produces a recommendation for that gameweek and therefore holding the last
advice published before its deadline. After the deadline ``week`` advises the next gameweek, so
the file is never touched again: that is what makes it evidence rather than recollection (E8 §3).

Pure functions over a directory (DP-03). The git plumbing that makes the directory durable in CI
lives in ``pipeline/scripts/retention.py``, which already keeps the ``snapshots`` branch the same
way.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.paths import DataLayout

log = get_logger(__name__)

ADVICE_DIRECTORY = "advice"


def advice_path(layout: DataLayout, gameweek: int) -> Path:
    """``<data>/ledger/advice/gw05.json`` — two digits so the directory lists in order."""
    return layout.ledger / ADVICE_DIRECTORY / f"gw{gameweek:02d}.json"


def record_advice(layout: DataLayout, week_payload: Mapping[str, Any]) -> Path | None:
    """Write the ``advised`` block of a week payload to the ledger, keyed by its gameweek.

    Returns the path written, or ``None`` when the payload carries no advice (a skipped week).
    The whole recommendation is kept alongside the advised XI, because "why" is as much a part of
    the record as "what" (DP-09), and the run id ties it back to its manifest (DP-11).
    """
    advised = week_payload.get("advised")
    if not isinstance(advised, Mapping) or "gameweek" not in advised:
        return None
    gameweek = int(advised["gameweek"])
    entry = {
        "gameweek": gameweek,
        "run_id": week_payload.get("run_id"),
        "recorded_at": utcnow().isoformat().replace("+00:00", "Z"),
        "advised": dict(advised),
        "recommendation": week_payload.get("recommendation"),
        "squad_state": week_payload.get("squad_state"),
    }
    path = advice_path(layout, gameweek)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    log.info("ledger.advice_recorded", extra={"gameweek": gameweek, "path": str(path)})
    return path


def read_advice(layout: DataLayout, gameweek: int) -> dict[str, Any] | None:
    """The ledger entry for one gameweek, or ``None`` when nothing was ever advised for it.

    An unreadable file is reported and treated as absent rather than raised: the ledger is
    evidence about the past, and a corrupt entry must not stop this week's decision (DP-15).
    """
    path = advice_path(layout, gameweek)
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("ledger.unreadable", extra={"path": str(path), "detail": str(exc)})
        return None
    if not isinstance(loaded, dict) or int(loaded.get("gameweek", -1)) != gameweek:
        log.warning("ledger.mismatched", extra={"path": str(path)})
        return None
    return loaded


def read_all_advice(layout: DataLayout) -> dict[int, dict[str, Any]]:
    """Every ledger entry, keyed by gameweek. Empty when nothing has been advised yet."""
    directory = layout.ledger / ADVICE_DIRECTORY
    if not directory.is_dir():
        return {}
    entries: dict[int, dict[str, Any]] = {}
    for path in sorted(directory.glob("gw*.json")):
        try:
            gameweek = int(path.stem.removeprefix("gw"))
        except ValueError:
            continue
        loaded = read_advice(layout, gameweek)
        if loaded is not None:
            entries[gameweek] = loaded
    return entries
