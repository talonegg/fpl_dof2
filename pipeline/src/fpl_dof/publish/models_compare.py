"""The five-model comparison artefact (``models.json``).

Generalises ``week_challenger.json``: rather than one extra model in week.json's schema, every
frozen model's pre-deadline advice per gameweek, the points each actually scored once the gameweek
is finished, and a season-to-date table.

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

#: Harness model key -> (web id, label, role, description). Order is the display order.
MODEL_REGISTRY: tuple[tuple[str, str, str, str, str], ...] = (
    ("C3", "champion", "Champion (C3)", "champion", "Engine + minutes_v2, price/position captain"),
    ("C1", "challenger", "Challenger (C1)", "challenger", "Boosted xG + minutes model"),
    ("engine", "engine", "Engine", "comparison", "Original engine, engine captain"),
    ("A", "a", "Model A", "comparison", "Component xPts model"),
    ("A_odds", "a_odds", "A + odds", "comparison", "Model A with the odds team layer"),
)
CHAMPION_KEY = "C3"
_BY_KEY = {key: (wid, label, role, desc) for key, wid, label, role, desc in MODEL_REGISTRY}


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
) -> dict[str, Any] | None:
    """The ``models.json`` payload, or ``None`` when the harness has recorded no decision yet.

    Models the registry does not know are skipped rather than guessed at; a score row without a
    recorded decision for the same gameweek is ignored (points without advice are unattributable).
    """
    if not decisions:
        return None
    by_gw = sorted(decisions, key=lambda d: int(d["gw"]))
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
        advice = {}
        for key, pick in dict(doc.get("models", {})).items():
            if key in _BY_KEY:
                advice[_BY_KEY[key][0]] = _advice(pick, c2e)
                seen.add(key)
        commit = doc.get("code_commit") or commit
        actual = {m: a for m, a in actual_by_gw.get(gw, {}).items() if m in advice}
        gameweeks.append(
            {
                "gameweek": gw,
                "deadline": doc.get("deadline"),
                "decided_at": doc.get("decided_at"),
                "advice": advice,
                "actual": actual or None,
            }
        )

    models = [
        {"id": wid, "key": key, "label": label, "role": role, "description": desc}
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
        "models": models,
        "gameweeks": gameweeks,
        "season_to_date": season_to_date,
    }
