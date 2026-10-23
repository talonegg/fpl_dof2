"""Which gameweek is being decided: the one definition, shared by forecast, week and publish.

Lives outside ``week`` so the model factory can use it without importing the orchestrator
(MOD-01); :mod:`fpl_dof.week.cadence` re-exports it.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from fpl_dof.frames import as_int


class NoDeadlineError(RuntimeError):
    """Every gameweek is behind us, or the gameweek table is empty."""


def gameweek_ahead(gameweeks: pd.DataFrame, as_of: dt.datetime | pd.Timestamp) -> int | None:
    """The gameweek whose deadline is the first still ahead of ``as_of``; ``None`` if none is.

    **The one definition of which gameweek is being decided** (PIPE-12, REM-08). Forecast, publish
    and transform read it through :func:`current_gameweek`; week, decision and the schedule through
    :func:`next_deadline`; the day-before gate through :func:`find_next_deadline_event`. They differ
    only in what they do once the season's last deadline has passed.
    """
    if gameweeks.empty:
        return None
    moment = pd.Timestamp(as_of)
    moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
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
