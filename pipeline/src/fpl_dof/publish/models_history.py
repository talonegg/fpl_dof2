"""The models history (``models_history.json``, ORC-06).

How every registered strategy would have played an archive season in the standing backtest (FPL
auto-subs, vice-captain fallback, hits, no chips): the weekly backtest simulates each strategy's
season (:mod:`fpl_dof.factory.history`), records the history on ``ledger`` and the pipeline
publishes the latest. This module is the pure assembly step: ranks, cumulative totals, and paired
deltas against the champion with a seeded GW bootstrap. It scores nothing itself (DP-03).

The live season as if each model had played it (``as_if_played.json``, ORC-13, DL-97) is the same
document, ``kind`` ``in_sample``: today's models replayed on the season's finished gameweeks
(:mod:`fpl_dof.factory.as_if_played`). A model that could not play a gameweek has no entry in it
and its reason under the gameweek's ``unavailable``, so each gameweek is ranked among the models
that played it and each delta is over the gameweeks both played.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from fpl_dof.factory import bootstrap_ci
from fpl_dof.factory.registry import champion, resolve_alias, strategies

BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 0
#: ``as_if_played.json``'s caveat (DL-97), the label the app shows wherever its ladder is.
IN_SAMPLE_CAVEAT = (
    "In-sample: today's models replayed on past gameweeks; not evidence of skill. Each model, "
    "with the weights it is fitted with today, plays {season} from GW1 on its own squad, picked "
    "under the budget, with its own transfers, hits and chips, on the features, prices and "
    "fixtures known at each deadline. The evidence is the ladder of each model's advice on your "
    "squad and the backtest."
)


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
    in_sample: bool = False,
    skipped: Mapping[str, Mapping[int, str]] | None = None,
) -> dict[str, Any]:
    """Assemble the artefact from per-model decision rows keyed by strategy id or legacy alias.

    Each row: ``gw``, ``points`` (final XI after auto-subs incl. armband, net of hits),
    ``points_before_hits``, ``hit_points``, ``n_transfers``, ``transfers`` (list of str),
    ``captain``, ``vice_captain``, ``captain_points``, ``vice_used``, ``n_autosubs``, and ``chip``
    when one was played. A backtest compares only gameweeks every available model played, so ranks
    and deltas are paired; ``in_sample`` (the published models only) keeps every gameweek any model
    played or was ``skipped`` at (strategy id -> gameweek -> why).
    """
    rows = {sid: v for k, v in rows.items() if (sid := resolve_alias(k)) is not None}
    unavailable = {sid: v for k, v in unavailable.items() if (sid := resolve_alias(k)) is not None}
    registered = [s for s in strategies() if s.role != "retired" and (s.published or not in_sample)]
    champ_id = champion().id
    present = [s.id for s in registered if rows.get(s.id)]
    by_model = {m: {int(r["gw"]): r for r in rows[m]} for m in present}
    missed = {s.id: (skipped or {}).get(s.id, {}) for s in registered}
    if in_sample:
        gws = sorted(set().union(*by_model.values(), *missed.values()))
    else:
        gws = sorted(set.intersection(*(set(v) for v in by_model.values()))) if present else []

    cum = dict.fromkeys(present, 0.0)
    gameweeks: list[dict[str, Any]] = []
    ranks_by_gw: list[dict[str, int]] = []
    for gw in gws:
        at = [m for m in present if gw in by_model[m]]
        pts = {m: float(by_model[m][gw]["points"]) for m in at}
        for m in at:
            cum[m] += pts[m]
        gw_rank, cum_rank = _ranks(pts), _ranks({m: cum[m] for m in at})
        ranks_by_gw.append(gw_rank)
        entries = {}
        for m in at:
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
                **({"chip": str(r["chip"])} if r.get("chip") else {}),
            }
        gameweek: dict[str, Any] = {"gameweek": gw, "models": entries}
        if why := {m: str(r[gw]) for m, r in missed.items() if gw in r}:
            gameweek["unavailable"] = why
        gameweeks.append(gameweek)

    summary = []
    champ = by_model.get(champ_id, {})
    for m in present:
        series = [float(by_model[m][g]["points"]) for g in gws if g in by_model[m]]
        delta = None
        d = [
            float(by_model[m][g]["points"]) - float(champ[g]["points"])
            for g in gws
            if g in by_model[m] and g in champ
        ]
        if d and m != champ_id:
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
                "gameweeks_won": sum(1 for r in ranks_by_gw if r.get(m) == 1),
                "hit_points": float(
                    sum(float(by_model[m][g]["hit_points"]) for g in gws if g in by_model[m])
                ),
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
            else unavailable.get(s.id, f"Not simulated in {season}"),
        }
        for s in registered
    ]
    return {
        "contract_version": contract_version,
        "season": season,
        "kind": "in_sample" if in_sample else "backtest",
        "caveat": IN_SAMPLE_CAVEAT.format(season=season)
        if in_sample
        else (
            f"Backtest, not real play: a walk-forward replay of each strategy over {season}. Each "
            "starts at its first graded gameweek with its own fresh squad, uses no chips, and "
            "sees only data from before each deadline. Real results will differ."
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
