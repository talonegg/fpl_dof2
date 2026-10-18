from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from fpl_dof.retention import UndatedSnapshotError, plan_retention, snapshot_date


def test_snapshot_date_finds_the_date_directory_at_any_depth() -> None:
    assert snapshot_date(
        "bronze/fpl/bootstrap-static/2026-08-10/all__20260810T041530Z.json.gz"
    ) == dt.date(2026, 8, 10)
    assert snapshot_date(
        "bronze/fpl/element-summary/nested/2026-01-01/x__20260101T000000Z.json.gz"
    ) == dt.date(2026, 1, 1)


def test_snapshot_date_raises_when_no_date_directory_is_present() -> None:
    with pytest.raises(UndatedSnapshotError):
        snapshot_date("bronze/fpl/bootstrap-static/all__20260810T041530Z.json.gz")


def test_plan_retention_keeps_the_window_and_prunes_the_rest() -> None:
    today = dt.date(2026, 8, 31)
    paths = [
        "bronze/fpl/bootstrap-static/2026-08-31/all__x.json.gz",  # today, kept
        "bronze/fpl/bootstrap-static/2026-08-02/all__x.json.gz",  # 29 days ago, kept
        "bronze/fpl/bootstrap-static/2026-08-01/all__x.json.gz",  # exactly the cutoff, pruned
        "bronze/fpl/bootstrap-static/2025-01-01/all__x.json.gz",  # ancient, pruned
    ]

    plan = plan_retention(paths, today=today, window_days=30)

    assert plan.retain == (paths[0], paths[1])
    assert plan.prune == (paths[2], paths[3])
    assert plan.undated == ()


def test_plan_retention_never_prunes_an_undated_path() -> None:
    paths = ["bronze/fpl/bootstrap-static/all__no_date_dir.json.gz"]

    plan = plan_retention(paths, today=dt.date(2026, 8, 31), window_days=30)

    assert plan.retain == ()
    assert plan.prune == ()
    assert plan.undated == tuple(paths)


def test_plan_retention_rejects_a_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window_days"):
        plan_retention([], today=dt.date(2026, 8, 31), window_days=0)


def test_plan_retention_is_stable_across_a_simulated_month_of_daily_runs() -> None:
    """The E7 DoD acceptance test in miniature: a month of daily churn must not grow the retained
    set past the window, which is the property that keeps a rebuilt `data` branch bounded."""
    start = dt.date(2026, 1, 1)
    retained_counts: list[int] = []

    for day_offset in range(60):
        today = start + dt.timedelta(days=day_offset)
        # One new snapshot per day since the start, simulating an ever-growing bronze store.
        paths = [
            f"bronze/fpl/bootstrap-static/{(start + dt.timedelta(days=i)).isoformat()}"
            "/all__x.json.gz"
            for i in range(day_offset + 1)
        ]
        plan = plan_retention(paths, today=today, window_days=30)
        retained_counts.append(len(plan.retain))

    # Bounded at the window size once the simulated history exceeds it — never grows past 30.
    assert max(retained_counts) <= 30
    assert retained_counts[-1] == 30


def test_rebuild_rolling_branch_stages_silver_price_history(tmp_path: Path) -> None:
    import sys

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from retention import rebuild_rolling_branch

    bronze = tmp_path / "data" / "bronze" / "fpl" / "bootstrap-static" / "2026-08-31"
    bronze.mkdir(parents=True)
    (bronze / "all__x.json.gz").write_bytes(b"dummy")
    (bronze / "all__x.json.gz.meta.json").write_text("{}", encoding="utf-8")

    silver = tmp_path / "data" / "silver" / "season=2026-27"
    silver.mkdir(parents=True)
    (silver / "price_history.parquet").write_bytes(b"parquet-bytes")

    staging = tmp_path / "staging"
    counts = rebuild_rolling_branch(
        bronze_dir=tmp_path / "data" / "bronze",
        staging_dir=staging,
        remote="dummy",
        window_days=30,
        today=dt.date(2026, 8, 31),
        dry_run=True,
    )
    assert counts["silver"] == 1
    staged_silver = staging / "silver" / "season=2026-27" / "price_history.parquet"
    assert staged_silver.exists()
    assert staged_silver.read_bytes() == b"parquet-bytes"


def test_restore_rolling_branch_restores_bronze_and_silver(tmp_path: Path) -> None:
    import subprocess
    import sys

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from retention import restore_rolling_branch

    bare_repo = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare_repo)], check=True, capture_output=True)

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    subprocess.run(["git", "init"], cwd=scratch, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "data"], cwd=scratch, check=True, capture_output=True)

    b_dir = scratch / "bronze" / "fpl"
    b_dir.mkdir(parents=True)
    (b_dir / "sample.json.gz").write_bytes(b"hello-bronze")

    s_dir = scratch / "silver" / "season=2026-27"
    s_dir.mkdir(parents=True)
    (s_dir / "price_history.parquet").write_bytes(b"hello-silver")

    subprocess.run(["git", "add", "-A"], cwd=scratch, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=CI", "-c", "user.email=ci@test", "commit", "-m", "init data"],
        cwd=scratch,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", str(bare_repo), "data:data"],
        cwd=scratch,
        check=True,
        capture_output=True,
    )

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    subprocess.run(["git", "init"], cwd=consumer, check=True, capture_output=True)

    target = consumer / "data"
    ok = restore_rolling_branch(data_dir=target, remote=str(bare_repo), branch="data", cwd=consumer)
    assert ok is True
    assert (target / "bronze" / "fpl" / "sample.json.gz").read_bytes() == b"hello-bronze"
    restored_parquet = target / "silver" / "season=2026-27" / "price_history.parquet"
    assert restored_parquet.read_bytes() == b"hello-silver"


def test_restore_rolling_branch_missing_branch(tmp_path: Path) -> None:
    import subprocess
    import sys

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from retention import restore_rolling_branch

    bare_repo = tmp_path / "empty_remote.git"
    subprocess.run(["git", "init", "--bare", str(bare_repo)], check=True, capture_output=True)

    consumer = tmp_path / "consumer_empty"
    consumer.mkdir()
    subprocess.run(["git", "init"], cwd=consumer, check=True, capture_output=True)

    target = consumer / "data"
    ok = restore_rolling_branch(data_dir=target, remote=str(bare_repo), branch="data", cwd=consumer)
    assert ok is False


def test_append_permanent_snapshot_maintains_index(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from retention import append_permanent_snapshot

    bare_repo = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare_repo)], check=True, capture_output=True)

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    subprocess.run(["git", "init"], cwd=scratch, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", "snapshots"], cwd=scratch, check=True, capture_output=True
    )
    (scratch / "README.md").write_text("snapshots branch", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=scratch, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=CI", "-c", "user.email=ci@test", "commit", "-m", "init"],
        cwd=scratch,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", str(bare_repo), "snapshots:snapshots"],
        cwd=scratch,
        check=True,
        capture_output=True,
    )

    tarball = tmp_path / "bronze-gw5.tar.gz"
    tarball.write_bytes(b"dummy tarball content")

    ok = append_permanent_snapshot(
        checkout_dir=tmp_path / "perm_checkout",
        payload_path=tarball,
        remote=str(bare_repo),
        branch="snapshots",
        source="bronze-full",
        gameweek=5,
    )
    assert ok is True

    # Clone snapshots and verify index.json
    verify_dir = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", "--branch", "snapshots", str(bare_repo), str(verify_dir)],
        check=True,
        capture_output=True,
    )
    index_file = verify_dir / "index.json"
    assert index_file.exists()
    index_data = json.loads(index_file.read_text(encoding="utf-8"))
    assert len(index_data["snapshots"]) == 1
    assert index_data["snapshots"][0]["gameweek"] == 5
    assert index_data["lost_gameweeks"] == [1, 2, 3, 4]
    assert "Gameweeks 1-4 were lost" in index_data["note"]
