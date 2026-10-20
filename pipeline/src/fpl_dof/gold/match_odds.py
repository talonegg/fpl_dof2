"""Unified match odds and market expectations in Gold (PIPE-05).

Built from silver's ``team_match_expectation`` alone (REM-06). Every source's odds are parsed and
de-vigged behind its adapter, so this module knows no source and no file format, and every season
shares one schema and one accessor.

- One row per fixture (season, home club, away club): the latest capture knowable when the fixture
  was decided — before its gameweek deadline where the gameweek is known, otherwise before kickoff.
  A later capture would be look-ahead (Invariant 5).
- Clubs carry their permanent code, by each row's season (REM-05).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.gold.player_career import _season_from_path, club_codes, to_club_code
from fpl_dof.obs.logging import get_logger
from fpl_dof.silver.tables import Table

log = get_logger(__name__)

MATCH_ODDS_FILENAME = "team_match_odds.parquet"

#: Silver column -> gold column.
_RENAMED = {
    "kickoff_time": "match_date_utc",
    "home_win_probability": "home_win_prob",
    "draw_probability": "draw_prob",
    "away_win_probability": "away_win_prob",
    "expected_goals_home": "expected_home_goals",
    "expected_goals_away": "expected_away_goals",
    "clean_sheet_probability_home": "clean_sheet_home",
    "clean_sheet_probability_away": "clean_sheet_away",
}

MATCH_ODDS_COLUMNS: tuple[str, ...] = (
    "season",
    "gameweek",
    "fixture_id",
    "match_date_utc",
    "captured_at",
    "home_team_code",
    "away_team_code",
    "home_win_prob",
    "draw_prob",
    "away_win_prob",
    "expected_home_goals",
    "expected_away_goals",
    "clean_sheet_home",
    "clean_sheet_away",
)

_FIXTURE = ["season", "home_team_code", "away_team_code"]


def _fixtures(partition: Path, season: str, codes: dict[int, int]) -> pd.DataFrame:
    """The partition season's fixtures by club code, with each one's gameweek deadline."""
    fixture_path = partition / f"{Table.FIXTURE.value}.parquet"
    gameweek_path = partition / f"{Table.GAMEWEEK.value}.parquet"
    if not (fixture_path.exists() and gameweek_path.exists()):
        return pd.DataFrame(columns=[*_FIXTURE, "fixture_id", "gameweek", "deadline_time"])
    fixtures = pd.read_parquet(
        fixture_path, columns=["fixture_id", "gameweek", "home_team_id", "away_team_id"]
    )
    deadlines = pd.read_parquet(gameweek_path, columns=["gameweek", "deadline_time"])
    fixtures = fixtures.merge(deadlines, on="gameweek", how="left")
    return fixtures.assign(
        season=season,
        home_team_code=fixtures["home_team_id"].map(codes).astype("Int64"),
        away_team_code=fixtures["away_team_id"].map(codes).astype("Int64"),
    )[[*_FIXTURE, "fixture_id", "gameweek", "deadline_time"]]


def build_team_match_odds(
    silver_dir: Path,
    gold_dir: Path | None = None,
    seasons: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Consolidate every season's match odds held in silver into one row per fixture."""
    frames: list[pd.DataFrame] = []
    for partition in sorted(silver_dir.glob("season=*")):
        season = _season_from_path(partition)
        if season is None or (seasons is not None and season not in seasons):
            continue
        path = partition / f"{Table.TEAM_MATCH_EXPECTATION.value}.parquet"
        if not path.exists():
            continue
        odds = pd.read_parquet(path)
        if odds.empty:
            continue

        codes = club_codes(partition)
        odds["home_team_code"] = to_club_code(odds["home_team_id"], odds["season"], season, codes)
        odds["away_team_code"] = to_club_code(odds["away_team_id"], odds["season"], season, codes)
        odds = odds.dropna(subset=["home_team_code", "away_team_code"])
        odds = odds.merge(_fixtures(partition, season, codes), on=_FIXTURE, how="left")

        cutoff = odds["deadline_time"].fillna(odds["kickoff_time"])
        knowable = odds[odds["captured_at"] <= cutoff]
        latest = knowable.sort_values("captured_at").groupby(_FIXTURE, as_index=False).last()
        frames.append(latest.rename(columns=_RENAMED)[list(MATCH_ODDS_COLUMNS)])

    odds_df = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=list(MATCH_ODDS_COLUMNS))
    )
    odds_df = odds_df.sort_values(_FIXTURE, ignore_index=True)

    if gold_dir is not None:
        gold_dir.mkdir(parents=True, exist_ok=True)
        odds_df.to_parquet(gold_dir / MATCH_ODDS_FILENAME, index=False)
        log.info(
            "gold.team_match_odds.written",
            extra={"matches": len(odds_df), "path": str(gold_dir / MATCH_ODDS_FILENAME)},
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
