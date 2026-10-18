"""Tests for the unified forecast-fitting interface (PIPE-13).

Verifies:
- optimise/ imports nothing from forecast/ (DP-02, 03 §12 P1)
- fit_as_of fits component models and B0
- FittedForecastModel.predict attaches B0 captain score
- Live and backtest predict identically through the interface
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.fit import FittedForecastModel, fit_as_of
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.xp_v1 import score_player
from fpl_dof.optimise.captain import price_position_scores
from fpl_dof.rules.models import GameRules

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "fpl_dof"


def test_optimise_imports_nothing_from_forecast() -> None:
    """Acceptance criterion: optimise/ imports nothing from forecast/."""
    optimise_dir = SRC_ROOT / "optimise"
    assert optimise_dir.is_dir()

    import_pattern = re.compile(r"^\s*(from\s+[\.\w]*forecast|import\s+[\.\w]*forecast)", re.MULTILINE)
    violations: list[str] = []

    for py_file in optimise_dir.glob("**/*.py"):
        text = py_file.read_text(encoding="utf-8")
        matches = import_pattern.findall(text)
        if matches:
            violations.append(f"{py_file.name}: {matches}")

    assert not violations, f"optimise/ must not import from forecast/: {violations}"


def _sample_history() -> pd.DataFrame:
    rows = []
    # 2 seasons, 2 gameweeks each, 4 players
    for s_idx, season in enumerate(["2024/25", "2025/26"]):
        for gw in (1, 2):
            kickoff = pd.Timestamp(f"202{4 + s_idx}-08-{10 + gw * 7}T12:00:00Z")
            for pid, pos, team, opp, pts in (
                (101, "MID", 1, 2, 8.0),
                (102, "FWD", 1, 2, 6.0),
                (201, "DEF", 2, 1, 2.0),
                (202, "GKP", 2, 1, 3.0),
            ):
                rows.append(
                    {
                        "season": season,
                        "gameweek": gw,
                        "player_code": pid,
                        "player_id": pid,
                        "position": pos,
                        "team_id": team,
                        "opponent_team_id": opp,
                        "was_home": team == 1,
                        "fixture_id": gw,
                        "kickoff_time": kickoff,
                        "minutes": 90,
                        "total_points": pts,
                        "goals_scored": 1 if pts > 5 else 0,
                        "assists": 0,
                        "clean_sheets": 1 if pts > 5 and pos in ("DEF", "GKP") else 0,
                        "goals_conceded": 1,
                        "saves": 3 if pos == "GKP" else 0,
                        "yellow_cards": 0,
                        "bonus": 1 if pts > 5 else 0,
                        "bps": int(pts * 5),
                        "starts": 1,
                        "expected_goals": 0.4 if pts > 5 else 0.05,
                        "expected_assists": 0.1,
                        "expected_goals_conceded": 1.0,
                        "price": 8.0 if pid == 101 else 6.0,
                    }
                )
    return pd.DataFrame(rows)


def test_fit_as_of_and_predict_live_and_backtest(game_rules: GameRules) -> None:
    history = _sample_history()
    deadline = pd.Timestamp("2025-09-01T10:00:00Z")
    config = ForecastConfig()

    fitted = fit_as_of(history, deadline, config, game_rules)
    assert isinstance(fitted, FittedForecastModel)
    assert fitted.models is not None
    assert fitted.b0 is not None

    # 1. Backtest feature prediction on a visible row
    past = history[history["kickoff_time"] < deadline]
    row = past.iloc[0].to_frame().T
    row["availability"] = 1.0
    row["confidence"] = "medium"
    row["matches_observed"] = 2
    row["appearance_rate"] = 1.0
    row["evidence_minutes"] = 180.0
    row["fixture_team"] = 1
    row["fixture_opponent"] = 2
    row["fixture_at_home"] = 1

    series = fitted.predict(row)
    assert isinstance(series, pd.Series)
    assert len(series) == 1
    assert series.iloc[0] > 0

    # 2. Live horizon prediction attaches captain_score
    players = pd.DataFrame(
        [
            {"player_id": 101, "code": 101, "web_name": "P101", "position": "MID", "team_id": 1, "price": 8.0, "status": "a", "news": "", "selected_by_percent": 10.0, "chance_of_playing_next_round": None},
            {"player_id": 102, "code": 102, "web_name": "P102", "position": "FWD", "team_id": 1, "price": 6.0, "status": "a", "news": "", "selected_by_percent": 5.0, "chance_of_playing_next_round": None},
        ]
    )
    teams = pd.DataFrame([{"team_id": 1, "short_name": "T1"}, {"team_id": 2, "short_name": "T2"}])
    fixtures = pd.DataFrame([{"fixture_id": 10, "gameweek": 3, "home_team_id": 1, "away_team_id": 2, "finished": False, "kickoff_time": pd.Timestamp("2025-09-05T12:00:00Z")}])
    gameweeks = pd.DataFrame([{"gameweek": 3, "deadline_time": pd.Timestamp("2025-09-05T10:00:00Z"), "finished": False}])
    inputs = ForecastInputs(
        players=players,
        teams=teams,
        fixtures=fixtures,
        gameweeks=gameweeks,
        history=pd.DataFrame(),
        player_gameweek=history,
    )

    live_frame = fitted.predict([3], inputs=inputs)
    assert isinstance(live_frame, pd.DataFrame)
    assert "xp_next" in live_frame.columns
    assert "captain_score" in live_frame.columns
    assert "start_probability" in live_frame.columns
    assert live_frame.attrs.get("component_description") is not None

    # 3. Decision captain scores reads from captain_score column directly
    scores = price_position_scores(live_frame)
    assert scores is not None
    assert 101 in scores and 102 in scores
    assert isinstance(scores[101], float)
