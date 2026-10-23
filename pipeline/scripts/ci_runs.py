"""Ask GitHub about this repository's workflow runs.

    python pipeline/scripts/ci_runs.py today-done --workflow ingest-slow.yml [--job ingest]
    python pipeline/scripts/ci_runs.py budget ci_workflow_budget_seconds [--since <ISO time>]

``today-done``, for fallback cron firings, prints ``done=true|false`` to GITHUB_OUTPUT. Uses ``gh``
with the job's read-only GITHUB_TOKEN. If GitHub cannot be asked, ``done=false``: a fallback firing
then does the work (a duplicate refresh is harmless; a missed one is not). ``--job`` additionally
requires that job to have succeeded (a guard-only Pipeline run also concludes "success" without
doing anything).

``budget`` fails when a wall clock exceeds its budget in ``schedule`` config (ORC-09): from
``--since`` to now, or without it from this run's start to its last finished job.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpl_dof.config import load_config
from fpl_dof.week.ci_runs import start_of_utc_day, succeeded_since

FIELDS = "databaseId,status,conclusion,createdAt,event"


def gh_json(*args: str) -> Any:
    out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout)


def list_runs(workflow: str, limit: int = 30) -> list[dict[str, Any]]:
    return list(
        gh_json("run", "list", "--workflow", workflow, "--limit", str(limit), "--json", FIELDS)
    )


def job_succeeded(run_id: int, job: str) -> bool:
    jobs = gh_json("run", "view", str(run_id), "--json", "jobs")["jobs"]
    return any(j.get("name") == job and j.get("conclusion") == "success" for j in jobs)


def today_done(workflow: str, job: str | None, now: dt.datetime, self_id: int | None) -> bool:
    runs = list_runs(workflow)
    since = start_of_utc_day(now)
    while True:
        hit = succeeded_since(runs, since, exclude_id=self_id)
        if hit is None:
            return False
        if job is None or job_succeeded(int(hit["databaseId"]), job):
            print(f"already done today: run {hit['databaseId']}")
            return True
        runs = [r for r in runs if r["databaseId"] != hit["databaseId"]]


def _at(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def run_seconds(run: dict[str, Any], jobs: list[dict[str, Any]]) -> float:
    """This run's wall clock so far: its start to the last job that has finished."""
    finished = [_at(j["completed_at"]) for j in jobs if j.get("completed_at")]
    return (max(finished) - _at(run["run_started_at"])).total_seconds()


def budget(name: str, since: str | None) -> int:
    budget_seconds = int(getattr(load_config()[0].schedule, name))
    if since is not None:
        seconds = (dt.datetime.now(dt.UTC) - _at(since)).total_seconds()
    else:
        path = f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        jobs = gh_json("api", f"{path}/jobs")["jobs"]
        seconds = run_seconds(gh_json("api", path), jobs)
    print(f"{name}: {seconds:.0f}s of {budget_seconds}s")
    if seconds > budget_seconds:
        print(f"::error title=Over budget::{name}: took {seconds:.0f}s, budget {budget_seconds}s")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("today-done")
    t.add_argument("--workflow", required=True)
    t.add_argument("--job")
    b = sub.add_parser("budget")
    b.add_argument("name", help="a *_budget_seconds field of schedule config")
    b.add_argument("--since")
    a = ap.parse_args(argv)
    if a.cmd == "budget":
        return budget(a.name, a.since)
    self_id = int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None
    try:
        done = today_done(a.workflow, a.job, dt.datetime.now(dt.UTC), self_id)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        print(f"::warning::could not list {a.workflow} runs ({exc}); treating today as not done")
        done = False
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with Path(out).open("a", encoding="utf-8") as f:
            f.write(f"done={str(done).lower()}\n")
    print(f"done={str(done).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
