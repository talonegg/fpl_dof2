"""Stage orchestration.

The pipeline is an ordered list of named stages, each a pure-ish function from a
:class:`StageContext` to a :class:`StageResult`. The orchestrator owns everything cross-cutting —
timing, logging context, manifest records, checksums, failure handling — so no stage has to.

Stage callables are resolved lazily by import path. That keeps the registry readable as a single
table and means an incomplete stage cannot break ``--help``.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from fpl_dof.config import Config
from fpl_dof.obs import (
    ManifestWriter,
    RunManifest,
    StageRecord,
    StageStatus,
    get_logger,
    stage_context,
    utcnow,
)
from fpl_dof.paths import DataLayout

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StageOptions:
    """Run-time switches that apply across stages."""

    force_refresh: bool = False
    offline: bool = False
    player_limit: int | None = None


@dataclass(frozen=True, slots=True)
class StageContext:
    config: Config
    layout: DataLayout
    run_id: str
    options: StageOptions = field(default=StageOptions())


@dataclass(frozen=True, slots=True)
class Output:
    """A file a stage produced. ``rows`` is recorded where the artefact is tabular."""

    path: Path
    rows: int | None = None


@dataclass
class StageResult:
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    outputs: list[Output] = field(default_factory=list)


class StageFn(Protocol):
    def __call__(self, ctx: StageContext) -> StageResult: ...


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    summary: str
    target: str  # "module:function"

    def resolve(self) -> StageFn:
        module_name, _, attribute = self.target.partition(":")
        module = importlib.import_module(module_name)
        fn = getattr(module, attribute)
        return fn  # type: ignore[no-any-return]


#: The pipeline, in order. ``run`` executes all of these.
STAGES: tuple[Stage, ...] = (
    Stage(
        name="ingest",
        summary="Fetch source data and write immutable bronze snapshots",
        target="fpl_dof.stages.ingest:run",
    ),
    Stage(
        name="transform",
        summary="Conform bronze into validated silver tables",
        target="fpl_dof.stages.transform:run",
    ),
    Stage(
        name="quality",
        summary="Check the silver layer; a blocking failure stops the run before anything is built",
        target="fpl_dof.stages.quality:run",
    ),
    Stage(
        name="forecast",
        summary="Produce expected points per player, with uncertainty",
        target="fpl_dof.stages.forecast:run",
    ),
    Stage(
        name="optimise",
        summary="Solve for the best legal squad",
        target="fpl_dof.stages.optimise:run",
    ),
    Stage(
        name="week",
        summary="Produce the weekly transfer, lineup and alert recommendation",
        target="fpl_dof.stages.week:run",
    ),
    Stage(
        name="decision",
        summary="Plan the next few gameweeks and the chip calendar (E4)",
        target="fpl_dof.stages.decision:run",
    ),
    Stage(
        name="publish",
        summary="Write the versioned web contract",
        target="fpl_dof.stages.publish:run",
    ),
)

#: Stages that exist as commands but are **not** part of ``run``.
#:
#: The backtest is slow, needs the historical backfill, and produces a finding rather than an
#: artefact the weekly pipeline consumes. Keeping it out of ``run`` keeps the deadline path fast —
#: and keeps the backtest honest, because nobody is tempted to skip it for making Friday late.
AUXILIARY_STAGES: tuple[Stage, ...] = (
    Stage(
        name="backtest",
        summary="Walk-forward replay against history, with baselines. Not part of `run`",
        target="fpl_dof.stages.backtest:run",
    ),
)

STAGE_NAMES: tuple[str, ...] = tuple(stage.name for stage in STAGES)
ALL_STAGES: tuple[Stage, ...] = (*STAGES, *AUXILIARY_STAGES)
ALL_STAGE_NAMES: tuple[str, ...] = tuple(stage.name for stage in ALL_STAGES)
_BY_NAME = {stage.name: stage for stage in ALL_STAGES}


class UnknownStageError(KeyError):
    """A stage name was requested that is not in the registry."""


def get_stage(name: str) -> Stage:
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        raise UnknownStageError(
            f"unknown stage {name!r}; known stages are {', '.join(ALL_STAGE_NAMES)}"
        ) from exc


def resolve_stages(names: Sequence[str] | None) -> list[Stage]:
    if not names:
        return list(STAGES)
    return [get_stage(name) for name in names]


class StageFailedError(RuntimeError):
    """A stage raised. The run is over; the manifest records how far it got."""


def run_stages(
    stages: Sequence[Stage],
    ctx: StageContext,
    writer: ManifestWriter,
    *,
    resolver: Callable[[Stage], StageFn] | None = None,
) -> RunManifest:
    """Execute ``stages`` in order, recording each in the manifest.

    A failing stage stops the run — a half-finished pipeline must never publish (Invariant 7).
    """
    resolve = resolver or (lambda stage: stage.resolve())
    overall = StageStatus.SUCCEEDED

    for stage in stages:
        started = utcnow()
        with stage_context(stage.name):
            log.info("stage.start", extra={"stage_summary": stage.summary})
            try:
                result = resolve(stage)(ctx)
            except Exception as exc:
                finished = utcnow()
                log.exception("stage.failed")
                writer.record(
                    StageRecord(
                        name=stage.name,
                        status=StageStatus.FAILED,
                        started_at=started,
                        finished_at=finished,
                        duration_seconds=(finished - started).total_seconds(),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                writer.finish(StageStatus.FAILED)
                raise StageFailedError(f"stage {stage.name!r} failed: {exc}") from exc

            finished = utcnow()
            artefacts = [
                writer.artefact(output.path, rows=output.rows)
                for output in result.outputs
                if output.path.exists()
            ]
            writer.record(
                StageRecord(
                    name=stage.name,
                    status=StageStatus.SUCCEEDED,
                    started_at=started,
                    finished_at=finished,
                    duration_seconds=(finished - started).total_seconds(),
                    metrics=result.metrics,
                    artefacts=artefacts,
                )
            )
            log.info(
                "stage.done",
                extra={
                    "duration_seconds": round((finished - started).total_seconds(), 3),
                    "artefact_count": len(artefacts),
                    **{f"metric.{k}": v for k, v in result.metrics.items()},
                },
            )

    return writer.finish(overall)
