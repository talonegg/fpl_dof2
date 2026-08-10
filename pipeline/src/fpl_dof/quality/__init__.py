"""Data quality gates.

The difference between "it produced output" and "the output can be relied on". The steel thread
had schema validation and nothing else, which catches a column that changed type and misses
everything that matters more: a table that silently halved in size, a foreign key that points
nowhere, a snapshot three days stale that still parses perfectly.

**A failing gate blocks publication (Invariant 7).** Stale and honest beats fresh and wrong, because
a stale artefact is visibly stale while a wrong one looks exactly like a right one.
"""

from fpl_dof.quality.gates import (
    GateOutcome,
    GateReport,
    GateResult,
    GateSeverity,
    QualityGateError,
    run_gates,
)
from fpl_dof.quality.rules import GATES, Gate, GateClass

__all__ = [
    "GATES",
    "Gate",
    "GateClass",
    "GateOutcome",
    "GateReport",
    "GateResult",
    "GateSeverity",
    "QualityGateError",
    "run_gates",
]
