"""Score per-player xP accuracy for the 2026/27 GW1-6 replay -> data/xp_scores_2026-27_replay.csv.

Replaces the replay half of forge/xp-accuracy's scripts/xp_accuracy/score_backtest.py for 2026/27:

- engine/C3/C1/A predictions: the replay's ``r2627/GW{n}/xp_<model>.parquet``;
- A_odds: the opening-odds proxy run (replay_2627_aodds.py, scratch ``GW{n}/xp_A_odds.parquet``),
  descriptive only and outside the C1 vs C3 pre-registration;
- actuals: realised minutes/points summed per player over the GW from silver player_gameweek. The
  xp frames' own ``actual``/``minutes`` columns are the zeroed placeholders the walk-forward feeds
  the model, so scoring against them (as the first version did) measured MAE against 0.

    python scripts/models_history/score_replay_2627.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from fpl_dof.prospective.xp_accuracy import SCORE_FIELDS, score_gw  # noqa: E402

REPLAY = Path("/workspace/fpl_dof2/backtest/r2627")
SCRATCH = Path("/workspace/scratch/r2627_aodds")
SILVER = Path("/workspace/fpl_prospective/data/silver/season=2026-27")
OUT = ROOT / "scripts" / "models_history" / "data" / "xp_scores_2026-27_replay.csv"
SEASON = "2026/27"
MODELS = ("engine", "C3", "C1", "A", "A_odds")


def main() -> int:
    pg = pd.read_parquet(SILVER / "player_gameweek.parquet")
    pg = (
        pg[pg.season == SEASON]
        .groupby(["gameweek", "player_code"])[["minutes", "total_points"]]
        .sum()
    )
    rows: list[dict] = []
    for gw in range(1, 7):
        xp = {}
        for m in MODELS:
            src = (SCRATCH if m == "A_odds" else REPLAY) / f"GW{gw}" / f"xp_{m}.parquet"
            xp[m] = pd.read_parquet(src).rename(columns={"player_id": "player", "xp_next": "xp"})
        base = xp["C3"][["player"]].copy()
        act = pg.loc[gw].rename(columns={"total_points": "actual"})
        base["actual"] = base.player.map(act.actual).fillna(0.0)
        base["minutes"] = base.player.map(act.minutes).fillna(0.0)
        av = pd.read_parquet(REPLAY / f"GW{gw}" / "avail.parquet").rename(
            columns={"player_id": "player"}
        )
        base = base.merge(av[["player", "avail"]], on="player", how="left")
        rows += score_gw(season=SEASON, gw=gw, xp=xp, actual=base)
    pd.DataFrame(rows, columns=list(SCORE_FIELDS)).to_csv(OUT, index=False, float_format="%.6f")
    print(f"wrote {OUT} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
