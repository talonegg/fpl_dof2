"""Start pipeline.yml from an ingest, with typed inputs (ORC-02, DL-94 item 4).

    python pipeline/scripts/dispatch_pipeline.py [--daily] [--day-before] [--manifest PATH]

Reads the change manifest the ingest stage just wrote. A change of any kind dispatches a
``change`` run with its kinds; ``--daily`` (the slow ingest) dispatches the daily ``schedule``
refresh when nothing changed; ``--day-before`` dispatches a ``day-before`` run that must publish.
With none of those, nothing is dispatched. The pipeline's guard validates the inputs and applies
the freeze (``fpl_dof.week.schedule.dispatch_decision``); this script only says what happened.
Needs ``gh`` with a token that has ``actions: write``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

MANIFEST = Path("data/runs/changes.json")


def inputs(manifest: dict[str, Any], *, daily: bool, day_before: bool) -> dict[str, str] | None:
    """The `workflow_dispatch` inputs for pipeline.yml, or ``None`` when there is nothing to run."""
    kinds = ",".join(manifest.get("kinds") or [])
    gameweek = "" if manifest.get("gameweek") is None else str(manifest["gameweek"])
    if day_before:
        trigger = "day-before"
    elif kinds:
        trigger = "change"
    elif daily:
        trigger = "schedule"
    else:
        return None
    return {
        "trigger": trigger,
        "kinds": kinds if trigger == "change" else "",
        "gameweek": gameweek,
        "must_publish": str(day_before).lower(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true", help="the slow ingest's daily refresh")
    ap.add_argument("--day-before", action="store_true", help="the day-before refresh")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    a = ap.parse_args(argv)
    manifest = json.loads(a.manifest.read_text(encoding="utf-8"))
    wanted = inputs(manifest, daily=a.daily, day_before=a.day_before)
    if wanted is None:
        print("no material change: no pipeline run")
        return 0
    fields = [arg for name, value in wanted.items() for arg in ("-f", f"{name}={value}")]
    subprocess.run(["gh", "workflow", "run", "pipeline.yml", *fields], check=True, timeout=60)
    print(f"pipeline dispatched: {wanted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
