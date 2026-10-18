"""Unit tests for Gold conformed datasets (PIPE-02 and PIPE-05).

Verifies:
- PIPE-02: Unified player career history across seasons keyed on permanent player_code.
- PIPE-02: Defensive contribution columns strictly null prior to 2025/26 (DL-18).
- PIPE-02: Reassigned seasonal player IDs never collide across seasons.
- PIPE-05: Consolidated team_match_odds with consistent mathematical formulation.
- PIPE-05: Standardized permanent team codes across all seasons.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fpl_dof.gold.match_odds import (
    MATCH_ODDS_COLUMNS,
    build_team_match_odds,
    read_team_match_odds,
)
from fpl_dof.gold.player_career import (
    CAREER_COLUMNS,
    DEFENSIVE_METRICS,
    build_player_career_history,
    read_player_career_history,
)
from fpl_dof.silver.tables import Table


def _create_mock_silver(silver_dir: Path) -> None:
    # 1. Past season 2024/25: defensive metrics were not measured (must be null)
    s24 = silver_dir / "season=2024-25"
    s24.mkdir(parents=True, exist_ok=True)
    df_24 = pd.DataFrame(
        [
            {
                "season": "2024/25",
                "gameweek": 1,
                "player_code": 111,
                "player_id": 10,  # seasonal id in 2024/25
                "web_name": "Saka",
                "position": "MID",
                "team_id": 3,     # Arsenal code
                "opponent_team_id": 7,  # Aston Villa code
                "fixture_id": 1,
                "kickoff_time": pd.Timestamp("2024-08-17T14:00:00Z"),
                "was_home": True,
                "minutes": 90,
                "starts": 1,
                "goals_scored": 1,
                "assists": 1,
                "clean_sheets": 1,
                "goals_conceded": 0,
                "own_goals": 0,
                "penalties_saved": 0,
                "penalties_missed": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "saves": 0,
                "bonus": 3,
                "bps": 40,
                "defensive_contribution": 0,  # even if source put 0, gold must make it null (DL-18)
                "tackles": 2,
                "recoveries": 5,
                "clearances_blocks_interceptions": 1,
                "expected_goals": 0.5,
                "expected_assists": 0.4,
                "expected_goals_conceded": 0.8,
                "price": 8.5,
                "total_points": 12,
            }
        ]
    )
    df_24.to_parquet(s24 / f"{Table.PLAYER_GAMEWEEK.value}.parquet", index=False)

    # 2. Live season 2026/27: defensive metrics are measured; player_id is reassigned!
    s26 = silver_dir / "season=2026-27"
    s26.mkdir(parents=True, exist_ok=True)
    df_26 = pd.DataFrame(
        [
            {
                "season": "2026/27",
                "gameweek": 1,
                "player_code": 111,
                "player_id": 99,  # reassigned seasonal id in 2026/27
                "web_name": "Saka",
                "position": "MID",
                "team_id": 1,     # local id 1 for Arsenal in 2026/27
                "opponent_team_id": 2,  # local id 2 for Aston Villa in 2026/27
                "fixture_id": 101,
                "kickoff_time": pd.Timestamp("2026-08-15T14:00:00Z"),
                "was_home": True,
                "minutes": 85,
                "starts": 1,
                "goals_scored": 1,
                "assists": 0,
                "clean_sheets": 1,
                "goals_conceded": 0,
                "own_goals": 0,
                "penalties_saved": 0,
                "penalties_missed": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "saves": 0,
                "bonus": 2,
                "bps": 32,
                "defensive_contribution": 2,  # legitimate measurement in 2026/27
                "tackles": 3,
                "recoveries": 4,
                "clearances_blocks_interceptions": 2,
                "expected_goals": 0.6,
                "expected_assists": 0.2,
                "expected_goals_conceded": 0.5,
                "price": 10.0,
                "total_points": 8,
            },
            # Another player who has player_id=10 in 2026/27! (Potential collision with Saka's 2024 id)
            {
                "season": "2026/27",
                "gameweek": 1,
                "player_code": 222,  # different player!
                "player_id": 10,   # inherited number 10 in 2026/27
                "web_name": "Havertz",
                "position": "FWD",
                "team_id": 1,
                "opponent_team_id": 2,
                "fixture_id": 101,
                "kickoff_time": pd.Timestamp("2026-08-15T14:00:00Z"),
                "was_home": True,
                "minutes": 90,
                "starts": 1,
                "goals_scored": 1,
                "assists": 1,
                "clean_sheets": 1,
                "goals_conceded": 0,
                "own_goals": 0,
                "penalties_saved": 0,
                "penalties_missed": 0,
                "yellow_cards": 1,
                "red_cards": 0,
                "saves": 0,
                "bonus": 3,
                "bps": 38,
                "defensive_contribution": 1,
                "tackles": 1,
                "recoveries": 2,
                "clearances_blocks_interceptions": 0,
                "expected_goals": 0.7,
                "expected_assists": 0.3,
                "expected_goals_conceded": 0.5,
                "price": 8.0,
                "total_points": 11,
            },
        ]
    )
    df_26.to_parquet(s26 / f"{Table.PLAYER_GAMEWEEK.value}.parquet", index=False)

    # Silver fixtures for 2026/27
    fix_26 = pd.DataFrame(
        [
            {
                "fixture_id": 101,
                "gameweek": 1,
                "home_team_id": 1,
                "away_team_id": 2,
                "home_difficulty": 3,
                "away_difficulty": 4,
                "finished": True,
                "kickoff_time": pd.Timestamp("2026-08-15T14:00:00Z"),
            }
        ]
    )
    fix_26.to_parquet(s26 / f"{Table.FIXTURE.value}.parquet", index=False)

    # Silver expectation table for 2026/27
    exp_26 = pd.DataFrame(
        [
            {
                "season": "2026/27",
                "source": "fdcouk",
                "captured_at": pd.Timestamp("2026-08-14T10:00:00Z"),
                "kickoff_time": pd.Timestamp("2026-08-15T14:00:00Z"),
                "home_team": "Arsenal",
                "away_team": "Aston Villa",
                "home_team_id": 1,
                "away_team_id": 2,
                "expected_goals_home": 1.85,
                "expected_goals_away": 0.95,
                "clean_sheet_probability_home": 0.386,
                "clean_sheet_probability_away": 0.157,
                "home_win_probability": 0.582,
                "draw_probability": 0.231,
                "away_win_probability": 0.187,
                "total_goals": 2.80,
            }
        ]
    )
    exp_26.to_parquet(s26 / f"{Table.TEAM_MATCH_EXPECTATION.value}.parquet", index=False)


def test_player_career_history_unification(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    _create_mock_silver(silver)

    career = build_player_career_history(silver, gold_dir=gold)
    assert len(career) == 3

    # 1. Verify permanent player_code indexing
    saka_history = read_player_career_history(gold, player_code=111)
    assert len(saka_history) == 2
    assert set(saka_history["season"]) == {"2024/25", "2026/27"}

    # Seasonal ID 10 in 2024/25 belonged to Saka, and in 2026/27 belonged to Havertz:
    # No identity corruption: Saka is player_code 111 across both seasons
    assert (saka_history["player_code"] == 111).all()

    havertz_history = read_player_career_history(gold, player_code=222)
    assert len(havertz_history) == 1
    assert havertz_history.iloc[0]["web_name"] == "Havertz"
    assert havertz_history.iloc[0]["player_id"] == 10  # seasonal ID preserved

    # 2. Defensive Contribution columns must be strictly null for 2024/25 (DL-18)
    row_24 = saka_history[saka_history["season"] == "2024/25"].iloc[0]
    for metric in DEFENSIVE_METRICS:
        assert pd.isna(row_24[metric]), f"{metric} must be null for 2024/25"

    # For 2026/27, defensive contribution is non-null
    row_26 = saka_history[saka_history["season"] == "2026/27"].iloc[0]
    assert row_26["defensive_contribution"] == 2

    # 3. Canonical club codes standardized (Arsenal is permanent code 3)
    assert row_24["team_code"] == 3
    assert row_26["team_code"] == 3


def test_team_match_odds_unification(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    _create_mock_silver(silver)

    # Also provide a sample historical E0 CSV
    csv_file = tmp_path / "E0_2425.csv"
    csv_content = (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A\n"
        "E0,17/08/2024,15:00,Arsenal,Wolves,2,0,H,1.25,6.50,11.00\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    odds = build_team_match_odds(
        silver,
        gold_dir=gold,
        extra_historical_csvs=[csv_file],
    )
    assert len(odds) >= 2

    # Check 2026/27 match
    row_26 = odds[odds["season"] == "2026/27"].iloc[0]
    assert row_26["home_team_code"] == 3  # Arsenal
    assert row_26["away_team_code"] == 7  # Aston Villa
    assert row_26["home_win_prob"] == 0.582
    assert row_26["fixture_id"] == 101

    # Check 2024/25 match from historical CSV
    row_24 = odds[odds["season"] == "2024/25"].iloc[0]
    assert row_24["home_team_code"] == 3   # Arsenal
    assert row_24["away_team_code"] == 39  # Wolves
    assert row_24["home_win_prob"] > 0.7   # De-vigged favourite
    assert row_24["expected_home_goals"] > row_24["expected_away_goals"]

    # Test universal accessor
    queried = read_team_match_odds(gold, season="2026/27")
    assert len(queried) == 1
    assert queried.iloc[0]["home_team_code"] == 3
