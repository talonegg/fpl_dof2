"""When CI writes a prospective decision (pure; the I/O is in ``scripts/prospective_ci.py``).

Rule (2026-10-14): decide at the first scheduled pipeline run within :data:`DECIDE_WINDOW` of the
deadline whose match odds ``fixtures.csv`` already carries odds rows (Div E0) for every
fixture of that gameweek. If they never appear, decide anyway at the *last* scheduled run before
the deadline — the T-45m deadline-relative run, which fires in ``[T-65m, T-45m]`` — so a decision
is never skipped for want of odds (A+odds is then marked unavailable by the freshness check).
Decisions stay write-once: an existing ``decisions/GW{n}.json`` is never rewritten.

Cadence inside the window (pipeline.yml): the deadline-relative trigger always gives the T-3h and
T-45m runs; the nightly 01:00 UTC run and the run after ingest-slow (02:20 UTC) add up to two more
when the deadline is before ~15:00 UTC. So at least two runs always fall inside the window.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from fpl_dof.config.models import ScheduleConfig
from fpl_dof.sources import CLUB_ALIASES, resolve_team

#: Mirrors the bundled harness's ``live_frame.ALIAS`` + ``EXTRA_ALIAS`` (parity is tested).
ALIASES: dict[str, str] = CLUB_ALIASES

DECIDE_WINDOW = dt.timedelta(hours=14)
_S = ScheduleConfig()
#: The last scheduled run's window opens this far before the deadline (min offset + tolerance).
LAST_RUN_LEAD = dt.timedelta(
    minutes=min(_S.pipeline_offsets_minutes) + _S.pipeline_window_tolerance_minutes
)


def odds_coverage(
    odds: pd.DataFrame,
    gw: int,
    teams: Sequence[Mapping[str, Any]],
    fixtures: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    """(gameweek fixtures with a priced odds row, gameweek fixtures).

    ``odds`` is the conformed upcoming odds, ``home_team``/``away_team`` as the market names them.
    """
    want = {(int(f["team_h"]), int(f["team_a"])) for f in fixtures if f.get("event") == gw}
    if odds.empty:
        return 0, len(want)
    pairs = zip(
        (resolve_team(str(name), teams) for name in odds["home_team"]),
        (resolve_team(str(name), teams) for name in odds["away_team"]),
        strict=True,
    )
    return len({pair for pair in pairs if pair in want}), len(want)


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
