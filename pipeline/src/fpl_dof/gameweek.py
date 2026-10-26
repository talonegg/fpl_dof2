"""Which gameweek is being decided, what state every gameweek is in, and when a matchday of the
gameweek in play is done: one definition of each.

Lives outside ``week`` so the model factory and the squad core can use it without importing the
orchestrator (MOD-01); :mod:`fpl_dof.week.cadence` re-exports it. Pure: frames and an instant in,
an answer out. The clock and the files are read at the edge (DP-03).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import pandas as pd

from fpl_dof.frames import as_int


class NoDeadlineError(RuntimeError):
    """Every gameweek is behind us, or the gameweek table is empty."""


def _utc(moment: dt.datetime | pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(moment)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def gameweek_ahead(gameweeks: pd.DataFrame, as_of: dt.datetime | pd.Timestamp) -> int | None:
    """The gameweek whose deadline is the first still ahead of ``as_of``; ``None`` if none is.

    **The one definition of which gameweek is being decided** (PIPE-12, REM-08), and so of the one
    gameweek that is Open (ORC-01). Forecast, publish and transform read it through
    :func:`current_gameweek`; week, decision and the schedule through :func:`open_gameweek`; the
    day-before gate through ``find_next_deadline_event``. They differ only in what they do once the
    season's last deadline has passed.
    """
    if gameweeks.empty:
        return None
    moment = _utc(as_of)
    upcoming = gameweeks[pd.to_datetime(gameweeks["deadline_time"], utc=True) > moment]
    if "finished" in upcoming.columns:
        upcoming = upcoming[~upcoming["finished"].fillna(False).astype(bool)]  # not decidable
    if upcoming.empty:
        return None
    return as_int(upcoming.sort_values("deadline_time").iloc[0]["gameweek"])


def current_gameweek(gameweeks: pd.DataFrame, as_of: dt.datetime | pd.Timestamp) -> int:
    """The next gameweek whose deadline is ahead of as_of (PIPE-12, 03 §12 P4).

    Between a deadline passing and that gameweek finishing, the next gameweek to be decided
    is the upcoming deadline, not the in-flight one. If all deadlines have passed, returns
    the final gameweek of the season.
    """
    if gameweeks.empty:
        raise NoDeadlineError("the gameweek table is empty")
    gameweek = gameweek_ahead(gameweeks, as_of)
    return as_int(gameweeks["gameweek"].max()) if gameweek is None else gameweek


# --- Gameweek state (ORC-01) ------------------------------------------------------------------


class Phase(StrEnum):
    """Where a gameweek is in its life. Derived on every read, never stored (ORC-01)."""

    UPCOMING = "upcoming"
    """Its deadline is ahead but is not the next one: a later gameweek, not yet Open."""
    OPEN = "open"
    """The next deadline's gameweek, and only that one: the advice can still change."""
    RECORDED = "recorded"
    """From the deadline: the advice of record is closed (ORC-03)."""
    PLAYING = "playing"
    """From its first kick-off."""
    FINISHED = "finished"
    """FPL has marked it finished and data-checked: its points are final."""
    EVALUATED = "evaluated"
    """The ledger holds its evaluation for the current evaluation version (ORC-05)."""


class Due(StrEnum):
    """What a run does for a gameweek in a given phase."""

    ADVISE = "advise"
    """Refresh every strategy's advice."""
    INGEST = "ingest"
    """Nothing beyond ingest."""
    EVALUATE = "evaluate"
    """The evaluation step (ORC-05)."""
    NOTHING = "nothing"


DUE: Mapping[Phase, Due] = {
    Phase.UPCOMING: Due.NOTHING,
    Phase.OPEN: Due.ADVISE,
    Phase.RECORDED: Due.INGEST,
    Phase.PLAYING: Due.INGEST,
    Phase.FINISHED: Due.EVALUATE,
    Phase.EVALUATED: Due.NOTHING,
}


@dataclass(frozen=True, slots=True)
class SilverTables:
    """The silver tables the state reads: the gameweek table, and optionally the fixtures and the
    owner's chips (entry history). Without fixtures nothing is Playing; without chips none is in
    force."""

    gameweeks: pd.DataFrame
    fixtures: pd.DataFrame | None = None
    entry_chips: pd.DataFrame | None = None


@dataclass(frozen=True, slots=True)
class GameweekState:
    gameweek: int
    phase: Phase
    deadline: dt.datetime
    chip: str | None
    """The chip the owner played in this gameweek, from entry history; ``None`` when none was."""

    @property
    def due(self) -> Due:
        return DUE[self.phase]


def chips_by_gameweek(entry_chips: pd.DataFrame | None) -> dict[int, str]:
    """``gameweek -> chip`` the owner played, from entry history: the one reading of it."""
    if entry_chips is None or entry_chips.empty:
        return {}
    return {as_int(row["gameweek"]): str(row["name"]) for _, row in entry_chips.iterrows()}


def gameweek_state(
    gameweek: int, silver: SilverTables, ledger: Collection[int], now: dt.datetime
) -> GameweekState:
    """The state of ``gameweek`` at ``now``; ``ledger`` is the gameweeks evaluated for the current
    evaluation version.

    A blank or postponed fixture changes which fixtures a gameweek has, and so when it starts
    Playing, never which phase it is in by any other route: the deadline and FPL's flags decide.
    """
    table = silver.gameweeks
    rows = table[table["gameweek"] == gameweek]
    if rows.empty:
        raise KeyError(f"gameweek {gameweek} is not in the gameweek table")
    row = rows.iloc[0]
    deadline = _utc(row["deadline_time"])
    moment = _utc(now)
    chip = chips_by_gameweek(silver.entry_chips).get(gameweek)

    if moment < deadline:
        phase = Phase.OPEN if gameweek == gameweek_ahead(table, moment) else Phase.UPCOMING
    elif bool(row["finished"]) and bool(row.get("data_checked", False)):
        phase = Phase.EVALUATED if gameweek in ledger else Phase.FINISHED
    else:
        kickoff = _first_kickoff(silver.fixtures, gameweek)
        phase = Phase.PLAYING if kickoff is not None and moment >= kickoff else Phase.RECORDED
    return GameweekState(gameweek, phase, deadline.to_pydatetime(), chip)


def season_states(
    silver: SilverTables, ledger: Collection[int], now: dt.datetime
) -> list[GameweekState]:
    """Every gameweek's state, in gameweek order."""
    gameweeks = sorted(as_int(gw) for gw in silver.gameweeks["gameweek"])
    return [gameweek_state(gw, silver, ledger, now) for gw in gameweeks]


def open_gameweek(
    silver: SilverTables, ledger: Collection[int], now: dt.datetime
) -> GameweekState | None:
    """The one Open gameweek, the next deadline's; ``None`` once the last deadline has passed."""
    gameweek = gameweek_ahead(silver.gameweeks, now)
    return None if gameweek is None else gameweek_state(gameweek, silver, ledger, now)


def _first_kickoff(fixtures: pd.DataFrame | None, gameweek: int) -> pd.Timestamp | None:
    """The gameweek's earliest scheduled kick-off. A postponed fixture has left the gameweek (no
    gameweek, or no kick-off), so it no longer counts."""
    if fixtures is None or fixtures.empty:
        return None
    times = fixtures.loc[fixtures["gameweek"] == gameweek, "kickoff_time"].dropna()
    return None if times.empty else _utc(times.min())


#: The phases a gameweek is *in play* in: from its deadline until FPL marks it finished and
#: data-checked (ORC-01, LIVE-02).
IN_PLAY: frozenset[Phase] = frozenset({Phase.RECORDED, Phase.PLAYING})


def gameweeks_in_play(gameweeks: pd.DataFrame, now: dt.datetime) -> tuple[int, ...]:
    """The gameweeks in play at ``now``, in gameweek order: past their deadline, not yet finished
    and data-checked. Usually one; two when a midweek deadline passes before the gameweek before
    it is data-checked; none preseason, between data-checked and the next deadline, and after the
    season."""
    if gameweeks.empty:
        return ()
    states = season_states(SilverTables(gameweeks), (), now)
    return tuple(state.gameweek for state in states if state.phase in IN_PLAY)


# --- Matchdays (LIVE-02) ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Matchday:
    """One gameweek's fixtures that share a kick-off date in the matchday zone (R1.4.3 §1).

    **Done** once every one of its fixtures is finished with bonus confirmed (the fixture's
    ``finished``), or once the settle cap has passed since its last kick-off. Done by the cap with
    a bonus still unconfirmed, it is **bonus pending**: the run that publishes it derives that from
    the same flags, so the change that starts the run carries nothing but its kind.
    """

    gameweek: int
    day: dt.date
    fixtures: int
    finished: int
    last_kickoff: dt.datetime
    done: bool

    @property
    def bonus_pending(self) -> bool:
        return self.done and self.finished < self.fixtures


def matchdays(
    fixtures: pd.DataFrame | None, at: dt.datetime, *, zone: str, settle: dt.timedelta
) -> list[Matchday]:
    """Every matchday in ``fixtures`` (silver's fixture shape: ``gameweek``, ``kickoff_time``,
    ``finished``) as it stands at ``at``, in gameweek and date order.

    A postponed fixture has left its gameweek (no gameweek, or no kick-off), so it belongs to no
    matchday and holds none open. ``zone`` groups the dates and is used for nothing else: every
    instant stays UTC (DL-11).
    """
    if fixtures is None or fixtures.empty:
        return []
    frame = fixtures.dropna(subset=["gameweek", "kickoff_time"])
    if frame.empty:
        return []
    kickoffs = pd.to_datetime(frame["kickoff_time"], utc=True)
    days = kickoffs.dt.tz_convert(zone).dt.date
    finished = frame["finished"].eq(True)  # an unknown flag is not a confirmed bonus
    moment = _utc(at)
    result = []
    for (gameweek, day), group in frame.groupby([frame["gameweek"].astype(int), days]):
        last = kickoffs[group.index].max()
        played = int(finished[group.index].sum())
        result.append(
            Matchday(
                gameweek=as_int(gameweek),
                day=cast(dt.date, day),
                fixtures=len(group),
                finished=played,
                last_kickoff=last.to_pydatetime(),
                done=played == len(group) or moment >= last + settle,
            )
        )
    return sorted(result, key=lambda matchday: (matchday.gameweek, matchday.day))


def matchdays_done_since(
    before: pd.DataFrame | None,
    before_at: dt.datetime,
    after: pd.DataFrame | None,
    after_at: dt.datetime,
    *,
    zone: str,
    settle: dt.timedelta,
) -> list[Matchday]:
    """The matchdays done in ``after`` at ``after_at`` that were not done in ``before`` at
    ``before_at``: what moves the ``results`` change (LIVE-02).

    Comparing two captures, not reading the clock alone, is what makes each matchday move once:
    whichever capture first sees it done moves it, however many firings GitHub drops or delays
    before that one (D-35), and every later capture sees it done on both sides. In practice only
    the gameweek in play has one: every earlier matchday is done on both sides, every later one on
    neither.
    """
    was = {
        (matchday.gameweek, matchday.day)
        for matchday in matchdays(before, before_at, zone=zone, settle=settle)
        if matchday.done
    }
    return [
        matchday
        for matchday in matchdays(after, after_at, zone=zone, settle=settle)
        if matchday.done and (matchday.gameweek, matchday.day) not in was
    ]
