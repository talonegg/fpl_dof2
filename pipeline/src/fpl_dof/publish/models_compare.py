"""The five-model comparison artefact (``models.json``).

Generalises ``week_challenger.json``: rather than one extra model in week.json's schema, every
frozen model's pre-deadline advice per gameweek, the points each actually scored once the gameweek
is finished, and a season-to-date table. Before a gameweek's frozen decision exists, a dry-run
preview of each model's current advice may stand in for it, flagged ``provisional``.

**This module scores nothing.** The advice is what the prospective harness recorded *before* each
deadline (``decisions/GW{n}.json``) and the points are what its scorer wrote afterwards
(``scores.csv``: final XI after auto-subs, armband with vice fallback, plus hits). Re-deriving
either here would be a second opinion that could disagree with the frozen record, so this is
assembly only.

Pure: no I/O, no clock. The stage reads the files and hands their contents in (DP-03).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fpl_dof.publish.benchmark import (
    CHAMPION_KEY,
    MODEL_REGISTRY,
)
from fpl_dof.publish.benchmark import (
    REGISTRY_BY_KEY as _BY_KEY,
)


def _element(code: Any, code_to_element: Mapping[str, Any]) -> int | None:
    """Harness picks are keyed by player *code*; the app looks players up by element id."""
    if code is None:
        return None
    found = code_to_element.get(str(code))
    return int(found) if found is not None else None


def _elements(codes: Sequence[Any], code_to_element: Mapping[str, Any]) -> list[int]:
    """Element ids for a list of codes; a code the game no longer lists is dropped, not guessed."""
    return [e for e in (_element(c, code_to_element) for c in codes) if e is not None]


def _advice(pick: Mapping[str, Any], c2e: Mapping[str, Any]) -> dict[str, Any]:
    bench_codes = ([pick["bench_gk"]] if pick.get("bench_gk") is not None else []) + list(
        pick.get("bench_order", [])
    )
    return {
        "transfers": [
            {
                "out": _element(t.get("out"), c2e),
                "out_name": str(t.get("out_name", "")),
                "in": _element(t.get("in"), c2e),
                "in_name": str(t.get("in_name", "")),
            }
            for t in pick.get("transfers", [])
        ],
        "n_transfers": int(pick.get("n_transfers", 0)),
        "hit_points": int(pick.get("hit_points", 0)),
        "starting": _elements(pick.get("xi", []), c2e),
        "starting_names": [str(n) for n in pick.get("xi_names", [])],
        "bench_order": _elements(bench_codes, c2e),
        "bench_names": [str(n) for n in pick.get("bench_names", [])],
        "captain": _element(pick.get("captain"), c2e),
        "captain_name": str(pick.get("captain_name", "")),
        "vice_captain": _element(pick.get("vice"), c2e),
        "vice_name": str(pick.get("vice_name", "")),
        "expected_points": round(float(pick.get("xp_xi", 0.0)), 2),
    }


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _actual(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "points": float(row["points"]),
        "points_before_hits": float(row["points_before_hits"]),
        "hit_points": float(row["hit_points"]),
        "n_autosubs": int(float(row["n_autosubs"])),
        "vice_used": _truthy(row["vice_used"]),
        "armband_points": float(row["armband_pts"]),
    }


def build_models(
    *,
    season: str,
    decisions: Sequence[Mapping[str, Any]],
    scores: Sequence[Mapping[str, Any]],
    frozen_tag: str | None,
    contract_version: int,
    statuses: Mapping[int, Mapping[str, Any]] | None = None,
    previews: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    """The ``models.json`` payload, or ``None`` when the harness has recorded no decision yet.

    Models the registry does not know are skipped rather than guessed at; a score row without a
    recorded decision for the same gameweek is ignored (points without advice are unattributable).

    **Fail closed on inputs.** ``statuses`` maps gameweek -> the CI input check for that decision
    (``status/GW{n}.json``: model key -> ``{"available", "reason"}``). A model whose inputs were
    missing or stale is published as unavailable with the reason, and neither its advice nor its
    points for that gameweek appear. A gameweek with no recorded check makes every model
    unavailable: no check is not the same as a passed check.

    **Provisional previews.** ``previews`` are ``decide.py --dry-run`` documents (same shape as a
    decision, with their own input check under ``preview_status``) for gameweeks that have no
    frozen decision yet. They are published with ``provisional: true`` and are dropped the moment
    a frozen decision for that gameweek exists, so the frozen record always wins.
    """
    decided = {int(d["gw"]) for d in decisions}
    pending = [p for p in previews if int(p["gw"]) not in decided]
    if not decisions and not pending:
        return None
    preview_checks = {int(p["gw"]): p.get("preview_status") for p in pending}
    by_gw = sorted([*decisions, *pending], key=lambda d: int(d["gw"]))
    actual_by_gw: dict[int, dict[str, Any]] = {}
    for row in scores:
        key = str(row.get("model", ""))
        if key in _BY_KEY:
            actual_by_gw.setdefault(int(row["gw"]), {})[_BY_KEY[key][0]] = _actual(row)

    gameweeks: list[dict[str, Any]] = []
    seen: set[str] = set()
    commit: str | None = None
    for doc in by_gw:
        gw = int(doc["gw"])
        c2e = {str(k): v for k, v in dict(doc.get("code_to_element", {})).items()}
        provisional = gw in preview_checks
        check = preview_checks[gw] if provisional else (statuses or {}).get(gw)
        availability: dict[str, dict[str, Any]] = {}
        advice = {}
        for key, pick in dict(doc.get("models", {})).items():
            if key not in _BY_KEY:
                continue
            wid = _BY_KEY[key][0]
            seen.add(key)
            status = ((check or {}).get("models") or {}).get(key)
            if check is None:
                reason: str | None = "no input-freshness check recorded for this decision"
            elif status is None:
                reason = "model missing from the input-freshness check"
            else:
                reason = (
                    None if status.get("available") else str(status.get("reason") or "inputs stale")
                )
            availability[wid] = {"available": reason is None, "reason": reason}
            if reason is None:
                advice[wid] = _advice(pick, c2e)
        commit = doc.get("code_commit") or commit
        actual = {m: a for m, a in actual_by_gw.get(gw, {}).items() if m in advice}
        gameweeks.append(
            {
                "gameweek": gw,
                "deadline": doc.get("deadline"),
                "decided_at": doc.get("decided_at"),
                "availability": availability,
                "advice": advice,
                "actual": None if provisional else (actual or None),
                "provisional": provisional,
            }
        )

    latest = gameweeks[-1]["availability"] if gameweeks else {}
    latest_provisional = bool(gameweeks and gameweeks[-1]["provisional"])
    models = [
        {
            "id": wid,
            "key": key,
            "label": label,
            "role": role,
            "description": desc,
            "available": bool(latest.get(wid, {}).get("available")),
            "unavailable_reason": latest.get(wid, {}).get("reason")
            if wid in latest
            else "not decided this gameweek",
            "provisional": latest_provisional and wid in latest,
        }
        for key, wid, label, role, desc in MODEL_REGISTRY
        if key in seen
    ]
    season_to_date = []
    for info in models:
        running = 0.0
        per_gw = []
        for g in gameweeks:
            a = (g["actual"] or {}).get(info["id"])
            if a is None:
                continue
            running += a["points"]
            per_gw.append({"gameweek": g["gameweek"], "points": a["points"], "cumulative": running})
        season_to_date.append(
            {
                "model": info["id"],
                "gameweeks_scored": len(per_gw),
                "total": running,
                "per_gameweek": per_gw,
            }
        )
    return {
        "contract_version": contract_version,
        "season": season,
        "champion": _BY_KEY[CHAMPION_KEY][0],
        "frozen": {"tag": frozen_tag, "code_commit": commit},
        "provisional": latest_provisional,
        "models": models,
        "gameweeks": gameweeks,
        "season_to_date": season_to_date,
    }
