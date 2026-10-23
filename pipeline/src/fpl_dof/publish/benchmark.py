"""Model benchmark accuracy: all-player xP MAE per strategy, keyed by registry id (MOD-03)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fpl_dof.factory.registry import strategies
from fpl_dof.publish.contract import CONTRACT_VERSION


def build_live_xp_accuracy(
    season: str,
    evaluations: Mapping[int, Mapping[str, Any]],
    *,
    contract_version: int = CONTRACT_VERSION,
) -> dict[str, Any] | None:
    """The live season's ``xp_accuracy.json``: each evaluated gameweek's MAE per strategy, from the
    xP it recorded before the deadline (ORC-05, ORC-08). ``None`` before any gameweek has one.

    The app shows it beside the checked-in 2025/26 backtest and 2026/27 replay seasons.
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


__all__ = ["build_live_xp_accuracy"]
