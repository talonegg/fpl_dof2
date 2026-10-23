"""The season log: what was played, what it scored, and what was advised, per gameweek (DL-69).

E8 §3 calls this "the single most valuable dataset the project produces about itself" — the record
that eventually answers whether the model or the owner's judgement is better, with evidence rather
than impression. Three sources, deliberately kept apart:

- **played** comes from ``entry_pick``, the game's own record of the submitted squad;
- **scored** comes from ``entry_gameweek``, the game's own points and ranks;
- **advised** comes from the ledger, the pipeline's own record written *before* the deadline.

Each row is the one the evaluation step stored when the gameweek was judged, once, after it
finished (ORC-05, ``ledger:evaluation/gwNN.json``); nothing here recomputes it. A gameweek not yet
evaluated has no row. A gameweek with picks and no ledger entry is published with ``advised: null``
and says so. The owner decided GW1 to GW4 of 2026/27 without the tool; that is a fact about the
season, and nothing reconstructs advice after the event, because advice reconstructed with
hindsight is not advice (DP-11, DP-13).

Pure (DP-03): evaluations in, one payload out.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_log(
    *,
    entry_id: int,
    season: str,
    evaluations: Mapping[int, Mapping[str, Any]],
    contract_version: int,
) -> dict[str, Any] | None:
    """The whole ``log.json`` payload, one row per evaluated gameweek of this owner's, or ``None``
    when there is none yet."""
    rows = [
        dict(e["log"])
        for _, e in sorted(evaluations.items())
        if e.get("entry_id") == entry_id and isinstance(e.get("log"), Mapping)
    ]
    if not rows:
        return None
    advised_count = sum(1 for row in rows if row["advised"] is not None)
    followed = sum(
        1
        for row in rows
        if row["reconciliation"] is not None and bool(row["reconciliation"]["followed"])
    )
    return {
        "contract_version": contract_version,
        "season": season,
        "entry_id": entry_id,
        "summary": {
            "gameweeks_played": len(rows),
            "gameweeks_advised": advised_count,
            "advice_followed": followed,
            "advice_overridden": advised_count - followed,
            "total_points": max(
                (int(row["score"]["total_points"]) for row in rows if row["score"]), default=0
            ),
        },
        "gameweeks": rows,
    }
