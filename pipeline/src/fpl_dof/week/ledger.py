"""The advice ledger: what the pipeline advised, per gameweek, kept after the fact (DL-69).

E1-S5's reconciliation compares last week's advice with what was played. Advice used to live only
in the previous ``week.json``, which the next run overwrote and which CI never had at all — every
CI run starts from a fresh checkout, so in production the comparison had never once happened.

The ledger fixes the *persistence*, not the comparison. One file per gameweek advised. Each
strategy's entry is its **advice of record**: its last success before the deadline (DL-94). A later
failure never replaces it; it is noted beside it as ``last_failure``. A strategy that has not yet
succeeded records "no advice" with its reason. The record closes at the deadline: a write for a
gameweek whose deadline has passed is refused by the writer, not merely avoided because ``week``
has moved on. That is what makes it evidence rather than recollection (E8 §3).

Pure functions over a directory (DP-03). The git plumbing that makes the directory durable in CI
lives in ``pipeline/scripts/retention.py``, which already keeps the ``snapshots`` branch the same
way.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.paths import DataLayout

log = get_logger(__name__)

ADVICE_DIRECTORY = "advice"
PREDICTIONS_DIRECTORY = "predictions"
#: The forecast frame's own names, kept as they are: the mean and standard deviation of the
#: gameweek being decided, and P(plays). Variance is not optional (Invariant 6).
PREDICTION_COLUMNS = ("player_id", "xp_next", "xp_next_sd", "start_probability")


def advice_path(layout: DataLayout, gameweek: int) -> Path:
    """``<data>/ledger/advice/gw05.json`` — two digits so the directory lists in order."""
    return layout.ledger / ADVICE_DIRECTORY / f"gw{gameweek:02d}.json"


def record_advice(
    layout: DataLayout,
    week_payload: Mapping[str, Any],
    as_of: dt.datetime,
    *,
    now: dt.datetime,
) -> Path | None:
    """Write the ``advised`` block of a week payload to the ledger, keyed by its gameweek.

    Returns the path written, or ``None`` when nothing was written: a skipped week, a gameweek
    whose deadline has passed at ``now`` (the real time, from the edge), or a write older than the
    entry already held. Each strategy under ``models`` is merged with what is held (see
    :func:`merge_models`). The whole recommendation is kept alongside the advised XI, because
    "why" is as much a part of the record as "what" (DP-09), and the run id ties it to its
    manifest (DP-11).
    """
    advised = week_payload.get("advised")
    if not isinstance(advised, Mapping) or "gameweek" not in advised:
        return None
    gameweek = int(advised["gameweek"])
    deadline = _deadline(week_payload)
    if deadline is None or now >= deadline:
        log.warning(
            "ledger.closed",
            extra={"gameweek": gameweek, "deadline": str(deadline), "now": now.isoformat()},
        )
        return None
    held = read_advice(layout, gameweek)
    if held is not None and _parse(held.get("recorded_at")) > as_of:
        log.info("ledger.older_write_ignored", extra={"gameweek": gameweek})
        return None
    entry = {
        "gameweek": gameweek,
        "run_id": week_payload.get("run_id"),
        "recorded_at": _iso(as_of),
        "trigger": week_payload.get("trigger"),
        "advised": dict(advised),
        "recommendation": week_payload.get("recommendation"),
        "squad_state": week_payload.get("squad_state"),
    }
    if "models" in week_payload:
        entry["models"] = merge_models((held or {}).get("models") or {}, week_payload["models"])
    path = advice_path(layout, gameweek)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    log.info("ledger.advice_recorded", extra={"gameweek": gameweek, "path": str(path)})
    return path


def predictions_path(layout: DataLayout, gameweek: int, strategy_id: str) -> Path:
    """``ledger/predictions/gw05/c3.parquet``: one file per strategy and gameweek (ORC-08)."""
    return layout.ledger / PREDICTIONS_DIRECTORY / f"gw{gameweek:02d}" / f"{strategy_id}.parquet"


def record_predictions(
    layout: DataLayout,
    gameweek: int,
    strategy_id: str,
    frame: pd.DataFrame,
    *,
    deadline: dt.datetime,
    now: dt.datetime,
) -> Path | None:
    """Write a strategy's full-pool forecast for the gameweek it advised, as advice is written.

    Called only for a strategy that advised, so a failure never reaches it and the last success
    stays in place. Refused at or after the deadline, exactly as advice is.
    """
    if now >= deadline:
        log.warning("ledger.closed", extra={"gameweek": gameweek, "what": "predictions"})
        return None
    path = predictions_path(layout, gameweek, strategy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[list(PREDICTION_COLUMNS)].to_parquet(path, index=False)
    return path


def read_predictions(layout: DataLayout, gameweek: int) -> dict[str, pd.DataFrame]:
    """Every strategy's recorded forecast for ``gameweek``, keyed by strategy id; empty if none."""
    directory = predictions_path(layout, gameweek, "_").parent
    return {p.stem: pd.read_parquet(p) for p in sorted(directory.glob("*.parquet"))}


def merge_models(held: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    """Each strategy's advice of record: replaced by a success, never by a failure (DL-94).

    A failure over a held success keeps the success and notes ``last_failure {as_of, reason}``
    beside it; a failure with no success held is "no advice", and keeps ``since``, the ``as_of``
    of the first failure in the run of them, so the app can say how long it has waited (ORC-07).
    A strategy this write does not mention keeps what is held.
    """
    merged = dict(held)
    for strategy_id, entry in new.items():
        prior = held.get(strategy_id)
        if "advised" not in entry and isinstance(prior, Mapping) and "advised" in prior:
            failure = {"as_of": entry.get("as_of"), "reason": entry.get("no_advice")}
            merged[strategy_id] = dict(prior) | {"last_failure": failure}
        elif "advised" not in entry and isinstance(prior, Mapping) and "no_advice" in prior:
            since = prior.get("since") or prior.get("as_of") or entry.get("as_of")
            merged[strategy_id] = dict(entry) | {"since": since}
        else:
            merged[strategy_id] = dict(entry)
    return merged


def _deadline(week_payload: Mapping[str, Any]) -> dt.datetime | None:
    """The advised gameweek's deadline; ``None`` (the record cannot be shown open) when absent."""
    deadline = week_payload.get("deadline")
    raw = deadline.get("deadline_utc") if isinstance(deadline, Mapping) else None
    return _parse(raw) if raw else None


def _parse(raw: object) -> dt.datetime:
    """An ISO instant; an absent one is the earliest, so any write is newer than it."""
    if not raw:
        return dt.datetime.min.replace(tzinfo=dt.UTC)
    return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


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
