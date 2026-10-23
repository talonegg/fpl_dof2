"""The 2025/26 model-history artefact (``models_history_2526.json``).

How the five frozen models would have played 2025/26 in the realistic walk-forward backtest (FPL
auto-subs, vice-captain fallback, deadline availability, hits). CI cannot run the backtest, so the
artefact is built once, offline, from the backtest's per-GW decision rows and checked in. This
module is the pure assembly step: ranks, cumulative totals, and paired deltas against the champion
with a seeded GW bootstrap. It scores nothing itself (DP-03).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from fpl_dof.factory import bootstrap_ci
from fpl_dof.factory.registry import champion, resolve_alias, strategies

BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 0


def _ranks(values: Mapping[str, float]) -> dict[str, int]:
    """Competition ranking: 1 is best, ties share the better rank."""
    return {m: 1 + sum(1 for o in values.values() if o > v) for m, v in values.items()}


def build_models_history(
    *,
    season: str,
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    unavailable: Mapping[str, str],
    provenance: Mapping[str, Any],
    contract_version: int,
) -> dict[str, Any]:
    """Assemble the artefact from per-model decision rows keyed by strategy id or legacy alias.

    Each row: ``gw``, ``points`` (final XI after auto-subs incl. armband, net of hits),
    ``points_before_hits``, ``hit_points``, ``n_transfers``, ``transfers`` (list of str),
    ``captain``, ``vice_captain``, ``captain_points``, ``vice_used``, ``n_autosubs``.
    Only gameweeks every available model played are compared, so ranks and deltas are paired.
    """
    rows = {sid: v for k, v in rows.items() if (sid := resolve_alias(k)) is not None}
    unavailable = {sid: v for k, v in unavailable.items() if (sid := resolve_alias(k)) is not None}
    registered = strategies()
    champ_id = champion().id
    present = [s.id for s in registered if rows.get(s.id)]
    by_model = {m: {int(r["gw"]): r for r in rows[m]} for m in present}
    gws = sorted(set.intersection(*(set(v) for v in by_model.values()))) if present else []

    cum = dict.fromkeys(present, 0.0)
    gameweeks: list[dict[str, Any]] = []
    ranks_by_gw: list[dict[str, int]] = []
    for gw in gws:
        pts = {m: float(by_model[m][gw]["points"]) for m in present}
        for m in present:
            cum[m] += pts[m]
        gw_rank, cum_rank = _ranks(pts), _ranks(cum)
        ranks_by_gw.append(gw_rank)
        entries = {}
        for m in present:
            r = by_model[m][gw]
            entries[m] = {
                "points": pts[m],
                "points_before_hits": float(r["points_before_hits"]),
                "hit_points": float(r["hit_points"]),
                "n_transfers": int(r["n_transfers"]),
                "transfers": [str(t) for t in r.get("transfers", [])],
                "captain": str(r["captain"]),
                "vice_captain": str(r["vice_captain"]),
                "captain_points": float(r["captain_points"]),
                "vice_used": bool(r["vice_used"]),
                "n_autosubs": int(r["n_autosubs"]),
                "cumulative": cum[m],
                "rank": gw_rank[m],
                "cumulative_rank": cum_rank[m],
            }
        gameweeks.append({"gameweek": gw, "models": entries})

    summary = []
    champ = [float(by_model[champ_id][g]["points"]) for g in gws] if champ_id in present else []
    for m in present:
        series = [float(by_model[m][g]["points"]) for g in gws]
        delta = None
        if champ and m != champ_id:
            d = [a - b for a, b in zip(series, champ, strict=True)]
            lo, hi = (
                round(v, 2) for v in bootstrap_ci(d, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED)
            )
            delta = {
                "mean": round(float(np.mean(d)), 2),
                "ci_low": lo,
                "ci_high": hi,
                "total": float(sum(d)),
                "significant": bool(lo > 0 or hi < 0),
                "gameweeks_better": sum(1 for x in d if x > 0),
                "gameweeks_worse": sum(1 for x in d if x < 0),
            }
        summary.append(
            {
                "model": m,
                "total": float(sum(series)),
                "mean_per_gameweek": round(float(np.mean(series)), 2) if series else 0.0,
                "gameweeks_won": sum(1 for r in ranks_by_gw if r[m] == 1),
                "hit_points": float(sum(float(by_model[m][g]["hit_points"]) for g in gws)),
                "final_rank": _ranks(dict(cum))[m],
                "delta_vs_champion": delta,
            }
        )

    models = [
        {
            "id": s.id,
            "label": s.label,
            "role": s.role,
            "available": s.id in present,
            "unavailable_reason": None
            if s.id in present
            else unavailable.get(s.id, "No realistic 2025/26 run"),
        }
        for s in registered
    ]
    return {
        "contract_version": contract_version,
        "season": season,
        "kind": "backtest",
        "caveat": (
            "Backtest, not real play: a walk-forward replay of the frozen models over a finished "
            "season. Each model starts 2025/26 with its own fresh squad, uses no chips, and sees "
            "only data from before each deadline. Real results will differ."
        ),
        "champion": champ_id,
        "provenance": dict(provenance),
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "unit": "gameweek",
            "level": 0.95,
        },
        "models": models,
        "gameweeks": gameweeks,
        "summary": summary,
    }
