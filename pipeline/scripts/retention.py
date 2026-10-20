"""Rebuild the `data` branch (rolling bronze, orphan, force-pushed) and append to `snapshots`
(permanent, append-only). The git plumbing — the effectful edge, per DP-03. All the "which files
survive" logic lives in :mod:`fpl_dof.retention` and is unit-tested without touching git.

Architecture §7.3 is explicit that the *mechanism* is the part that gets got wrong: deleting a file
from the tip of a git branch does not reclaim anything, so `data` is not maintained by committing
deletions — it is rebuilt from nothing and force-pushed, every run. `snapshots` is the opposite
shape on purpose: normal commits, never rewritten, because it is the NFR-06 evidence trail and no
amount of `data`-branch churn may threaten it.

Usage (run from the repo root, with `bronze_dir` pointing at a checked-out bronze store)::

    python pipeline/scripts/retention.py rolling <bronze_dir> --remote <url> --window-days 30
    python pipeline/scripts/retention.py permanent <payload> --remote <url> --gameweek 3
    python pipeline/scripts/retention.py archive <bronze_dir> --remote <url>

Both subcommands push to a real remote. `--dry-run` runs the same planning and staging logic
without pushing, for verification against a scratch local remote.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpl_dof.config import load_config
from fpl_dof.retention import plan_gameweek_archive, plan_retention
from fpl_dof.silver.store import append_table
from fpl_dof.silver.tables import Table
from fpl_dof.sources import gameweeks_from_bronze


class GitError(RuntimeError):
    """A git subprocess exited non-zero. The command and output are in the message."""


def _rmtree(path: Path) -> None:
    """``shutil.rmtree``, tolerant of git's read-only object files.

    Git marks blobs under ``.git/objects`` read-only on write, which is invisible on Linux (where
    the owner can still unlink a read-only file) and fatal on Windows (where it cannot). A local
    Windows run that reuses a staging directory across two invocations hits this on the second one;
    CI runners get a fresh directory every time and would never see it — but "only breaks in local
    dev" is still a bug, not a non-issue, so it is fixed rather than routed around.
    """

    def _on_error(func: object, target: str, _exc: object) -> None:
        Path(target).chmod(stat.S_IWRITE)
        func(target)  # type: ignore[operator]

    shutil.rmtree(path, onexc=_on_error)


def _run_git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120, check=False
    )
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def _bronze_paths(bronze_dir: Path) -> list[str]:
    """Every snapshot and its lineage sidecar, as paths relative to `bronze_dir`."""
    return sorted(
        str(path.relative_to(bronze_dir)).replace("\\", "/")
        for path in bronze_dir.rglob("*")
        if path.is_file()
    )


#: Pushes to `data` that lose the lease to another workflow are retried this many times.
PUSH_ATTEMPTS = 3


def _fold_in_remote(
    staging_dir: Path, remote: str, branch: str, bronze_dir: Path, silver_dir: Path | None
) -> str:
    """Fold what `branch` holds now into the local store, and return the commit it was read from.

    Three workflows rebuild `data` from what they restored when they started. Folding the branch in
    again just before pushing, and pushing only if it has not moved since, means no run's push can
    drop bronze or price rows that another run pushed meanwhile. Bronze files are immutable and
    uniquely named, so the local copy wins a clash; price rows are merged on their keys. ``""`` when
    the branch does not exist yet.
    """
    try:
        _run_git(["fetch", "--depth=1", remote, f"+{branch}:refs/fpl-dof/lease"], cwd=staging_dir)
    except GitError:
        return ""
    sha = _run_git(["rev-parse", "refs/fpl-dof/lease"], cwd=staging_dir).strip()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", sha],
        cwd=staging_dir,
        capture_output=True,
        timeout=120,
        check=True,
    ).stdout
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tmp, filter="data")
        held = Path(tmp)
        for path in (held / "bronze").rglob("*"):
            target = bronze_dir / path.relative_to(held / "bronze")
            if path.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        if silver_dir is not None:
            for path in (held / "silver").glob("season=*/price_history.parquet"):
                season = path.parent.name.removeprefix("season=").replace("-", "/")
                append_table(silver_dir, season, Table.PRICE_HISTORY, pd.read_parquet(path))
    return sha


def rebuild_rolling_branch(
    *,
    bronze_dir: Path,
    staging_dir: Path,
    remote: str,
    branch: str = "data",
    window_days: int | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    silver_dir: Path | None = None,
) -> dict[str, int]:
    """Rebuild `branch` from scratch as an orphan, containing only the retained window, and
    force-push it, but only over the commit folded in first (REM-03). Returns counts for
    reporting; the caller decides what to log."""
    if window_days is None:
        try:
            cfg, _ = load_config()
            window_days = cfg.retention.bronze_days
        except Exception:
            window_days = 30
    if silver_dir is None and (bronze_dir.parent / "silver").is_dir():
        silver_dir = bronze_dir.parent / "silver"

    for attempt in range(1, PUSH_ATTEMPTS + 1):
        if staging_dir.exists():
            _rmtree(staging_dir)
        staging_dir.mkdir(parents=True)
        _run_git(["init", "--quiet"], cwd=staging_dir)
        lease = (
            "" if dry_run else _fold_in_remote(staging_dir, remote, branch, bronze_dir, silver_dir)
        )
        counts = _stage_rolling(bronze_dir, staging_dir, silver_dir, window_days, today)
        if dry_run:
            return counts

        _run_git(["checkout", "--orphan", branch], cwd=staging_dir)
        _commit_all(
            staging_dir,
            f"data: rolling {window_days}-day bronze window as of {today or dt.date.today()}",
        )
        try:
            _run_git(
                [
                    "push",
                    f"--force-with-lease=refs/heads/{branch}:{lease}",
                    remote,
                    f"{branch}:{branch}",
                ],
                cwd=staging_dir,
            )
            return counts
        except GitError as exc:
            if "stale info" not in str(exc) and "rejected" not in str(exc):
                raise
            print(f"rolling: {branch} moved during this run; folding it in again ({attempt})")
    raise GitError(f"{branch} kept moving; gave up after {PUSH_ATTEMPTS} attempts")


def _stage_rolling(
    bronze_dir: Path,
    staging_dir: Path,
    silver_dir: Path | None,
    window_days: int,
    today: dt.date | None,
) -> dict[str, int]:
    """Copy the retained window and the accumulated price history into the staging checkout."""
    paths = _bronze_paths(bronze_dir)
    # A retention window applies to dated snapshots; sidecars share their snapshot's date
    # directory, so partitioning the full path list (snapshots and sidecars together) keeps a
    # snapshot and its lineage record moving together rather than pruning one without the other.
    plan = plan_retention(paths, today=today or dt.date.today(), window_days=window_days)
    retained = plan.retain + plan.undated

    for relative in retained:
        source = bronze_dir / relative
        destination = staging_dir / "bronze" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    # PIPE-06: Persist accumulating silver partitions (price_history.parquet)
    silver_count = 0
    if silver_dir is not None and silver_dir.is_dir():
        for p in sorted(silver_dir.glob("season=*/price_history.parquet")):
            rel = p.relative_to(silver_dir)
            dest = staging_dir / "silver" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            silver_count += 1

    return {
        "retained": len(retained),
        "pruned": len(plan.prune),
        "undated": len(plan.undated),
        "silver": silver_count,
    }


def restore_rolling_branch(
    *,
    data_dir: Path,
    remote: str = "origin",
    branch: str = "data",
    cwd: Path | None = None,
) -> bool:
    """Restore bronze and silver tiers from the rolling data branch (DL-79 O3, O4)."""
    work_cwd = cwd or Path.cwd()
    target_data_dir = (work_cwd / data_dir) if not data_dir.is_absolute() else data_dir
    target_data_dir.mkdir(parents=True, exist_ok=True)

    try:
        res = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", remote, branch],
            cwd=work_cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print(f"no {branch} branch on {remote} yet; starting from an empty store")
            return False
    except Exception as exc:
        print(f"could not check {remote}/{branch}: {exc}; starting from an empty store")
        return False

    _run_git(["fetch", "--depth=1", remote, f"{branch}:refs/fpl-dof/data-staging"], cwd=work_cwd)
    worktree_dir = target_data_dir.parent / f".worktree-{branch}"
    if worktree_dir.exists():
        _rmtree(worktree_dir)
    try:
        _run_git(["worktree", "add", str(worktree_dir), "refs/fpl-dof/data-staging"], cwd=work_cwd)

        for tier in ["bronze", "silver"]:
            tier_src = worktree_dir / tier
            if tier_src.is_dir():
                tier_dst = target_data_dir / tier
                tier_dst.mkdir(parents=True, exist_ok=True)
                for item in tier_src.rglob("*"):
                    if item.is_file():
                        rel = item.relative_to(tier_src)
                        target = tier_dst / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
        print(f"restored data from {remote}/{branch} into {target_data_dir}")
        return True
    finally:
        try:
            _run_git(["worktree", "remove", str(worktree_dir), "--force"], cwd=work_cwd)
        except Exception:
            if worktree_dir.exists():
                _rmtree(worktree_dir)
        _run_git(["worktree", "prune"], cwd=work_cwd)


def append_permanent_snapshot(
    *,
    checkout_dir: Path,
    remote: str,
    branch: str,
    source: str,
    gameweek: int,
    payload_path: Path,
    dry_run: bool = False,
) -> bool:
    """Append one source/gameweek snapshot to the append-only `snapshots` branch.

    Returns ``False`` (a no-op, not an error) if this exact snapshot is already present — running
    the same gameweek twice must not grow the branch, since it is meant to be kept forever.
    """
    destination_relative = f"{source}/gw{gameweek:02d}{payload_path.suffix}"
    branch_exists = _checkout_branch(checkout_dir, remote, branch)

    destination = checkout_dir / destination_relative
    if destination.exists() and destination.read_bytes() == payload_path.read_bytes():
        return False  # already recorded, identical bytes — nothing to append

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(payload_path, destination)

    if dry_run:
        return True

    try:
        _commit_all(checkout_dir, f"snapshots: {source} gw{gameweek}")
    except GitError as exc:
        # `git commit` on a clean tree is the same fact the byte-comparison above already checks
        # for, reached by a different path (e.g. `git add` normalising line endings or file mode
        # so the working tree ends up byte-identical to what was already committed even though the
        # two `read_bytes()` calls above compared unequal). Belt and braces: the append-only
        # contract is "this exact snapshot ends up recorded once", not "this exact code path was
        # the one that achieved it".
        if "nothing to commit" not in str(exc):
            raise
        return False

    _push(checkout_dir, remote, branch, branch_exists)
    return True


def _checkout_branch(checkout_dir: Path, remote: str, branch: str) -> bool:
    """A fresh checkout of `branch`, or an empty orphan of that name. True if it already existed."""
    if checkout_dir.exists():
        _rmtree(checkout_dir)
    checkout_dir.mkdir(parents=True)
    _run_git(["init", "--quiet"], cwd=checkout_dir)
    try:
        _run_git(["fetch", remote, f"{branch}:refs/fpl-dof/snapshots-staging"], cwd=checkout_dir)
        _run_git(["checkout", "refs/fpl-dof/snapshots-staging"], cwd=checkout_dir)
        return True
    except GitError:
        _run_git(["checkout", "--orphan", branch], cwd=checkout_dir)
        return False


def _commit_all(checkout_dir: Path, message: str) -> None:
    _run_git(["add", "-A"], cwd=checkout_dir)
    _run_git(
        [
            "-c",
            "user.email=fpl-dof-ci@users.noreply.github.com",
            "-c",
            "user.name=fpl-dof CI",
            "commit",
            "--quiet",
            "-m",
            message,
        ],
        cwd=checkout_dir,
    )


def _push(checkout_dir: Path, remote: str, branch: str, branch_exists: bool) -> None:
    push_ref = "HEAD:refs/heads/" + branch if not branch_exists else f"HEAD:{branch}"
    _run_git(["push", remote, push_ref], cwd=checkout_dir)


class NoGameweekScheduleError(RuntimeError):
    """Bronze holds no readable gameweek schedule, so no gameweek can be archived."""


def archive_bronze_by_gameweek(
    *,
    bronze_dir: Path,
    checkout_dir: Path,
    remote: str,
    branch: str = "snapshots",
    source: str = "bronze-full",
    today: dt.date | None = None,
    dry_run: bool = False,
) -> dict[str, list[int]]:
    """Write each closed gameweek's bronze to `snapshots` once, and record what is lost (PIPE-14).

    Paths are ``<source>/<season>/gwNN.tar.gz``; one that exists is never rewritten. The season's
    ``index.json`` lists the gameweeks archived, archived partially (their window began before the
    oldest bronze still held) and lost. Raises :class:`NoGameweekScheduleError` when bronze has no
    gameweek schedule: that is a broken ingest, never a quiet skip.
    """
    gameweeks = gameweeks_from_bronze(bronze_dir)
    if gameweeks is None or gameweeks.empty:
        raise NoGameweekScheduleError(f"no gameweek schedule in the bronze at {bronze_dir}")
    deadlines: dict[int, dt.datetime] = {}
    for gameweek, deadline in zip(gameweeks["gameweek"], gameweeks["deadline_time"], strict=True):
        deadlines[int(gameweek)] = deadline
    first = deadlines[min(deadlines)]
    season = f"{first.year}-{(first.year + 1) % 100:02d}"

    branch_exists = _checkout_branch(checkout_dir, remote, branch)
    season_dir = checkout_dir / source / season
    archived = {int(path.name[2:4]) for path in season_dir.glob("gw[0-9][0-9].tar.gz")}
    plan = plan_gameweek_archive(
        _bronze_paths(bronze_dir),
        deadlines=deadlines,
        today=today or dt.datetime.now(dt.UTC).date(),
        archived=archived,
    )

    index_path = season_dir / "index.json"
    index: dict[str, list[int]] = {"archived": [], "partial": [], "lost": []}
    if index_path.exists():
        index.update(json.loads(index_path.read_text(encoding="utf-8")))
    updated = {
        "archived": sorted(archived | set(plan.archive)),
        "partial": sorted(set(index["partial"]) | set(plan.partial)),
        "lost": sorted(set(index["lost"]) | set(plan.lost)),
    }
    result = {
        "written": sorted(plan.archive),
        "partial": list(plan.partial),
        "lost": list(plan.lost),
    }
    if updated == index and index_path.exists():
        return result

    season_dir.mkdir(parents=True, exist_ok=True)
    for gameweek, paths in plan.archive.items():
        with tarfile.open(season_dir / f"gw{gameweek:02d}.tar.gz", "w:gz") as tar:
            for relative in paths:
                tar.add(bronze_dir / relative, arcname=f"bronze/{relative}")
    index_path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")

    if dry_run:
        return result
    _commit_all(checkout_dir, f"snapshots: {source} {season} gameweeks {result['written']}")
    _push(checkout_dir, remote, branch, branch_exists)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rolling = sub.add_parser("rolling", help="Rebuild and force-push the rolling `data` branch")
    rolling.add_argument("bronze_dir", type=Path)
    rolling.add_argument("--remote", required=True)
    rolling.add_argument("--branch", default="data")
    rolling.add_argument(
        "--window-days",
        type=int,
        default=None,
        help="Retention window in days (default: read from config).",
    )
    rolling.add_argument("--silver-dir", type=Path, default=None)
    rolling.add_argument("--staging-dir", type=Path, default=Path(".retention-staging"))
    rolling.add_argument("--dry-run", action="store_true")
    rolling.add_argument(
        "--today",
        type=dt.date.fromisoformat,
        default=None,
        help="Override 'today' for the retention window (testing only; production uses the "
        "real date).",
    )

    restore = sub.add_parser("restore", help="Restore bronze and silver from the data branch")
    restore.add_argument("data_dir", type=Path, nargs="?", default=Path("data"))
    restore.add_argument("--remote", default="origin")
    restore.add_argument("--branch", default="data")

    permanent = sub.add_parser("permanent", help="Append one snapshot to `snapshots`")
    permanent.add_argument("payload_path", type=Path)
    permanent.add_argument("--remote", required=True)
    permanent.add_argument("--branch", default="snapshots")
    permanent.add_argument("--source", required=True)
    permanent.add_argument("--gameweek", type=int, required=True)
    permanent.add_argument("--checkout-dir", type=Path, default=Path(".snapshots-staging"))
    permanent.add_argument("--dry-run", action="store_true")

    archive = sub.add_parser("archive", help="Archive each closed gameweek's bronze once")
    archive.add_argument("bronze_dir", type=Path)
    archive.add_argument("--remote", required=True)
    archive.add_argument("--branch", default="snapshots")
    archive.add_argument("--checkout-dir", type=Path, default=Path(".snapshots-staging"))
    archive.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "restore":
        restore_rolling_branch(
            data_dir=args.data_dir,
            remote=args.remote,
            branch=args.branch,
        )
        return 0

    if args.command == "rolling":
        counts = rebuild_rolling_branch(
            bronze_dir=args.bronze_dir,
            staging_dir=args.staging_dir,
            remote=args.remote,
            branch=args.branch,
            window_days=args.window_days,
            today=args.today,
            dry_run=args.dry_run,
            silver_dir=args.silver_dir,
        )
        print(
            f"rolling: retained={counts['retained']} pruned={counts['pruned']} "
            f"undated={counts['undated']} silver={counts.get('silver', 0)}"
        )
        return 0

    if args.command == "archive":
        try:
            result = archive_bronze_by_gameweek(
                bronze_dir=args.bronze_dir,
                checkout_dir=args.checkout_dir,
                remote=args.remote,
                branch=args.branch,
                dry_run=args.dry_run,
            )
        except NoGameweekScheduleError as exc:
            print(f"::error title=Archive failed::{exc}")
            return 1
        if not (result["written"] or result["lost"]):
            print("archive: no gameweek has closed since the last archive; nothing to write")
        else:
            print(f"archive: {result}")
        return 0

    appended = append_permanent_snapshot(
        checkout_dir=args.checkout_dir,
        remote=args.remote,
        branch=args.branch,
        source=args.source,
        gameweek=args.gameweek,
        payload_path=args.payload_path,
        dry_run=args.dry_run,
    )
    print(f"permanent: {'appended' if appended else 'already present, no-op'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
