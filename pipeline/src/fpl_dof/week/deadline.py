"""When the deadline is, in both the zone FPL talks in and the zone you live in.

The finding this exists for is in INPUTS-REQUIRED §7 and is not a display preference. The owner is
on AEST; every FPL deadline is published in UK time; and **the offset between them changes twice a
season and not on the same dates**. The UK leaves BST in late October while Australia enters AEDT in
early October, so the gap moves from +9 to +11 inside a few weeks. Any code that reasons in local
time is wrong during that window, and wrong in a way that looks like nothing until a deadline is
missed.

So: everything is stored and computed in UTC (DL-11), zone conversion happens here and only here,
and both zones are rendered because FPL communities all talk in UK time and translating in your head
at 03:00 is how mistakes get made.

**"Decide by" is deliberately not the deadline.** Most deadlines fall between 02:30 and 05:00 local,
which means the practical rule is to decide the evening before. A countdown to a moment you will be
asleep for is not a useful countdown.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from fpl_dof.frames import as_int

#: The zone FPL publishes deadlines in. Not a preference — it is where the game is administered.
UK_ZONE = "Europe/London"


class NoDeadlineError(RuntimeError):
    """Every gameweek is behind us, or the gameweek table is empty."""


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

    def in_zone(self, zone: str) -> dt.datetime:
        return self.deadline_utc.astimezone(_zone(zone))

    def decide_by_in_zone(self, zone: str) -> dt.datetime:
        return self.decide_by_utc.astimezone(_zone(zone))

    @property
    def uk(self) -> dt.datetime:
        return self.in_zone(UK_ZONE)

    @property
    def local(self) -> dt.datetime:
        return self.in_zone(self.local_zone)

    @property
    def offset_hours(self) -> float:
        """Hours the local zone is ahead of the UK **at this deadline**.

        Computed per deadline rather than once, because it is not a constant: it is +9 for part of
        the season and +11 for another part.
        """
        delta = self.local.utcoffset() or dt.timedelta()
        uk_delta = self.uk.utcoffset() or dt.timedelta()
        return (delta - uk_delta).total_seconds() / 3600


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise NoDeadlineError(
            f"unknown timezone {name!r}; set runtime.timezone to an IANA name such as "
            "'Australia/Sydney'"
        ) from exc


def next_deadline(
    gameweeks: pd.DataFrame,
    *,
    now: dt.datetime,
    local_zone: str,
    decide_by_hours: float,
) -> DeadlineView:
    """The first deadline still ahead of ``now``.

    Chosen by time rather than by FPL's own ``is_next`` flag: the flag is updated when the API is,
    which is usually but not always the moment the deadline passes, and "usually" is not a property
    to schedule around.
    """
    if gameweeks.empty:
        raise NoDeadlineError("the gameweek table is empty")

    moment = pd.Timestamp(now).tz_convert("UTC")
    upcoming = gameweeks[gameweeks["deadline_time"] > moment].sort_values("deadline_time")
    if upcoming.empty:
        raise NoDeadlineError("every gameweek deadline has passed; the season is over")

    row = upcoming.iloc[0]
    deadline = row["deadline_time"].to_pydatetime()
    return DeadlineView(
        gameweek=as_int(row["gameweek"]),
        name=str(row["name"]),
        deadline_utc=deadline,
        decide_by_utc=deadline - dt.timedelta(hours=decide_by_hours),
        now_utc=moment.to_pydatetime(),
        local_zone=local_zone,
    )


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
    """The shape the web contract carries. UTC on the wire; the browser renders zones itself."""
    return {
        "gameweek": view.gameweek,
        "name": view.name,
        "deadline_utc": view.deadline_utc.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "decide_by_utc": view.decide_by_utc.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "local_zone": view.local_zone,
        "uk_zone": UK_ZONE,
    }


__all__ = [
    "UK_ZONE",
    "DeadlineView",
    "NoDeadlineError",
    "describe_deadline",
    "next_deadline",
    "to_contract",
]
