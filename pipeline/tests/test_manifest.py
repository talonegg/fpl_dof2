from __future__ import annotations

import datetime as dt
from pathlib import Path

from fpl_dof.obs.manifest import (
    Artefact,
    ManifestWriter,
    StageRecord,
    StageStatus,
    new_run_id,
    read_manifest,
    sha256_file,
    utcnow,
)


def test_run_id_is_sortable_and_unique() -> None:
    early = new_run_id(dt.datetime(2026, 8, 10, 1, 0, tzinfo=dt.UTC))
    late = new_run_id(dt.datetime(2026, 8, 10, 2, 0, tzinfo=dt.UTC))
    assert early < late
    assert new_run_id() != new_run_id()


def test_utcnow_is_timezone_aware_utc() -> None:
    assert utcnow().tzinfo is dt.UTC


def test_artefact_records_checksum_and_relative_path(tmp_path: Path) -> None:
    target = tmp_path / "silver" / "player.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"abc")
    artefact = Artefact.of(target, root=tmp_path, rows=3)
    assert artefact.path == "silver/player.parquet"
    assert artefact.sha256 == sha256_file(target)
    assert artefact.bytes == 3
    assert artefact.rows == 3


def test_manifest_is_written_incrementally_and_reread(tmp_path: Path) -> None:
    writer = ManifestWriter(
        run_id="20260810T000000Z-deadbeef",
        config_digest="0" * 64,
        runs_dir=tmp_path / "runs",
        data_root=tmp_path,
        requested_stages=["ingest"],
    )
    assert writer.path.exists(), "manifest must exist before any stage runs"

    started = utcnow()
    writer.record(
        StageRecord(
            name="ingest",
            status=StageStatus.SUCCEEDED,
            started_at=started,
            finished_at=started,
            duration_seconds=0.0,
            metrics={"rows": 700},
        )
    )
    writer.finish(StageStatus.SUCCEEDED)

    reloaded = read_manifest(writer.path)
    assert reloaded.run_id == "20260810T000000Z-deadbeef"
    assert reloaded.status is StageStatus.SUCCEEDED
    assert reloaded.stage("ingest") is not None
    assert reloaded.stage("absent") is None
    assert reloaded.finished_at is not None
