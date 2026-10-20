"""2026/27 GW1-6 opening odds (scripts/models_history/odds_2627.py): every fixture joins."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from fpl_dof.sources.fdcouk.adapter import HISTORY, SEASONS

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "models_history" / "odds_2627.py"
#: FPL 2026/27 team names (silver team.parquet), season-local ids 1..20.
FPL_TEAMS = [
    "Arsenal",
    "Aston Villa",
    "Bournemouth",
    "Brentford",
    "Brighton",
    "Chelsea",
    "Coventry City",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Hull City",
    "Ipswich Town",
    "Leeds",
    "Liverpool",
    "Man City",
    "Man Utd",
    "Newcastle",
    "Nott'm Forest",
    "Spurs",
    "Sunderland",
]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("odds_2627", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["odds_2627"] = mod
    spec.loader.exec_module(mod)
    return mod


def _teams() -> pd.DataFrame:
    return pd.DataFrame({"team_id": range(1, 21), "name": FPL_TEAMS})


def _csv_fixtures(mod: ModuleType) -> pd.DataFrame:
    """The CSV's own GW1-6 fixtures as an FPL fixture frame (codes from the team-key map)."""
    codes = mod.team_codes(_teams())
    f = pd.read_csv(mod.CSV, encoding="latin-1")
    return pd.DataFrame(
        {
            "fixture_id": range(1, len(f) + 1),
            "gameweek": [i // 10 + 1 for i in range(len(f))],
            "kickoff": pd.Timestamp("2026-08-21", tz="UTC"),
            "home": [mod.resolve(n, codes) for n in f.HomeTeam],
            "away": [mod.resolve(n, codes) for n in f.AwayTeam],
        }
    )


def test_2627_in_season_map_but_not_frozen_history() -> None:
    assert SEASONS["2627"] == "https://www.football-data.co.uk/mmz4281/2627/E0.csv"
    assert not any("2627" in k for k in HISTORY)  # never a frozen A+odds input


def test_every_csv_team_resolves_including_promoted_sides() -> None:
    mod = _module()
    codes = mod.team_codes(_teams())
    names = set(pd.read_csv(mod.CSV, encoding="latin-1")[["HomeTeam", "AwayTeam"]].stack())
    assert len(names) == 20
    resolved = {n: mod.resolve(n, codes) for n in names}
    assert all(c is not None for c in resolved.values()), resolved
    assert len(set(resolved.values())) == 20
    for n in ("Coventry", "Hull", "Ipswich", "Man United", "Tottenham"):
        assert n in names


def test_all_gw1_6_fixtures_join_to_opening_odds() -> None:
    mod = _module()
    fx = _csv_fixtures(mod)
    assert len(fx) == 60 and fx.groupby("gameweek").size().eq(10).all()
    j = mod.load_opening(mod.CSV, fx, mod.team_codes(_teams()))
    assert len(j) == 60
    assert j[["H", "D", "A", "O", "U"]].notna().all().all()
    assert set(j.src12) == {"b365_open"}  # opening Bet365 for every match, no Avg fallback needed


def test_opening_not_closing_columns(tmp_path: Path) -> None:
    mod = _module()
    csv = tmp_path / "e0.csv"
    csv.write_text(
        "Div,HomeTeam,AwayTeam,B365H,B365D,B365A,AvgH,AvgD,AvgA,B365>2.5,B365<2.5,Avg>2.5,Avg<2.5,"
        "B365CH,B365CD,B365CA\nE0,Arsenal,Coventry,,,,1.2,7,14,,,1.3,3.5,9,9,9\n"
    )
    codes = mod.team_codes(_teams())
    fx = pd.DataFrame(
        {
            "fixture_id": [1],
            "gameweek": [1],
            "kickoff": [pd.Timestamp("2026-08-21", tz="UTC")],
            "home": [mod.resolve("Arsenal", codes)],
            "away": [mod.resolve("Coventry", codes)],
        }
    )
    r = mod.load_opening(csv, fx, codes).iloc[0]
    assert (r.H, r.D, r.A, r.src12, r.srcou) == (1.2, 7, 14, "avg_open", "avg_open")


def test_missing_fixture_or_unknown_team_raises(tmp_path: Path) -> None:
    mod = _module()
    codes = mod.team_codes(_teams())
    fx = _csv_fixtures(mod)
    bad = fx.copy()
    bad.loc[0, ["home", "away"]] = bad.loc[0, ["away", "home"]].to_numpy()
    with pytest.raises(ValueError, match="without opening"):
        mod.load_opening(mod.CSV, bad, codes)
    csv = tmp_path / "e0.csv"
    csv.write_text("Div,HomeTeam,AwayTeam,B365H,B365D,B365A\nE0,Arsenal,Atlantis,1.5,4,6\n")
    with pytest.raises(ValueError, match="Atlantis"):
        mod.load_opening(csv, fx, codes)
