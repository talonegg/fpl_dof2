"""Has a workflow already done today's (or this gameweek's) work?

Preserved as a facade delegating to fpl_dof.week.cadence.
"""

from __future__ import annotations

from fpl_dof.week.cadence import (
    active_or_succeeded,
    start_of_utc_day,
    succeeded_since,
)

__all__ = [
    "active_or_succeeded",
    "start_of_utc_day",
    "succeeded_since",
]
