"""Model benchmark accuracy: all-player xP MAE per strategy, keyed by registry id (MOD-03)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fpl_dof.factory.registry import strategies
from fpl_dof.publish.contract import CONTRACT_VERSION

#: The 2025/26 backtest's xP accuracy: a frozen-era record nothing in the repository can rebuild
#: (DL-94), so every published ``xp_accuracy.json`` carries it forward (WEB-04).
XP_ACCURACY_RECORD = Path(__file__).parent / "records" / "xp_accuracy_2025-26.json"


def build_live_xp_accuracy(
    season: str,
    evaluations: Mapping[int, Mapping[str, Any]],
    *,
    contract_version: int = CONTRACT_VERSION,
) -> dict[str, Any] | None:
    """The live season's ``xp_accuracy.json``: each evaluated gameweek's MAE per strategy, from the
    xP it recorded before the deadline (ORC-05, ORC-08). ``None`` before any gameweek has one.

    Published beside the 2025/26 record by ``with_record``.
    """
    gws: dict[int, dict[str, float]] = {}
    tot: dict[str, list[float]] = {}
    for gw, evaluation in sorted(evaluations.items()):
        for sid, judged in (evaluation.get("strategies") or {}).items():
            acc = judged.get("xp_accuracy") or {}
            if acc.get("mae") is None:
                continue
            gws.setdefault(gw, {})[sid] = float(acc["mae"])
            t = tot.setdefault(sid, [0.0, 0.0])
            t[0] += float(acc["mae"]) * int(acc["players"])
            t[1] += int(acc["players"])
    if not gws:
        return None
    return {
        "contract_version": contract_version,
        "metric": "all-player MAE of next-GW xP vs actual FPL points (lower is better)",
        "seasons": [
            {
                "season": season,
                "kind": "prospective",
                "gameweeks": [
                    {"gameweek": g, "phase": "prospective", "mae": gws[g]} for g in sorted(gws)
                ],
                "pooled_mae": {m: round(s / n, 4) for m, (s, n) in tot.items() if n},
                "missing_models": {
                    m: "no recorded predictions"
                    for m in (x.id for x in strategies())
                    if m not in tot
                },
            }
        ],
    }


def with_record(
    live: Mapping[str, Any] | None, *, contract_version: int = CONTRACT_VERSION
) -> dict[str, Any]:
    """The recorded seasons, then the live ones; a live season replaces a recorded one of the same
    season and kind."""
    record: dict[str, Any] = json.loads(XP_ACCURACY_RECORD.read_text(encoding="utf-8"))
    seasons = list(live["seasons"]) if live else []
    fresh = {(s["season"], s["kind"]) for s in seasons}
    kept = [s for s in record["seasons"] if (s["season"], s["kind"]) not in fresh]
    return {**record, "contract_version": contract_version, "seasons": [*kept, *seasons]}


__all__ = ["XP_ACCURACY_RECORD", "build_live_xp_accuracy", "with_record"]
