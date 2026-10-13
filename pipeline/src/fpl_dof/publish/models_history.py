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

#: Web model id -> (label, role). Display order; the champion is first.
HISTORY_MODELS: tuple[tuple[str, str, str], ...] = (
    ("champion", "Champion (C3)", "champion"),
    ("challenger", "Challenger (C1)", "challenger"),
    ("engine", "Engine", "comparison"),
    ("a", "Model A", "comparison"),
    ("a_odds", "A + odds", "comparison"),
)
CHAMPION = "champion"
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 0


def bootstrap_ci(
    deltas: Sequence[float], draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float]:
    """95% iid GW-bootstrap CI of the mean. Seeded, so the checked-in artefact is reproducible."""
    x = np.asarray(deltas, dtype=float)
    if x.size == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(draws, x.size), replace=True).mean(axis=1)
    return (round(float(np.quantile(means, 0.025)), 2), round(float(np.quantile(means, 0.975)), 2))


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
    """Assemble the artefact from per-model decision rows keyed by web model id.

    Each row: ``gw``, ``points`` (final XI after auto-subs incl. armband, net of hits),
    ``points_before_hits``, ``hit_points``, ``n_transfers``, ``transfers`` (list of str),
    ``captain``, ``vice_captain``, ``captain_points``, ``vice_used``, ``n_autosubs``.
    Only gameweeks every available model played are compared, so ranks and deltas are paired.
    """
    present = [m for m, *_ in HISTORY_MODELS if rows.get(m)]
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
    champ = [float(by_model[CHAMPION][g]["points"]) for g in gws] if CHAMPION in present else []
    for m in present:
        series = [float(by_model[m][g]["points"]) for g in gws]
        delta = None
        if champ and m != CHAMPION:
            d = [a - b for a, b in zip(series, champ, strict=True)]
            lo, hi = bootstrap_ci(d)
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
            "id": m,
            "label": label,
            "role": role,
            "available": m in present,
            "unavailable_reason": None
            if m in present
            else unavailable.get(m, "No realistic 2025/26 run"),
        }
        for m, label, role in HISTORY_MODELS
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
        "champion": CHAMPION,
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
