"""Build the as-of-now inputs for one upcoming GW: history up to the last finished GW, placeholder
(outcome-free) rows for the upcoming GW's fixtures, current availability, and live pre-closing odds."""
from __future__ import annotations
import io
import numpy as np
import pandas as pd
from common import DATA_DIR, POS, SEASON

OUTCOME_ZERO = ["minutes", "starts", "goals_scored", "assists", "clean_sheets", "goals_conceded", "own_goals",
                "penalties_saved", "penalties_missed", "yellow_cards", "red_cards", "saves", "bonus", "bps",
                "defensive_contribution", "tackles", "recoveries", "clearances_blocks_interceptions",
                "total_points", "expected_goals", "expected_assists", "expected_goals_conceded"]


def last_finished(bootstrap) -> int:
    done = [e["id"] for e in bootstrap["events"] if e["finished"] and e["data_checked"]]
    return max(done) if done else 0


def history(gw: int, deadline: pd.Timestamp, bootstrap, fixtures) -> pd.DataFrame:
    h = pd.read_parquet(DATA_DIR / "silver" / "season=2026-27" / "player_gameweek.parquet")
    h["kickoff_time"] = pd.to_datetime(h["kickoff_time"], utc=True)
    lf = last_finished(bootstrap)
    cur = h.season == SEASON
    h = h[(~cur) | ((h.gameweek <= lf) & (h.kickoff_time < deadline))].copy()
    assert (h.kickoff_time < deadline).all()
    code = {t["id"]: t["code"] for t in bootstrap["teams"]}
    # silver stores the CURRENT season with season-local team ids and archive seasons with stable club
    # codes (D-26). Recode 2026/27 to club codes so one id space spans every season.
    cur = h.season == SEASON
    assert h.loc[cur, "team_id"].isin(code.keys()).all()
    h.loc[cur, "team_id"] = h.loc[cur, "team_id"].map(code)
    h.loc[cur, "opponent_team_id"] = h.loc[cur, "opponent_team_id"].map(code)
    last_sel = h[h.season == SEASON].sort_values("kickoff_time").groupby("player_code").selected_by.last()
    rows = []
    for e in bootstrap["elements"]:
        if e.get("can_select") is False and e["status"] == "u":
            pass  # still include: unavailable players get availability 0 later
        for f in fixtures:
            if f["event"] != gw or f["kickoff_time"] is None:
                continue
            if e["team"] not in (f["team_h"], f["team_a"]):
                continue
            home = e["team"] == f["team_h"]
            r = dict(season=SEASON, gameweek=gw, player_code=e["code"], player_id=e["id"], web_name=e["web_name"],
                     position=POS[e["element_type"]], team_id=code[e["team"]],
                     opponent_team_id=code[f["team_a"] if home else f["team_h"]], fixture_id=f["id"],
                     kickoff_time=pd.Timestamp(f["kickoff_time"]), was_home=home, price=e["now_cost"] / 10.0,
                     selected_by=int(last_sel.get(e["code"], 0)))
            r.update({c: 0 for c in OUTCOME_ZERO})
            rows.append(r)
    ph = pd.DataFrame(rows)
    for c in h.columns:
        if c in ph:
            ph[c] = ph[c].astype(h[c].dtype) if c != "kickoff_time" else pd.to_datetime(ph[c], utc=True)
    out = pd.concat([h, ph[h.columns]], ignore_index=True)
    return out


def availability(bootstrap) -> pd.DataFrame:
    """Current status/chance (taken now, before the deadline) -> avail per player code, as availability.py."""
    import availability as av
    el = pd.DataFrame(bootstrap["elements"])
    a = av.availability(el.status, pd.to_numeric(el.chance_of_playing_next_round, errors="coerce"))
    return pd.DataFrame({"player_id": el.code, "avail": a})


# football-data.co.uk short names for 2026/27's promoted sides (FPL uses the full name). Harness fix
# 2026-10-14: without these the A+odds join silently dropped every fixture involving them.
EXTRA_ALIAS = {"Coventry": "Coventry City", "Hull": "Hull City", "Ipswich": "Ipswich Town"}


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalpha())


def team_resolver(teams, alias):
    """football-data.co.uk name -> FPL team code: alias, exact, then unique prefix (as
    fpl_dof.sources.fdcouk.odds.team_name_map). Unresolvable or ambiguous names map to None."""
    by_norm = {_norm(t["name"]): t["code"] for t in teams}
    aliases = {**alias, **EXTRA_ALIAS}

    class _R(dict):
        def __missing__(self, key):
            target = _norm(aliases.get(key, key))
            if target in by_norm:
                return by_norm[target]
            hits = [c for n, c in by_norm.items() if target and (n.startswith(target) or target.startswith(n))]
            return hits[0] if len(hits) == 1 else None

        def get(self, key, default=None):
            v = self[key]
            return default if v is None else v

    return _R()


def live_odds(csv_bytes: bytes, fetched_at: pd.Timestamp, gw: int, deadline: pd.Timestamp, bootstrap, fixtures) -> pd.DataFrame:
    """football-data.co.uk fixtures.csv -> rows in odds_team.fixtures() layout for this GW.
    Pre-closing columns only (Pinnacle PSH/PSD/PSA, P>2.5/P<2.5 else Avg*). Collection time = our
    fetch time; a fixture is kept only if fetched strictly before the FPL deadline."""
    import odds_team as ot
    from ds_features import ALIAS
    cols = ["season", "gameweek", "fixture_id", "home", "away", "kickoff", "coll", "deadline", "kept", "src12", "srcou",
            "FTHG", "FTAG", "HST", "AST", "lh", "la", "ph", "pdr", "pa", "pov", "ovr12", "ovrou", "devig"]
    try:
        f = pd.read_csv(io.BytesIO(csv_bytes), encoding="latin-1")
        f.columns = [c.lstrip("\ufeff").replace("ï»¿", "") for c in f.columns]
    except Exception:
        return pd.DataFrame(columns=cols)
    f = f[f.get("Div", pd.Series(dtype=str)) == "E0"]
    n2c = team_resolver(bootstrap["teams"], ALIAS)
    id2c = {t["id"]: t["code"] for t in bootstrap["teams"]}
    fx = {(id2c[x["team_h"]], id2c[x["team_a"]]): x for x in fixtures if x["event"] == gw}
    rows = []
    for r in f.to_dict("records"):
        hc, ac = n2c.get(r["HomeTeam"]), n2c.get(r["AwayTeam"])
        m = fx.get((hc, ac))
        if m is None:
            continue
        x12, s12 = ot._price(r, ["PSH", "PSD", "PSA"], ["AvgH", "AvgD", "AvgA"])
        xou, sou = ot._price(r, ["P>2.5", "P<2.5"], ["Avg>2.5", "Avg<2.5"])
        d = dict(season=SEASON, gameweek=gw, fixture_id=m["id"], home=hc, away=ac, kickoff=pd.Timestamp(m["kickoff_time"]),
                 coll=fetched_at, deadline=deadline, kept=bool(fetched_at < deadline and x12 is not None), src12=s12, srcou=sou,
                 FTHG=np.nan, FTAG=np.nan, HST=np.nan, AST=np.nan, lh=np.nan, la=np.nan, ph=np.nan, pdr=np.nan, pa=np.nan,
                 pov=np.nan, ovr12=np.nan, ovrou=np.nan, devig=None)
        if d["kept"]:
            p, how = ot.devig_1x2(x12)
            d.update(ph=p[0], pdr=p[1], pa=p[2], ovr12=sum(1 / x for x in x12) - 1, devig=how)
            if xou is not None:
                io_, iu = 1 / xou[0], 1 / xou[1]
                d.update(pov=io_ / (io_ + iu), ovrou=io_ + iu - 1)
            d["lh"], d["la"] = ot.fit_lambdas(d["ph"], d["pdr"], d["pa"], d["pov"], 2.8)
        rows.append(d)
    return pd.DataFrame(rows, columns=cols)
