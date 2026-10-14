"""Has a workflow already done today's (or this gameweek's) work? Pure; stdlib only.

GitHub drops and delays scheduled firings on this repo, so key workflows fire more than once and
each extra firing asks this module whether the work is already done. Input is the JSON that
``gh run list --json databaseId,displayTitle,status,conclusion,createdAt,event`` prints.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any


def _created(run: Mapping[str, Any]) -> dt.datetime:
    return dt.datetime.fromisoformat(str(run["createdAt"]).replace("Z", "+00:00"))


def succeeded_since(
    runs: Iterable[Mapping[str, Any]],
    since: dt.datetime,
    *,
    exclude_id: int | None = None,
    title_contains: str | None = None,
) -> Mapping[str, Any] | None:
    """The first completed-successfully run created at or after ``since`` (optionally titled)."""
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
    """A run with this title that is queued/in progress or succeeded. A failed one is retried."""
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
