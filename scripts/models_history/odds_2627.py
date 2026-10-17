"""football-data.co.uk 2026/27 OPENING odds joined to FPL fixtures (GW1-6 A_odds replay).

Pure data layer, no model code. Opening columns only: 1X2 B365H/D/A (fallback AvgH/D/A) and totals
B365>2.5/B365<2.5 (fallback Avg>2.5/Avg<2.5). The closing columns (B365CH, AvgCH, ...) are not read.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data" / "fdcouk"
CSV = DATA / "E0_2627_20261017.csv"
TEAM_KEYS = DATA / "team_keys_2627.csv"

#: football-data.co.uk name -> FPL team name, for every name that does not match FPL exactly
#: (promoted sides Coventry/Hull/Ipswich, and the long-standing abbreviations).
ALIAS: dict[str, str] = {
    "Man United": "Man Utd",
    "Tottenham": "Spurs",
    "Nott'm Forest": "Nott'm Forest",
    "Sheffield United": "Sheffield Utd",
    "Coventry": "Coventry City",
    "Hull": "Hull City",
    "Ipswich": "Ipswich Town",
}

OPEN_1X2 = (("B365H", "B365D", "B365A"), ("AvgH", "AvgD", "AvgA"))
OPEN_OU = (("B365>2.5", "B365<2.5"), ("Avg>2.5", "Avg<2.5"))


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalpha())


def team_codes(teams: pd.DataFrame, keys: Path = TEAM_KEYS) -> dict[str, int]:
    """FPL team name (normalised) -> stable club code, from silver team + the 2026/27 id map."""
    k = pd.read_csv(keys).set_index("team_id").team_code
    return {_norm(r.name): int(k[r.team_id]) for r in teams.itertuples()}


def resolve(name: str, codes: dict[str, int]) -> int | None:
    return codes.get(_norm(ALIAS.get(name, name)))


def fixture_codes(
    fixtures: pd.DataFrame, teams: pd.DataFrame, keys: Path = TEAM_KEYS
) -> pd.DataFrame:
    """Silver fixtures with home/away recoded to stable club codes."""
    k = pd.read_csv(keys).set_index("team_id").team_code
    f = fixtures.copy()
    f["home"] = f.home_team_id.map(k).astype(int)
    f["away"] = f.away_team_id.map(k).astype(int)
    f["kickoff"] = pd.to_datetime(f.kickoff_time, utc=True)
    return f[["fixture_id", "gameweek", "kickoff", "home", "away"]]


def _pick(r: dict, groups: tuple[tuple[str, ...], ...], labels: tuple[str, ...]):
    for cols, lab in zip(groups, labels, strict=True):
        v = [r.get(c) for c in cols]
        if all(pd.notna(x) and float(x) > 1 for x in v):
            return [float(x) for x in v], lab
    return [None] * len(groups[0]), None


def load_opening(path: Path, fixtures: pd.DataFrame, codes: dict[str, int]) -> pd.DataFrame:
    """One row per FPL fixture in ``fixtures``: opening H/D/A and O/U prices + sources.

    Raises if a CSV team name does not resolve or a fixture has no odds row, so a gap is never
    silently filled.
    """
    f = pd.read_csv(path, encoding="latin-1")
    f.columns = [c.lstrip("\ufeff").replace("ï»¿", "") for c in f.columns]
    f = f[f["Div"] == "E0"]
    rows, unresolved = {}, set()
    for r in f.to_dict("records"):
        h, a = resolve(r["HomeTeam"], codes), resolve(r["AwayTeam"], codes)
        if h is None or a is None:
            unresolved |= {n for n, c in ((r["HomeTeam"], h), (r["AwayTeam"], a)) if c is None}
            continue
        (ph, pdr, pa), s12 = _pick(r, OPEN_1X2, ("b365_open", "avg_open"))
        (po, pu), sou = _pick(r, OPEN_OU, ("b365_open", "avg_open"))
        rows[(h, a)] = {"H": ph, "D": pdr, "A": pa, "O": po, "U": pu, "src12": s12, "srcou": sou}
    if unresolved:
        raise ValueError(f"unresolved football-data.co.uk team names: {sorted(unresolved)}")
    out = fixtures.copy()
    odds = pd.DataFrame([rows.get((r.home, r.away), {}) for r in out.itertuples()], index=out.index)
    out = pd.concat(
        [out, odds.reindex(columns=["H", "D", "A", "O", "U", "src12", "srcou"])], axis=1
    )
    missing = out[out.src12.isna()]
    if len(missing):
        raise ValueError(
            f"{len(missing)} fixtures without opening 1X2 odds: {missing.fixture_id.tolist()}"
        )
    return out
