#!/usr/bin/env python3
"""Pre-deadline decision for the next GW by every frozen model.

    decide.py [--force-window] [--dry-run] [--gw N]

Refuses unless: verify passes, the next deadline is in the future, and decisions/GW{n}.json does not
exist. Writes decisions/GW{n}.json (create-only) and advances state/<model>.json. --dry-run does
everything except writing decision/state files (outputs go to cache/dryrun_GW{n}/)."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "/workspace/fpl_dof2_frozen/pipeline/src")
sys.path.insert(0, "/workspace/fpl_dof2_frozen/backtest")
sys.path.insert(0, "/workspace/fpl_prospective/prospective")
import pandas as pd
from common import (DECISIONS, PY, RAW, ROOT, SEASON, STATE, canon, fpl, get, next_event, now_utc, parse_ts,
                    sha256_bytes, team_id, write_json_new, POS, MANIFEST)
from models import MODELS
import live_frame as lf

ENV = {**os.environ, "PYTHONPATH": "/workspace/fpl_dof2_frozen/pipeline/src"}
ODDS_URL = "https://www.football-data.co.uk/fixtures.csv"


def run(*args):
    r = subprocess.run([PY, str(ROOT / "prospective" / "model_runner.py"), *args], env=ENV, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"model_runner {args[:2]} failed:\n{r.stderr[-3000:]}")
    return r.stdout.strip()


def real_squad_state(tid, bootstrap, cur_event):
    """Katryn's actual squad as of the latest picks, as the common starting state for every model."""
    picks = fpl(f"entry/{tid}/event/{cur_event}/picks/")
    hist = fpl(f"entry/{tid}/history/")
    el = {e["id"]: e for e in bootstrap["elements"]}
    code = {t["id"]: t["code"] for t in bootstrap["teams"]}
    chips = {c["event"]: c["name"] for c in hist.get("chips", [])}
    ft = 1
    for h in hist["current"]:
        if h["event"] == 1:
            ft = 1; continue
        chip = chips.get(h["event"])
        rem = ft if chip in ("wildcard", "freehit") else ft - h["event_transfers"]
        ft = max(1, min(5, rem + 1))
    players = [{"code": el[p["element"]]["code"], "element": p["element"], "position": POS[el[p["element"]]["element_type"]],
                "team_code": code[el[p["element"]]["team"]], "current_price": el[p["element"]]["now_cost"] / 10.0,
                "purchase_price": el[p["element"]]["now_cost"] / 10.0} for p in picks["picks"]]
    return dict(players=players, bank=picks["entry_history"]["bank"] / 10.0, free_transfers=ft,
                source=f"entry {tid} picks GW{cur_event} (purchase price approximated by current price; FT derived from history)")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--gw", type=int); ap.add_argument("--reuse-folds", action="store_true")
    a = ap.parse_args()
    t0 = now_utc()
    bs_bytes = get("https://fantasy.premierleague.com/api/bootstrap-static/", raw=True)
    bootstrap = json.loads(bs_bytes)
    ev = next_event(bootstrap)
    if ev is None:
        print("decide: no next GW (season over?)"); return 0
    gw = a.gw or ev["id"]
    deadline = pd.Timestamp(parse_ts(ev["deadline_time"]))
    out = DECISIONS / f"GW{gw}.json"
    if out.exists() and not a.dry_run:
        print(f"decide: {out.name} already exists, not overwriting"); return 0
    if not (pd.Timestamp(t0) < deadline):
        print(f"decide: GW{gw} deadline {deadline} has passed; refusing"); return 3
    fx_bytes = get("https://fantasy.premierleague.com/api/fixtures/", raw=True)
    fixtures = json.loads(fx_bytes)
    odds_fetched = pd.Timestamp(now_utc())
    try:
        odds_bytes = get(ODDS_URL, raw=True)
    except Exception as e:
        odds_bytes = b""; print(f"decide: odds fetch failed ({e}); odds layer falls back")
    work = (ROOT / "cache" / (f"dryrun_GW{gw}" if a.dry_run else f"GW{gw}_{t0.strftime('%Y%m%dT%H%M%SZ')}"))
    work.mkdir(parents=True, exist_ok=True)
    raw = RAW / f"GW{gw}_{t0.strftime('%Y%m%dT%H%M%SZ')}"; raw.mkdir(parents=True, exist_ok=True)
    (raw / "bootstrap-static.json").write_bytes(bs_bytes); (raw / "fixtures.json").write_bytes(fx_bytes)
    (raw / "fdcouk_fixtures.csv").write_bytes(odds_bytes)
    h = lf.history(gw, deadline, bootstrap, fixtures)
    h.to_parquet(work / "history.parquet")
    lf.availability(bootstrap).to_parquet(work / "avail.parquet")
    odds = lf.live_odds(odds_bytes, odds_fetched, gw, deadline, bootstrap, fixtures)
    odds.to_parquet(work / "odds.parquet")
    (work / "meta.json").write_text(json.dumps({"gw": gw, "deadline": str(deadline), "season": SEASON}))
    from common import DATA_DIR as _DD
    silver = _DD / "silver" / "season=2026-27" / "player_gameweek.parquet"
    inputs = {"bootstrap_static": sha256_bytes(bs_bytes), "fixtures": sha256_bytes(fx_bytes),
              "fdcouk_fixtures_csv": sha256_bytes(odds_bytes), "silver_player_gameweek": sha256_bytes(silver.read_bytes()),
              "history_frame": sha256_bytes(pd.util.hash_pandas_object(h, index=False).values.tobytes())}
    if not (a.dry_run and a.reuse_folds and (work / "training.parquet").exists()):
        print(run("folds", str(work)))
    tid = team_id()
    cur = next((e["id"] for e in bootstrap["events"] if e["is_current"]), gw - 1)
    real = real_squad_state(tid, bootstrap, cur)
    inputs["real_squad"] = sha256_bytes(canon(real))
    os.chdir("/workspace/fpl_dof2_frozen")
    from backtest import CFG
    import backtest as bt
    from policy import decide as pdecide
    from common import DATA_DIR
    cfg = CFG(); rules, _ = bt.load(str(DATA_DIR), ["2026/27"])
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
    elif a.dry_run:
        manifest = {"code_commit": "UNFROZEN", "models": {k: {"config_sha256": "", "source_sha256": ""} for k in MODELS}}
    else:
        raise SystemExit("no manifest.json: run freeze.py first")
    picks, states = {}, {}
    for name, m in MODELS.items():
        print(run("predict", name, str(work)))
        pf = pd.read_parquet(work / f"xp_{name}.parquet")
        sp = STATE / f"{name}.json"
        st = json.loads(sp.read_text()) if sp.exists() else dict(model=name, next_gw=gw, **{k: real[k] for k in ("players", "bank", "free_transfers")},
                                                                  log=[], started_from=real["source"])
        while st["next_gw"] < gw:  # a skipped GW: roll the transfer (no moves made)
            st["free_transfers"] = min(5, st["free_transfers"] + 1); st["next_gw"] += 1
        if st["next_gw"] > gw:
            raise RuntimeError(f"{name}: state already at GW{st['next_gw']}")
        pick, ns = pdecide(pf, json.loads(json.dumps(st)), gw, m["config"], cfg, rules)
        pick["info"] = json.loads((work / f"xp_{name}.info.json").read_text())
        pick["config_sha256"] = manifest["models"][name]["config_sha256"]
        pick["source_sha256"] = manifest["models"][name]["source_sha256"]
        picks[name], states[name] = pick, ns
    # xP accuracy (harness-only fix, 2026-10-14): hash every model's full-pool xP file and the
    # deadline availability into the decision, and keep a copy under data/gold/xp/GW{n}/ so the
    # files survive cache cleaning and score_xp.py can verify them. No model input or pick changes.
    xp_files = {name: work / f"xp_{name}.parquet" for name in picks}
    xp_files["avail"] = work / "avail.parquet"
    xp_sha = {k: sha256_bytes(p.read_bytes()) for k, p in xp_files.items()}
    gold = DATA_DIR / "gold" / "xp" / f"GW{gw}"
    ts = now_utc()
    assert pd.Timestamp(ts) < deadline, f"decision finished at {ts}, after the deadline {deadline}"
    el = {e["code"]: e["id"] for e in bootstrap["elements"]}
    doc = dict(gw=gw, season=SEASON, deadline=str(deadline), decided_at=ts.isoformat(), started_at=t0.isoformat(),
               before_deadline=True, team_id=tid, code_commit=manifest["code_commit"], inputs_sha256=inputs,
               inputs_sha256_combined=sha256_bytes(canon(inputs)), raw_inputs_dir=str(raw),
               odds={"fixtures_in_gw": sum(1 for f in fixtures if f["event"] == gw), "fixtures_with_odds": int(len(odds)),
                     "kept": int(odds.kept.sum()) if len(odds) else 0, "fetched_at": str(odds_fetched)},
               real_squad_start=real, code_to_element=el, models=picks,
               xp_sha256=xp_sha, xp_gold_dir=f"data/gold/xp/GW{gw}")
    if a.dry_run:
        (work / "decision_preview.json").write_text(json.dumps(doc, indent=2, default=str))
        print(f"DRY RUN GW{gw}: preview at {work/'decision_preview.json'} (no decision/state written)")
    else:
        gold.mkdir(parents=True, exist_ok=True)
        for p in xp_files.values():
            shutil.copy2(p, gold / p.name)
        write_json_new(out, doc)
        for name, ns in states.items():
            (STATE / f"{name}.json").write_text(json.dumps(ns, indent=2))
        print(f"decide: wrote {out}")
    for name, p in picks.items():
        tr = ", ".join(f"{t['out_name']}->{t['in_name']}" for t in p["transfers"]) or "roll"
        print(f"  {name:7s} {tr} | hit {p['hit_points']} | C {p['captain_name']} V {p['vice_name']} | xP {p['xp_xi']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
