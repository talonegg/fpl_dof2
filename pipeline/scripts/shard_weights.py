"""Rewrite the test shards' weights from a full run's JUnit report (ORC-09, DL-103).

    cd pipeline
    python -m pytest -q -n auto --junitxml=../junit.xml
    python scripts/shard_weights.py ../junit.xml

Each test module's seconds, setup and teardown included, summed over its tests, written to
``tests/shard_weights.json``; ``tests/conftest.py`` balances CI's shards on them. Rewrite them when
the shards drift apart, not on every run: the plan is meant to be stable from commit to commit.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

WEIGHTS = Path(__file__).resolve().parent.parent / "tests" / "shard_weights.json"


def module_seconds(report: Path) -> dict[str, float]:
    """Seconds per test module, from a pytest JUnit report's ``classname``s (``tests.test_x``)."""
    seconds: dict[str, float] = defaultdict(float)
    for case in ET.parse(report).iter("testcase"):
        module = next(
            (part for part in case.get("classname", "").split(".") if part.startswith("test_")),
            None,
        )
        if module is not None:
            seconds[f"{module}.py"] += float(case.get("time") or 0.0)
    return {module: round(total, 1) for module, total in sorted(seconds.items())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path, help="a full run's pytest --junitxml report")
    args = ap.parse_args(argv)
    weights = module_seconds(args.report)
    if not weights:
        print(f"::error::{args.report} names no test module", file=sys.stderr)
        return 1
    WEIGHTS.write_text(json.dumps(weights, indent=2) + "\n", encoding="utf-8")
    print(f"{len(weights)} modules, {sum(weights.values()):.0f} s, written to {WEIGHTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
