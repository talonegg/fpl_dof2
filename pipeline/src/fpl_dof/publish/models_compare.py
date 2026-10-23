"""The five-model comparison artefact (``models.json``), keyed by strategy registry id (MOD-03).

Beside each published strategy's own week in week.json's schema, this is every frozen model's
pre-deadline advice per gameweek, the points each actually scored once the gameweek
is finished, and a season-to-date table.

**Two records, one switch (DL-87, DL-89).** Gameweeks before the switch gameweek S come from the
retired prospective harness: its advice (``decisions/GW{n}.json``, recorded *before* each deadline)
and its points (``scores.csv``), taken as written, never re-derived. S is the last gameweek it
scored, plus one (a decision it never scored gives way to the ledger).
Gameweeks from S come from the live ledger: every published strategy's
advice, with the points it scored on the owner's real squad taken from the gameweek's evaluation
(ORC-05, scored once by ``rules.realised``, as the season log's rows are), never rescored here.
The two quantities differ (a virtual season versus real-squad advice); ``record`` marks which.

Pure: no I/O, no clock. The stage reads the files and hands their contents in (DP-03).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fpl_dof.factory.registry import champion, resolve_alias, strategies


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


def _live_advice(
    advised: Mapping[str, Any], rec: Mapping[str, Any], names: Mapping[int, str]
) -> dict[str, Any]:
    """A ledger ``advised`` block and recommendation in the shape of a frozen model's advice."""

    def name(pid: Any) -> str:
        return names.get(int(pid), "") if pid is not None else ""

    bench = ([advised["reserve_goalkeeper"]] if advised.get("reserve_goalkeeper") else []) + list(
        advised.get("bench_order") or []
    )
    starting = [int(p) for p in advised.get("starting") or []]
    return {
        "transfers": [
            {
                "out": int(m["out"]["player_id"]),
                "out_name": str(m["out"].get("web_name", "")),
                "in": int(m["in"]["player_id"]),
                "in_name": str(m["in"].get("web_name", "")),
            }
            for m in rec.get("moves") or []
        ],
        "n_transfers": int(rec.get("transfers") or 0),
        "hit_points": int(rec.get("hit_points") or 0),
        "starting": starting,
        "starting_names": [name(p) for p in starting],
        "bench_order": [int(p) for p in bench],
        "bench_names": [name(p) for p in bench],
        "captain": advised.get("captain"),
        "captain_name": name(advised.get("captain")),
        "vice_captain": advised.get("vice_captain"),
        "vice_name": name(advised.get("vice_captain")),
        "expected_points": round(float(advised.get("expected_points") or 0.0), 2),
    }


def _offline(
    m: Mapping[str, Any], sources: Mapping[str, Sequence[str]], next_check: str | None
) -> dict[str, Any]:
    """Which sources a strategy without advice waits for, since when, and when next checked.

    Empty unless the ledger says a table it needs was missing and a source can supply it (ORC-07).
    """
    labels = sorted({label for t in m.get("missing") or () for label in sources.get(t, ())})
    if not labels:
        return {}
    return {"sources": labels, "since": m.get("since") or m.get("as_of"), "next_check": next_check}


def _live_gameweek(
    gw: int,
    entry: Mapping[str, Any],
    evaluation: Mapping[str, Any] | None,
    names: Mapping[int, str],
    sources: Mapping[str, Sequence[str]],
    next_check: str | None,
) -> dict[str, Any]:
    """One live gameweek from a ledger entry; with its points once the gameweek is evaluated."""
    availability: dict[str, dict[str, Any]] = {}
    advice: dict[str, Any] = {}
    for key, m in dict(entry.get("models") or {}).items():
        sid = resolve_alias(key) or key
        advised = m.get("advised") if isinstance(m, Mapping) else None
        if not isinstance(advised, Mapping):
            reason = str((m or {}).get("no_advice") or "no advice recorded")
            offline = _offline(m or {}, sources, next_check)
            availability[sid] = {"available": False, "reason": reason} | offline
            continue
        availability[sid] = {"available": True, "reason": None}
        # The advice of record's own stamp (ORC-03); a pre-R1.3.0 entry has none.
        stamp = {k: m[k] for k in ("as_of", "trigger") if m.get(k)}
        advice[sid] = _live_advice(advised, m.get("recommendation") or {}, names) | stamp
    judged = (evaluation or {}).get("strategies") or {}
    actual = {
        sid: dict(s["actual"]) for sid, s in judged.items() if sid in advice and s.get("actual")
    }
    return {
        "gameweek": gw,
        "deadline": None,
        "decided_at": entry.get("recorded_at"),
        "availability": availability,
        "advice": advice,
        "actual": actual or None,
        "provisional": False,
        "record": "live",
    }


def build_models(
    *,
    season: str,
    decisions: Sequence[Mapping[str, Any]],
    scores: Sequence[Mapping[str, Any]],
    frozen_tag: str | None,
    contract_version: int,
    statuses: Mapping[int, Mapping[str, Any]] | None = None,
    ledger: Mapping[int, Mapping[str, Any]] | None = None,
    evaluations: Mapping[int, Mapping[str, Any]] | None = None,
    names: Mapping[int, str] | None = None,
    sources: Mapping[str, Sequence[str]] | None = None,
    open_gameweek: int | None = None,
    next_check: str | None = None,
) -> dict[str, Any] | None:
    """The ``models.json`` payload, or ``None`` when the harness has recorded no decision yet.

    Models the registry does not know are skipped rather than guessed at; a score row without a
    recorded decision for the same gameweek is ignored (points without advice are unattributable).

    **Fail closed on inputs.** ``statuses`` maps gameweek -> the CI input check for that decision
    (``status/GW{n}.json``: model key -> ``{"available", "reason"}``). A model whose inputs were
    missing or stale is published as unavailable with the reason, and neither its advice nor its
    points for that gameweek appear. A gameweek with no recorded check makes every model
    unavailable: no check is not the same as a passed check.

    **A live strategy waiting for a source** (ORC-07): ``sources`` maps a silver table to the
    labels of the sources that supply it, so a ledger entry's ``missing`` tables name what it
    waits for; ``next_check`` is when that is next fetched, and applies to ``open_gameweek`` only.
    """
    decided = {int(d["gw"]) for d in decisions}
    scored = decided & {int(r["gw"]) for r in scores}
    # The frozen record yields from the first gameweek it never scored: the live ledger scores it.
    switch = max(scored) + 1 if scored else (min(decided) if decided else None)
    live = {
        gw: e
        for gw, e in (ledger or {}).items()
        if gw >= (switch or 1) and isinstance(e.get("models"), Mapping)
    }
    if not decisions and not live:
        return None
    by_gw = sorted(
        (
            d
            for d in decisions
            if not (switch is not None and int(d["gw"]) >= switch and int(d["gw"]) in live)
        ),
        key=lambda d: int(d["gw"]),
    )
    actual_by_gw: dict[int, dict[str, Any]] = {}
    for row in scores:
        sid = resolve_alias(str(row.get("model", "")))
        if sid is not None:
            actual_by_gw.setdefault(int(row["gw"]), {})[sid] = _actual(row)

    gameweeks: list[dict[str, Any]] = []
    seen: dict[str, str] = {}  # registry id -> the harness's key for it
    commit: str | None = None
    for doc in by_gw:
        gw = int(doc["gw"])
        c2e = {str(k): v for k, v in dict(doc.get("code_to_element", {})).items()}
        check = (statuses or {}).get(gw)
        availability: dict[str, dict[str, Any]] = {}
        advice = {}
        for key, pick in dict(doc.get("models", {})).items():
            wid = resolve_alias(key)
            if wid is None:
                continue
            seen[wid] = key
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
                "actual": actual or None,
                "provisional": False,
                "record": "frozen",
            }
        )
    for gw in sorted(live):
        live_gw = _live_gameweek(
            gw,
            live[gw],
            (evaluations or {}).get(gw),
            names or {},
            sources or {},
            next_check if gw == open_gameweek else None,
        )
        seen.update({m: m for m in live_gw["availability"] if m not in seen})
        gameweeks.append(live_gw)

    latest = gameweeks[-1]["availability"] if gameweeks else {}
    models = [
        {
            "id": s.id,
            "key": seen[s.id],
            "label": s.label,
            "role": s.role,
            "description": s.description,
            "available": bool(latest.get(s.id, {}).get("available")),
            "unavailable_reason": latest.get(s.id, {}).get("reason")
            if s.id in latest
            else "not decided this gameweek",
            "provisional": False,
        }
        for s in strategies()
        if s.id in seen
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
        "champion": champion().id,
        "switch_gameweek": switch,
        "frozen": {"tag": frozen_tag, "code_commit": commit},
        "provisional": False,
        "models": models,
        "gameweeks": gameweeks,
        "season_to_date": season_to_date,
    }
