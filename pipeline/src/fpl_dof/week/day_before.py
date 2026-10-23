"""The day-before refresh gate.

Preserved as a facade delegating to fpl_dof.week.cadence.
"""

from __future__ import annotations

from fpl_dof.week.cadence import (
    CRON,
    LOCAL_HOUR,
    SYDNEY,
    GateDecision,
    gate,
)
from fpl_dof.week.cadence import (
    find_next_deadline_event as next_deadline,
)

__all__ = [
    "CRON",
    "LOCAL_HOUR",
    "SYDNEY",
    "GateDecision",
    "gate",
    "next_deadline",
]
