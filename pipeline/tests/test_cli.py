from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpl_dof.cli import EXIT_BAD_USAGE, EXIT_OK, build_parser, main
from fpl_dof.pipeline import STAGE_NAMES


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
