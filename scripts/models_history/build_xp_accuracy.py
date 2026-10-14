"""Build web/public/static/xp_accuracy.json (all-player xP MAE per GW) for the Models page.

Inputs are the xp_scores.csv-schema files written by forge/xp-accuracy's
scripts/xp_accuracy/score_backtest.py, copied to scripts/models_history/data/:
``xp_scores_2025-26.csv`` (backtest) and ``xp_scores_2026-27_replay.csv`` (GW1-6 replay).
Prospective 2026/27 GW7+ scores come from CI's xp_scores.csv once it is published; until then the
page shows the replay only. Subset ``all`` (the pre-registered primary population).

    python scripts/models_history/build_xp_accuracy.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "scripts" / "models_history" / "data"
OUT = ROOT / "web" / "public" / "static" / "xp_accuracy.json"
IDS = {"C3": "champion", "C1": "challenger", "engine": "engine", "A": "a", "A_odds": "a_odds"}
SOURCES = (("2025/26", "backtest", "xp_scores_2025-26.csv"), ("2026/27", "replay", "xp_scores_2026-27_replay.csv"))


def season(name: str, kind: str, path: Path) -> dict:
    gws: dict[int, dict[str, float]] = {}
    tot: dict[str, list[float]] = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["subset"] != "all" or not r["mae"]:
                continue
            m, n, mae = IDS[r["model"]], int(r["n_rows"]), float(r["mae"])
            gws.setdefault(int(r["gw"]), {})[m] = round(mae, 4)
            t = tot.setdefault(m, [0.0, 0.0])
            t[0] += mae * n
            t[1] += n
    return {
        "season": name,
        "kind": kind,
        "gameweeks": [{"gameweek": g, "phase": kind, "mae": gws[g]} for g in sorted(gws)],
        "pooled_mae": {m: round(s / n, 4) for m, (s, n) in tot.items() if n},
        "missing_models": {m: "no saved predictions" for m in IDS.values() if m not in tot},
    }


def main() -> int:
    doc = {
        "contract_version": 1,
        "metric": "all-player MAE of next-GW xP vs actual FPL points (lower is better)",
        "seasons": [season(n, k, DATA / f) for n, k, f in SOURCES if (DATA / f).exists()],
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
