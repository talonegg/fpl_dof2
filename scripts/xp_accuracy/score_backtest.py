"""Score per-player xP accuracy on the saved backtest and 2026/27 replay predictions.

    python scripts/xp_accuracy/score_backtest.py [--backtest-dir /workspace/fpl_dof2/backtest]

Inputs (local-only, not in git; see research/fpl-xp-accuracy-scoring.md section 1):
- ``xp_L1_baseline.csv`` / ``xp_L1_c3.csv`` / ``xp_L1_c1.csv`` (engine, C3, C1) and
  ``cache_comp_A.parquet`` (A) for 2023/24-2025/26. A_odds has no saved backtest predictions.
- ``r2627/GW{n}/xp_{engine,C3,C1,A}.parquet`` + ``avail.parquet``: the 2026/27 GW1-6 replay.

Writes ``backtest/xp_scores_{season}.csv`` (xp_scores.csv schema), plus
``xp_scores_paired_{season}.csv`` and ``xp_calibration_{season}.csv``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from fpl_dof.prospective.xp_accuracy import (  # noqa: E402
    PAIRED_FIELDS,
    SCORE_FIELDS,
    calibration,
    paired,
    population,
    score_gw,
)

OUT = ROOT / "backtest"


def _slug(season: str) -> str:
    return season.replace("/", "-")


def _write(season: str, rows: list[dict], pops: list, models: list[str], kind: str) -> None:
    s = pd.DataFrame(rows, columns=list(SCORE_FIELDS))
    s.to_csv(OUT / f"xp_scores_{_slug(season)}{kind}.csv", index=False, float_format="%.6f")
    pd.DataFrame(paired(s), columns=list(PAIRED_FIELDS)).to_csv(
        OUT / f"xp_scores_paired_{_slug(season)}{kind}.csv", index=False, float_format="%.6f"
    )
    pd.DataFrame(calibration(pops, models)).to_csv(
        OUT / f"xp_calibration_{_slug(season)}{kind}.csv", index=False, float_format="%.4f"
    )
    print(f"{season}{kind}: {s.gw.nunique()} GWs, {len(s)} rows")


def backtest(bdir: Path) -> None:
    m = {
        "engine": pd.read_csv(bdir / "xp_L1_baseline.csv"),
        "C3": pd.read_csv(bdir / "xp_L1_c3.csv"),
        "C1": pd.read_csv(bdir / "xp_L1_c1.csv"),
    }
    a = pd.read_parquet(bdir / "cache_comp_A.parquet").rename(
        columns={"player_id": "player", "xp_next": "xp"}
    )
    m["A"] = a[["season", "gw", "player", "position", "xp", "actual", "minutes"]]
    act = m["engine"]
    for season in sorted(act["season"].unique()):
        rows, pops = [], []
        for gw in sorted(act.loc[act.season == season, "gw"].unique()):
            xp = {n: d[(d.season == season) & (d.gw == gw)] for n, d in m.items()}
            actual = xp["engine"][["player", "actual", "minutes"]]
            rows += score_gw(season=season, gw=int(gw), xp=xp, actual=actual)
            pops.append((season, int(gw), population(xp, actual)[0]))
        _write(season, rows, pops, list(m), "")


def replay(bdir: Path) -> None:
    season, rows, pops = "2026/27", [], []
    for gdir in sorted((bdir / "r2627").glob("GW*"), key=lambda p: int(p.name[2:])):
        gw = int(gdir.name[2:])
        xp = {}
        for n in ("engine", "C3", "C1", "A"):
            d = pd.read_parquet(gdir / f"xp_{n}.parquet")
            xp[n] = d.rename(columns={"player_id": "player", "xp_next": "xp"})
        actual = xp["C3"][["player", "actual", "minutes"]]
        av = gdir / "avail.parquet"
        if av.exists():
            v = pd.read_parquet(av).rename(columns={"player_id": "player"})
            actual = actual.merge(v[["player", "avail"]], on="player", how="left")
        rows += score_gw(season=season, gw=gw, xp=xp, actual=actual)
        pops.append((season, gw, population(xp, actual)[0]))
    _write(season, rows, pops, ["engine", "C3", "C1", "A"], "_replay")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest-dir", type=Path, default=Path("/workspace/fpl_dof2/backtest"))
    a = ap.parse_args()
    backtest(a.backtest_dir)
    replay(a.backtest_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
