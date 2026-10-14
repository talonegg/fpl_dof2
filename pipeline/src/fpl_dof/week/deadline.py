"""When the deadline is, in both the zone FPL talks in and the zone you live in.

Preserved as a facade delegating to fpl_dof.week.cadence (DL-11).
"""

from __future__ import annotations

from fpl_dof.week.cadence import (
    UK_ZONE,
    DeadlineView,
    NoDeadlineError,
    describe_deadline,
    next_deadline,
    to_contract,
)

__all__ = [
    "UK_ZONE",
    "DeadlineView",
    "NoDeadlineError",
    "describe_deadline",
    "next_deadline",
    "to_contract",
]
