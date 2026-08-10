"""The weekly operating loop: what to do this week, and why.

E0 answered "what squad should I build". This package answers "it is Thursday evening, what am I
doing" — which is the question that has to be answerable 37 more times.
"""

from fpl_dof.week.alerts import Alert, AlertSeverity, collect_alerts
from fpl_dof.week.deadline import DeadlineView, describe_deadline, next_deadline
from fpl_dof.week.reconcile import Divergence, Reconciliation, reconcile

__all__ = [
    "Alert",
    "AlertSeverity",
    "DeadlineView",
    "Divergence",
    "Reconciliation",
    "collect_alerts",
    "describe_deadline",
    "next_deadline",
    "reconcile",
]
