"""Fail-closed check of a downloaded web contract before a day-before deploy.

    python pipeline/scripts/contract_fresh.py web/public/data/v1 --max-age-hours 6

Exit 1 (with ``::error::``) if the directory is empty, ``meta.json`` is missing or unreadable, or
its ``generated_at`` is older than the limit — so deploy-pages never runs and the previous site
stays live.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


def check(root: Path, max_age: dt.timedelta, now: dt.datetime) -> str | None:
    """None if fresh, else the reason it is not."""
    if not root.is_dir() or not any(root.iterdir()):
        return f"{root} is empty"
    meta = root / "meta.json"
    try:
        generated = dt.datetime.fromisoformat(
            str(json.loads(meta.read_text(encoding="utf-8"))["generated_at"]).replace("Z", "+00:00")
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f"{meta} unreadable or without generated_at ({exc!r})"
    if generated.tzinfo is None:
        return f"generated_at {generated} has no timezone"
    age = now - generated
    if age > max_age:
        return f"contract is stale: generated {generated.isoformat()}, {age} old (limit {max_age})"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--max-age-hours", type=float, default=6.0)
    a = ap.parse_args(argv)
    problem = check(a.root, dt.timedelta(hours=a.max_age_hours), dt.datetime.now(dt.UTC))
    if problem:
        print(f"::error title=Day-before deploy skipped::{problem}; the previous site stays live")
        return 1
    print("contract is fresh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
