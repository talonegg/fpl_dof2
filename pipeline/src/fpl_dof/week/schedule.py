"""Should this scheduled firing actually do any work?

GitHub Actions cron is static: the schedule is fixed at commit time and cannot depend on when the
next FPL deadline is. The cadences E7 asks for are not fixed — "every four hours, but hourly within
a day of the deadline or while a gameweek is in play", "at T-3h and T-45m" — so the schedule
cannot express them.

The resolution is the same in both cases: **fire the cron often, and decide here.** Each workflow
runs a cheap guard step that calls one of these functions; the expensive work is conditional on the
answer. The cost of a firing that decides not to run is a few seconds of a runner, which is free on
a public repository (NFR-01) and is much cheaper than the alternatives — a workflow that guesses at
UK local time, or one that solves a MILP every hour.

This module is pure: it takes a clock reading, the Open gameweek's state (ORC-01) and the gameweeks
in play, and returns a decision; no function decides from the clock alone. The I/O that produces
those inputs lives in :mod:`fpl_dof.schedule_cli` (DP-03). That split is what makes "does the
T-45m trigger ever fire inside the freeze?" a unit test rather than a question you answer by
waiting for a Saturday.

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
correct failure: the T-3h run has already published a recommendation, and a manual dispatch before
the freeze is always available (Architecture §9). The freeze binds every trigger, dispatched or
scheduled (:func:`dispatch_decision`, ORC-02).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from fpl_dof.config.models import ScheduleConfig
from fpl_dof.gameweek import Due, GameweekState
from fpl_dof.triggers import CHANGE, CHANGE_KINDS, DAY_BEFORE, RESULTS, TRIGGERS

MINUTES_PER_HOUR = 60.0


def _minutes_to_deadline(state: GameweekState | None, now: dt.datetime) -> float | None:
    """Minutes to the deadline of the gameweek the state says advice is due for; else ``None``."""
    if state is None or state.due is not Due.ADVISE:
        return None
    return (state.deadline - now).total_seconds() / 60


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
    state: GameweekState | None,
    config: ScheduleConfig,
    in_play: Collection[int] = (),
) -> ScheduleDecision:
    """Whether this hourly firing of ``ingest-fast.yml`` should fetch.

    ``state`` is the Open gameweek's, ``None`` when none can be established — no silver yet, or the
    season is over. That falls back to the base four-hourly cadence rather than to hourly: an
    unknown deadline is not evidence that one is imminent, and the conservative reading costs at
    most three hours of staleness (DP-15).

    ``in_play`` is the gameweeks from their deadline until data-checked
    (:func:`~fpl_dof.gameweek.gameweeks_in_play`). While one is, every firing fetches, so a done
    matchday moves the ``results`` change within the hour (LIVE-02): two cheap requests an hour,
    free (NFR-01). Unknown is none, and keeps the base cadence, for the reason above.

    No freeze applies here. The freeze exists so that the *recommendation* cannot change under you
    in the last three quarters of an hour (R-09); a two-request read-only fetch changes no
    recommendation, and keeping prices and availability fresh while you are acting is the whole
    point of the fast cadence.
    """
    minutes_to_deadline = _minutes_to_deadline(state, now)
    gameweek = None if state is None else state.gameweek
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

    if in_play:
        return ScheduleDecision(
            should_run=True,
            reason=(
                f"gameweek {', '.join(str(gw) for gw in sorted(in_play))} in play, from its "
                "deadline until data-checked: hourly cadence"
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
            f"{hour:02d}:00 UTC is not a four-hourly boundary hour, no gameweek is in play and no "
            f"deadline is inside the {config.fast_ingest_deadline_window_hours:g}h window"
        ),
        minutes_to_deadline=minutes_to_deadline,
        gameweek=gameweek,
    )


def next_fast_ingest(
    *,
    now: dt.datetime,
    state: GameweekState | None,
    config: ScheduleConfig,
    in_play: Collection[int] = (),
) -> dt.datetime | None:
    """The next firing of ``ingest-fast.yml`` its guard lets fetch, before the Open gameweek's
    deadline: when a source a strategy awaits is next checked (ORC-07). ``None`` when no gameweek
    is Open or no such firing falls before its deadline. GitHub may drop the firing (D-35).
    ``in_play`` is read as of ``now`` for every firing; a gameweek data-checked sooner only makes a
    firing after it stand down, and the next check is then the one after."""
    if state is None or state.due is not Due.ADVISE:
        return None
    hour = dt.timedelta(hours=1)
    firing = now.astimezone(dt.UTC).replace(
        minute=config.fast_ingest_cron_minute, second=0, microsecond=0
    )
    if firing <= now:
        firing += hour
    while firing < state.deadline:
        if fast_ingest_decision(now=firing, state=state, config=config, in_play=in_play).should_run:
            return firing
        firing += hour
    return None


def pipeline_decision(
    *,
    now: dt.datetime,
    state: GameweekState | None,
    config: ScheduleConfig,
) -> ScheduleDecision:
    """Whether this firing of ``pipeline.yml``'s one scheduled tick should run the pipeline.

    Only the tick consults this; a dispatched run goes through :func:`dispatch_decision`, which
    applies the same freeze but no window, since it was started by something that happened.

    See the module docstring for how R-09 is enforced. The short version: the freeze is checked
    first, and every window ends at its offset rather than straddling it. Only a gameweek whose
    state makes advice due (Open) has a window at all.
    """
    minutes_to_deadline = _minutes_to_deadline(state, now)
    gameweek = None if state is None else state.gameweek
    if minutes_to_deadline is None:
        return ScheduleDecision(
            should_run=False,
            reason=(
                "no open gameweek could be established; the deadline-relative trigger stands down"
            ),
        )

    if minutes_to_deadline < config.deadline_freeze_minutes:
        return ScheduleDecision(
            should_run=False,
            reason=(
                f"{minutes_to_deadline:.0f}m to the gameweek {gameweek} deadline is inside the "
                f"{config.deadline_freeze_minutes:g}m freeze (R-09); nothing runs inside it"
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


def dispatch_decision(
    *,
    trigger: str,
    kinds: Sequence[str],
    gameweek: int | None,
    now: dt.datetime,
    state: GameweekState | None,
    config: ScheduleConfig,
    in_play: Collection[int] = (),
) -> ScheduleDecision:
    """Whether this run of ``pipeline.yml`` goes ahead; every trigger passes through here (ORC-02).

    The tick (``trigger`` empty) is :func:`pipeline_decision`. A dispatched run is refused inside
    the freeze (R-09) whatever started it, and refused when it was dispatched for a gameweek that is
    no longer the Open one: a run that queued across a deadline has nothing left to advise.

    A change that carries ``results`` (LIVE-02) is the exception to the second rule, never the
    first. Its gameweek may be one in play (``in_play``): what it is about is a gameweek past its
    deadline. And it goes ahead with no gameweek Open, so the season's last weekend refreshes, and
    the run in which the last gameweek is data-checked evaluates it (LIVE-07).

    Raises :class:`ValueError` on a trigger or kind nobody sends: a wiring fault, failed loudly.
    """
    if trigger and trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}; expected one of {', '.join(TRIGGERS)}")
    unknown = sorted(set(kinds) - set(CHANGE_KINDS))
    if unknown or bool(kinds) != (trigger == CHANGE):
        raise ValueError(
            f"kinds {','.join(kinds) or '(none)'} do not fit trigger {trigger or 'tick'!r}: a "
            f"change carries one or more of {', '.join(CHANGE_KINDS)}, any other trigger none"
        )
    if not trigger:
        return pipeline_decision(now=now, state=state, config=config)

    minutes_to_deadline = _minutes_to_deadline(state, now)
    open_gw = None if state is None or minutes_to_deadline is None else state.gameweek
    if minutes_to_deadline is not None and minutes_to_deadline < config.deadline_freeze_minutes:
        reason = (
            f"{minutes_to_deadline:.0f}m to the gameweek {open_gw} deadline is inside the "
            f"{config.deadline_freeze_minutes:g}m freeze (R-09); a {trigger} run is refused"
        )
        return ScheduleDecision(False, reason, minutes_to_deadline, open_gw)
    results = RESULTS in kinds
    if gameweek is not None and gameweek != open_gw and not (results and gameweek in in_play):
        reason = f"dispatched for gameweek {gameweek}, but the Open gameweek is {open_gw}"
        if results:
            reason += f" and none in play is {gameweek}"
        return ScheduleDecision(False, reason, minutes_to_deadline, open_gw)
    if open_gw is None and trigger in (CHANGE, DAY_BEFORE) and not results:
        reason = f"no open gameweek could be established; a {trigger} run has nothing to advise"
        return ScheduleDecision(False, reason)
    name = f"{trigger} run" + (" with results" if results else "")
    return ScheduleDecision(True, name, minutes_to_deadline, open_gw)


__all__ = [
    "MINUTES_PER_HOUR",
    "TRIGGERS",
    "ScheduleDecision",
    "dispatch_decision",
    "fast_ingest_decision",
    "pipeline_decision",
]
