"""2025/26 realistic walk-forward replay of the five frozen models (local only).
Simulator: forge/autosubs 3de5329 backtest.simulate (auto-subs + vice, deadline availability, hits),
autosubs.py identical to frozen-2026-10-13. Forecasts: the walk-forward caches each model was evaluated on."""
import json, os, sys
from pathlib import Path
model, cache, policy = sys.argv[1:4]
sys.path.insert(0, "/workspace/fpl_dof2_subs/backtest")
os.chdir("/workspace/fpl_dof2_subs")
import pandas as pd
import backtest as bt
import availability as av
cap_log = []
orig = bt.autosub_score
def spy(o, xi, cap, vice, lookup, m):
    r = orig(o, xi, cap, vice, lookup, m)
    nm = lambda i: str(lookup.loc[i, "web_name"]) if i in lookup.index else str(i)
    cap_log.append(dict(captain=nm(cap), captain_id=int(cap), vice=nm(vice), vice_id=int(vice),
                        vice_pts=float(lookup["actual"].get(vice, 0)),
                        moves=[[int(t.player_out_id), int(t.player_in_id)] for t in o.moves]))
    return r
bt.autosub_score = spy
allpf = pd.read_parquet(f"/workspace/fpl_dof2/backtest/cache_{cache}.parquet")
allpf = allpf[allpf.season == "2025/26"]
allpf = av.apply(allpf, av.load())
out = Path("/workspace/history_run/out"); out.mkdir(exist_ok=True)
dec = bt.simulate(allpf, policy, model, out)
assert len(dec) == len(cap_log), (len(dec), len(cap_log))
dec = pd.concat([dec.reset_index(drop=True), pd.DataFrame(cap_log)], axis=1)
dec.to_json(out / f"{model}.json", orient="records", indent=1)
print(model, len(dec), dec.xi_points_as.sum(), dec.xi_points_as.mean())
