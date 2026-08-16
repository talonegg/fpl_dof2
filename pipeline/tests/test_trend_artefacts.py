"""The two trend artefacts — `history.json` and `fixtures.json`. E6-S3/S5/S8, DL-37.

Where being wrong here is invisible (DP-13), and therefore where the effort goes:

* **Absent versus zero.** A gameweek in which expected goals were not measured must not publish as
  a nil return. Nothing throws if it does; a chart just quietly draws a flat line for a player who
  was never measured, and it looks exactly like a player who did nothing.
* **The season filter.** ``player_id`` is reassigned between seasons and the silver table holds the
  backfilled ones. A series that spanned seasons would attribute one player's past to whoever
  inherited their number — R-10, in chart form, with nothing red anywhere.
* **The difficulty scale's anchors.** A monotone-looking scale that is not actually anchored where
  it claims produces a ticker that is subtly, plausibly wrong every week.
* **Doubles and blanks.** These come from the chip calendar's own fixture counting; the test is
  that they still agree once a club has two fixtures in a gameweek.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import pytest

from fpl_dof.config.models import FixtureTickerConfig, HistoryArtefactConfig
from fpl_dof.forecast.models import TeamStrengthModel
from fpl_dof.publish.contract import Contract, find_contracts_root
from fpl_dof.publish.fixtures import build_fixtures
from fpl_dof.publish.history import build_history
from fpl_dof.rules.models import GameRules


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract(root=find_contracts_root())


# --- history ------------------------------------------------------------------------------------


SEASON = "2026/27"


def _players() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"player_id": 1, "web_name": "Saka"},
            {"player_id": 2, "web_name": "Gabriel"},
        ]
    )


def _gameweek_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "season": SEASON,
        "gameweek": 1,
        "player_code": 1000,
        "player_id": 1,
        "position": "MID",
        "kickoff_time": pd.Timestamp("2026-08-21T19:00:00Z"),
        "minutes": 90,
        "goals_scored": 1,
        "assists": 0,
        "total_points": 8,
        "expected_goals": 0.42,
        "expected_assists": 0.15,
        "defensive_contribution": 4,
        "price": 9.5,
    }
    row.update(overrides)
    return row


def _prices(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _history(
    game_rules: GameRules,
    *,
    gameweeks: list[dict[str, Any]] | None = None,
    prices: list[dict[str, Any]] | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    return build_history(
        player_gameweek=pd.DataFrame(gameweeks) if gameweeks else None,
        price_history=_prices(prices) if prices else None,
        players=_players(),
        season=SEASON,
        rules=game_rules,
        config=HistoryArtefactConfig(ownership_change_threshold=threshold),
        contract_version=1,
    )


def test_an_empty_season_publishes_a_valid_empty_artefact(
    contract: Contract, game_rules: GameRules
) -> None:
    """Preseason is a normal state, not a failure (DL-20). The shape must still be there."""
    payload = _history(game_rules)
    contract.validate("history", payload)
    assert payload["gameweeks_played"] == 0
    assert payload["players"] == []
    assert payload["observed_from"] is None


def test_a_populated_season_validates(contract: Contract, game_rules: GameRules) -> None:
    payload = _history(
        game_rules,
        gameweeks=[_gameweek_row(), _gameweek_row(gameweek=2, total_points=2, goals_scored=0)],
        prices=[
            {
                "observed_at": pd.Timestamp("2026-08-10T00:00:00Z"),
                "player_id": 1,
                "price": 9.5,
                "selected_by_percent": 20.0,
            }
        ],
    )
    contract.validate("history", payload)
    assert payload["gameweeks_played"] == 2
    series = payload["players"][0]["gameweeks"]
    assert [point["gw"] for point in series] == [1, 2]


def test_prior_seasons_are_excluded(game_rules: GameRules) -> None:
    """`player_id` is reassigned between seasons, so a cross-season series is a mis-attribution."""
    payload = _history(
        game_rules,
        gameweeks=[
            _gameweek_row(season="2025/26", gameweek=30, total_points=99),
            _gameweek_row(),
        ],
    )
    series = payload["players"][0]["gameweeks"]
    assert [point["gw"] for point in series] == [1]
    assert 99 not in [point["pts"] for point in series]


def test_an_unmeasured_gameweek_omits_the_field_rather_than_publishing_zero(
    game_rules: GameRules,
) -> None:
    """Absent is not zero (DL-18): a chart must tell "not measured" from "did nothing"."""
    payload = _history(
        game_rules,
        gameweeks=[
            _gameweek_row(expected_goals=None, expected_assists=None, defensive_contribution=None)
        ],
    )
    point = payload["players"][0]["gameweeks"][0]
    assert "xg" not in point
    assert "xa" not in point
    assert "dc" not in point
    assert "dc_pts" not in point
    # A genuinely measured zero is still published, which is the other half of the distinction.
    zero = _history(game_rules, gameweeks=[_gameweek_row(expected_goals=0.0)])
    assert zero["players"][0]["gameweeks"][0]["xg"] == 0.0


def test_defensive_contribution_points_come_from_the_rules_not_a_literal(
    game_rules: GameRules,
) -> None:
    """Invariant 2. The threshold is per position and has changed between seasons."""
    from fpl_dof.rules.models import Position

    threshold = game_rules.scoring.defensive_contribution_threshold[Position.MID]
    award = game_rules.scoring.defensive_contribution[Position.MID]

    under = _history(game_rules, gameweeks=[_gameweek_row(defensive_contribution=threshold - 1)])
    over = _history(game_rules, gameweeks=[_gameweek_row(defensive_contribution=threshold)])
    assert under["players"][0]["gameweeks"][0]["dc_pts"] == 0
    assert over["players"][0]["gameweeks"][0]["dc_pts"] == award


def test_a_double_gameweek_is_two_entries_sharing_a_gameweek(game_rules: GameRules) -> None:
    payload = _history(
        game_rules,
        gameweeks=[
            _gameweek_row(gameweek=24, total_points=6),
            _gameweek_row(gameweek=24, total_points=9),
        ],
    )
    series = payload["players"][0]["gameweeks"]
    assert [point["gw"] for point in series] == [24, 24]
    assert sorted(point["pts"] for point in series) == [6, 9]


def _observation(day: int, price: float, owned: float) -> dict[str, Any]:
    return {
        "observed_at": pd.Timestamp(f"2026-08-{day:02d}T00:00:00Z"),
        "player_id": 1,
        "price": price,
        "selected_by_percent": owned,
    }


def test_unchanged_price_observations_are_compacted_away(game_rules: GameRules) -> None:
    payload = _history(
        game_rules,
        prices=[_observation(day, 9.5, 20.0) for day in range(10, 20)],
    )
    points = payload["players"][0]["prices"]
    # First and last only: nothing moved in between, and ten identical points is nine lies about
    # how much there was to say.
    assert [point["on"] for point in points] == ["2026-08-10", "2026-08-19"]


def test_a_price_change_is_always_emitted(game_rules: GameRules) -> None:
    payload = _history(
        game_rules,
        prices=[
            _observation(10, 9.5, 20.0),
            _observation(11, 9.6, 20.0),
            _observation(12, 9.6, 20.0),
        ],
    )
    assert [point["price"] for point in payload["players"][0]["prices"]] == [9.5, 9.6, 9.6]


def test_ownership_moves_below_the_threshold_are_compacted(game_rules: GameRules) -> None:
    payload = _history(
        game_rules,
        prices=[
            _observation(10, 9.5, 20.0),
            _observation(11, 9.5, 20.2),  # below the 0.5pp threshold
            _observation(12, 9.5, 21.0),  # above it
            _observation(13, 9.5, 21.0),
        ],
        threshold=0.5,
    )
    assert [point["owned"] for point in payload["players"][0]["prices"]] == [20.0, 21.0, 21.0]


def test_the_last_observation_always_lands(game_rules: GameRules) -> None:
    """A trend line that stops at the last change reads as a player who stopped existing."""
    payload = _history(
        game_rules,
        prices=[
            _observation(10, 9.5, 20.0),
            _observation(11, 9.6, 25.0),
            _observation(20, 9.6, 25.0),
        ],
    )
    assert payload["players"][0]["prices"][-1]["on"] == "2026-08-20"


def test_ownership_is_published_only_as_a_percentage(
    contract: Contract, game_rules: GameRules
) -> None:
    """The per-gameweek `selected_by` is a manager *count*; two scales invite a wrong chart."""
    payload = _history(
        game_rules, gameweeks=[_gameweek_row()], prices=[_observation(10, 9.5, 20.0)]
    )
    contract.validate("history", payload)
    assert "selected_by" not in payload["players"][0]["gameweeks"][0]
    assert payload["players"][0]["prices"][0]["owned"] == 20.0


# --- fixtures -----------------------------------------------------------------------------------


def _teams() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"team_id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"team_id": 2, "name": "Burnley", "short_name": "BUR"},
            {"team_id": 3, "name": "Chelsea", "short_name": "CHE"},
        ]
    )


def _fixture_rows(rows: list[tuple[int, int, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fixture_id": index + 1,
                "gameweek": gameweek,
                "kickoff_time": pd.Timestamp(f"2026-08-{20 + gameweek:02d}T14:00:00Z"),
                "home_team_id": home,
                "away_team_id": away,
                "finished": False,
            }
            for index, (gameweek, home, away) in enumerate(rows)
        ]
    )


def _strong_model() -> TeamStrengthModel:
    """Arsenal strong, Burnley weak, Chelsea average. Set directly rather than fitted.

    The mapping from ratings to a difficulty score is what is under test; fitting first would make
    a failure ambiguous between the fit and the scale.
    """
    return TeamStrengthModel(
        attack={1: 2.0, 2: 0.5, 3: 1.0},
        defence={1: 0.5, 2: 2.0, 3: 1.0},
        league_mean_goals=1.4,
        home_advantage=1.0,
    )


def _grid(
    model: TeamStrengthModel,
    rows: list[tuple[int, int, int]],
    *,
    to_gameweek: int = 1,
    config: FixtureTickerConfig | None = None,
) -> dict[str, Any]:
    return build_fixtures(
        fixtures=_fixture_rows(rows),
        teams=_teams(),
        model=model,
        from_gameweek=1,
        to_gameweek=to_gameweek,
        config=config or FixtureTickerConfig(),
        contract_version=1,
    )


def _entry(grid: dict[str, Any], team_id: int, gameweek: int) -> dict[str, Any]:
    team = next(t for t in grid["teams"] if t["team_id"] == team_id)
    week = next(w for w in team["gameweeks"] if w["gameweek"] == gameweek)
    entry: dict[str, Any] = week["fixtures"][0]
    return entry


def test_the_grid_validates(contract: Contract) -> None:
    contract.validate("fixtures", _grid(_strong_model(), [(1, 1, 2)]))


def test_a_league_average_fixture_scores_exactly_neutral() -> None:
    """The anchor the whole scale hangs on. Chelsea are average, and so is their opponent."""
    model = TeamStrengthModel(
        attack={3: 1.0}, defence={3: 1.0}, league_mean_goals=1.4, home_advantage=1.0
    )
    # Opponent 2 is unrated and so defaults to 1.0 — a genuinely average fixture both ways.
    entry = _entry(_grid(model, [(1, 3, 2)]), 3, 1)
    assert entry["difficulty"] == pytest.approx(3.0)
    assert entry["attack_difficulty"] == pytest.approx(3.0)
    assert entry["defence_difficulty"] == pytest.approx(3.0)


def test_a_good_fixture_is_easier_than_a_bad_one() -> None:
    grid = _grid(_strong_model(), [(1, 1, 2)])
    arsenal = _entry(grid, 1, 1)
    burnley = _entry(grid, 2, 1)
    assert arsenal["difficulty"] < 3.0 < burnley["difficulty"]
    # And the two sides of one fixture are mirror images, because the ratings are.
    assert arsenal["expected_goals_for"] == pytest.approx(burnley["expected_goals_against"])


def test_the_anchor_ratio_means_what_the_scale_says_it_means() -> None:
    """A club expected to score `anchor_ratio` x the league mean scores `minimum` for attack."""
    config = FixtureTickerConfig(difficulty_anchor_ratio=2.0)
    model = TeamStrengthModel(
        attack={1: 2.0}, defence={1: 1.0}, league_mean_goals=1.4, home_advantage=1.0
    )
    entry = _entry(_grid(model, [(1, 1, 2)], config=config), 1, 1)
    assert entry["expected_goals_for"] == pytest.approx(2.8)  # 2x the 1.4 league mean
    assert entry["attack_difficulty"] == pytest.approx(config.minimum)


def test_scores_are_clipped_to_the_published_scale() -> None:
    model = TeamStrengthModel(
        attack={1: 40.0, 2: 0.01}, defence={1: 0.01, 2: 40.0}, league_mean_goals=1.4
    )
    grid = _grid(model, [(1, 1, 2)])
    scale = grid["scale"]
    for team in grid["teams"]:
        for week in team["gameweeks"]:
            for entry in week["fixtures"]:
                for key in ("difficulty", "attack_difficulty", "defence_difficulty"):
                    assert scale["minimum"] <= entry[key] <= scale["maximum"]


def test_home_advantage_makes_the_same_pairing_easier_at_home() -> None:
    model = TeamStrengthModel(
        attack={1: 1.0, 3: 1.0},
        defence={1: 1.0, 3: 1.0},
        league_mean_goals=1.4,
        home_advantage=1.2,
    )
    grid = _grid(model, [(1, 1, 3), (2, 3, 1)], to_gameweek=2)
    at_home = _entry(grid, 1, 1)
    away = _entry(grid, 1, 2)
    assert at_home["difficulty"] < away["difficulty"]


def test_a_blank_gameweek_is_present_and_flagged() -> None:
    """The entry that would otherwise be invisible: a blank *is* the absence of a row."""
    grid = _grid(_strong_model(), [(1, 1, 2)])
    chelsea = next(t for t in grid["teams"] if t["team_id"] == 3)
    week = chelsea["gameweeks"][0]
    assert week["is_blank"] is True
    assert week["is_double"] is False
    assert week["fixtures"] == []
    # Nothing was scheduled, so there is no run to average — null, not a fabricated number.
    assert chelsea["mean_difficulty"] is None


def test_a_double_gameweek_is_flagged_and_carries_both_fixtures() -> None:
    grid = _grid(_strong_model(), [(1, 1, 2), (1, 3, 1)])
    arsenal = next(t for t in grid["teams"] if t["team_id"] == 1)
    week = arsenal["gameweeks"][0]
    assert week["is_double"] is True
    assert week["is_blank"] is False
    assert len(week["fixtures"]) == 2
    assert {f["opponent_id"] for f in week["fixtures"]} == {2, 3}


def test_doubles_and_blanks_agree_with_the_chip_calendar() -> None:
    """Reused rather than re-derived: two answers to the same question can disagree (DL-37)."""
    from fpl_dof.optimise.chips import gameweek_shapes

    rows = [(1, 1, 2), (1, 3, 1)]
    grid = _grid(_strong_model(), rows)
    shapes = gameweek_shapes(_fixture_rows(rows), [1, 2, 3])

    for team in grid["teams"]:
        week = team["gameweeks"][0]
        assert week["is_double"] == (shapes[1].fixtures_by_team[team["team_id"]] >= 2)
        assert week["is_blank"] == (shapes[1].fixtures_by_team[team["team_id"]] == 0)


def test_the_mean_run_ignores_blanks_rather_than_scoring_them() -> None:
    grid = _grid(_strong_model(), [(1, 1, 2)], to_gameweek=3)
    arsenal = next(t for t in grid["teams"] if t["team_id"] == 1)
    scored = [entry["difficulty"] for week in arsenal["gameweeks"] for entry in week["fixtures"]]
    assert arsenal["mean_difficulty"] == pytest.approx(sum(scored) / len(scored))
    assert len(arsenal["gameweeks"]) == 3  # every gameweek present, blanks included


def test_an_unfitted_model_degrades_visibly_rather_than_silently(contract: Contract) -> None:
    """Preseason: no ratings at all. Every fixture is neutral, `teams_rated` says why (DP-15)."""
    grid = _grid(TeamStrengthModel(home_advantage=1.0), [(1, 1, 2)])
    contract.validate("fixtures", grid)
    assert grid["model"]["teams_rated"] == 0
    assert _entry(grid, 1, 1)["difficulty"] == pytest.approx(grid["scale"]["neutral"])


def test_the_published_scale_describes_the_arithmetic_actually_used() -> None:
    """DP-10: the reader must be able to check the score against the stated formula."""
    config = FixtureTickerConfig(difficulty_anchor_ratio=3.0)
    model = _strong_model()
    entry = _entry(_grid(model, [(1, 1, 2)], config=config), 1, 1)

    k = (config.neutral - config.minimum) / math.log(config.difficulty_anchor_ratio)
    expected_attack = config.neutral - k * math.log(
        entry["expected_goals_for"] / model.league_mean_goals
    )
    assert entry["attack_difficulty"] == pytest.approx(
        max(config.minimum, min(config.maximum, expected_attack)), abs=0.01
    )
