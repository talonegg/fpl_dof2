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
    python pipeline/scripts/retention.py permanent <bronze_dir> --remote <url> --gameweek 3

Both subcommands push to a real remote. `--dry-run` runs the same planning and staging logic
without pushing, for verification against a scratch local remote.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpl_dof.retention import plan_retention


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


def rebuild_rolling_branch(
    *,
    bronze_dir: Path,
    staging_dir: Path,
    remote: str,
    branch: str = "data",
    window_days: int,
    today: dt.date | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Rebuild `branch` from scratch as an orphan, containing only the retained window, and
    force-push it. Returns counts for reporting — the caller decides what to log."""
    paths = _bronze_paths(bronze_dir)
    # A retention window applies to dated snapshots; sidecars share their snapshot's date
    # directory, so partitioning the full path list (snapshots and sidecars together) keeps a
    # snapshot and its lineage record moving together rather than pruning one without the other.
    plan = plan_retention(paths, today=today or dt.date.today(), window_days=window_days)
    retained = plan.retain + plan.undated

    if staging_dir.exists():
        _rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    for relative in retained:
        source = bronze_dir / relative
        destination = staging_dir / "bronze" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    counts = {"retained": len(retained), "pruned": len(plan.prune), "undated": len(plan.undated)}
    if dry_run:
        return counts

    _run_git(["init", "--quiet"], cwd=staging_dir)
    _run_git(["checkout", "--orphan", branch], cwd=staging_dir)
    _run_git(["add", "-A"], cwd=staging_dir)
    _run_git(
        [
            "-c",
            "user.email=fpl-dof-ci@users.noreply.github.com",
            "-c",
            "user.name=fpl-dof CI",
            "commit",
            "--quiet",
            "-m",
            f"data: rolling {window_days}-day bronze window as of {today or dt.date.today()}",
        ],
        cwd=staging_dir,
    )
    _run_git(["push", "--force", remote, f"{branch}:{branch}"], cwd=staging_dir)
    return counts


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

    if checkout_dir.exists():
        _rmtree(checkout_dir)
    checkout_dir.mkdir(parents=True)
    _run_git(["init", "--quiet"], cwd=checkout_dir)

    branch_exists = True
    try:
        _run_git(["fetch", remote, f"{branch}:refs/fpl-dof/snapshots-staging"], cwd=checkout_dir)
        _run_git(["checkout", "refs/fpl-dof/snapshots-staging"], cwd=checkout_dir)
    except GitError:
        branch_exists = False
        _run_git(["checkout", "--orphan", branch], cwd=checkout_dir)

    destination = checkout_dir / destination_relative
    if destination.exists() and destination.read_bytes() == payload_path.read_bytes():
        return False  # already recorded, identical bytes — nothing to append

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(payload_path, destination)

    if dry_run:
        return True

    _run_git(["add", "-A"], cwd=checkout_dir)
    try:
        _run_git(
            [
                "-c",
                "user.email=fpl-dof-ci@users.noreply.github.com",
                "-c",
                "user.name=fpl-dof CI",
                "commit",
                "--quiet",
                "-m",
                f"snapshots: {source} gw{gameweek}",
            ],
            cwd=checkout_dir,
        )
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

    push_ref = "HEAD:refs/heads/" + branch if not branch_exists else f"HEAD:{branch}"
    _run_git(["push", remote, push_ref], cwd=checkout_dir)
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rolling = sub.add_parser("rolling", help="Rebuild and force-push the rolling `data` branch")
    rolling.add_argument("bronze_dir", type=Path)
    rolling.add_argument("--remote", required=True)
    rolling.add_argument("--branch", default="data")
    rolling.add_argument("--window-days", type=int, default=30)
    rolling.add_argument("--staging-dir", type=Path, default=Path(".retention-staging"))
    rolling.add_argument("--dry-run", action="store_true")
    rolling.add_argument(
        "--today",
        type=dt.date.fromisoformat,
        default=None,
        help="Override 'today' for the retention window (testing only; production uses the "
        "real date).",
    )

    permanent = sub.add_parser("permanent", help="Append one snapshot to `snapshots`")
    permanent.add_argument("payload_path", type=Path)
    permanent.add_argument("--remote", required=True)
    permanent.add_argument("--branch", default="snapshots")
    permanent.add_argument("--source", required=True)
    permanent.add_argument("--gameweek", type=int, required=True)
    permanent.add_argument("--checkout-dir", type=Path, default=Path(".snapshots-staging"))
    permanent.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "rolling":
        counts = rebuild_rolling_branch(
            bronze_dir=args.bronze_dir,
            staging_dir=args.staging_dir,
            remote=args.remote,
            branch=args.branch,
            window_days=args.window_days,
            today=args.today,
            dry_run=args.dry_run,
        )
        print(
            f"rolling: retained={counts['retained']} pruned={counts['pruned']} "
            f"undated={counts['undated']}"
        )
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
