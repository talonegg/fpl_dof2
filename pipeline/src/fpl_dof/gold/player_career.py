"""Unified multi-season player view in Gold (PIPE-02).

Conforms historical gameweek actuals and live data across seasons into a single
career-stable dataset keyed on permanent player_code.

Guarantees:
- Reassigned seasonal player IDs never collide across seasons.
- Defensive Contribution metrics prior to 2025/26 remain strictly nullable (DL-18).
- Canonical club codes are standardized across all seasons.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.silver.tables import Table

log = get_logger(__name__)

CAREER_FILENAME = "player_career_history.parquet"

#: Defensive metrics introduced in 2025/26. Strictly null prior to 2025/26 (DL-18).
DEFENSIVE_METRICS: tuple[str, ...] = (
    "defensive_contribution",
    "tackles",
    "recoveries",
    "clearances_blocks_interceptions",
)

#: Standard 2026/27 FPL local team ID -> permanent club code.
TEAM_ID_TO_CODE_2627: dict[int, int] = {
    1: 3,  # Arsenal
    2: 7,  # Aston Villa
    3: 91,  # Bournemouth
    4: 94,  # Brentford
    5: 36,  # Brighton
    6: 8,  # Chelsea
    7: 9,  # Coventry
    8: 31,  # Crystal Palace
    9: 11,  # Everton
    10: 54,  # Fulham
    11: 88,  # Hull
    12: 40,  # Ipswich
    13: 2,  # Leeds
    14: 14,  # Liverpool
    15: 43,  # Man City
    16: 1,  # Man Utd
    17: 4,  # Newcastle
    18: 17,  # Nott'm Forest
    19: 6,  # Spurs
    20: 56,  # Sunderland
}

CAREER_COLUMNS: tuple[str, ...] = (
    "season",
    "gameweek",
    "player_code",
    "player_id",
    "web_name",
    "position",
    "team_code",
    "opponent_team_code",
    "fixture_id",
    "kickoff_time",
    "was_home",
    "minutes",
    "starts",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "bonus",
    "bps",
    "defensive_contribution",
    "tackles",
    "recoveries",
    "clearances_blocks_interceptions",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "price",
    "total_points",
)


def _season_from_path(path: Path) -> str | None:
    for part in path.parts:
        if part.startswith("season="):
            return part.split("=", 1)[1].replace("-", "/")
    return None


def build_player_career_history(
    silver_dir: Path,
    gold_dir: Path | None = None,
    seasons: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Build the conformed player_career_history dataset from silver partitions."""
    all_frames: list[pd.DataFrame] = []
    season_dirs = sorted(silver_dir.glob("season=*"))

    for s_dir in season_dirs:
        season = _season_from_path(s_dir)
        if season is None or (seasons is not None and season not in seasons):
            continue

        gw_path = s_dir / f"{Table.PLAYER_GAMEWEEK.value}.parquet"
        if not gw_path.exists():
            continue

        df = pd.read_parquet(gw_path)
        if df.empty:
            continue

        frame = df.copy()
        if "season" not in frame.columns:
            frame["season"] = season

        # 1. Standardize club codes across seasons
        if season == "2026/27":
            frame["team_code"] = frame["team_id"].map(TEAM_ID_TO_CODE_2627)
            frame["opponent_team_code"] = frame["opponent_team_id"].map(TEAM_ID_TO_CODE_2627)
        else:
            # Historical archives already store permanent club codes in team_id
            frame["team_code"] = frame["team_id"]
            frame["opponent_team_code"] = frame["opponent_team_id"]

        # 2. Defensive Contribution columns must be strictly null for seasons before 2025/26 (DL-18)
        if season < "2025/26":
            for col in DEFENSIVE_METRICS:
                frame[col] = None
        else:
            for col in DEFENSIVE_METRICS:
                if col not in frame.columns:
                    frame[col] = None

        for col in CAREER_COLUMNS:
            if col not in frame.columns:
                frame[col] = None

        all_frames.append(frame[list(CAREER_COLUMNS)])

    if not all_frames:
        empty = pd.DataFrame(columns=list(CAREER_COLUMNS))
        if gold_dir is not None:
            gold_dir.mkdir(parents=True, exist_ok=True)
            empty.to_parquet(gold_dir / CAREER_FILENAME, index=False)
        return empty

    career = pd.concat(all_frames, ignore_index=True)

    # Ensure stable sorting: player_code, season, gameweek, fixture_id
    career["gameweek"] = career["gameweek"].astype(int)
    career["player_code"] = career["player_code"].astype(int)
    career = career.sort_values(
        ["player_code", "season", "gameweek", "fixture_id"],
        ignore_index=True,
    )

    if gold_dir is not None:
        gold_dir.mkdir(parents=True, exist_ok=True)
        career.to_parquet(gold_dir / CAREER_FILENAME, index=False)
        log.info(
            "gold.player_career_history.written",
            extra={
                "rows": len(career),
                "players": int(career["player_code"].nunique()),
                "seasons": sorted(career["season"].unique()),
                "path": str(gold_dir / CAREER_FILENAME),
            },
        )

    return career


def read_player_career_history(
    gold_dir: Path,
    *,
    player_code: int | None = None,
    season: str | None = None,
) -> pd.DataFrame:
    """Universal query interface for player career history."""
    path = gold_dir / CAREER_FILENAME
    if not path.exists():
        return pd.DataFrame(columns=list(CAREER_COLUMNS))

    df = pd.read_parquet(path)
    if player_code is not None:
        df = df[df["player_code"] == as_int(player_code)]
    if season is not None:
        df = df[df["season"] == season]
    return df
