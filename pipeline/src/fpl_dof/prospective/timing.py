"""When CI writes a prospective decision (pure; the I/O is in ``scripts/prospective_ci.py``).

Rule (2026-10-14): decide at the first scheduled pipeline run within :data:`DECIDE_WINDOW` of the
deadline whose football-data.co.uk ``fixtures.csv`` already carries odds rows (Div E0) for every
fixture of that gameweek. If they never appear, decide anyway at the *last* scheduled run before
the deadline — the T-45m deadline-relative run, which fires in ``[T-65m, T-45m]`` — so a decision
is never skipped for want of odds (A+odds is then marked unavailable by the freshness check).
Decisions stay write-once: an existing ``decisions/GW{n}.json`` is never rewritten.

Cadence inside the window (pipeline.yml): the deadline-relative trigger always gives the T-3h and
T-45m runs; the nightly 01:00 UTC run and the run after ingest-slow (02:20 UTC) add up to two more
when the deadline is before ~15:00 UTC. So at least two runs always fall inside the window.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fpl_dof.config.models import ScheduleConfig

DECIDE_WINDOW = dt.timedelta(hours=14)
_S = ScheduleConfig()
#: The last scheduled run's window opens this far before the deadline (min offset + tolerance).
LAST_RUN_LEAD = dt.timedelta(
    minutes=min(_S.pipeline_offsets_minutes) + _S.pipeline_window_tolerance_minutes
)

#: Mirrors the bundled harness's ``live_frame.ALIAS`` + ``EXTRA_ALIAS`` (parity is tested).
ALIASES: dict[str, str] = {
    "Man United": "Man Utd",
    "Tottenham": "Spurs",
    "Sheffield United": "Sheffield Utd",
    "Nott'm Forest": "Nott'm Forest",
    "Coventry": "Coventry City",
    "Hull": "Hull City",
    "Ipswich": "Ipswich Town",
}


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalpha())


def resolve_team(name: str, teams: Iterable[Mapping[str, Any]]) -> int | None:
    """football-data.co.uk name -> FPL team id: alias, exact, then unique prefix; else None."""
    by_norm = {_norm(t["name"]): int(t["id"]) for t in teams}
    target = _norm(ALIASES.get(name, name))
    if target in by_norm:
        return by_norm[target]
    hits = [
        i for n, i in by_norm.items() if target and (n.startswith(target) or target.startswith(n))
    ]
    return hits[0] if len(hits) == 1 else None


def odds_coverage(
    csv_bytes: bytes,
    gw: int,
    teams: Sequence[Mapping[str, Any]],
    fixtures: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    """(gameweek fixtures with an E0 odds row in ``fixtures.csv``, gameweek fixtures)."""
    want = {(int(f["team_h"]), int(f["team_a"])) for f in fixtures if f.get("event") == gw}
    try:
        text = csv_bytes.decode("latin-1").lstrip("\ufeff").replace("ï»¿", "", 1)
        rows = list(csv.DictReader(io.StringIO(text)))
    except UnicodeDecodeError, csv.Error:
        return 0, len(want)
    have = set()
    for r in rows:
        if r.get("Div") != "E0":
            continue
        pair = (
            resolve_team(r.get("HomeTeam", ""), teams),
            resolve_team(r.get("AwayTeam", ""), teams),
        )
        if pair in want:
            have.add(pair)
    return len(have), len(want)


@dataclass(frozen=True)
class DecideTiming:
    decide: bool
    reason: str


def decide_timing(
    *, now: dt.datetime, deadline: dt.datetime, already_decided: bool, joined: int, total: int
) -> DecideTiming:
    to_go = deadline - now
    if already_decided:
        return DecideTiming(False, "already decided (write-once)")
    if to_go <= dt.timedelta(0):
        return DecideTiming(False, "deadline passed")
    if to_go > DECIDE_WINDOW:
        return DecideTiming(False, f"outside the {DECIDE_WINDOW.total_seconds() / 3600:g}h window")
    if total > 0 and joined == total:
        return DecideTiming(True, f"odds ready ({joined}/{total} fixtures)")
    if to_go <= LAST_RUN_LEAD:
        return DecideTiming(True, f"fallback: last scheduled run, odds {joined}/{total}")
    return DecideTiming(False, f"waiting for odds ({joined}/{total} fixtures)")
