"""The day-before refresh gate (pure; stdlib only, so the gate job needs no install).

Goal: one full refresh (ingest → pipeline → deploy) on the morning of the calendar day before each
gameweek deadline in Sydney — e.g. Friday morning for a Saturday deadline.

GitHub drops and delays cron firings on this repo, so the workflow fires many times (every 20
minutes at odd minutes, 19:07 to 22:47 UTC = 05:07 to 09:47 Sydney under either offset). The gate
proceeds on the **first** firing that is on or after 07:00 Sydney time on the day before the next
deadline, and is idempotent: once a day-before ingest for that gameweek is queued, running or
succeeded (its run title carries ``[day-before GW{n}]``), every later firing is a logged no-op. A
failed one is retried by the next firing. Anything the gate cannot establish — FPL API down,
malformed JSON, no upcoming deadline, GitHub's run list unreadable — is a skip with a reason,
never a partial run.

Prospective decisions are never written by this refresh: a deadline "tomorrow" is more than 14 h
after a morning firing (at least 14 h 13 m after 09:47), and the pipeline vetoes ``decide`` for
day-before runs regardless (belt and braces).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from fpl_dof.week.ci_runs import active_or_succeeded

SYDNEY = ZoneInfo("Australia/Sydney")
LOCAL_HOUR = 7
#: Every 20 minutes at odd minutes, 19:07 to 22:47 UTC (05:07 to 09:47 Sydney, AEST or AEDT).
CRON = "7,27,47 19-22 * * *"


def marker(gameweek: int) -> str:
    """The run-title marker of a day-before ingest for this gameweek."""
    return f"[day-before GW{gameweek}]"


@dataclass(frozen=True)
class GateDecision:
    run: bool
    reason: str
    gameweek: int | None = None
    deadline_utc: dt.datetime | None = None

    def lines(self) -> str:
        dl = self.deadline_utc.isoformat() if self.deadline_utc else ""
        return f"run={str(self.run).lower()}\ngameweek={self.gameweek or ''}\ndeadline={dl}\n"


def next_deadline(bootstrap: Mapping[str, Any], now: dt.datetime) -> tuple[int, dt.datetime] | None:
    upcoming = []
    for ev in bootstrap.get("events", []):
        raw = ev.get("deadline_time")
        if not raw or ev.get("finished"):
            continue
        when = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if when > now:
            upcoming.append((when, int(ev["id"])))
    if not upcoming:
        return None
    when, gw = min(upcoming)
    return gw, when


def gate(
    *,
    now: dt.datetime,
    bootstrap: Mapping[str, Any] | None,
    error: str | None = None,
    prior_runs: Iterable[Mapping[str, Any]] | None = (),
    runs_error: str | None = None,
    manual: bool = False,
) -> GateDecision:
    """``prior_runs``: recent Ingest (slow) runs (``gh run list --json``) for the idempotency check.
    ``manual``: a workflow_dispatch skips the 07:00 check, nothing else."""
    if error is not None or bootstrap is None:
        return GateDecision(False, f"skip: could not read the FPL deadline ({error or 'no data'})")
    local = now.astimezone(SYDNEY)
    try:
        found = next_deadline(bootstrap, now)
    except (KeyError, TypeError, ValueError) as exc:
        return GateDecision(False, f"skip: malformed bootstrap-static ({exc!r})")
    if found is None:
        return GateDecision(False, "skip: no upcoming deadline (season over?)")
    gw, deadline = found
    dl_local = deadline.astimezone(SYDNEY)
    tomorrow = local.date() + dt.timedelta(days=1)
    if dl_local.date() != tomorrow:
        return GateDecision(
            False,
            f"skip: GW{gw} deadline is {dl_local:%a %d %b %H:%M %Z}, "
            f"not tomorrow ({tomorrow:%a %d %b})",
            gw,
            deadline,
        )
    if not manual and local.hour < LOCAL_HOUR:
        return GateDecision(
            False, f"skip: {local:%H:%M %Z} is before {LOCAL_HOUR:02d}:00 Sydney", gw, deadline
        )
    if runs_error is not None or prior_runs is None:
        return GateDecision(
            False,
            f"skip: cannot check for an earlier day-before run ({runs_error or 'no data'}); "
            "the next firing retries",
            gw,
            deadline,
        )
    earlier = active_or_succeeded(prior_runs, title_contains=marker(gw))
    if earlier is not None:
        state = earlier.get("conclusion") or earlier.get("status")
        return GateDecision(
            False,
            f"no-op: the day-before refresh for GW{gw} already ran "
            f"(run {earlier.get('databaseId')}, {state})",
            gw,
            deadline,
        )
    return GateDecision(
        True,
        f"run: GW{gw} deadline is tomorrow, {dl_local:%a %d %b %H:%M %Z} "
        f"({deadline:%H:%M} UTC); day-before refresh at {local:%a %H:%M %Z}",
        gw,
        deadline,
    )


VETO_REASON = "day-before refresh: never writes a prospective decision (14 h window)"


def veto_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """The prospective plan with ``decide`` forced off; scoring and everything else unchanged."""
    out = dict(plan)
    if out.get("decide"):
        out["decide_vetoed"] = out.get("decide_reason", "planned")
    out["decide"] = False
    out["decide_reason"] = VETO_REASON
    return out
