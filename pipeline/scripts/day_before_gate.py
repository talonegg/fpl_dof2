"""Gate for .github/workflows/day-before.yml. Always exits 0; the decision is in GITHUB_OUTPUT.

    python pipeline/scripts/day_before_gate.py [--manual]

Reads the game's state once, through the source layer (REM-06), and lists recent Ingest (slow)
runs with ``gh`` (read-only GITHUB_TOKEN) for the idempotency check. Any failure to read either
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

FIELDS = "databaseId,displayTitle,status,conclusion,createdAt"


def fetch() -> tuple[dict[str, Any] | None, str | None]:
    try:
        with LiveFeed() as feed:
            return feed.state(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def prior_runs() -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        out = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                "ingest-slow.yml",
                "--limit",
                "50",
                "--json",
                FIELDS,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return list(json.loads(out.stdout)), None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
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
