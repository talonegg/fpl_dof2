"""Build web/public/static/models_history_2627_replay.json from the GW1-6 replay CSV.

The 2026/27 GW1-6 *replay*: the frozen models (tag frozen-2026-10-13) run after the fact on
gameweeks already played (forge/team-keys 4102834, backtest/replay_2627.csv, copied to
scripts/models_history/data/). It is retrospective, not advice recorded before a deadline, and the
web page labels it so. GW7+ prospective results are NOT in this file: the page reads them from the
published models.json (the frozen harness's scores.csv), so this never needs updating in-season.

    python scripts/models_history/build_replay_2627.py [csv] [out]
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "scripts" / "models_history" / "data" / "replay_2627.csv"
OUT = ROOT / "web" / "public" / "static" / "models_history_2627_replay.json"

#: Harness model key -> web model id (same mapping as publish/models_compare.py).
IDS = {
    "C3": "champion",
    "C1": "challenger",
    "engine": "engine",
    "A": "a",
    "A_odds": "a_odds",
}

CAVEAT = (
    "Replay, not live: the frozen models (tag frozen-2026-10-13) were run after these gameweeks "
    "had been played, seeing only data from before each deadline. These picks were never recorded "
    "before a deadline. GW1-6 A_odds replay uses opening-odds proxy (football-data.co.uk opening "
    "B365 1X2 and totals); descriptive only, outside the C1 vs C3 pre-registration."
)


def build(rows: list[dict[str, str]]) -> dict[str, Any]:
    gws: dict[int, dict[str, dict[str, Any]]] = {}
    seen: set[str] = set()
    for r in rows:
        mid = IDS[r["model"]]
        seen.add(mid)
        gws.setdefault(int(r["gw"]), {})[mid] = {
            "points": float(r["xi_points"]),
            "hit_points": float(r["hit_points"]),
            "captain": r["captain"],
        }
    return {
        "contract_version": 1,
        "season": "2026/27",
        "kind": "replay",
        "caveat": CAVEAT,
        "frozen_tag": "frozen-2026-10-13 (79e080c)",
        "models": [m for m in IDS.values() if m in seen],
        "missing_models": {m: "not in the GW1-6 replay run" for m in IDS.values() if m not in seen},
        "as_of_gameweek": max(gws) if gws else 0,
        "gameweeks": [{"gameweek": g, "models": gws[g]} for g in sorted(gws)],
    }


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else CSV
    out = Path(argv[2]) if len(argv) > 2 else OUT
    with src.open(encoding="utf-8") as f:
        doc = build(list(csv.DictReader(f)))
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} (GW1-{doc['as_of_gameweek']}, {len(doc['models'])} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
