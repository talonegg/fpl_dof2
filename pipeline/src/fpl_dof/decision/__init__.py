"""The decision engine: one :func:`decide` for every strategy (MOD-04). Core: pure, no I/O."""

from fpl_dof.decision.engine import Decision, DecisionPolicy, decide, solve_plan

__all__ = ["Decision", "DecisionPolicy", "decide", "solve_plan"]
