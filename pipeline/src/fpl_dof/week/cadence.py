"""Gameweek cadence, timing, and gating.

Consolidates deadline calculation, multi-zone handling (UK and Sydney), cron gating,
and CI idempotency into one deep module.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.gameweek import NoDeadlineError, current_gameweek, gameweek_ahead

#: Standard timezones
UK_ZONE = "Europe/London"
SYDNEY_ZONE = "Australia/Sydney"
SYDNEY = ZoneInfo(SYDNEY_ZONE)

#: Day-before refresh schedule constants
LOCAL_HOUR = 7
CRON = "7,27,47 19-22 * * *"
VETO_REASON = "day-before refresh: never writes a prospective decision (14 h window)"


def zone(name: str) -> ZoneInfo:
    """Resolve an IANA timezone name safely."""
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise NoDeadlineError(
            f"unknown timezone {name!r}; set runtime.timezone to an IANA name such as "
            "'Australia/Sydney'"
        ) from exc


@dataclass(frozen=True, slots=True)
class DeadlineView:
    """One deadline, rendered for a human in two zones."""

    gameweek: int
    name: str
    deadline_utc: dt.datetime
    decide_by_utc: dt.datetime
    now_utc: dt.datetime
    local_zone: str

    @property
    def time_remaining(self) -> dt.timedelta:
        return self.deadline_utc - self.now_utc

    @property
    def decide_by_remaining(self) -> dt.timedelta:
        return self.decide_by_utc - self.now_utc

    @property
    def has_passed(self) -> bool:
        return self.time_remaining.total_seconds() <= 0

    def in_zone(self, zone_name: str) -> dt.datetime:
        return self.deadline_utc.astimezone(zone(zone_name))

    def decide_by_in_zone(self, zone_name: str) -> dt.datetime:
        return self.decide_by_utc.astimezone(zone(zone_name))

    @property
    def uk(self) -> dt.datetime:
        return self.in_zone(UK_ZONE)

    @property
    def local(self) -> dt.datetime:
        return self.in_zone(self.local_zone)

    @property
    def offset_hours(self) -> float:
        """Hours the local zone is ahead of the UK at this deadline."""
        delta = self.local.utcoffset() or dt.timedelta()
        uk_delta = self.uk.utcoffset() or dt.timedelta()
        return (delta - uk_delta).total_seconds() / 3600


def _parse_utc_iso(raw: str) -> dt.datetime:
    return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def find_next_deadline_event(
    events_or_bootstrap: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    now: dt.datetime,
) -> tuple[int, dt.datetime] | None:
    """Find (gameweek, deadline_utc) from raw bootstrap dict or event list."""
    if isinstance(events_or_bootstrap, Mapping):
        events = events_or_bootstrap.get("events", [])
    else:
        events = events_or_bootstrap

    deadlines = pd.DataFrame(
        [
            {
                "gameweek": int(ev["id"]),
                "deadline_time": _parse_utc_iso(str(ev["deadline_time"])),
                "finished": bool(ev.get("finished")),
            }
            for ev in events
            if ev.get("deadline_time")
        ],
        columns=["gameweek", "deadline_time", "finished"],
    )
    gameweek = gameweek_ahead(deadlines, now)
    if gameweek is None:
        return None
    when = deadlines.loc[deadlines["gameweek"] == gameweek, "deadline_time"].iloc[0]
    return gameweek, pd.Timestamp(when).to_pydatetime()


def next_deadline(
    gameweeks: pd.DataFrame,
    *,
    now: dt.datetime,
    local_zone: str,
    decide_by_hours: float,
) -> DeadlineView:
    """The first deadline ahead of ``now`` from a gameweeks DataFrame."""
    if gameweeks.empty:
        raise NoDeadlineError("the gameweek table is empty")

    moment = pd.Timestamp(now).tz_convert("UTC")
    gameweek = gameweek_ahead(gameweeks, moment)
    if gameweek is None:
        raise NoDeadlineError("every gameweek deadline has passed; the season is over")

    row = gameweeks[gameweeks["gameweek"] == gameweek].iloc[0]
    deadline = row["deadline_time"].to_pydatetime()
    return DeadlineView(
        gameweek=as_int(row["gameweek"]),
        name=str(row["name"]),
        deadline_utc=deadline,
        decide_by_utc=deadline - dt.timedelta(hours=decide_by_hours),
        now_utc=moment.to_pydatetime(),
        local_zone=local_zone,
    )


next_deadline_dataframe = next_deadline


def _format_delta(delta: dt.timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "passed"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def describe_deadline(view: DeadlineView) -> list[str]:
    """Both zones, the offset that applies to this deadline, and the decide-by time."""
    fmt = "%a %d %b %H:%M"
    lines = [
        f"{view.name} deadline",
        f"  UK    {view.uk.strftime(fmt)} {view.uk.tzname()}",
        f"  local {view.local.strftime(fmt)} {view.local.tzname()} (UK{view.offset_hours:+.0f}h)",
        f"  in    {_format_delta(view.time_remaining)}",
    ]
    decide = view.decide_by_in_zone(view.local_zone)
    if view.decide_by_remaining.total_seconds() > 0:
        lines.append(
            f"  decide by {decide.strftime(fmt)} {decide.tzname()} "
            f"({_format_delta(view.decide_by_remaining)} away)"
        )
    else:
        lines.append(
            f"  decide-by time ({decide.strftime(fmt)} {decide.tzname()}) has passed — "
            "you are inside the window where you would have to be awake for the deadline"
        )
    return lines


def to_contract(view: DeadlineView) -> dict[str, object]:
    """The shape the web contract carries. UTC on the wire."""
    return {
        "gameweek": view.gameweek,
        "name": view.name,
        "deadline_utc": view.deadline_utc.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "decide_by_utc": view.decide_by_utc.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "local_zone": view.local_zone,
        "uk_zone": UK_ZONE,
    }


# --- CI Run Helpers ---


def _created(run: Mapping[str, Any]) -> dt.datetime:
    return dt.datetime.fromisoformat(str(run["createdAt"]).replace("Z", "+00:00"))


def succeeded_since(
    runs: Iterable[Mapping[str, Any]],
    since: dt.datetime,
    *,
    exclude_id: int | None = None,
    title_contains: str | None = None,
) -> Mapping[str, Any] | None:
    """The first completed-successfully run created at or after ``since``."""
    for run in runs:
        if exclude_id is not None and int(run.get("databaseId", -1)) == exclude_id:
            continue
        if title_contains and title_contains not in str(run.get("displayTitle", "")):
            continue
        if run.get("conclusion") == "success" and _created(run) >= since:
            return run
    return None


def active_or_succeeded(
    runs: Iterable[Mapping[str, Any]], *, title_contains: str, exclude_id: int | None = None
) -> Mapping[str, Any] | None:
    """A run with this title that is queued/in progress or succeeded."""
    for run in runs:
        if exclude_id is not None and int(run.get("databaseId", -1)) == exclude_id:
            continue
        if title_contains not in str(run.get("displayTitle", "")):
            continue
        if run.get("status") != "completed" or run.get("conclusion") == "success":
            return run
    return None


def start_of_utc_day(now: dt.datetime) -> dt.datetime:
    return now.astimezone(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)


# --- Day-Before Gate ---


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


def gate(
    *,
    now: dt.datetime,
    bootstrap: Mapping[str, Any] | None,
    error: str | None = None,
    prior_runs: Iterable[Mapping[str, Any]] | None = (),
    runs_error: str | None = None,
    manual: bool = False,
) -> GateDecision:
    """Day-before gate decision."""
    if error is not None or bootstrap is None:
        return GateDecision(False, f"skip: could not read the FPL deadline ({error or 'no data'})")
    local = now.astimezone(SYDNEY)
    try:
        found = find_next_deadline_event(bootstrap, now)
    except (KeyError, TypeError, ValueError) as exc:
        return GateDecision(False, f"skip: malformed FPL events data ({exc!r})")
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


def veto_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """The prospective plan with ``decide`` forced off; scoring and everything else unchanged."""
    out = dict(plan)
    if out.get("decide"):
        out["decide_vetoed"] = out.get("decide_reason", "planned")
    out["decide"] = False
    out["decide_reason"] = VETO_REASON
    return out


__all__ = [
    "CRON",
    "LOCAL_HOUR",
    "SYDNEY",
    "SYDNEY_ZONE",
    "UK_ZONE",
    "VETO_REASON",
    "DeadlineView",
    "GateDecision",
    "NoDeadlineError",
    "active_or_succeeded",
    "current_gameweek",
    "describe_deadline",
    "find_next_deadline_event",
    "gate",
    "marker",
    "next_deadline",
    "next_deadline_dataframe",
    "start_of_utc_day",
    "succeeded_since",
    "to_contract",
    "veto_plan",
    "zone",
]
