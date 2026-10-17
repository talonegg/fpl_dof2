"""Replay A_odds on 2026/27 GW1-6 with football-data.co.uk OPENING odds (local only, not run in CI).

The GW1-6 replay (backtest/replay_2627.py on forge/team-keys) ran engine/C3/C1/A only; A_odds
duplicated A because no 2026/27 odds were on file. This adds A_odds as an *opening-odds proxy*:

- odds: the dated in-repo copy of mmz4281/2627/E0.csv (``data/fdcouk/E0_2627_<date>.csv``), opening
  1X2 columns B365H/D/A (fallback AvgH/D/A) and opening totals B365>2.5/B365<2.5 (fallback
  Avg>2.5/Avg<2.5). Closing columns (``...C...``, e.g. B365CH) are never read.
- collection time: the frozen ``ds_features`` rule (Fri 18:00 London for Fri-Mon fixtures, Tue
  18:00 for midweek); a fixture is kept only if that is strictly before the FPL deadline.
- rows are laid out exactly as the frozen harness's ``live_frame.live_odds`` builds them, so only
  this GW's odds are injected, as in a live run. The model itself is the frozen A_odds
  (tag frozen-2026-10-13) run by the frozen ``model_runner.py`` in a fresh interpreter.
- inputs (history/folds/availability) are the replay's own per-GW dirs, copied to a scratch dir;
  the decision chain and scoring reuse the frozen ``policy.decide`` and ``scoring.score_pick``.

Descriptive only: outside the C1 vs C3 pre-registration (prospective/PREREG_C1_vs_C3.md).

    python scripts/models_history/replay_2627_aodds.py
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from odds_2627 import CSV as ODDS_CSV  # noqa: E402
from odds_2627 import fixture_codes, load_opening, team_codes  # noqa: E402

FROZEN = Path("/workspace/fpl_dof2_frozen")
PROS = Path("/workspace/fpl_prospective")
REPLAY = Path("/workspace/fpl_dof2/backtest/r2627")
SCRATCH = Path(os.environ.get("AODDS_SCRATCH", "/workspace/scratch/r2627_aodds"))
SILVER = PROS / "data" / "silver" / "season=2026-27"
DATA = ROOT / "scripts" / "models_history" / "data"
SEASON = "2026/27"
LABEL = "opening-odds proxy"
PY = sys.executable


def coll_time(kickoff: pd.Timestamp) -> pd.Timestamp:
    """Frozen ds_features rule: Fri 18:00 London for Fri-Mon fixtures, Tue 18:00 for midweek."""
    date = kickoff.tz_convert("Europe/London").normalize()
    wd = date.weekday()
    back = (wd - 4) % 7 if wd in (4, 5, 6, 0) else (wd - 1) % 7
    return (date - pd.Timedelta(days=back)).replace(hour=18).tz_convert("UTC")


def odds_frame(gw: int, deadline: pd.Timestamp, joined: pd.DataFrame) -> pd.DataFrame:
    sys.path[:0] = [str(FROZEN / "backtest")]
    import odds_team as ot

    rows = []
    for r in joined[joined.gameweek == gw].to_dict("records"):
        x12 = [r["H"], r["D"], r["A"]]
        coll = coll_time(r["kickoff"])
        d = {
            "season": SEASON,
            "gameweek": gw,
            "fixture_id": r["fixture_id"],
            "home": r["home"],
            "away": r["away"],
            "kickoff": r["kickoff"],
            "coll": coll,
            "deadline": deadline,
            "kept": bool(coll < deadline),
            "src12": r["src12"],
            "srcou": r["srcou"],
            "FTHG": np.nan,
            "FTAG": np.nan,
            "HST": np.nan,
            "AST": np.nan,
            "lh": np.nan,
            "la": np.nan,
            "ph": np.nan,
            "pdr": np.nan,
            "pa": np.nan,
            "pov": np.nan,
            "ovr12": np.nan,
            "ovrou": np.nan,
            "devig": None,
        }
        if d["kept"]:
            p, how = ot.devig_1x2(x12)
            d.update(ph=p[0], pdr=p[1], pa=p[2], ovr12=sum(1 / x for x in x12) - 1, devig=how)
            if pd.notna(r["O"]) and pd.notna(r["U"]):
                io_, iu = 1 / r["O"], 1 / r["U"]
                d.update(pov=io_ / (io_ + iu), ovrou=io_ + iu - 1)
            d["lh"], d["la"] = ot.fit_lambdas(d["ph"], d["pdr"], d["pa"], d["pov"], 2.8)
        rows.append(d)
    return pd.DataFrame(rows)


def main() -> int:
    os.chdir(FROZEN)
    sys.path[:0] = [
        str(FROZEN / "pipeline/src"),
        str(FROZEN / "backtest"),
        str(PROS / "prospective"),
    ]
    os.environ["FPL_PROSPECTIVE_DATA"] = str(PROS / "data")
    import backtest as bt
    from models import MODELS as FM
    from policy import decide
    from scoring import score_pick

    from fpl_dof.optimise.squad import optimise_squad

    fx = fixture_codes(
        pd.read_parquet(SILVER / "fixture.parquet"), pd.read_parquet(SILVER / "team.parquet")
    )
    joined = load_opening(
        ODDS_CSV, fx[fx.gameweek <= 6], team_codes(pd.read_parquet(SILVER / "team.parquet"))
    )
    gws = pd.read_parquet(SILVER / "gameweek.parquet").set_index("gameweek")
    pg = pd.read_parquet(SILVER / "player_gameweek.parquet")
    pg = (
        pg[pg.season == SEASON]
        .groupby(["gameweek", "player_code"])[["minutes", "total_points"]]
        .sum()
    )
    cfg = bt.CFG()
    rules, _ = bt.load(str(PROS / "data"), [SEASON])
    old = {(int(r["gw"]), r["model"]): r for r in csv.DictReader((DATA / "replay_2627.csv").open())}
    m, state, rows, info = "A_odds", None, [], {}
    env = {**os.environ, "PYTHONPATH": str(FROZEN / "pipeline/src")}
    runner = str(PROS / "prospective" / "model_runner.py")
    for gw in range(1, 7):
        deadline = pd.Timestamp(gws.loc[gw, "deadline_time"])
        src, d = REPLAY / f"GW{gw}", SCRATCH / f"GW{gw}"
        d.mkdir(parents=True, exist_ok=True)
        for n in ("history", "training", "merged", "avail"):
            shutil.copy2(src / f"{n}.parquet", d / f"{n}.parquet")
        shutil.copy2(src / "meta.json", d / "meta.json")
        odds = odds_frame(gw, deadline, joined)
        odds.to_parquet(d / "odds.parquet")
        subprocess.run([PY, runner, "predict", m, str(d)], env=env, check=True)
        pf = pd.read_parquet(d / f"xp_{m}.parquet")
        info[gw] = dict(
            json.loads((d / f"xp_{m}.info.json").read_text()),
            fixtures=len(odds),
            kept=int(odds.kept.sum()),
            src12=odds.src12.value_counts().to_dict(),
            srcou=odds.srcou.value_counts().to_dict(),
        )
        if state is None:
            opt = cfg.optimiser.model_copy(update=FM[m]["config"]["optimiser_overrides"])
            sq, _ = optimise_squad(pf, rules, opt)
            state = {
                "model": m,
                "players": [
                    {
                        "code": int(p.player_id),
                        "position": str(getattr(p.position, "value", p.position)),
                        "team_code": int(p.team_id),
                        "current_price": float(p.price),
                        "purchase_price": float(p.price),
                    }
                    for p in sq.players
                ],
                "bank": max(0.0, rules.squad.budget - sum(p.price for p in sq.players)),
                "free_transfers": 1,
            }
            fresh = True
        else:
            fresh = False
        pick, state = decide(pf, state, gw, FM[m]["config"], cfg, rules)
        act = pg.loc[gw]  # realised outcomes (the xp frame's own actual/minutes are zeroed)
        mins, pts = act.minutes.to_dict(), act.total_points.to_dict()
        s = score_pick(pick, mins, pts)
        ref = old[(gw, "A")]
        rows.append(
            {
                "gw": gw,
                "model": m,
                "xi_points": s["points"],
                "points_before_hits": s["points_before_hits"],
                "hit_points": pick["hit_points"],
                "n_transfers": pick["n_transfers"],
                "ft_before": pick["free_transfers_before"],
                "fresh_squad": fresh,
                "captain": pick["captain_name"],
                "captain_pts": pts.get(pick["captain"], 0.0),
                "captain_mins": mins.get(pick["captain"], 0.0),
                "vice": pick["vice_name"],
                "vice_used": s["vice_used"],
                "armband_pts": s["armband_pts"],
                "n_autosubs": s["n_autosubs"],
                "xi_raw_no_subs": s["xi_raw_no_subs"],
                "xp_xi": round(pick["xp_xi"], 2),
                "transfers": "; ".join(
                    f"{t['out_name']}->{t['in_name']}" for t in pick["transfers"]
                ),
                "snapshot": ref["snapshot"],
                "snap_hours_before": ref["snap_hours_before"],
                "notes": "; ".join([*pick["notes"], LABEL]),
            }
        )
        print(rows[-1], info[gw], flush=True)
    (SCRATCH / "rows.json").write_text(json.dumps(rows, default=str))
    (SCRATCH / "odds_info.json").write_text(json.dumps(info, default=str, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
