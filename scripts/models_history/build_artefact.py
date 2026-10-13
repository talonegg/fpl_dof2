import json, sys
sys.path.insert(0, "/workspace/fpl_dof2_history/pipeline/src")
import pandas as pd
from fpl_dof.publish.models_history import build_models_history
from fpl_dof.publish.contract import Contract, find_contracts_root
h = pd.read_parquet("/workspace/fpl_data/silver/season=2026-27/player_gameweek.parquet", columns=["season", "player_code", "web_name"])
short = h[h.season == "2026/27"].drop_duplicates("player_code").set_index("player_code").web_name.to_dict()
full = h[h.season == "2025/26"].drop_duplicates("player_code").set_index("player_code").web_name.to_dict()
name = lambda c: short.get(c) or full.get(c) or f"#{c}"
cache = {}
def src_names(model_cache):
    d = pd.read_parquet(f"/workspace/fpl_dof2/backtest/cache_{model_cache}.parquet", columns=["player_id"])
    return d
M = {"champion": "C3", "challenger": "C1", "engine": "engine", "a": "A", "a_odds": "A_odds"}
rows = {}
for wid, key in M.items():
    d = pd.read_json(f"/workspace/history_run/out/{key}.json")
    rows[wid] = [dict(gw=int(r.gw), points=float(r.xi_points_as), points_before_hits=float(r.xi_points_as - r.hit), hit_points=float(r.hit),
                      n_transfers=int(r.transfers), transfers=[f"{name(a)} → {name(b)}" for a, b in r.moves], captain=name(int(r.captain_id)), vice_captain=name(int(r.vice_id)),
                      captain_points=float(r.captain_pts), vice_used=bool(r.vice_used), n_autosubs=int(r.n_autosubs)) for r in d.itertuples()]
    # transfer names: moves list was built from the junk cache web_name; rebuild from ids is not stored, so omit names
prov = {
    "frozen_tag": "frozen-2026-10-13 (79e080c)",
    "simulator": "forge/autosubs 3de5329 backtest.simulate (autosubs.py identical to the frozen tag)",
    "forecasts": "walk-forward caches: engine=baseline, C3=minutes_v2, C1=vec_xg2, A=comp_A (forge/round2), A+odds=comp_ot (round 3, e0390a4)",
    "captain": "engine: engine captain/vice; others: price/position (B0) captain, vice = 2nd by B0",
    "settings": "deadline availability from fplcache (strictly before deadline); FPL auto-subs + vice fallback; 1 FT rolling to 5, -4 per extra; no chips; fresh squad at GW1",
    "reproduces": "engine 47.47, C3 47.84, C1 50.76 pts/GW = RESULTS_autosubs.md L1 auto-subs 2025/26",
}
p = build_models_history(season="2025/26", rows=rows, unavailable={}, provenance=prov, contract_version=1)
Contract(root=find_contracts_root(__import__("pathlib").Path("/workspace/fpl_dof2_history"))).validate("models_history", p)
out = "/workspace/fpl_dof2_history/web/public/static/models_history_2526.json"
import os; os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(p, open(out, "w"), indent=1, ensure_ascii=False)
for s in p["summary"]:
    print(s["model"], s["total"], s["mean_per_gameweek"], s["gameweeks_won"], s["final_rank"], s["hit_points"], s["delta_vs_champion"])
