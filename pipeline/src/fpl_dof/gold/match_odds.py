"""Unified match odds and market expectations in Gold (PIPE-05).

Consolidates historical and live match odds into a single
canonical dataset using a consistent Shin / Poisson de-vigging formulation.

Guarantees:
- Historical match odds (2023-2026) and live odds share an identical schema and accessor.
- All clubs are standardized to canonical, permanent team codes.
- De-vigged probabilities and expected goals are mathematically consistent across all seasons.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from fpl_dof.frames import as_float, as_int
from fpl_dof.gold.player_career import _season_from_path, club_codes
from fpl_dof.obs.logging import get_logger
from fpl_dof.silver.tables import Table
from fpl_dof.sources import (
    MarketError,
    devig,
    fit_goal_expectations,
)

log = get_logger(__name__)

MATCH_ODDS_FILENAME = "team_match_odds.parquet"

#: Team name alias -> permanent club code
TEAM_NAME_TO_CODE: dict[str, int] = {
    "arsenal": 3,
    "astonvilla": 7,
    "bournemouth": 91,
    "brentford": 94,
    "brighton": 36,
    "chelsea": 8,
    "coventry": 9,
    "coventrycity": 9,
    "crystalpalace": 31,
    "everton": 11,
    "fulham": 54,
    "hull": 88,
    "hullcity": 88,
    "ipswich": 40,
    "ipswichtown": 40,
    "leeds": 2,
    "leedsunited": 2,
    "liverpool": 14,
    "mancity": 43,
    "manchestercity": 43,
    "manutd": 1,
    "manunited": 1,
    "manchesterunited": 1,
    "newcastle": 4,
    "newcastleunited": 4,
    "nottinghamforest": 17,
    "nottmforest": 17,
    "spurs": 6,
    "tottenham": 6,
    "tottenhamhotspur": 6,
    "sunderland": 56,
    "sheffieldutd": 49,
    "sheffieldunited": 49,
    "burnley": 90,
    "luton": 102,
    "lutontown": 102,
    "wolves": 39,
    "wolverhampton": 39,
    "wolverhamptonwanderers": 39,
    "westham": 21,
    "westhamunited": 21,
    "leicester": 13,
    "leicestercity": 13,
    "southampton": 20,
}

MATCH_ODDS_COLUMNS: tuple[str, ...] = (
    "season",
    "gameweek",
    "fixture_id",
    "match_date_utc",
    "home_team_code",
    "away_team_code",
    "home_odds",
    "draw_odds",
    "away_odds",
    "home_win_prob",
    "draw_prob",
    "away_win_prob",
    "expected_home_goals",
    "expected_away_goals",
    "clean_sheet_home",
    "clean_sheet_away",
)


def _resolve_team_code(val: Any) -> int | None:
    if val is None or pd.isna(val):
        return None
    try:
        iv = int(val)
        return iv
    except ValueError, TypeError:
        pass
    cleaned = "".join(ch for ch in str(val).lower() if ch.isalnum())
    return TEAM_NAME_TO_CODE.get(cleaned)


def _code(team_id: object, row_season: str, current: str, codes: dict[int, int]) -> int | None:
    """A row's club code: mapped through ``codes`` in the current season, as stored otherwise."""
    return codes.get(as_int(team_id)) if row_season == current else as_int(team_id)


def build_team_match_odds(
    silver_dir: Path,
    gold_dir: Path | None = None,
    seasons: Sequence[str] | None = None,
    extra_historical_csvs: Sequence[Path] | None = None,
) -> pd.DataFrame:
    """Consolidate match odds across all available silver and historical sources."""
    rows: list[dict[str, Any]] = []
    season_dirs = sorted(silver_dir.glob("season=*"))

    for s_dir in season_dirs:
        season = _season_from_path(s_dir)
        if season is None or (seasons is not None and season not in seasons):
            continue

        exp_path = s_dir / f"{Table.TEAM_MATCH_EXPECTATION.value}.parquet"
        if not exp_path.exists():
            continue

        df = pd.read_parquet(exp_path)
        if df.empty:
            continue

        codes = club_codes(s_dir)
        fix_map: dict[tuple[int, int], tuple[int | None, int | None]] = {}
        fix_path = s_dir / f"{Table.FIXTURE.value}.parquet"
        if fix_path.exists():
            fix_df = pd.read_parquet(fix_path)
            for r in fix_df.itertuples():
                fix_home = codes.get(as_int(r.home_team_id))
                fix_away = codes.get(as_int(r.away_team_id))
                if fix_home is None or fix_away is None:
                    continue
                fix_map[(fix_home, fix_away)] = (
                    as_int(r.fixture_id) if pd.notna(r.fixture_id) else None,
                    as_int(r.gameweek) if pd.notna(r.gameweek) else None,
                )

        for row in df.itertuples():
            h_code = (
                _code(row.home_team_id, getattr(row, "season", season), season, codes)
                if pd.notna(getattr(row, "home_team_id", None))
                else _resolve_team_code(getattr(row, "home_team", None))
            )
            a_code = (
                _code(row.away_team_id, getattr(row, "season", season), season, codes)
                if pd.notna(getattr(row, "away_team_id", None))
                else _resolve_team_code(getattr(row, "away_team", None))
            )

            if h_code is None or a_code is None:
                continue

            fid, gw = fix_map.get((h_code, a_code), (None, None))
            kickoff = getattr(row, "kickoff_time", None)

            rows.append(
                {
                    "season": season,
                    "gameweek": gw,
                    "fixture_id": fid,
                    "match_date_utc": kickoff,
                    "home_team_code": h_code,
                    "away_team_code": a_code,
                    "home_odds": getattr(row, "home_odds", None),
                    "draw_odds": getattr(row, "draw_odds", None),
                    "away_odds": getattr(row, "away_odds", None),
                    "home_win_prob": round(as_float(row.home_win_probability), 6),
                    "draw_prob": round(as_float(row.draw_probability), 6),
                    "away_win_prob": round(as_float(row.away_win_probability), 6),
                    "expected_home_goals": round(as_float(row.expected_goals_home), 4),
                    "expected_away_goals": round(as_float(row.expected_goals_away), 4),
                    "clean_sheet_home": round(as_float(row.clean_sheet_probability_home), 6),
                    "clean_sheet_away": round(as_float(row.clean_sheet_probability_away), 6),
                }
            )

    # Process any extra historical E0 CSVs
    if extra_historical_csvs:
        for csv_path in extra_historical_csvs:
            if not csv_path.exists():
                continue
            try:
                hist_df = pd.read_csv(csv_path, encoding="latin-1")
            except Exception:
                continue
            hist_df.columns = [c.lstrip("\ufeff").replace("ï»¿", "") for c in hist_df.columns]
            if "Div" in hist_df.columns:
                hist_df = hist_df[hist_df["Div"] == "E0"]

            # Derive season from filename or path (e.g. E0_2324.csv -> 2023/24)
            s_name = "2023/24"
            stem = csv_path.stem
            for scode, slabel in (
                ("2324", "2023/24"),
                ("2425", "2024/25"),
                ("2526", "2025/26"),
                ("2627", "2026/27"),
            ):
                if scode in stem:
                    s_name = slabel
                    break

            for rec in hist_df.to_dict("records"):
                h_raw = rec.get("HomeTeam")
                a_raw = rec.get("AwayTeam")
                home_code = _resolve_team_code(h_raw)
                away_code = _resolve_team_code(a_raw)
                if home_code is None or away_code is None:
                    continue

                h_odds = rec.get("B365H") or rec.get("AvgH")
                d_odds = rec.get("B365D") or rec.get("AvgD")
                a_odds = rec.get("B365A") or rec.get("AvgA")
                if not (h_odds and d_odds and a_odds):
                    continue
                try:
                    h_val, d_val, a_val = float(h_odds), float(d_odds), float(a_odds)
                    if h_val <= 1 or d_val <= 1 or a_val <= 1:
                        continue
                    devigged = devig({"home": h_val, "draw": d_val, "away": a_val})
                    fitted = fit_goal_expectations(result=devigged)
                except MarketError, ValueError:
                    continue

                date_str = str(rec.get("Date") or "").strip()
                time_str = str(rec.get("Time") or "").strip()
                match_date: pd.Timestamp | None = None
                if date_str:
                    combo = f"{date_str} {time_str}".strip() if time_str else date_str
                    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%y %H:%M", "%d/%m/%Y", "%d/%m/%y"):
                        try:
                            match_date = pd.to_datetime(combo, format=fmt, utc=True)
                            break
                        except ValueError:
                            pass

                rows.append(
                    {
                        "season": s_name,
                        "gameweek": None,
                        "fixture_id": None,
                        "match_date_utc": match_date,
                        "home_team_code": home_code,
                        "away_team_code": away_code,
                        "home_odds": h_val,
                        "draw_odds": d_val,
                        "away_odds": a_val,
                        "home_win_prob": fitted.home_win_probability,
                        "draw_prob": fitted.draw_probability,
                        "away_win_prob": fitted.away_win_probability,
                        "expected_home_goals": fitted.expected_goals_home,
                        "expected_away_goals": fitted.expected_goals_away,
                        "clean_sheet_home": fitted.clean_sheet_probability_home,
                        "clean_sheet_away": fitted.clean_sheet_probability_away,
                    }
                )

    if not rows:
        empty = pd.DataFrame(columns=list(MATCH_ODDS_COLUMNS))
        if gold_dir is not None:
            gold_dir.mkdir(parents=True, exist_ok=True)
            empty.to_parquet(gold_dir / MATCH_ODDS_FILENAME, index=False)
        return empty

    odds_df = pd.DataFrame(rows).drop_duplicates(
        subset=["season", "home_team_code", "away_team_code"],
        keep="first",
    )
    odds_df = odds_df.sort_values(["season", "home_team_code", "away_team_code"], ignore_index=True)

    if gold_dir is not None:
        gold_dir.mkdir(parents=True, exist_ok=True)
        odds_df.to_parquet(gold_dir / MATCH_ODDS_FILENAME, index=False)
        log.info(
            "gold.team_match_odds.written",
            extra={
                "matches": len(odds_df),
                "seasons": sorted(odds_df["season"].unique()),
                "path": str(gold_dir / MATCH_ODDS_FILENAME),
            },
        )

    return odds_df


def read_team_match_odds(
    gold_dir: Path,
    *,
    season: str | None = None,
    gameweek: int | None = None,
) -> pd.DataFrame:
    """Universal accessor for gold match odds."""
    path = gold_dir / MATCH_ODDS_FILENAME
    if not path.exists():
        return pd.DataFrame(columns=list(MATCH_ODDS_COLUMNS))

    df = pd.read_parquet(path)
    if season is not None:
        df = df[df["season"] == season]
    if gameweek is not None:
        df = df[df["gameweek"] == as_int(gameweek)]
    return df
