"""Should this scheduled firing actually do any work?

GitHub Actions cron is static: the schedule is fixed at commit time and cannot depend on when the
next FPL deadline is. The cadences E7 asks for are not fixed — "every four hours, but hourly within
a day of the deadline", "at T-3h and T-45m" — so the schedule cannot express them.

The resolution is the same in both cases: **fire the cron often, and decide here.** Each workflow
runs a cheap guard step that calls one of these functions; the expensive work is conditional on the
answer. The cost of a firing that decides not to run is a few seconds of a runner, which is free on
a public repository (NFR-01) and is much cheaper than the alternatives — a workflow that guesses at
UK local time, or one that solves a MILP every hour.

This module is pure: it takes a clock reading and a number of minutes, and returns a decision. The
I/O that produces those inputs lives in :mod:`fpl_dof.schedule_cli` (DP-03). That split is what
makes "does the T-45m trigger ever fire inside the freeze?" a unit test rather than a question you
answer by waiting for a Saturday.

**Everything is UTC.** Actions cron is UTC and deadlines are stored in UTC (DL-11); no conversion
happens on this path, deliberately, because the UK/AEST offset changes twice a season and not on
the same dates (CON-11).

R-09 — the deadline freeze
--------------------------
Nothing that produces a recommendation may run inside 45 minutes of a deadline. Two properties of
:func:`pipeline_decision` enforce that together:

1. **The tolerance is one-sided and points backwards in time.** A firing matches an offset when
   ``offset <= minutes_to_deadline <= offset + tolerance``. The window for the T-45m trigger is
   therefore ``[T-65m, T-45m]`` — it opens earlier and closes *at* T-45m. A symmetric window would
   have let a delayed firing land at T-35m, inside the freeze, which is exactly the bug this shape
   exists to make impossible.
2. **A hard freeze check runs first**, so any firing closer than
   ``deadline_freeze_minutes`` stands down whatever the offsets say.

A cron firing delayed past the end of a window means the run is skipped, not deferred. That is the
correct failure: the T-3h run has already published a recommendation, and manual dispatch is always
available (Architecture §9).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from fpl_dof.config.models import ScheduleConfig

MINUTES_PER_HOUR = 60.0


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    """Whether to proceed, and the reason — which is logged, so a skipped run is never a mystery."""

    should_run: bool
    reason: str
    minutes_to_deadline: float | None = None
    gameweek: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "should_run": self.should_run,
            "reason": self.reason,
            "minutes_to_deadline": (
                None if self.minutes_to_deadline is None else round(self.minutes_to_deadline, 2)
            ),
            "hours_to_deadline": (
                None
                if self.minutes_to_deadline is None
                else round(self.minutes_to_deadline / MINUTES_PER_HOUR, 3)
            ),
            "gameweek": self.gameweek,
        }


def fast_ingest_decision(
    *,
    now: dt.datetime,
    minutes_to_deadline: float | None,
    gameweek: int | None,
    config: ScheduleConfig,
) -> ScheduleDecision:
    """Whether this hourly firing of ``ingest-fast.yml`` should fetch.

    ``minutes_to_deadline`` is ``None`` when no deadline can be established — no silver yet, or the
    season is over. That falls back to the base four-hourly cadence rather than to hourly: an
    unknown deadline is not evidence that one is imminent, and the conservative reading costs at
    most three hours of staleness (DP-15).

    No freeze applies here. The freeze exists so that the *recommendation* cannot change under you
    in the last three quarters of an hour (R-09); a two-request read-only fetch changes no
    recommendation, and keeping prices and availability fresh while you are acting is the whole
    point of the fast cadence.
    """
    hour = now.astimezone(dt.UTC).hour
    on_boundary = hour in set(config.fast_ingest_boundary_hours)
    window_minutes = config.fast_ingest_deadline_window_hours * MINUTES_PER_HOUR

    if minutes_to_deadline is not None and 0 < minutes_to_deadline <= window_minutes:
        return ScheduleDecision(
            should_run=True,
            reason=(
                f"{minutes_to_deadline / MINUTES_PER_HOUR:.1f}h to the gameweek "
                f"{gameweek} deadline, inside the "
                f"{config.fast_ingest_deadline_window_hours:g}h window: hourly cadence"
            ),
            minutes_to_deadline=minutes_to_deadline,
            gameweek=gameweek,
        )

    if on_boundary:
        return ScheduleDecision(
            should_run=True,
            reason=f"{hour:02d}:00 UTC is a four-hourly boundary hour",
            minutes_to_deadline=minutes_to_deadline,
            gameweek=gameweek,
        )

    return ScheduleDecision(
        should_run=False,
        reason=(
            f"{hour:02d}:00 UTC is not a four-hourly boundary hour and no deadline is inside the "
            f"{config.fast_ingest_deadline_window_hours:g}h window"
        ),
        minutes_to_deadline=minutes_to_deadline,
        gameweek=gameweek,
    )


def pipeline_decision(
    *,
    minutes_to_deadline: float | None,
    gameweek: int | None,
    config: ScheduleConfig,
) -> ScheduleDecision:
    """Whether this firing of ``pipeline.yml``'s deadline-relative cron should run the pipeline.

    Only the deadline-relative trigger consults this. The nightly cron, the run that follows the
    slow ingest, and manual dispatch all proceed unconditionally — they are not deadline-relative,
    so there is no window for them to be inside or outside.

    See the module docstring for how R-09 is enforced. The short version: the freeze is checked
    first, and every window ends at its offset rather than straddling it.
    """
    if minutes_to_deadline is None:
        return ScheduleDecision(
            should_run=False,
            reason="no deadline could be established; the deadline-relative trigger stands down",
        )

    if minutes_to_deadline < config.deadline_freeze_minutes:
        return ScheduleDecision(
            should_run=False,
            reason=(
                f"{minutes_to_deadline:.0f}m to the gameweek {gameweek} deadline is inside the "
                f"{config.deadline_freeze_minutes:g}m freeze (R-09); dispatch manually if you "
                "really want a fresh solve this late"
            ),
            minutes_to_deadline=minutes_to_deadline,
            gameweek=gameweek,
        )

    for offset in sorted(config.pipeline_offsets_minutes, reverse=True):
        if offset <= minutes_to_deadline <= offset + config.pipeline_window_tolerance_minutes:
            return ScheduleDecision(
                should_run=True,
                reason=(
                    f"{minutes_to_deadline:.0f}m to the gameweek {gameweek} deadline is in the "
                    f"T-{offset}m window "
                    f"[{offset}, {offset + config.pipeline_window_tolerance_minutes:g}]"
                ),
                minutes_to_deadline=minutes_to_deadline,
                gameweek=gameweek,
            )

    return ScheduleDecision(
        should_run=False,
        reason=(
            f"{minutes_to_deadline:.0f}m to the gameweek {gameweek} deadline is in no "
            "pre-deadline window"
        ),
        minutes_to_deadline=minutes_to_deadline,
        gameweek=gameweek,
    )


__all__ = [
    "MINUTES_PER_HOUR",
    "ScheduleDecision",
    "fast_ingest_decision",
    "pipeline_decision",
]
