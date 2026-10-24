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


def test_a_run_leaves_web_src_untouched(tmp_path: Path) -> None:
    """WEB-03: the generated types are written by `contract types`, never by a pipeline run."""
    from fpl_dof.paths import find_repo_root

    repo = find_repo_root()
    assert repo is not None

    def snapshot() -> dict[str, tuple[int, int]]:
        return {
            str(f): (f.stat().st_size, f.stat().st_mtime_ns)
            for f in (repo / "web" / "src").rglob("*")
            if f.is_file()
        }

    before = snapshot()
    assert main(["--data-dir", str(tmp_path / "data"), "run"]) == EXIT_OK
    assert snapshot() == before


def test_silver_replay_prices_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "ingest"]) == EXIT_OK
    assert main(["--data-dir", str(data_dir), "silver", "replay-prices"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "replay-prices: processed" in out


@pytest.mark.parametrize("stages", [["ingest"], ["run"], ["run", "--only", "ingest", "transform"]])
def test_as_of_refuses_to_run_ingest(tmp_path: Path, stages: list[str]) -> None:
    """REM-02: ingest fetches the present; filing it under a past date would corrupt bronze."""
    code = main(["--data-dir", str(tmp_path / "data"), "--as-of", "2026-08-15T12:00:00Z", *stages])
    assert code == EXIT_BAD_USAGE


def test_every_artefact_names_one_gameweek_while_a_gameweek_is_in_play(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REM-08 / PIPE-12: after GW1's deadline and before it finishes, the forecast, the week and
    the plan all decide GW2. Each stage used to pick its gameweek by its own predicate."""
    monkeypatch.setenv("FPL_DOF_AS_OF", "2026-08-22T12:00:00+00:00")  # GW1 deadline 21 Aug
    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "run"]) == EXIT_OK

    def read(name: str) -> dict[str, object]:
        return dict(json.loads((data_dir / "web" / "v1" / name).read_text(encoding="utf-8")))

    meta, week, plan = read("meta.json"), read("week.json"), read("plan.json")
    gameweeks = {
        meta["next_gameweek"],
        week["deadline"]["gameweek"],  # type: ignore[index]
        plan["deadline"]["gameweek"],  # type: ignore[index]
    }
    assert gameweeks == {2}
    assert plan.get("gameweeks", [2])[0] == 2  # type: ignore[index]


def test_silver_from_before_a_schema_change_names_the_rebuild_and_the_rebuild_works(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """REM-10: old-layout silver stops transform with the fix in the message, not a schema dump;
    `silver rebuild` sets it aside (kept) and rebuilds from bronze."""
    import pandas as pd

    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "run", "--only", "ingest", "transform"]) == EXIT_OK
    table = next((data_dir / "silver").glob("season=*/price_history.parquet"))
    pd.read_parquet(table).drop(columns=["player_code"]).to_parquet(table)  # an older layout

    assert main(["--data-dir", str(data_dir), "transform"]) != EXIT_OK
    assert "fpl-dof silver rebuild" in capsys.readouterr().err

    assert main(["--data-dir", str(data_dir), "silver", "rebuild"]) == EXIT_OK
    assert "player_code" in pd.read_parquet(table).columns
    kept = list((data_dir / "quarantine").glob("silver-*/season=*/price_history.parquet"))
    assert len(kept) == 1 and "player_code" not in pd.read_parquet(kept[0]).columns
