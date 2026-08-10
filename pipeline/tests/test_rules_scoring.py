from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.scoring import PointsBreakdown, StatLine, points_for

ALL_POSITIONS = list(Position)


def test_a_player_who_did_not_appear_scores_nothing(game_rules: GameRules) -> None:
    """Not even the penalties they could not have incurred."""
    stats = StatLine(minutes=0, yellow_cards=1, own_goals=1, goals_conceded=4)
    for position in ALL_POSITIONS:
        result = points_for(stats, position, game_rules)
        assert result.total == 0
        assert result.components == {}


@pytest.mark.parametrize(
    ("minutes", "expected_component"),
    [(1, "short"), (59, "short"), (60, "long"), (90, "long")],
)
def test_appearance_points_switch_at_the_configured_boundary(
    game_rules: GameRules, minutes: int, expected_component: str
) -> None:
    result = points_for(StatLine(minutes=minutes), Position.MID, game_rules)
    expected = (
        game_rules.scoring.short_play
        if expected_component == "short"
        else game_rules.scoring.long_play
    )
    assert result["appearance"] == expected


def test_a_goalkeeper_goal_is_worth_ten(game_rules: GameRules) -> None:
    result = points_for(StatLine(minutes=90, goals_scored=1), Position.GKP, game_rules)
    assert result["goals"] == 10


def test_goal_value_differs_by_position(game_rules: GameRules) -> None:
    stats = StatLine(minutes=90, goals_scored=1)
    scored = {p: points_for(stats, p, game_rules)["goals"] for p in ALL_POSITIONS}
    assert scored[Position.GKP] > scored[Position.DEF] > scored[Position.MID] > scored[Position.FWD]


def test_a_clean_sheet_requires_a_full_appearance(game_rules: GameRules) -> None:
    full = points_for(StatLine(minutes=90, clean_sheet=True), Position.DEF, game_rules)
    partial = points_for(StatLine(minutes=45, clean_sheet=True), Position.DEF, game_rules)
    assert full["clean_sheet"] == 4
    assert partial["clean_sheet"] == 0


def test_forwards_get_nothing_for_a_clean_sheet(game_rules: GameRules) -> None:
    result = points_for(StatLine(minutes=90, clean_sheet=True), Position.FWD, game_rules)
    assert "clean_sheet" not in result.components


@pytest.mark.parametrize(
    ("conceded", "expected"), [(0, 0), (1, 0), (2, -1), (3, -1), (4, -2), (5, -2)]
)
def test_goals_conceded_are_charged_per_two(
    game_rules: GameRules, conceded: int, expected: int
) -> None:
    result = points_for(StatLine(minutes=90, goals_conceded=conceded), Position.DEF, game_rules)
    assert result["goals_conceded"] == expected


def test_midfielders_are_not_charged_for_goals_conceded(game_rules: GameRules) -> None:
    result = points_for(StatLine(minutes=90, goals_conceded=6), Position.MID, game_rules)
    assert "goals_conceded" not in result.components


@pytest.mark.parametrize(("saves", "expected"), [(0, 0), (2, 0), (3, 1), (5, 1), (6, 2), (9, 3)])
def test_saves_are_paid_per_three(game_rules: GameRules, saves: int, expected: int) -> None:
    result = points_for(StatLine(minutes=90, saves=saves), Position.GKP, game_rules)
    assert result["saves"] == expected


@pytest.mark.parametrize(
    ("position", "actions", "expected"),
    [
        (Position.DEF, 9, 0),
        (Position.DEF, 10, 2),
        (Position.DEF, 25, 2),
        (Position.MID, 11, 0),
        (Position.MID, 12, 2),
        (Position.FWD, 12, 2),
        (Position.GKP, 40, 0),
    ],
)
def test_defensive_contribution_is_all_or_nothing_and_capped(
    game_rules: GameRules, position: Position, actions: int, expected: int
) -> None:
    """Doubling the threshold does not double the award."""
    result = points_for(StatLine(minutes=90, defensive_actions=actions), position, game_rules)
    assert result["defensive_contribution"] == expected


def test_negatives_are_applied(game_rules: GameRules) -> None:
    stats = StatLine(minutes=90, yellow_cards=1, red_cards=1, own_goals=1, penalties_missed=1)
    result = points_for(stats, Position.FWD, game_rules)
    assert result["yellow_cards"] == -1
    assert result["red_cards"] == -3
    assert result["own_goals"] == -2
    assert result["penalties_missed"] == -2


def test_a_penalty_save_is_worth_five(game_rules: GameRules) -> None:
    result = points_for(StatLine(minutes=90, penalties_saved=1), Position.GKP, game_rules)
    assert result["penalties_saved"] == 5


def test_bonus_passes_through(game_rules: GameRules) -> None:
    result = points_for(StatLine(minutes=90, bonus=3), Position.MID, game_rules)
    assert result["bonus"] == 3


def test_missing_components_read_as_zero(game_rules: GameRules) -> None:
    result = points_for(StatLine(minutes=90), Position.MID, game_rules)
    assert result["goals"] == 0
    assert isinstance(result, PointsBreakdown)


def test_a_realistic_haul_adds_up(game_rules: GameRules) -> None:
    """A defender: 90 minutes, a goal, a clean sheet, DefCon, three bonus."""
    stats = StatLine(minutes=90, goals_scored=1, clean_sheet=True, defensive_actions=12, bonus=3)
    result = points_for(stats, Position.DEF, game_rules)
    assert result.components == {
        "appearance": 2,
        "goals": 6,
        "clean_sheet": 4,
        "defensive_contribution": 2,
        "bonus": 3,
    }
    assert result.total == 17


@given(
    minutes=st.integers(min_value=0, max_value=90),
    goals=st.integers(min_value=0, max_value=4),
    assists=st.integers(min_value=0, max_value=4),
    conceded=st.integers(min_value=0, max_value=9),
    saves=st.integers(min_value=0, max_value=12),
    actions=st.integers(min_value=0, max_value=30),
    bonus=st.integers(min_value=0, max_value=3),
    position=st.sampled_from(ALL_POSITIONS),
)
def test_total_is_always_the_sum_of_its_parts(
    game_rules: GameRules,
    minutes: int,
    goals: int,
    assists: int,
    conceded: int,
    saves: int,
    actions: int,
    bonus: int,
    position: Position,
) -> None:
    """The decomposition is the explanation. If it does not add up, the explanation is a lie."""
    stats = StatLine(
        minutes=minutes,
        goals_scored=goals,
        assists=assists,
        goals_conceded=conceded,
        saves=saves,
        defensive_actions=actions,
        bonus=bonus,
    )
    result = points_for(stats, position, game_rules)
    assert result.total == sum(result.components.values())


@given(
    extra=st.integers(min_value=1, max_value=5),
    position=st.sampled_from(ALL_POSITIONS),
)
def test_scoring_another_goal_never_reduces_the_total(
    game_rules: GameRules, extra: int, position: Position
) -> None:
    base = points_for(StatLine(minutes=90, goals_scored=1), position, game_rules)
    more = points_for(StatLine(minutes=90, goals_scored=1 + extra), position, game_rules)
    assert more.total >= base.total
