"""PIPE-11: Bronze store integrity audit & snapshot hygiene tooling tests.

Verifies:
1. Valid snapshots pass verification with exact counts.
2. Gzip decompression corruption is detected with exact file path.
3. Checksum mismatch against meta.sha256 is detected.
4. Orphaned payloads and orphaned metadata sidecars are detected.
5. Quarantine moves corrupt/orphaned files out of bronze, keeping them, and leaves valid ones.
6. CLI command `fpl-dof bronze verify` produces expected outputs and exit codes.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from fpl_dof.cli import EXIT_OK, EXIT_STAGE_FAILED, main
from fpl_dof.sources.bronze import META_SUFFIX, BronzeStore


@pytest.fixture
def bronze_with_valid_snapshot(tmp_path: Path) -> tuple[BronzeStore, Path]:
    bronze_dir = tmp_path / "bronze"
    store = BronzeStore(bronze_dir)
    snapshot = store.write(
        b'{"status": "ok"}',
        source="test_source",
        source_version="1",
        resource="test_resource",
        key="test_key",
        url="https://example.com/api",
        http_status=200,
    )
    return store, snapshot.path


def test_valid_snapshot_passes_verification(
    bronze_with_valid_snapshot: tuple[BronzeStore, Path],
) -> None:
    store, _ = bronze_with_valid_snapshot
    report = store.verify()
    assert report.is_clean
    assert report.total_snapshots == 1
    assert report.passed == 1
    assert report.failed == 0
    assert len(report.issues) == 0


def test_corrupt_gzip_is_flagged_with_exact_path(
    bronze_with_valid_snapshot: tuple[BronzeStore, Path],
) -> None:
    store, path = bronze_with_valid_snapshot
    # Corrupt the gzip payload with non-gzip bytes
    path.write_bytes(b"corrupted-non-gzip-content")

    report = store.verify()
    assert not report.is_clean
    assert report.total_snapshots == 1
    assert report.failed == 1
    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.path == path
    assert issue.kind == "corrupt_gzip"


def test_checksum_mismatch_is_flagged_with_exact_path(
    bronze_with_valid_snapshot: tuple[BronzeStore, Path],
) -> None:
    store, path = bronze_with_valid_snapshot
    # Write a valid gzip payload whose content does not match the original meta.sha256
    with gzip.open(path, "wb") as gz:
        gz.write(b'{"different": "data"}')

    report = store.verify()
    assert not report.is_clean
    assert report.total_snapshots == 1
    assert report.failed == 1
    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.path == path
    assert issue.kind == "checksum_mismatch"
    assert "checksum mismatch" in issue.detail


def test_orphaned_payload_without_metadata_is_flagged_and_quarantined(
    bronze_with_valid_snapshot: tuple[BronzeStore, Path],
) -> None:
    store, path = bronze_with_valid_snapshot
    meta_path = path.with_name(path.name + META_SUFFIX)
    meta_path.unlink()  # Remove metadata, making payload an orphan

    report = store.verify()
    assert not report.is_clean
    assert any(i.kind == "missing_metadata" and i.path == path for i in report.issues)

    quarantined = store.verify(quarantine=True)
    assert path in quarantined.quarantined
    assert not quarantined.unresolved
    assert not path.exists()
    assert (store.quarantine_root / path.relative_to(store.root)).read_bytes()


def test_orphaned_metadata_without_payload_is_flagged_and_quarantined(
    bronze_with_valid_snapshot: tuple[BronzeStore, Path],
) -> None:
    store, path = bronze_with_valid_snapshot
    meta_path = path.with_name(path.name + META_SUFFIX)
    path.unlink()  # Remove payload, making meta an orphan

    report = store.verify()
    assert not report.is_clean
    assert any(i.kind == "missing_payload" and i.path == meta_path for i in report.issues)

    quarantined = store.verify(quarantine=True)
    assert meta_path in quarantined.quarantined
    assert not meta_path.exists()
    assert (store.quarantine_root / meta_path.relative_to(store.root)).exists()


def test_invalid_directory_structure_is_flagged(tmp_path: Path) -> None:
    bronze_dir = tmp_path / "bronze"
    bad_dir = bronze_dir / "src" / "res" / "not-a-date"
    bad_dir.mkdir(parents=True)
    (bad_dir / "file.json.gz").write_bytes(b"data")

    store = BronzeStore(bronze_dir)
    report = store.verify()
    assert not report.is_clean
    assert any(i.kind == "invalid_directory" and i.path == bad_dir for i in report.issues)


def test_cli_bronze_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir = tmp_path / "data"
    store = BronzeStore(data_dir / "bronze")
    store.write(
        b'{"test": 123}',
        source="fpl",
        source_version="1",
        resource="bootstrap_static",
        key="all",
        url="https://example.com",
        http_status=200,
    )

    # Clean run returns EXIT_OK
    assert main(["--data-dir", str(data_dir), "bronze", "verify"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "bronze verify: 1 snapshots checked, 1 passed, 0 failed, 0 issue(s)" in out

    # Corrupting payload causes EXIT_STAGE_FAILED
    payload_file = next((data_dir / "bronze").glob("*/*/*/*.json.gz"))
    payload_file.write_bytes(b"bad bytes")

    assert main(["--data-dir", str(data_dir), "bronze", "verify"]) == EXIT_STAGE_FAILED
    out = capsys.readouterr().out
    assert "1 failed" in out
    assert "[corrupt_gzip]" in out

    # Quarantine moves it aside; nothing remains in bronze, so the command passes.
    assert main(["--data-dir", str(data_dir), "bronze", "verify", "--quarantine"]) == EXIT_OK
    assert "quarantined 2 file(s)" in capsys.readouterr().out
    assert main(["--data-dir", str(data_dir), "bronze", "verify"]) == EXIT_OK

    # An issue quarantine cannot move stays, and keeps failing the command (REM-10).
    (data_dir / "bronze" / "fpl" / "bootstrap_static" / "not-a-date").mkdir()
    assert main(["--data-dir", str(data_dir), "bronze", "verify", "--quarantine"]) == (
        EXIT_STAGE_FAILED
    )


def test_a_damaged_deflate_stream_is_labelled_a_corrupt_payload(
    bronze_with_valid_snapshot: tuple[BronzeStore, Path],
) -> None:
    """REM-10: zlib.error is not an OSError; it used to be reported as corrupt metadata."""
    store, path = bronze_with_valid_snapshot
    good = gzip.compress(b'{"status": "ok", "padding": "' + b"x" * 400 + b'"}', mtime=0)
    damaged = bytearray(good)
    damaged[12:20] = bytes([0xFF] * 8)  # inside the deflate stream, past the gzip header
    path.write_bytes(bytes(damaged))

    issue = store.verify().issues[0]
    assert issue.kind == "corrupt_gzip"
    assert issue.path == path


def test_touch_never_leaves_a_half_written_sidecar(
    bronze_with_valid_snapshot: tuple[BronzeStore, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """REM-10: a revalidation that dies mid-write keeps the old lineage whole."""
    store, path = bronze_with_valid_snapshot
    sidecar = path.with_name(path.name + META_SUFFIX)
    before = sidecar.read_text(encoding="utf-8")
    snapshot = next(s for s in [store.latest("test_source", "test_resource", "test_key")] if s)

    def torn(self: Path, data: str, *args: object, **kwargs: object) -> int:
        with self.open("w", encoding="utf-8") as handle:
            handle.write(data[: len(data) // 2])
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", torn)
    with pytest.raises(OSError, match="disk full"):
        store.touch(snapshot, now=snapshot.meta.fetched_at)
    monkeypatch.undo()
    assert sidecar.read_text(encoding="utf-8") == before
