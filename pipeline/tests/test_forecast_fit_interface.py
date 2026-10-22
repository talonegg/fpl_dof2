"""Tests for the unified forecast-fitting interface (PIPE-13).

Verifies:
- optimise/ imports nothing from forecast/ (DP-02, 03 §12 P1)
- fit_as_of fits component models and B0
- B0 stays on the fitted model, out of the forecast frame (captaincy is policy, MOD-02)
- Live and backtest predict identically through the interface
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from conftest import before_next_deadline
from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.fit import FittedForecastModel, fit_as_of
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.rules.models import GameRules

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "fpl_dof"


def test_optimise_imports_nothing_from_forecast() -> None:
    """Acceptance criterion: optimise/ imports nothing from forecast/."""
    optimise_dir = SRC_ROOT / "optimise"
    assert optimise_dir.is_dir()

    import_pattern = re.compile(
        r"^\s*(from\s+[\.\w]*forecast|import\s+[\.\w]*forecast)", re.MULTILINE
    )
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

    # 2. Live horizon prediction carries no captain column: B0 is the captain policy's input
    players = pd.DataFrame(
        [
            {
                "player_id": 101,
                "code": 101,
                "web_name": "P101",
                "position": "MID",
                "team_id": 1,
                "price": 8.0,
                "status": "a",
                "news": "",
                "selected_by_percent": 10.0,
                "chance_of_playing_next_round": None,
            },
            {
                "player_id": 102,
                "code": 102,
                "web_name": "P102",
                "position": "FWD",
                "team_id": 1,
                "price": 6.0,
                "status": "a",
                "news": "",
                "selected_by_percent": 5.0,
                "chance_of_playing_next_round": None,
            },
        ]
    )
    teams = pd.DataFrame([{"team_id": 1, "short_name": "T1"}, {"team_id": 2, "short_name": "T2"}])
    fixtures = pd.DataFrame(
        [
            {
                "fixture_id": 10,
                "gameweek": 3,
                "home_team_id": 1,
                "away_team_id": 2,
                "finished": False,
                "kickoff_time": pd.Timestamp("2025-09-05T12:00:00Z"),
            }
        ]
    )
    gameweeks = pd.DataFrame(
        [
            {
                "gameweek": 3,
                "deadline_time": pd.Timestamp("2025-09-05T10:00:00Z"),
                "finished": False,
            }
        ]
    )
    inputs = ForecastInputs(
        players=players,
        teams=teams,
        fixtures=fixtures,
        gameweeks=gameweeks,
        as_of=before_next_deadline(gameweeks),
        history=pd.DataFrame(),
        player_gameweek=history,
    )

    live_frame = fitted.predict([3], inputs=inputs)
    assert isinstance(live_frame, pd.DataFrame)
    assert "xp_next" in live_frame.columns
    assert "captain_score" not in live_frame.columns
    assert "start_probability" in live_frame.columns
    assert live_frame.attrs.get("component_description") is not None

    # 3. The fitted B0 scores every player in the frame, for the captain policy to use
    scores = fitted.b0.predict(live_frame)
    assert len(scores) == len(live_frame)
    assert scores.notna().all()


def test_replay_predicts_one_season_against_the_archive_calendar(game_rules: GameRules) -> None:
    """REM-01: the replay path runs without ``--slow`` and never pools players across seasons."""
    history = _sample_history()
    # GW3 of 2025/26 kicks off after the deadline: the horizon's fixture, known from the calendar.
    gw3 = history[(history["season"] == "2025/26") & (history["gameweek"] == 2)].copy()
    gw3["gameweek"] = 3
    gw3["fixture_id"] = 3
    gw3["kickoff_time"] = pd.Timestamp("2025-09-07T12:00:00Z")
    # A player seen only in the earlier season must not join the replayed squad pool.
    retired = history[(history["season"] == "2024/25") & (history["player_code"] == 101)].copy()
    retired["player_code"] = retired["player_id"] = 301
    history = pd.concat([history, gw3, retired], ignore_index=True)
    history["web_name"] = "P" + history["player_code"].astype(str)  # the archive carries names

    fitted = fit_as_of(history, pd.Timestamp("2025-09-01T10:00:00Z"), ForecastConfig(), game_rules)
    frame = fitted.predict([3], history=history, season="2025/26")

    assert set(frame["player_id"]) == {101, 102, 201, 202}
    assert (frame["next_gameweek"] == 3).all()
    assert "captain_score" not in frame.columns


def test_a_gameweek_in_play_never_enters_the_fit() -> None:
    """REM-08: between GW1's deadline and GW1 finishing, GW2 is decided but the fit stops at GW1's
    deadline, so GW1's partial minutes and points never train anything."""
    from fpl_dof.forecast.live import next_deadline

    d1, d2 = pd.Timestamp("2026-08-21T17:30Z"), pd.Timestamp("2026-08-28T17:30Z")
    gameweeks = pd.DataFrame(
        {"gameweek": [1, 2, 3], "deadline_time": [d1, d2, d2 + pd.Timedelta(days=7)],
         "finished": [False, False, False]}
    )  # fmt: skip
    in_play = d1 + pd.Timedelta(hours=20)

    gameweek, cutoff, horizon = next_deadline(gameweeks, ForecastConfig(), in_play)
    assert (gameweek, horizon[0]) == (2, 2)
    assert cutoff == d1

    finished = gameweeks.assign(finished=[True, False, False])
    assert next_deadline(finished, ForecastConfig(), in_play)[1] == d2


def test_team_strength_is_league_average_before_the_forecast_seasons_first_kickoff(
    game_rules: GameRules,
) -> None:
    """REM-08: with no rows of the season being forecast, team strength is fitted on nothing. Last
    season's clubs are permanent codes; this season's fixtures are local ids (D-26)."""
    history = _sample_history()  # 2024/25 and 2025/26 only
    fitted = fit_as_of(
        history, pd.Timestamp("2026-08-01T00:00Z"), ForecastConfig(), game_rules, season="2026/27"
    )
    assert fitted.models.team_strength.attack == {}
    assert fitted.models.team_strength.home_advantage_matches == 0.0


def test_the_backtest_fits_the_live_model_through_fit_as_of(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REM-08 / PIPE-13: the backtest calls ``fit_as_of`` for the live model, and its fit predicts
    exactly what a live-style fit at the same deadline does."""
    import fpl_dof.forecast.fit as fit
    from fpl_dof.config.models import BacktestConfig
    from fpl_dof.forecast.backtest import OUTCOME_COLUMNS, deadlines_for, fold_rows, walk_forward
    from fpl_dof.forecast.xp_v1 import ComponentPredictor

    config = ForecastConfig()
    history = _sample_history()
    calls: list[tuple[pd.Timestamp, str | None, FittedForecastModel]] = []
    real = fit.fit_as_of

    def spy(*args: Any, **kwargs: Any) -> FittedForecastModel:
        fitted = real(*args, **kwargs)
        calls.append((args[1], kwargs.get("season"), fitted))
        return fitted

    monkeypatch.setattr(fit, "fit_as_of", spy)
    walk_forward(
        history,
        ComponentPredictor(config, game_rules),
        forecast_config=config,
        backtest_config=BacktestConfig(minimum_training_matches=1),
    )
    assert calls, "the backtest fitted the live model without fit_as_of"

    deadline, season, backtest_fit = calls[-1]
    assert season is not None, "the backtest fitted without naming the fold season"
    gameweek = next(gw for s, gw, d in deadlines_for(history) if d == deadline and s == season)
    rows = fold_rows(history, season, gameweek, deadline, config)
    visible = rows.drop(columns=list(OUTCOME_COLUMNS), errors="ignore")
    live_fit = real(history, deadline, config, game_rules, season=season)
    pd.testing.assert_series_equal(backtest_fit.predict(visible), live_fit.predict(visible))
