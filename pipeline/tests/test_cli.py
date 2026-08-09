from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from fpl_dof.cli import EXIT_BAD_USAGE, EXIT_OK, build_parser, main
from fpl_dof.pipeline import STAGE_NAMES
from fpl_dof.sources.base import IngestReport, IngestRequest, Resource, SourceAdapter
from fpl_dof.sources.registry import temporary_registry


class _StubSource(SourceAdapter):
    """A source that does nothing, so CLI tests exercise wiring rather than the FPL API."""

    name: ClassVar[str] = "stub"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "stub source for CLI tests"
    base_url: ClassVar[str] = "https://stub.invalid"
    resources: ClassVar[tuple[Resource, ...]] = (Resource(name="nothing", summary="nothing"),)

    def ingest(self, request: IngestRequest) -> IngestReport:
        return IngestReport(source=self.name, resources={"nothing": 0})


@pytest.fixture(autouse=True)
def stub_sources() -> Iterator[None]:
    with temporary_registry((_StubSource,)):
        yield


def test_help_lists_every_stage(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    out = capsys.readouterr().out
    for name in (*STAGE_NAMES, "run"):
        assert name in out


def test_no_op_run_writes_a_valid_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("FPL_DOF_CONFIG_FILE", raising=False)
    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "run"]) == EXIT_OK

    manifests = list((data_dir / "runs").glob("*/manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))

    assert manifest["run_id"]
    assert manifest["status"] == "succeeded"
    assert manifest["config_digest"]
    assert [s["name"] for s in manifest["stages"]] == list(STAGE_NAMES)
    assert all(s["status"] == "succeeded" for s in manifest["stages"])

    assert manifest["run_id"] in capsys.readouterr().out


def test_only_restricts_the_stages_that_run(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "run", "--only", "forecast", "optimise"]) == EXIT_OK
    manifest = json.loads(
        next((data_dir / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert [s["name"] for s in manifest["stages"]] == ["forecast", "optimise"]


def test_single_stage_invocation(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "ingest"]) == EXIT_OK
    manifest = json.loads(
        next((data_dir / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert [s["name"] for s in manifest["stages"]] == ["ingest"]


def test_unknown_stage_in_only_exits_with_usage_error(tmp_path: Path) -> None:
    code = main(["--data-dir", str(tmp_path / "data"), "run", "--only", "nonsense"])
    assert code == EXIT_BAD_USAGE
