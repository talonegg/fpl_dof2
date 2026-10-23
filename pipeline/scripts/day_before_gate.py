"""Gate for .github/workflows/day-before.yml. Always exits 0; the decision is in GITHUB_OUTPUT.

    python pipeline/scripts/day_before_gate.py [--manual]

Reads the game's state once, through the source layer (REM-06), and lists recent dispatched
ingest-slow.yml runs, with who started each, through ``gh api`` (read-only GITHUB_TOKEN) for the
idempotency check: ``gh run list`` cannot say who started a run. Any failure to read either
is a logged skip (``::warning::``), never a partial refresh. Logic and tests:
``fpl_dof.week.day_before``.
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

from fpl_dof.sources import LiveFeed
from fpl_dof.week.day_before import gate


def fetch() -> tuple[dict[str, Any] | None, str | None]:
    try:
        with LiveFeed() as feed:
            return feed.state(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


RUNS = (
    "repos/{owner}/{repo}/actions/workflows/ingest-slow.yml/runs"
    "?event=workflow_dispatch&per_page=50"
)


def prior_runs() -> tuple[list[dict[str, Any]] | None, str | None]:
    """The slow ingest's recent dispatched runs, in the shape the gate reads, with their actor."""
    try:
        out = subprocess.run(
            ["gh", "api", RUNS], check=True, capture_output=True, text=True, timeout=60
        )
        return [
            {
                "databaseId": run["id"],
                "event": run["event"],
                "status": run["status"],
                "conclusion": run["conclusion"],
                "createdAt": run["created_at"],
                "actor": (run.get("actor") or {}).get("login"),
            }
            for run in json.loads(out.stdout)["workflow_runs"]
        ], None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual", action="store_true", help="workflow_dispatch: skip the 07:00 check")
    a = ap.parse_args(argv)
    bootstrap, error = fetch()
    runs, runs_error = prior_runs() if error is None else ([], None)
    decision = gate(
        now=dt.datetime.now(dt.UTC),
        bootstrap=bootstrap,
        error=error,
        prior_runs=runs,
        runs_error=runs_error,
        manual=a.manual,
    )
    # Unreadable inputs are worth a visible annotation; an ordinary "not today" is a log line.
    prefix = "::warning title=Day-before refresh skipped::" if error or runs_error else ""
    print(prefix + decision.reason)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with Path(out).open("a", encoding="utf-8") as f:
            f.write(decision.lines())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
