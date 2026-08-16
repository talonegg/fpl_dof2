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


def plan_retention(paths: list[str], *, today: dt.date, window_days: int) -> RetentionPlan:
    """Partition bronze snapshot paths into what a rebuilt ``data`` branch should keep.

    A snapshot is retained when its embedded date is within ``window_days`` of ``today``,
    inclusive of the boundary day itself. An undated path is retained and reported separately
    rather than pruned, so a future change to the bronze layout fails loudly (as a growing
    ``undated`` list) instead of quietly deleting evidence.
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
        if date > cutoff:
            retain.append(path)
        else:
            prune.append(path)

    return RetentionPlan(retain=tuple(retain), prune=tuple(prune), undated=tuple(undated))


__all__ = [
    "RetentionPlan",
    "UndatedSnapshotError",
    "plan_retention",
    "snapshot_date",
]
