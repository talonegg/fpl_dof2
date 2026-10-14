"""Build web/public/static/xp_accuracy.json (all-player xP MAE per GW) for the Models page.

Inputs are the xp_scores.csv-schema files written by forge/xp-accuracy's
scripts/xp_accuracy/score_backtest.py, copied to scripts/models_history/data/:
``xp_scores_2025-26.csv`` (backtest) and ``xp_scores_2026-27_replay.csv`` (GW1-6 replay).
Prospective 2026/27 GW7+ scores come from CI's xp_scores.csv once it is published; until then the
page shows the replay only. Subset ``all`` (the pre-registered primary population).

    python scripts/models_history/build_xp_accuracy.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from fpl_dof.publish.benchmark import build_xp_accuracy
from fpl_dof.publish.contract import Contract, find_contracts_root

DATA = ROOT / "scripts" / "models_history" / "data"
OUT = ROOT / "web" / "public" / "static" / "xp_accuracy.json"
SOURCES = (
    ("2025/26", "backtest", DATA / "xp_scores_2025-26.csv"),
    ("2026/27", "replay", DATA / "xp_scores_2026-27_replay.csv"),
)


def main() -> int:
    doc = build_xp_accuracy(SOURCES)
    contract = Contract(root=find_contracts_root(ROOT))
    contract.validate("xp_accuracy", doc)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
