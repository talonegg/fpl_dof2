"""The rules must come from the game, not from us.

These tests are the enforcement of Invariant 2. They assert the values the API actually publishes
for 2026/27 — including the ones that changed this season and would otherwise be silently wrong,
because they are the values a reasonable person would have transcribed from memory.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fpl_dof.config.models import RulesConfig, SupplementaryScoring
from fpl_dof.rules.build import RulesError, build_game_rules
from fpl_dof.rules.models import ApiRules, GameRules, Position, SquadRules


def test_squad_rules_come_from_the_api(game_rules: GameRules) -> None:
    squad = game_rules.squad
    assert squad.size == 15
    assert squad.starting_size == 11
    assert squad.budget == 100.0
    assert squad.club_limit == 3
    assert squad.composition == {
        Position.GKP: 2,
        Position.DEF: 5,
        Position.MID: 5,
        Position.FWD: 3,
    }
    assert squad.formation_min == {
        Position.GKP: 1,
        Position.DEF: 3,
        Position.MID: 2,
        Position.FWD: 1,
    }
    assert squad.formation_max == {
        Position.GKP: 1,
        Position.DEF: 5,
        Position.MID: 5,
        Position.FWD: 3,
    }
    assert squad.sell_on_fee == 0.5
    assert squad.sell_at_purchase_price is False


def test_goalkeeper_goals_are_worth_ten_this_season(game_rules: GameRules) -> None:
    """2026/27 change. The long-standing value was 6, and the fpl-rules skill still says 6.

    This is precisely why the scoring table is read from game_config rather than transcribed:
    the number a well-informed person would have written down by hand is wrong.
    """
    assert game_rules.scoring.goals_scored[Position.GKP] == 10
    assert game_rules.scoring.goals_scored[Position.DEF] == 6
    assert game_rules.scoring.goals_scored[Position.MID] == 5
    assert game_rules.scoring.goals_scored[Position.FWD] == 4


def test_defensive_contribution_now_includes_forwards(game_rules: GameRules) -> None:
    """Another 2026/27 change: in 2025/26 forwards were not eligible."""
    defcon = game_rules.scoring.defensive_contribution
    assert defcon[Position.DEF] == 2
    assert defcon[Position.MID] == 2
    assert defcon[Position.FWD] == 2
    assert defcon[Position.GKP] == 0


def test_the_rest_of_the_scoring_table_matches_the_api(game_rules: GameRules) -> None:
    scoring = game_rules.scoring
    assert (scoring.short_play, scoring.long_play) == (1, 2)
    assert scoring.assists == 3
    assert scoring.clean_sheets == {
        Position.GKP: 4,
        Position.DEF: 4,
        Position.MID: 1,
        Position.FWD: 0,
    }
    assert scoring.goals_conceded[Position.GKP] == -1
    assert scoring.goals_conceded[Position.DEF] == -1
    assert scoring.goals_conceded[Position.MID] == 0
    assert scoring.saves == 1
    assert scoring.penalties_saved == 5
    assert scoring.penalties_missed == -2
    assert scoring.yellow_cards == -1
    assert scoring.red_cards == -3
    assert scoring.own_goals == -2
    assert scoring.bonus == 1


def test_supplementary_values_are_flagged_as_configured(game_rules: GameRules) -> None:
    """Provenance is published, so the contract can say which numbers the game told us."""
    assert game_rules.derived["squad"] == "api"
    assert game_rules.derived["scoring.events"] == "api"
    assert game_rules.derived["scoring.thresholds"] == "config"
    assert game_rules.derived["transfers"] == "config"


def test_supplementary_values_are_the_ones_the_api_cannot_provide(game_rules: GameRules) -> None:
    scoring = game_rules.scoring
    assert scoring.long_play_minutes == 60
    assert scoring.saves_per_point == 3
    assert scoring.goals_conceded_per_point == 2
    assert scoring.bonus_points == (3, 2, 1)
    assert scoring.defensive_contribution_threshold[Position.DEF] == 10
    assert scoring.defensive_contribution_threshold[Position.MID] == 12
    assert game_rules.transfers.max_free_transfers == 5
    assert game_rules.transfers.extra_transfer_cost == -4


def test_snapshot_checksum_is_recorded_when_supplied(api_rules: ApiRules) -> None:
    rules = build_game_rules(api_rules, RulesConfig(), source_snapshot_sha256="a" * 64)
    assert rules.source_snapshot_sha256 == "a" * 64


def test_missing_position_in_supplementary_config_is_rejected(api_rules: ApiRules) -> None:
    config = RulesConfig(
        scoring=SupplementaryScoring(defensive_contribution_threshold={"DEF": 10, "MID": 12})
    )
    with pytest.raises(RulesError, match="missing positions"):
        build_game_rules(api_rules, config)


def test_an_award_without_a_threshold_is_rejected(api_rules: ApiRules) -> None:
    """Otherwise every forward would collect the DefCon award for doing nothing."""
    config = RulesConfig(
        scoring=SupplementaryScoring(
            defensive_contribution_threshold={"GKP": 0, "DEF": 10, "MID": 12, "FWD": 0}
        )
    )
    with pytest.raises(RulesError, match="no threshold"):
        build_game_rules(api_rules, config)


def test_a_threshold_without_an_award_is_rejected(api_rules: ApiRules) -> None:
    config = RulesConfig(
        scoring=SupplementaryScoring(
            defensive_contribution_threshold={"GKP": 5, "DEF": 10, "MID": 12, "FWD": 12}
        )
    )
    with pytest.raises(RulesError, match="threshold of 5"):
        build_game_rules(api_rules, config)


def test_a_short_appearance_cannot_beat_a_full_one(api_rules: ApiRules) -> None:
    broken = api_rules.model_copy(
        update={"scoring": api_rules.scoring.model_copy(update={"short_play": 5})}
    )
    with pytest.raises(RulesError, match="short appearance"):
        build_game_rules(broken, RulesConfig())


def test_legal_formations_are_derived_not_listed(game_rules: GameRules) -> None:
    formations = game_rules.squad.legal_formations()
    shapes = {(f[Position.DEF], f[Position.MID], f[Position.FWD]) for f in formations}
    assert (3, 4, 3) in shapes
    assert (5, 4, 1) in shapes
    assert (4, 4, 2) in shapes
    assert (2, 5, 3) not in shapes, "only 3-5 defenders are legal"
    for formation in formations:
        assert sum(formation.values()) == game_rules.squad.starting_size
        assert formation[Position.GKP] == 1


def test_rules_are_immutable(game_rules: GameRules) -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises on frozen assignment
        game_rules.squad.budget = 200.0  # type: ignore[misc]


def _squad_kwargs(game_rules: GameRules) -> dict[str, object]:
    return game_rules.squad.model_dump()


def test_composition_must_sum_to_squad_size(game_rules: GameRules) -> None:
    kwargs = _squad_kwargs(game_rules)
    kwargs["composition"] = dict.fromkeys(Position, 1)
    with pytest.raises(ValidationError, match="composition sums to"):
        SquadRules(**kwargs)


def test_formation_minimums_cannot_exceed_the_starting_xi(game_rules: GameRules) -> None:
    kwargs = _squad_kwargs(game_rules)
    kwargs["formation_min"] = dict.fromkeys(Position, 5)
    with pytest.raises(ValidationError, match="formation minimums"):
        SquadRules(**kwargs)


def test_formation_maximums_must_be_able_to_fill_the_starting_xi(game_rules: GameRules) -> None:
    kwargs = _squad_kwargs(game_rules)
    kwargs["formation_max"] = dict.fromkeys(Position, 1)
    with pytest.raises(ValidationError, match="cannot fill"):
        SquadRules(**kwargs)


def test_a_position_cannot_start_more_players_than_the_squad_holds(game_rules: GameRules) -> None:
    kwargs = _squad_kwargs(game_rules)
    kwargs["formation_max"] = {Position.GKP: 3, Position.DEF: 5, Position.MID: 5, Position.FWD: 3}
    with pytest.raises(ValidationError, match="exceeds the squad allocation"):
        SquadRules(**kwargs)


def test_appearance_points_respect_the_configured_boundary(game_rules: GameRules) -> None:
    scoring = game_rules.scoring
    assert scoring.appearance_points(0) == 0
    assert scoring.appearance_points(1) == scoring.short_play
    assert scoring.appearance_points(scoring.long_play_minutes - 1) == scoring.short_play
    assert scoring.appearance_points(scoring.long_play_minutes) == scoring.long_play
    assert scoring.appearance_points(90) == scoring.long_play
