from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from fpl_dof.retention import (
    UndatedSnapshotError,
    plan_gameweek_archive,
    plan_retention,
    snapshot_date,
)


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


def _scripts_retention() -> ModuleType:
    import sys

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import retention

    return retention


DEADLINES = {
    1: dt.datetime(2026, 8, 14, 17, 30, tzinfo=dt.UTC),
    2: dt.datetime(2026, 8, 21, 17, 30, tzinfo=dt.UTC),
    3: dt.datetime(2026, 8, 28, 17, 30, tzinfo=dt.UTC),
    4: dt.datetime(2026, 9, 4, 17, 30, tzinfo=dt.UTC),
}


def test_plan_gameweek_archive_takes_each_closed_window_once() -> None:
    paths = [
        "fpl/bootstrap_static/2026-08-16/all.json.gz",  # GW2's window, after GW1's deadline day
        "fpl/bootstrap_static/2026-08-21/all.json.gz",  # GW2's own deadline day
        "fpl/bootstrap_static/2026-08-25/all.json.gz",  # GW3
        "fpl/bootstrap_static/2026-09-04/all.json.gz",  # GW4, still open
        "fpl/undated/all.json.gz",
    ]
    plan = plan_gameweek_archive(
        paths, deadlines=DEADLINES, today=dt.date(2026, 9, 2), archived=set()
    )
    assert plan.archive == {2: tuple(paths[:2]), 3: (paths[2],)}
    assert plan.partial == (2,)  # GW2's window began on 15 Aug; the oldest bronze is 16 Aug
    assert plan.lost == (1,)

    again = plan_gameweek_archive(
        paths, deadlines=DEADLINES, today=dt.date(2026, 9, 2), archived={2, 3}
    )
    assert again.archive == {}
    assert again.lost == (1,)


def test_plan_gameweek_archive_waits_for_the_deadline_day_to_end() -> None:
    paths = ["fpl/bootstrap_static/2026-08-14/all.json.gz"]
    on_the_day = plan_gameweek_archive(
        paths, deadlines=DEADLINES, today=dt.date(2026, 8, 14), archived=set()
    )
    assert on_the_day.archive == {}
    day_after = plan_gameweek_archive(
        paths, deadlines=DEADLINES, today=dt.date(2026, 8, 15), archived=set()
    )
    assert day_after.archive == {1: (paths[0],)}


def _git(*args: str, cwd: Path) -> str:
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def test_archive_bronze_by_gameweek_writes_once_and_records_losses(tmp_path: Path) -> None:
    import json
    import tarfile

    from fpl_dof.sources.bronze import BronzeStore

    retention = _scripts_retention()
    bare = tmp_path / "remote.git"
    _git("init", "--bare", str(bare), cwd=tmp_path)

    bronze = tmp_path / "bronze"
    store = BronzeStore(bronze)
    events = [
        {"id": gw, "deadline_time": deadline.isoformat(), "finished": False, "is_next": False}
        for gw, deadline in DEADLINES.items()
    ]
    for day in (16, 21, 25):
        store.write(
            json.dumps({"events": events}).encode(),
            source="fpl",
            source_version="1",
            resource="bootstrap_static",
            key="all",
            url="https://example.invalid/bootstrap-static/",
            http_status=200,
            now=dt.datetime(2026, 8, day, 6, 0, tzinfo=dt.UTC),
        )

    def archive() -> dict[str, list[int]]:
        result: dict[str, list[int]] = retention.archive_bronze_by_gameweek(
            bronze_dir=bronze,
            checkout_dir=tmp_path / "checkout",
            remote=str(bare),
            today=dt.date(2026, 9, 2),
        )
        return result

    assert archive() == {"written": [2, 3], "partial": [2], "lost": [1]}

    clone = tmp_path / "clone"
    _git("clone", "--branch", "snapshots", str(bare), str(clone), cwd=tmp_path)
    season = clone / "bronze-full" / "2026-27"
    index = json.loads((season / "index.json").read_text(encoding="utf-8"))
    assert index == {"archived": [2, 3], "partial": [2], "lost": [1]}
    with tarfile.open(season / "gw02.tar.gz") as tar:
        assert len([n for n in tar.getnames() if n.endswith(".json.gz")]) == 2

    # The same run again changes nothing: a written gameweek is never rewritten.
    commits = _git("rev-list", "--count", "HEAD", cwd=clone)
    assert archive() == {"written": [], "partial": [], "lost": [1]}
    _git("pull", "--quiet", cwd=clone)
    assert _git("rev-list", "--count", "HEAD", cwd=clone) == commits


def test_archive_bronze_by_gameweek_fails_without_a_schedule(tmp_path: Path) -> None:
    retention = _scripts_retention()
    with pytest.raises(retention.NoGameweekScheduleError):
        retention.archive_bronze_by_gameweek(
            bronze_dir=tmp_path / "bronze",
            checkout_dir=tmp_path / "checkout",
            remote=str(tmp_path / "unused.git"),
        )


def test_append_permanent_snapshot_writes_no_index(tmp_path: Path) -> None:
    """The ledger shares this mechanism; the archive's index must never appear there."""
    retention = _scripts_retention()
    bare = tmp_path / "remote.git"
    _git("init", "--bare", str(bare), cwd=tmp_path)
    payload = tmp_path / "gw05.json"
    payload.write_text("{}", encoding="utf-8")

    assert retention.append_permanent_snapshot(
        checkout_dir=tmp_path / "checkout",
        payload_path=payload,
        remote=str(bare),
        branch="ledger",
        source="advice",
        gameweek=5,
    )
    clone = tmp_path / "clone"
    _git("clone", "--branch", "ledger", str(bare), str(clone), cwd=tmp_path)
    assert (clone / "advice" / "gw05.json").exists()
    assert not (clone / "index.json").exists()


def test_a_named_ledger_record_is_appended_and_never_overwritten(tmp_path: Path) -> None:
    """MOD-08: experiments records are keyed by run, so a run never replaces another's record."""
    retention = _scripts_retention()
    bare = tmp_path / "remote.git"
    _git("init", "--bare", str(bare), cwd=tmp_path)

    def append(name: str, body: str) -> bool:
        payload = tmp_path / "record.json"
        payload.write_text(body, encoding="utf-8")
        appended: bool = retention.append_permanent_snapshot(
            checkout_dir=tmp_path / "checkout",
            payload_path=payload,
            remote=str(bare),
            branch="ledger",
            source="experiments",
            name=name,
        )
        return appended

    assert append("20261027T161700Z-aaaa", "[1]")
    assert append("20261103T161700Z-bbbb", "[2]")
    assert not append("20261103T161700Z-bbbb", "[2]")  # the same bytes again: a no-op
    with pytest.raises(FileExistsError):
        append("20261027T161700Z-aaaa", "[3]")

    clone = tmp_path / "clone"
    _git("clone", "--branch", "ledger", str(bare), str(clone), cwd=tmp_path)
    records = clone / "experiments"
    assert (records / "20261027T161700Z-aaaa.json").read_text(encoding="utf-8") == "[1]"
    assert (records / "20261103T161700Z-bbbb.json").read_text(encoding="utf-8") == "[2]"


def _price_rows(day: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observed_at": [pd.Timestamp(f"2026-08-{day:02d}T06:00Z")],
            "player_id": [1],
            "player_code": [101],
            "price": [5.0],
            "selected_by_percent": [1.0],
            "transfers_in_event": [0],
            "transfers_out_event": [0],
            "cost_change_event": [0.0],
            "cost_change_start": [0.0],
        }
    )


def _store(root: Path, day: int) -> Path:
    """A local data root holding one bronze snapshot and one price row, both dated `day`."""
    from fpl_dof.silver.store import write_table
    from fpl_dof.silver.tables import Table

    snapshot = root / "bronze" / "fpl" / "bootstrap_static" / f"2026-08-{day:02d}"
    snapshot.mkdir(parents=True)
    (snapshot / f"all__{day}.json.gz").write_bytes(b"payload")
    write_table(root / "silver", "2026/27", Table.PRICE_HISTORY, _price_rows(day))
    return root


def test_rebuild_rolling_branch_never_drops_what_another_run_pushed(tmp_path: Path) -> None:
    """REM-03: a run that restored before another pushed folds that push in, never drops it."""
    from fpl_dof.silver.store import read_table
    from fpl_dof.silver.tables import Table

    retention = _scripts_retention()
    bare = tmp_path / "remote.git"
    _git("init", "--bare", str(bare), cwd=tmp_path)

    def push(root: Path) -> None:
        retention.rebuild_rolling_branch(
            bronze_dir=root / "bronze",
            staging_dir=tmp_path / f"staging-{root.name}",
            remote=str(bare),
            window_days=30,
            today=dt.date(2026, 8, 31),
        )

    push(_store(tmp_path / "fast", 20))  # ingest-fast pushes first...
    late = _store(tmp_path / "pipeline", 21)  # ...the pipeline restored before that push
    push(late)

    clone = tmp_path / "clone"
    _git("clone", "--branch", "data", str(bare), str(clone), cwd=tmp_path)
    days = sorted(p.name for p in (clone / "bronze" / "fpl" / "bootstrap_static").iterdir())
    assert days == ["2026-08-20", "2026-08-21"]
    prices = read_table(clone / "silver", "2026/27", Table.PRICE_HISTORY)
    assert sorted(prices["observed_at"].dt.day) == [20, 21]


def test_rebuild_rolling_branch_retries_when_the_branch_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retention = _scripts_retention()
    bare = tmp_path / "remote.git"
    _git("init", "--bare", str(bare), cwd=tmp_path)
    root = _store(tmp_path / "data", 20)

    def rebuild() -> None:
        retention.rebuild_rolling_branch(
            bronze_dir=root / "bronze",
            staging_dir=tmp_path / "staging",
            remote=str(bare),
            window_days=30,
            today=dt.date(2026, 8, 31),
        )

    rebuild()
    real_fold = retention._fold_in_remote
    calls: list[str] = []

    def stale_once(*args: object) -> str:
        sha: str = real_fold(*args)
        calls.append(sha)
        return "1" * 40 if len(calls) == 1 else sha  # as if another run pushed after the fold

    monkeypatch.setattr(retention, "_fold_in_remote", stale_once)
    # New bronze, as a real run brings: an identical commit would be a no-op push, never leased.
    newer = root / "bronze" / "fpl" / "bootstrap_static" / "2026-08-21"
    newer.mkdir(parents=True)
    (newer / "all__21.json.gz").write_bytes(b"payload")
    rebuild()
    assert len(calls) == 2


def test_immutable_prior_season_bronze_outlives_the_window(tmp_path: Path) -> None:
    """REM-10: a finished season's snapshot cannot change, so the rolling branch keeps it rather
    than letting the next run fetch it again. Its mutable neighbour of the same age is pruned."""
    rebuild_rolling_branch = _scripts_retention().rebuild_rolling_branch
    day = tmp_path / "data" / "bronze" / "fplarchive" / "merged_gw" / "2026-07-01"
    day.mkdir(parents=True)
    for name, immutable in (("2024-25__x.csv.gz", True), ("live__x.csv.gz", False)):
        (day / name).write_bytes(b"payload")
        (day / f"{name}.meta.json").write_text(
            json.dumps({"immutable": immutable}), encoding="utf-8"
        )

    staging = tmp_path / "staging"
    counts = rebuild_rolling_branch(
        bronze_dir=tmp_path / "data" / "bronze",
        staging_dir=staging,
        remote="dummy",
        window_days=30,
        today=dt.date(2026, 10, 20),
        dry_run=True,
    )
    staged = staging / "bronze" / "fplarchive" / "merged_gw" / "2026-07-01"
    assert sorted(p.name for p in staged.iterdir()) == [
        "2024-25__x.csv.gz",
        "2024-25__x.csv.gz.meta.json",
    ]
    assert counts["pruned"] == 2


def test_retained_captures_outlive_the_window_and_unretained_ones_do_not(tmp_path: Path) -> None:
    """DL-87: every fdcouk capture is kept whatever its age; an old non-retained one is pruned."""
    rebuild_rolling_branch = _scripts_retention().rebuild_rolling_branch
    day = tmp_path / "data" / "bronze" / "fdcouk" / "fixtures" / "2026-07-01"
    day.mkdir(parents=True)
    for name, retain in (("kept__x.csv.gz", True), ("pruned__x.csv.gz", False)):
        (day / name).write_bytes(b"payload")
        (day / f"{name}.meta.json").write_text(
            json.dumps({"immutable": False, "retain": retain}), encoding="utf-8"
        )
    staging = tmp_path / "staging"
    rebuild_rolling_branch(
        bronze_dir=tmp_path / "data" / "bronze",
        staging_dir=staging,
        remote="dummy",
        window_days=30,
        today=dt.date(2026, 10, 20),
        dry_run=True,
    )
    staged = staging / "bronze" / "fdcouk" / "fixtures" / "2026-07-01"
    assert sorted(p.name for p in staged.iterdir()) == [
        "kept__x.csv.gz",
        "kept__x.csv.gz.meta.json",
    ]


def test_the_rolling_window_is_read_from_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REM-10: no fallback literal; a window set in config is the one applied."""
    retention = _scripts_retention()
    override = tmp_path / "window.yaml"
    override.write_text("retention:\n  bronze_days: 5\n", encoding="utf-8")
    monkeypatch.setenv("FPL_DOF_CONFIG_FILE", str(override))
    day = tmp_path / "data" / "bronze" / "fpl" / "bootstrap_static" / "2026-10-10"
    day.mkdir(parents=True)
    (day / "all__x.json.gz").write_bytes(b"payload")

    counts = retention.rebuild_rolling_branch(
        bronze_dir=tmp_path / "data" / "bronze",
        staging_dir=tmp_path / "staging",
        remote="dummy",
        today=dt.date(2026, 10, 20),
        dry_run=True,
    )
    assert counts["pruned"] == 1  # ten days old: kept by the old literal 30, pruned by config's 5
