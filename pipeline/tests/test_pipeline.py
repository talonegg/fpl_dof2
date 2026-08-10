from __future__ import annotations

from pathlib import Path

import pytest

from fpl_dof.config import Config
from fpl_dof.obs import ManifestWriter, StageStatus, read_manifest
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import (
    STAGE_NAMES,
    STAGES,
    Output,
    Stage,
    StageContext,
    StageFailedError,
    StageResult,
    UnknownStageError,
    get_stage,
    resolve_stages,
    run_stages,
)


def _writer(layout: DataLayout) -> ManifestWriter:
    return ManifestWriter(
        run_id="20260810T000000Z-testtest",
        config_digest="0" * 64,
        runs_dir=layout.runs,
        data_root=layout.root,
    )


def test_stage_registry_is_the_documented_pipeline() -> None:
    assert STAGE_NAMES == ("ingest", "transform", "forecast", "optimise", "publish")
    assert len({stage.name for stage in STAGES}) == len(STAGES)


def test_every_registered_stage_target_actually_resolves() -> None:
    for stage in STAGES:
        assert callable(stage.resolve()), stage.name


def test_unknown_stage_is_rejected() -> None:
    with pytest.raises(UnknownStageError):
        get_stage("nonsense")


def test_resolve_stages_defaults_to_the_whole_pipeline() -> None:
    assert resolve_stages(None) == list(STAGES)
    assert [s.name for s in resolve_stages(["publish", "ingest"])] == ["publish", "ingest"]


def test_run_records_outputs_with_checksums(config: Config, layout: DataLayout) -> None:
    artefact = layout.gold / "squad.json"
    artefact.write_text("{}", encoding="utf-8")

    def fake(ctx: StageContext) -> StageResult:
        return StageResult(metrics={"n": 1}, outputs=[Output(path=artefact, rows=15)])

    writer = _writer(layout)
    manifest = run_stages(
        [Stage(name="optimise", summary="", target="x:y")],
        StageContext(config=config, layout=layout, run_id="r"),
        writer,
        resolver=lambda _stage: fake,
    )

    record = manifest.stage("optimise")
    assert record is not None
    assert record.status is StageStatus.SUCCEEDED
    assert record.metrics == {"n": 1}
    assert [a.path for a in record.artefacts] == ["gold/squad.json"]
    assert record.artefacts[0].rows == 15


def test_missing_outputs_are_not_recorded(config: Config, layout: DataLayout) -> None:
    def fake(ctx: StageContext) -> StageResult:
        return StageResult(outputs=[Output(path=layout.gold / "never-written.json")])

    writer = _writer(layout)
    manifest = run_stages(
        [Stage(name="publish", summary="", target="x:y")],
        StageContext(config=config, layout=layout, run_id="r"),
        writer,
        resolver=lambda _stage: fake,
    )
    record = manifest.stage("publish")
    assert record is not None
    assert record.artefacts == []


def test_failure_stops_the_run_and_is_recorded(config: Config, layout: DataLayout) -> None:
    calls: list[str] = []

    def failing(ctx: StageContext) -> StageResult:
        calls.append("first")
        raise ValueError("source unreachable")

    def never(ctx: StageContext) -> StageResult:  # pragma: no cover - must not run
        calls.append("second")
        return StageResult()

    stages = [
        Stage(name="ingest", summary="", target="x:y"),
        Stage(name="transform", summary="", target="x:y"),
    ]
    writer = _writer(layout)
    resolver = {"ingest": failing, "transform": never}

    with pytest.raises(StageFailedError):
        run_stages(
            stages,
            StageContext(config=config, layout=layout, run_id="r"),
            writer,
            resolver=lambda stage: resolver[stage.name],
        )

    assert calls == ["first"], "a failed stage must stop the run"
    manifest = read_manifest(writer.path)
    assert manifest.status is StageStatus.FAILED
    ingest = manifest.stage("ingest")
    assert ingest is not None
    assert ingest.status is StageStatus.FAILED
    assert ingest.error is not None
    assert "source unreachable" in ingest.error


def test_data_layout_creates_every_tier(tmp_path: Path) -> None:
    built = DataLayout(root=tmp_path / "data")
    built.ensure()
    for tier in built.all_tiers():
        assert tier.is_dir()
    built.ensure()  # idempotent
