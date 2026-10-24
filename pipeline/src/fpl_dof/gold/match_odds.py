"""Unified match odds and market expectations in Gold (PIPE-05).

Built from silver's ``team_match_expectation`` alone (REM-06). Every source's odds are parsed and
de-vigged behind its adapter, so this module knows no source and no file format, and every season
shares one schema and one accessor.

- One row per fixture (season, home club, away club): the latest capture knowable when the fixture
  was decided — before its gameweek deadline where the gameweek is known, otherwise before kickoff.
  A later capture would be look-ahead (Invariant 5).
- Clubs carry their permanent code, by each row's season (REM-05). A current-season row a source
  wrote with club names only is matched to its club by name.

:func:`club_coded` and :func:`knowable` are the rule itself, pure, so a forecaster that reads silver
odds (A_odds, MOD-05) applies the same one (DP-14).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.gold.player_career import _season_from_path, to_club_code
from fpl_dof.obs.logging import get_logger
from fpl_dof.silver.tables import Table
from fpl_dof.sources import resolve_team

log = get_logger(__name__)

MATCH_ODDS_FILENAME = "team_match_odds.parquet"

#: Silver column -> gold column.
_RENAMED = {
    "kickoff_time": "match_date_utc",
    "home_win_probability": "home_win_prob",
    "draw_probability": "draw_prob",
    "away_win_probability": "away_win_prob",
    "over_2_5_probability": "over_2_5_prob",
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
    "over_2_5_prob",
)

_FIXTURE = ["season", "home_team_code", "away_team_code"]


def _teams(partition: Path) -> pd.DataFrame:
    path = partition / f"{Table.TEAM.value}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["team_id", "code", "name"])
    return pd.read_parquet(path, columns=["team_id", "code", "name"])


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


def club_coded(odds: pd.DataFrame, season: str, teams: pd.DataFrame) -> pd.DataFrame:
    """``odds`` with ``home_team_code`` and ``away_team_code``, rows with an unknown club dropped.

    A row's ids are the archive's permanent codes in a past season and season-local ids in
    ``season`` (D-26), mapped through ``teams`` (that season's ``team_id``, ``code``, ``name``). A
    current-season row with no id is matched by its club name.
    """
    codes = {int(t): int(c) for t, c in zip(teams["team_id"], teams["code"], strict=True)}
    named = [{"name": n, "id": c} for n, c in zip(teams["name"], teams["code"], strict=True)]
    current = odds["season"] == season
    out = odds.copy()
    for side in ("home", "away"):
        coded = to_club_code(odds[f"{side}_team_id"], odds["season"], season, codes)
        names = odds.loc[current, f"{side}_team"].astype(str)
        by_name = names.map({n: resolve_team(n, named) for n in names.unique()})
        out[f"{side}_team_code"] = coded.fillna(by_name.astype("Int64")).astype("Int64")
    return out.dropna(subset=["home_team_code", "away_team_code"])


def knowable(odds: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
    """One row per fixture: its latest capture at or before its gameweek's deadline, or before
    kickoff where the gameweek is unknown. A later capture would be look-ahead (Invariant 5).

    ``odds`` are :func:`club_coded`; ``fixtures`` carry ``season``, ``home_team_code``,
    ``away_team_code``, ``fixture_id``, ``gameweek`` and ``deadline_time``. Where two clubs meet
    more than once in ``fixtures``, a capture belongs to their next meeting: the earliest whose
    deadline it precedes.
    """
    joined = odds.assign(_capture=range(len(odds))).merge(fixtures, on=_FIXTURE, how="left")
    cutoff = joined["deadline_time"].fillna(joined["kickoff_time"])
    eligible = joined[joined["captured_at"] <= cutoff].sort_values("deadline_time", kind="stable")
    eligible = eligible.drop_duplicates("_capture", keep="first")
    latest = eligible.sort_values("captured_at", kind="stable")
    latest = latest.drop_duplicates([*_FIXTURE, "fixture_id"], keep="last")
    return latest.drop(columns="_capture").reset_index(drop=True)


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

        teams = _teams(partition)
        codes = {int(t): int(c) for t, c in zip(teams["team_id"], teams["code"], strict=True)}
        latest = knowable(club_coded(odds, season, teams), _fixtures(partition, season, codes))
        frames.append(latest.rename(columns=_RENAMED).reindex(columns=list(MATCH_ODDS_COLUMNS)))

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

    df = pd.read_parquet(path).reindex(columns=list(MATCH_ODDS_COLUMNS))
    if season is not None:
        df = df[df["season"] == season]
    if gameweek is not None:
        df = df[df["gameweek"] == as_int(gameweek)]
    return df
