"""The gate framework: how a check is declared, run, and acted on.

Four assertion classes (Design §3.4), because they fail in genuinely different ways:

``SCHEMA``
    Shape and type. Already enforced by Pandera on write; restated here so a gate report covers
    the whole picture rather than the part Pandera does not do.

``RANGE``
    Values inside their plausible bounds. A price of £250m parses fine.

``REFERENTIAL``
    Keys that point somewhere. A fixture against team 47 in a 20-team league is not a type error.

``FRESHNESS_AND_VOLUME``
    The class that catches the failures nobody anticipates. A source that returns 30 players
    instead of 700 produces a perfectly valid, perfectly wrong silver layer, and every other class
    of check passes.

Three severities, and the distinction is the whole point of having a framework rather than a list
of asserts:

``ERROR``   blocks publication. The last good artefact stays live.
``WARN``    publishes and surfaces. Something is odd; the decision is still usable.
``INFO``    records only. Useful for spotting drift over a season.

**Every gate names the requirement it protects (DP-14).** A check nobody can trace to a requirement
is a check nobody can argue with, and it will eventually be deleted by whoever it inconveniences.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

import pandas as pd

from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)


class GateSeverity(IntEnum):
    INFO = 10
    WARN = 20
    ERROR = 30

    @property
    def label(self) -> str:
        return self.name.lower()


class GateOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    """The data this gate checks is not present. Distinct from passing: a gate that never ran
    proves nothing, and reporting it as a pass is how a table quietly stops being checked."""


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: str
    gate_class: str
    severity: GateSeverity
    outcome: GateOutcome
    message: str
    requirement: str
    observed: dict[str, object] = field(default_factory=dict)

    @property
    def blocks_publication(self) -> bool:
        return self.outcome is GateOutcome.FAILED and self.severity is GateSeverity.ERROR

    def as_dict(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "class": self.gate_class,
            "severity": self.severity.label,
            "outcome": self.outcome.value,
            "message": self.message,
            "requirement": self.requirement,
            "observed": self.observed,
        }


@dataclass(frozen=True, slots=True)
class GateReport:
    results: tuple[GateResult, ...]

    @property
    def blocking(self) -> tuple[GateResult, ...]:
        return tuple(result for result in self.results if result.blocks_publication)

    @property
    def failures(self) -> tuple[GateResult, ...]:
        return tuple(r for r in self.results if r.outcome is GateOutcome.FAILED)

    @property
    def passed(self) -> bool:
        return not self.blocking

    def counts(self) -> dict[str, int]:
        counts = {outcome.value: 0 for outcome in GateOutcome}
        for result in self.results:
            counts[result.outcome.value] += 1
        return counts

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "counts": self.counts(),
            "blocking": [r.gate for r in self.blocking],
            "results": [r.as_dict() for r in self.results],
        }

    def summary(self) -> str:
        counts = self.counts()
        return f"{counts['passed']} passed, {counts['failed']} failed, {counts['skipped']} skipped"


class QualityGateError(RuntimeError):
    """An ``error``-severity gate failed. Publication stops here (Invariant 7)."""

    def __init__(self, report: GateReport) -> None:
        detail = "; ".join(f"{r.gate}: {r.message}" for r in report.blocking)
        super().__init__(
            f"{len(report.blocking)} blocking quality gate(s) failed, so nothing is published "
            f"and the last good artefact stays live: {detail}"
        )
        self.report = report


#: What a gate is handed. A mapping of table name to frame, plus whatever context the gate needs.
GateContext = Mapping[str, object]
GateCheck = Callable[[pd.DataFrame, GateContext], tuple[bool, str, dict[str, object]]]


def run_gates(
    gates: Sequence[object],
    tables: Mapping[str, pd.DataFrame],
    context: GateContext | None = None,
) -> GateReport:
    """Run every gate and return all of their results.

    Every gate runs even after one fails, for the same reason the squad validator returns every
    violation: being told about one problem at a time turns a five-minute fix into five runs.
    """
    from fpl_dof.quality.rules import Gate

    ctx: dict[str, object] = dict(context or {})
    results: list[GateResult] = []

    for gate in gates:
        assert isinstance(gate, Gate)
        frame = tables.get(gate.table)
        if frame is None:
            results.append(
                GateResult(
                    gate=gate.name,
                    gate_class=gate.gate_class.value,
                    severity=gate.severity,
                    outcome=GateOutcome.SKIPPED,
                    message=f"table {gate.table!r} is not present",
                    requirement=gate.requirement,
                )
            )
            continue

        ok, message, observed = gate.check(frame, ctx)
        outcome = GateOutcome.PASSED if ok else GateOutcome.FAILED
        result = GateResult(
            gate=gate.name,
            gate_class=gate.gate_class.value,
            severity=gate.severity,
            outcome=outcome,
            message=message,
            requirement=gate.requirement,
            observed=observed,
        )
        results.append(result)
        if outcome is GateOutcome.FAILED:
            log.warning(
                "quality.gate_failed",
                extra={
                    "gate": gate.name,
                    "severity": gate.severity.label,
                    "detail": message,
                },
            )

    return GateReport(results=tuple(results))


__all__ = [
    "GateCheck",
    "GateContext",
    "GateOutcome",
    "GateReport",
    "GateResult",
    "GateSeverity",
    "QualityGateError",
    "run_gates",
]
