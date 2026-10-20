"""Backdating a source added mid-season (PIPE-01, DL-81 item 6, DL-83).

A source switched on at gameweek 10 has no captures for gameweeks 1 to 9, and a backtest walking
those gameweeks needs to know what the source *would* have said at each deadline. There are two ways
to answer, depending on what the source publishes:

- **A timestamped match log.** Each event counts towards every gameweek whose deadline falls after
  it, so a season-to-date total is rebuilt exactly as it stood at each deadline.
- **Running totals only.** Each gameweek takes the latest snapshot captured before its deadline.
  A gameweek before the first snapshot gets no row at all. That is the "best effort": a stale total
  carried forward, never a later total scaled back, which would be look-ahead (Invariant 5).

Both return ``player_advanced`` rows, stamped with ``as_of_gameweek`` and ``observed_at`` so the
look-ahead gate can check them like any live capture. The adapter that uses one also stamps its
crosswalk references' ``ingress`` with the method, so the provenance is recorded.
"""

from __future__ import annotations

import pandas as pd

from fpl_dof.silver.tables import ADVANCED_METRICS, Table, columns_for

_PLAYER = ["season", "source", "source_player_id"]


def from_match_log(log: pd.DataFrame, gameweeks: pd.DataFrame, *, through: int) -> pd.DataFrame:
    """Season-to-date totals as they stood at each deadline up to gameweek ``through``.

    ``log`` has one row per player per match: ``season``, ``source``, ``source_player_id``,
    ``event_time`` and any metric columns. ``matches`` counts the rows unless the log carries it.
    """
    metrics = [m for m in ADVANCED_METRICS if m in log.columns and m != "matches"]
    log = log.assign(event_time=pd.to_datetime(log["event_time"], utc=True))
    frames = []
    for gameweek, deadline in _deadlines(gameweeks, through).items():
        known = log[log["event_time"] < deadline]
        if known.empty:
            continue
        grouped = known.groupby(_PLAYER, sort=True)
        totals = grouped[metrics].sum(min_count=1)
        totals["matches"] = grouped["matches"].sum() if "matches" in log.columns else grouped.size()
        totals["observed_at"] = grouped["event_time"].max()
        frames.append(_rows(totals.reset_index(), gameweek))
    return _concat(frames)


def from_running_totals(
    snapshots: pd.DataFrame, gameweeks: pd.DataFrame, *, through: int
) -> pd.DataFrame:
    """Each gameweek's totals: every player's latest snapshot captured before its deadline.

    ``snapshots`` has one row per player per capture: ``season``, ``source``,
    ``source_player_id``, ``observed_at`` and the totals as published at that moment.
    """
    ordered = snapshots.assign(observed_at=pd.to_datetime(snapshots["observed_at"], utc=True))
    ordered = ordered.sort_values("observed_at")
    frames = []
    for gameweek, deadline in _deadlines(gameweeks, through).items():
        known = ordered[ordered["observed_at"] < deadline]
        if not known.empty:
            frames.append(_rows(known.groupby(_PLAYER, sort=True).tail(1), gameweek))
    return _concat(frames)


def _deadlines(gameweeks: pd.DataFrame, through: int) -> dict[int, pd.Timestamp]:
    known = gameweeks[gameweeks["gameweek"] <= through].sort_values("gameweek")
    return dict(
        zip(
            known["gameweek"].astype(int),
            pd.to_datetime(known["deadline_time"], utc=True),
            strict=True,
        )
    )


def _rows(frame: pd.DataFrame, gameweek: int) -> pd.DataFrame:
    rows = frame.assign(
        as_of_gameweek=gameweek, player_id=None, player_code=None, scope="season", gameweek=None
    )
    return rows.reindex(columns=columns_for(Table.PLAYER_ADVANCED))


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=columns_for(Table.PLAYER_ADVANCED))
    return pd.concat(frames, ignore_index=True)
