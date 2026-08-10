"""Quality stage — check silver before anything is built on it.

Placed after ``transform`` and before ``forecast`` so a blocking failure stops the run *before* a
squad exists. That ordering is the whole mechanism behind Invariant 7: publication is blocked not
by a check inside the publisher, which could be bypassed, but by there being nothing new to
publish. Whatever was published last stays live, and it is visibly older rather than invisibly
wrong.

The gate report is written to gold and recorded in the manifest either way — a warning that
publishes still has to be findable afterwards, or it may as well not have fired.
"""

from __future__ import annotations

import json

from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.quality.gates import GateReport, GateSeverity, QualityGateError, run_gates
from fpl_dof.quality.rules import GATES
from fpl_dof.silver.store import read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.sources import BronzeStore
from fpl_dof.stages.transform import read_rules

log = get_logger(__name__)

REPORT_FILENAME = "quality.json"


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    silver = ctx.layout.silver

    tables = {
        table.value: frame
        for table in Table
        if (frame := read_table_optional(silver, season, table)) is not None
    }

    players = tables.get(Table.PLAYER.value)
    teams = tables.get(Table.TEAM.value)
    context: dict[str, object] = {
        "quality": ctx.config.quality,
        "now": utcnow(),
        "team_ids": frozenset(teams["team_id"]) if teams is not None else None,
        "player_ids": frozenset(players["player_id"]) if players is not None else None,
        "snapshot_age_seconds": _newest_snapshot_age(ctx),
        "previous_row_counts": _previous_row_counts(ctx, season),
    }

    report = run_gates(GATES, tables, context)
    if ctx.config.quality.fail_on_warnings:
        report = _promote_warnings(report)

    path = ctx.layout.gold / f"season={season.replace('/', '-')}" / REPORT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")

    result = StageResult(
        metrics={
            "passed": str(report.passed),
            "gates": len(report.results),
            **{f"gates.{key}": value for key, value in report.counts().items()},
            "blocking": len(report.blocking),
        },
        outputs=[Output(path=path)],
    )

    for failure in report.failures:
        log.warning(
            "quality.failure",
            extra={
                "gate": failure.gate,
                "severity": failure.severity.label,
                "requirement": failure.requirement,
                "detail": failure.message,
            },
        )

    if not report.passed:
        # Raised after the report is written, so the evidence survives the failure. A gate that
        # blocks a run and leaves nothing to read is a gate that gets disabled the first time it
        # fires at 03:00.
        raise QualityGateError(report)

    log.info("quality.passed", extra={"summary": report.summary()})
    return result


def _promote_warnings(report: GateReport) -> GateReport:
    """Treat every warning as blocking. For CI, where publishing nothing is cheap."""
    from dataclasses import replace

    return GateReport(
        results=tuple(
            replace(result, severity=GateSeverity.ERROR)
            if result.severity is GateSeverity.WARN
            else result
            for result in report.results
        )
    )


def _newest_snapshot_age(ctx: StageContext) -> float | None:
    """How old the freshest bronze snapshot is, in seconds.

    Freshest rather than oldest on purpose: an archive snapshot from last season is *supposed* to
    be a year old, and judging freshness by the oldest file would flag every run that has ever
    backfilled history.
    """
    bronze = BronzeStore(ctx.layout.bronze)
    if not bronze.root.is_dir():
        return None
    ages = [
        (utcnow().timestamp() - path.stat().st_mtime) for path in bronze.root.rglob("*.meta.json")
    ]
    return min(ages) if ages else None


def _previous_row_counts(ctx: StageContext, season: str) -> dict[str, int] | None:
    """Row counts from the most recent successful earlier run, for the volume-stability gate."""
    runs = ctx.layout.runs
    if not runs.is_dir():
        return None
    manifests = sorted(runs.glob("*/manifest.json"))
    for path in reversed(manifests):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if manifest.get("run_id") == ctx.run_id or manifest.get("status") != "succeeded":
            continue
        for stage in manifest.get("stages", []):
            if stage.get("name") != "transform":
                continue
            metrics = stage.get("metrics") or {}
            counts = {
                key.removeprefix("rows."): int(value)
                for key, value in metrics.items()
                if key.startswith("rows.") and isinstance(value, int | float)
            }
            if counts:
                return counts
    return None
