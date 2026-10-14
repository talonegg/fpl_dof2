"""Gate for .github/workflows/day-before.yml. Always exits 0; the decision is in GITHUB_OUTPUT.

    python pipeline/scripts/day_before_gate.py [--cron "0 20 * * *"]
    python pipeline/scripts/day_before_gate.py --veto-plan /workspace/fpl_prospective/ci/plan.json

Reads bootstrap-static once. Any failure to read it is a logged skip (``::warning::``), never a
partial refresh. Logic and tests: ``fpl_dof.week.day_before``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpl_dof.week.day_before import gate, veto_plan

URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
UA = "fpl-dof-ci/1.0 (+https://github.com/talonegg/fpl_dof2; low-rate)"


def fetch() -> tuple[dict[str, Any] | None, str | None]:
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cron", default="", help="github.event.schedule; empty for manual dispatch")
    ap.add_argument("--veto-plan", type=Path, help="force decide=false in a prospective plan.json")
    a = ap.parse_args(argv)
    if a.veto_plan is not None:
        plan = json.loads(a.veto_plan.read_text(encoding="utf-8")) if a.veto_plan.exists() else {}
        vetoed = veto_plan(plan)
        a.veto_plan.parent.mkdir(parents=True, exist_ok=True)
        a.veto_plan.write_text(json.dumps(vetoed, indent=2, sort_keys=True), encoding="utf-8")
        print(f"decide=false ({vetoed['decide_reason']})")
        return 0
    cron_hour = int(a.cron.split()[1]) if a.cron.strip() else None
    bootstrap, error = fetch()
    decision = gate(
        now=dt.datetime.now(dt.UTC), bootstrap=bootstrap, error=error, cron_hour=cron_hour
    )
    # An unreadable API is worth a visible annotation; an ordinary "not today" is just a log line.
    prefix = "::warning title=Day-before refresh skipped::" if error else ""
    print(prefix + decision.reason)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with Path(out).open("a", encoding="utf-8") as f:
            f.write(decision.lines())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
