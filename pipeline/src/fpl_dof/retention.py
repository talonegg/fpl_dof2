"""Which bronze snapshots survive a retention rebuild — pure, no filesystem, no git (DP-03).

The ``data`` branch (architecture §7.3) is rebuilt from scratch every run from a retained rolling
window and force-pushed, because deleting a file from the tip of a git branch does not reclaim
anything — the blob stays in history. This module answers only "which files are inside the window",
so that question can be tested without a checkout, a clock mock disguised as a fixture, or git.

**Age is read from the snapshot's own path, never from filesystem mtime.** ``git checkout``
rewrites every file's mtime to the moment of checkout, so an mtime-keyed retention job running
against a freshly cloned branch would see every file as brand new and retain all of them forever —
silently, and looking exactly like it was working. Bronze snapshots already carry their date in the
path (``bronze/<source>/<resource>/<YYYY-MM-DD>/...``, see ``sources/bronze.py``), which survives a
clone untouched.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class UndatedSnapshotError(ValueError):
    """A path under ``bronze/`` did not carry a ``YYYY-MM-DD`` directory component.

    Raised rather than guessed at: a file retention cannot date is a file retention must not
    silently delete (Invariant 7's spirit — a gate that cannot see a case must not act on it).
    """


def snapshot_date(path: str) -> dt.date:
    """The date directory embedded in a bronze snapshot path.

    Expects ``.../<source>/<resource>/<YYYY-MM-DD>/<file>`` anywhere in ``path`` — the date
    component is found by scanning path parts rather than assuming a fixed depth, so this keeps
    working if a source ever nests resources.
    """
    for part in PurePosixPath(path.replace("\\", "/")).parts:
        if _DATE_DIR.match(part):
            return dt.date.fromisoformat(part)
    raise UndatedSnapshotError(f"no YYYY-MM-DD directory component found in {path!r}")


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    """The result of partitioning a snapshot list by age. Both lists preserve input order."""

    retain: tuple[str, ...]
    prune: tuple[str, ...]
    undated: tuple[str, ...]
    """Paths retention could not date. Always retained (never pruned) — see UndatedSnapshotError."""


def plan_retention(
    paths: list[str], *, today: dt.date, window_days: int, keep: frozenset[str] = frozenset()
) -> RetentionPlan:
    """Partition bronze snapshot paths into what a rebuilt ``data`` branch should keep.

    A snapshot is retained when its embedded date is within ``window_days`` of ``today``,
    inclusive of the boundary day itself. An undated path is retained and reported separately
    rather than pruned, so a future change to the bronze layout fails loudly (as a growing
    ``undated`` list) instead of quietly deleting evidence.

    ``keep`` is retained whatever its age: immutable snapshots of finished seasons and their
    sidecars, which cannot change and would otherwise be re-fetched once they aged out (REM-10).
    """
    if window_days <= 0:
        raise ValueError(f"window_days must be positive, got {window_days}")

    cutoff = today - dt.timedelta(days=window_days)
    retain: list[str] = []
    prune: list[str] = []
    undated: list[str] = []

    for path in paths:
        try:
            date = snapshot_date(path)
        except UndatedSnapshotError:
            undated.append(path)
            continue
        if date > cutoff or path in keep:
            retain.append(path)
        else:
            prune.append(path)

    return RetentionPlan(retain=tuple(retain), prune=tuple(prune), undated=tuple(undated))


@dataclass(frozen=True, slots=True)
class ArchivePlan:
    """Which gameweeks the permanent archive writes now, and which it can no longer write."""

    archive: dict[int, tuple[str, ...]]
    """Gameweek -> the bronze paths that make up its evidence. Closed and not yet archived."""
    partial: tuple[int, ...]
    """Gameweeks in ``archive`` whose window began before the oldest bronze still held."""
    lost: tuple[int, ...]
    """Closed, never archived, and no bronze left for them: gone for good."""


def plan_gameweek_archive(
    paths: list[str],
    *,
    deadlines: Mapping[int, dt.datetime],
    today: dt.date,
    archived: set[int],
) -> ArchivePlan:
    """Partition bronze into one permanent archive per gameweek (PIPE-14, NFR-06).

    Gameweek N's evidence is the bronze dated after GW N-1's deadline day, up to and including GW
    N's deadline day: what was known when GW N was decided. The window closes the day after its
    deadline, so a gameweek is archived once and never rewritten. GW1 takes everything up to its
    deadline day.
    shortcut: bronze dated after the season's final deadline day is not archived; add a season-end
    window if those results are ever needed as evidence.
    """
    dated: list[tuple[dt.date, str]] = []
    for path in paths:
        try:
            dated.append((snapshot_date(path), path))
        except UndatedSnapshotError:
            continue
    oldest = min((date for date, _ in dated), default=None)

    archive: dict[int, tuple[str, ...]] = {}
    partial: list[int] = []
    lost: list[int] = []
    previous: dt.date | None = None
    for gameweek in sorted(deadlines):
        end = deadlines[gameweek].date()
        start = previous
        previous = end
        if gameweek in archived or today <= end:
            continue
        window = tuple(
            path for date, path in dated if (start is None or date > start) and date <= end
        )
        if not window:
            lost.append(gameweek)
            continue
        archive[gameweek] = window
        if start is not None and oldest is not None and oldest > start + dt.timedelta(days=1):
            partial.append(gameweek)

    return ArchivePlan(archive=archive, partial=tuple(partial), lost=tuple(lost))


__all__ = [
    "ArchivePlan",
    "RetentionPlan",
    "UndatedSnapshotError",
    "plan_gameweek_archive",
    "plan_retention",
    "snapshot_date",
]
