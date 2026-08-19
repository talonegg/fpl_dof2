"""E9-S1 — the fixture-aware horizon scorer, and ``xp_v1`` on the live path. Closes D-25.

**The parity test is the one that matters.** Everything else here checks that the published frame
has the right shape; that one checks that the model in the shape is the model the backtest graded.
Until it existed, the pipeline could publish a number nobody had ever measured while a report next
to it described a different model entirely — the failure DP-13 calls invisible, because both halves
look correct read on their own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast import live
from fpl_dof.forecast.features import build_features
from fpl_dof.forecast.horizon import (
    fixture_index_from_fixtures,
    horizon_frame,
    week_forecast,
)
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.models import fit_components
from fpl_dof.forecast.xp_v0 import MODEL_NAME as XP_V0
from fpl_dof.forecast.xp_v1 import MODEL_NAME as XP_V1
from fpl_dof.forecast.xp_v1 import ComponentPredictor, team_matches
from fpl_dof.frames import as_float, as_int
from fpl_dof.optimise.squad import REQUIRED_COLUMNS
from fpl_dof.rules.models import GameRules
from fpl_dof.stages import forecast as forecast_stage

CONFIG = ForecastConfig()
SEASON = "2026/27"
POSITIONS = ("GKP", "DEF", "MID", "FWD")

#: Both arms of the parity test call the identical scoring function, so any difference is a bug in
#: the assembly rather than a numerical one. The tolerance is set by the published frame rounding
#: expected points to four decimal places, and by nothing else.
PARITY_TOLERANCE = 5e-5

PLAYED_GAMEWEEKS = 8
TEAMS = (1, 2, 3, 4)
PLAYERS_PER_TEAM = 4
FIRST_KICKOFF = pd.Timestamp("2026-08-15T14:00:00Z")

#: Team 4 has no fixture in the gameweek being decided. A blank must score nothing, not the average
#: of nothing.
BLANK_TEAM = 4


def _code(player_id: int) -> int:
    return 100_000 + player_id


def _player_gameweek(seed: int = 11) -> pd.DataFrame:
    """Per-gameweek rows for a small, complete league. What M1-M8 are fitted on."""
    rng = np.random.default_rng(seed)
    rows = []
    for team in TEAMS:
        for slot in range(PLAYERS_PER_TEAM):
            player_id = (team - 1) * PLAYERS_PER_TEAM + slot + 1
            for gameweek in range(1, PLAYED_GAMEWEEKS + 1):
                opponent = TEAMS[(team + gameweek) % len(TEAMS)]
                if opponent == team:
                    opponent = TEAMS[(team + gameweek + 1) % len(TEAMS)]
                minutes = int(rng.integers(0, 91))
                rows.append(
                    {
                        "season": SEASON,
                        "gameweek": gameweek,
                        "player_code": _code(player_id),
                        "player_id": player_id,
                        "web_name": f"P{player_id}",
                        "position": POSITIONS[slot % len(POSITIONS)],
                        "team_id": team,
                        "opponent_team_id": opponent,
                        "fixture_id": gameweek * 100 + team,
                        "kickoff_time": FIRST_KICKOFF + pd.Timedelta(days=7 * (gameweek - 1)),
                        "was_home": gameweek % 2 == 0,
                        "minutes": minutes,
                        "starts": 1 if minutes >= 60 else 0,
                        "goals_scored": int(rng.integers(0, 2)),
                        "assists": int(rng.integers(0, 2)),
                        "clean_sheets": int(rng.integers(0, 2)),
                        "goals_conceded": int(rng.integers(0, 3)),
                        "own_goals": 0,
                        "penalties_saved": 0,
                        "penalties_missed": 0,
                        "yellow_cards": 0,
                        "red_cards": 0,
                        "saves": int(rng.integers(0, 4)),
                        "bonus": 0,
                        "bps": int(rng.integers(0, 40)),
                        "defensive_contribution": int(rng.integers(0, 14)),
                        "tackles": 1,
                        "recoveries": 1,
                        "clearances_blocks_interceptions": 1,
                        "expected_goals": 0.1,
                        "expected_assists": 0.1,
                        "expected_goals_conceded": 1.0,
                        "price": 4.0 + slot * 0.5,
                        "selected_by": 1000,
                        "total_points": float(2.0 + slot),
                    }
                )
    return pd.DataFrame(rows)


def _players(history: pd.DataFrame) -> pd.DataFrame:
    """The published player record, plus one signing with no minutes at all this season."""
    latest = history.sort_values("kickoff_time").groupby("player_code").last().reset_index()
    rows = [
        {
            "player_id": as_int(row.player_id),
            "code": as_int(row.player_code),
            "web_name": str(row.web_name),
            "full_name": f"Player {as_int(row.player_id)}",
            "position": str(row.position),
            "team_id": as_int(row.team_id),
            "price": as_float(row.price),
            "status": "a",
            "chance_of_playing_next_round": None,
            "selected_by_percent": 5.0,
            "news": "",
        }
        for row in latest.itertuples()
    ]
    rows.append(
        {
            "player_id": 999,
            "code": 999_999,
            "web_name": "NewSigning",
            "full_name": "New Signing",
            "position": "FWD",
            "team_id": 1,
            "price": 7.0,
            "status": "a",
            "chance_of_playing_next_round": None,
            "selected_by_percent": 0.5,
            "news": "",
        }
    )
    return pd.DataFrame(rows)


def _gameweeks(total: int = 16) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "gameweek": gameweek,
                "name": f"Gameweek {gameweek}",
                "deadline_time": FIRST_KICKOFF
                + pd.Timedelta(days=7 * (gameweek - 1))
                - pd.Timedelta(hours=2),
                "finished": gameweek <= PLAYED_GAMEWEEKS,
                "is_next": gameweek == PLAYED_GAMEWEEKS + 1,
            }
            for gameweek in range(1, total + 1)
        ]
    )


def _fixtures(total: int = 16) -> pd.DataFrame:
    """A calendar. Team 4 is left out of the decided gameweek, so a blank is exercised."""
    rows = []
    fixture_id = 0
    for gameweek in range(1, total + 1):
        pairings = [(1, 2), (3, 4)] if gameweek % 2 else [(2, 3), (4, 1)]
        for home, away in pairings:
            if gameweek == PLAYED_GAMEWEEKS + 1 and BLANK_TEAM in (home, away):
                continue
            fixture_id += 1
            rows.append(
                {
                    "fixture_id": fixture_id,
                    "gameweek": gameweek,
                    "kickoff_time": FIRST_KICKOFF + pd.Timedelta(days=7 * (gameweek - 1)),
                    "home_team_id": home,
                    "away_team_id": away,
                    "home_difficulty": 3,
                    "away_difficulty": 3,
                    "finished": gameweek <= PLAYED_GAMEWEEKS,
                }
            )
    return pd.DataFrame(rows)


def _season_history(history: pd.DataFrame) -> pd.DataFrame:
    """A prior-season career table, so the ``xp_v0`` fallback has something to shrink toward."""
    rows = []
    for player_id in sorted(history["player_id"].unique()):
        rows.append(
            {
                "player_id": int(player_id),
                "season_name": "2025/26",
                "minutes": 2700,
                "starts": 30,
                "goals_scored": 6,
                "assists": 4,
                "clean_sheets": 10,
                "goals_conceded": 30,
                "own_goals": 0,
                "penalties_saved": 0,
                "penalties_missed": 0,
                "yellow_cards": 3,
                "red_cards": 0,
                "saves": 0,
                "bonus": 12,
                "bps": 500,
                "defensive_contribution": 250,
                "tackles": 40,
                "recoveries": 100,
                "clearances_blocks_interceptions": 160,
                "expected_goals": 5.0,
                "expected_assists": 3.5,
                "start_cost": 6.0,
                "end_cost": 6.5,
                "total_points": 150,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def history() -> pd.DataFrame:
    return _player_gameweek()


@pytest.fixture
def inputs(history: pd.DataFrame) -> ForecastInputs:
    return ForecastInputs(
        players=_players(history),
        teams=pd.DataFrame([{"team_id": team, "short_name": f"T{team}"} for team in TEAMS]),
        fixtures=_fixtures(),
        gameweeks=_gameweeks(),
        history=_season_history(history),
        player_gameweek=history,
    )


# --- the parity test -------------------------------------------------------------------------


def test_the_live_scorer_reproduces_the_backtest_under_league_average_opposition(
    history: pd.DataFrame, game_rules: GameRules
) -> None:
    """The shipped model and the graded model are one object, not two implementations.

    Both arms are given the *same fitted components* and the same features, and M2 is flattened to
    carry no team identity at all — no attack rating, no defence rating, no home advantage — which
    is exactly the league-average opposition the backtest scores every prediction under today. Any
    difference that survives that is a difference in the model, which is what D-25 was.
    """
    _, deadline, _ = live.next_deadline(_gameweeks(), CONFIG)
    past = history[history["kickoff_time"] < deadline]

    predictor = ComponentPredictor(CONFIG, game_rules)
    predictor.fit(live.training_set(history, deadline, CONFIG))
    models = predictor.models
    assert models is not None

    # League-average opposition, stated rather than approximated: with no ratings and no home
    # advantage, every fixture's expected goals is the league mean and every clean-sheet
    # probability is the Poisson zero on it.
    models.team_strength.attack.clear()
    models.team_strength.defence.clear()
    models.team_strength.home_advantage = 1.0

    features = build_features(
        past,
        as_of=deadline,
        config=CONFIG.features,
        positions=past[["player_code", "position"]],
    )
    graded = predictor.predict(features)

    gameweek = PLAYED_GAMEWEEKS + 1
    identity = (
        past.sort_values("kickoff_time").groupby("player_code").last()[["team_id", "position"]]
    )
    # Every club plays exactly one fixture, so the horizon scorer's blank and double handling is
    # not what is under test here — the single-gameweek number is.
    published = horizon_frame(
        features,
        identity=identity,
        horizon=[gameweek],
        fixtures={(team, gameweek): ((99, True),) for team in TEAMS},
        models=models,
        rules=game_rules,
        config=CONFIG,
    )

    expected = dict(zip(features["player_code"], graded, strict=True))
    assert len(published) == len(expected)
    for row in published.itertuples():
        assert row.xp_next == pytest.approx(expected[row.player_code], abs=PARITY_TOLERANCE)


def test_the_parity_test_would_notice_a_difference(
    history: pd.DataFrame, game_rules: GameRules
) -> None:
    """A parity test that cannot fail proves nothing. Real opposition must move the number."""
    _, deadline, _ = live.next_deadline(_gameweeks(), CONFIG)
    past = history[history["kickoff_time"] < deadline]
    models = fit_components(
        live.training_set(history, deadline, CONFIG),
        team_matches(past),
        CONFIG,
        game_rules,
    )
    models.team_strength.attack[1] = 2.0
    models.team_strength.defence[2] = 2.0

    features = build_features(
        past,
        as_of=deadline,
        config=CONFIG.features,
        positions=past[["player_code", "position"]],
    )
    row = features.iloc[0]
    easy = week_forecast(
        row, ((2, True),), team_id=1, models=models, rules=game_rules, config=CONFIG
    )
    hard = week_forecast(
        row, ((1, True),), team_id=2, models=models, rules=game_rules, config=CONFIG
    )
    assert easy.mean != pytest.approx(hard.mean, abs=PARITY_TOLERANCE)


# --- the published frame ---------------------------------------------------------------------


def test_xp_v1_is_the_model_the_pipeline_publishes(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    """E9-S1's acceptance criterion: the app's ranking is produced by xp_v1 (DL-46)."""
    result = forecast_stage.build(inputs, game_rules, CONFIG)
    assert result.model == XP_V1
    assert result.fallback_reason is None
    assert set(result.frame["model"]) == {XP_V1}


def test_the_published_frame_carries_everything_the_optimiser_requires(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    """The swap is only safe if the frame's shape is unchanged; the solver reads it by name."""
    frame = live.build_forecast(inputs, game_rules, CONFIG)
    assert set(REQUIRED_COLUMNS) <= set(frame.columns)
    for column in ("web_name", "full_name", "status", "news", "selected_by_percent", "confidence"):
        assert column in frame.columns
    assert set(frame["confidence"]) <= {"high", "medium", "low", "none"}


def test_every_value_carries_uncertainty(inputs: ForecastInputs, game_rules: GameRules) -> None:
    """Invariant 6: expected points always carry variance, not just a mean."""
    frame = live.build_forecast(inputs, game_rules, CONFIG)
    assert "xp_next_sd" in frame.columns
    assert "xp_horizon_sd" in frame.columns
    assert (frame["xp_next_sd"] >= 0).all()
    scoring = frame[frame["xp_next"] > 0]
    assert not scoring.empty
    assert (scoring["xp_next_sd"] > 0).all()


def test_the_decomposition_sums_to_the_next_gameweek_total(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    frame = live.build_forecast(inputs, game_rules, CONFIG)
    components = [column for column in frame.columns if column.startswith("component_")]
    assert components
    assert np.allclose(frame[components].sum(axis=1), frame["xp_next"], atol=1e-3)


def test_a_blank_gameweek_scores_nothing(inputs: ForecastInputs, game_rules: GameRules) -> None:
    frame = live.build_forecast(inputs, game_rules, CONFIG)
    blank = frame[frame["team_id"] == BLANK_TEAM]
    assert not blank.empty
    assert (blank["xp_next"] == 0).all()
    # And the horizon still scores, because the blank is one gameweek and not the season.
    assert (blank["xp_horizon"] > 0).any()


def test_a_player_with_no_minutes_this_season_still_gets_a_row(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    """A new signing must be priced off the position prior, not dropped and not zeroed (DP-15)."""
    frame = live.build_forecast(inputs, game_rules, CONFIG)
    assert len(frame) == len(inputs.players)
    signing = frame[frame["player_id"] == 999]
    assert len(signing) == 1
    assert float(signing.iloc[0]["xp_next"]) > 0
    assert signing.iloc[0]["confidence"] == "none"


def test_an_injured_player_is_priced_at_zero(inputs: ForecastInputs, game_rules: GameRules) -> None:
    players = inputs.players.copy()
    players.loc[players["player_id"] == 1, "status"] = "i"
    frame = live.build_forecast(
        ForecastInputs(
            players=players,
            teams=inputs.teams,
            fixtures=inputs.fixtures,
            gameweeks=inputs.gameweeks,
            history=inputs.history,
            player_gameweek=inputs.player_gameweek,
        ),
        game_rules,
        CONFIG,
    )
    injured = frame[frame["player_id"] == 1].iloc[0]
    assert injured["start_probability"] == pytest.approx(0.0)
    assert injured["xp_next"] == pytest.approx(0.0, abs=1e-9)


def test_the_fixture_index_reads_the_calendar_not_the_players() -> None:
    """A blank is an absence in the calendar. Nothing about a player may create or remove one."""
    gameweek = PLAYED_GAMEWEEKS + 1
    index = fixture_index_from_fixtures(_fixtures(), [gameweek])
    # Dropping team 4's fixture blanks its opponent too, which is exactly how a real blank works.
    assert (BLANK_TEAM, gameweek) not in index
    playing = {team for team, week in index if week == gameweek}
    assert playing == {1, 2}
    for team in playing:
        assert len(index[(team, gameweek)]) == 1


def test_a_double_gameweek_adds_both_fixtures(history: pd.DataFrame, game_rules: GameRules) -> None:
    _, deadline, _ = live.next_deadline(_gameweeks(), CONFIG)
    past = history[history["kickoff_time"] < deadline]
    models = fit_components(
        live.training_set(history, deadline, CONFIG), team_matches(past), CONFIG, game_rules
    )
    features = build_features(
        past,
        as_of=deadline,
        config=CONFIG.features,
        positions=past[["player_code", "position"]],
    )
    row = features.iloc[0]
    single = week_forecast(
        row, ((2, True),), team_id=1, models=models, rules=game_rules, config=CONFIG
    )
    double = week_forecast(
        row, ((2, True), (3, False)), team_id=1, models=models, rules=game_rules, config=CONFIG
    )
    blank = week_forecast(row, (), team_id=1, models=models, rules=game_rules, config=CONFIG)
    assert blank.mean == 0.0 and blank.variance == 0.0
    assert double.mean > single.mean
    assert double.variance > single.variance


# --- the cold-start fallback ------------------------------------------------------------------


def test_too_little_history_falls_back_to_xp_v0_with_a_stated_reason(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    """DP-15: degrade, never break — and never silently (DL-46)."""
    minimum = CONFIG.published.cold_start_minimum_gameweeks
    assert inputs.player_gameweek is not None
    thin = inputs.player_gameweek[inputs.player_gameweek["gameweek"] < minimum]
    gameweeks = _gameweeks()
    gameweeks["finished"] = gameweeks["gameweek"] < minimum

    result = forecast_stage.build(
        ForecastInputs(
            players=inputs.players,
            teams=inputs.teams,
            fixtures=inputs.fixtures,
            gameweeks=gameweeks,
            history=inputs.history,
            player_gameweek=thin,
        ),
        game_rules,
        CONFIG,
    )
    assert result.model == XP_V0
    assert result.fallback_reason is not None
    assert str(minimum) in result.fallback_reason
    assert set(result.frame["model"]) == {XP_V0}


def test_no_per_gameweek_table_at_all_falls_back(
    inputs: ForecastInputs, game_rules: GameRules
) -> None:
    """Preseason. There is no current-season history because the season has not happened."""
    result = forecast_stage.build(
        ForecastInputs(
            players=inputs.players,
            teams=inputs.teams,
            fixtures=inputs.fixtures,
            gameweeks=_gameweeks().assign(finished=False),
            history=inputs.history,
            player_gameweek=None,
        ),
        game_rules,
        CONFIG,
    )
    assert result.model == XP_V0
    assert result.fallback_reason is not None


def test_completed_gameweeks_counts_kickoffs_not_rows(history: pd.DataFrame) -> None:
    """Invariant 5: the boundary is the kickoff, and it is the same one features are stamped on."""
    before = FIRST_KICKOFF + pd.Timedelta(days=7 * 3)
    assert live.completed_gameweeks(history, before=before) == 3
    assert live.completed_gameweeks(history, before=FIRST_KICKOFF) == 0
    assert live.completed_gameweeks(None, before=before) == 0
