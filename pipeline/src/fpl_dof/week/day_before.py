"""The day-before refresh gate (pure; stdlib only, so the gate job needs no install).

Goal: one full refresh (ingest → pipeline → deploy) at about 07:00 Sydney time on the calendar day
before each gameweek deadline — e.g. Friday morning for a Saturday deadline.

GitHub cron is UTC and Sydney moves between AEST (UTC+10) and AEDT (UTC+11), so the workflow fires
at both candidate times, 20:00 and 21:00 UTC. Exactly one of them is 07:00 in Sydney on any given
day; the gate takes the firing's *nominal* cron time (not the possibly-delayed start time) and
proceeds only if that is 07:00 Sydney **and** the next deadline falls on the next Sydney calendar
day. Anything it cannot establish — API down, malformed JSON, no upcoming deadline — is a skip with
a reason, never a partial run.

Prospective decisions are never written by this refresh: a deadline "tomorrow" is at least
``24 - 7 = 17`` hours after a 07:00 run, outside the prospective 14 h decision window, and the
pipeline vetoes ``decide`` for day-before runs regardless (belt and braces).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
LOCAL_HOUR = 7
#: 07:00 AEDT (UTC+11) and 07:00 AEST (UTC+10).
CRON_UTC_HOURS = (20, 21)


@dataclass(frozen=True)
class GateDecision:
    run: bool
    reason: str
    gameweek: int | None = None
    deadline_utc: dt.datetime | None = None

    def lines(self) -> str:
        dl = self.deadline_utc.isoformat() if self.deadline_utc else ""
        return f"run={str(self.run).lower()}\ngameweek={self.gameweek or ''}\ndeadline={dl}\n"


def nominal_fire_time(now: dt.datetime, cron_hour: int) -> dt.datetime:
    """The UTC time the firing was scheduled for (GitHub may start it late)."""
    start = now.astimezone(dt.UTC)
    nominal = start.replace(hour=cron_hour, minute=0, second=0, microsecond=0)
    if nominal > start:  # a late start that crossed midnight UTC
        nominal -= dt.timedelta(days=1)
    return nominal


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
    cron_hour: int | None = None,
) -> GateDecision:
    """``cron_hour`` is the firing's cron UTC hour; None for a manual dispatch (no hour check)."""
    if error is not None or bootstrap is None:
        return GateDecision(False, f"skip: could not read the FPL deadline ({error or 'no data'})")
    when = now if cron_hour is None else nominal_fire_time(now, cron_hour)
    local = when.astimezone(SYDNEY)
    if cron_hour is not None and local.hour != LOCAL_HOUR:
        return GateDecision(
            False,
            f"skip: this firing is {local:%H:%M %Z} in Sydney; "
            f"the {LOCAL_HOUR:02d}:00 one is the other cron",
        )
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
