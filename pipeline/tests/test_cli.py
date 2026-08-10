from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from conftest import FIXTURE_QUALITY
from fpl_dof.cli import EXIT_BAD_USAGE, EXIT_OK, build_parser, main
from fpl_dof.pipeline import STAGE_NAMES

pytestmark = pytest.mark.usefixtures("recorded_fpl_api")


@pytest.fixture(autouse=True)
def fixture_sized_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the CLI at gate thresholds that match the trimmed recorded league.

    The CLI reads configuration for itself rather than taking a Config object, so the override has
    to arrive through the environment. Without it the quality gate correctly rejects an 8-club,
    92-player fixture — which is the gate working, not the pipeline failing.
    """
    override = tmp_path / "cli-config.yaml"
    override.write_text(yaml.safe_dump(FIXTURE_QUALITY), encoding="utf-8")
    monkeypatch.setenv("FPL_DOF_CONFIG_FILE", str(override))


def test_help_lists_every_stage(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    out = capsys.readouterr().out
    for name in (*STAGE_NAMES, "run"):
        assert name in out


def test_no_op_run_writes_a_valid_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    assert main(["--data-dir", str(data_dir), "run", "--only", "ingest", "transform"]) == EXIT_OK
    manifest = json.loads(
        next((data_dir / "runs").glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert [s["name"] for s in manifest["stages"]] == ["ingest", "transform"]


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


def test_a_run_in_a_temporary_directory_leaves_the_app_data_alone(tmp_path: Path) -> None:
    """A test run must not overwrite what the application is serving.

    It did. The publish stage copied its artefacts into ``web/public/data`` on *every* run,
    including runs pointed at a temporary directory — so this suite silently replaced the real
    577-player data with the 8-club recorded fixture, and the browser verification went on
    reporting success while checking the wrong thing entirely.

    That is the exact failure DP-13 is about: nothing looked wrong. The verification still passed.
    """
    from fpl_dof.paths import find_repo_root
    from fpl_dof.stages.publish import WEB_PUBLIC_PATH

    repo = find_repo_root()
    assert repo is not None
    published = repo.joinpath(*WEB_PUBLIC_PATH) / "players.json"
    before = published.read_bytes() if published.exists() else None

    assert main(["--data-dir", str(tmp_path / "data"), "run"]) == EXIT_OK

    after = published.read_bytes() if published.exists() else None
    assert after == before, (
        "a run against a temporary data root modified the application's published data"
    )
