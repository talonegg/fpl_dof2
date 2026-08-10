"""E1-S2 — the transfer optimiser, and E1-S3 — team selection.

The acceptance criteria that carry real risk are the negative ones. "Recommends a good transfer" is
easy to satisfy and easy to check by eye. **"Never recommends a hit whose expected gain is below the
4-point cost"** is the one that costs points every week if it is subtly wrong, and it is invisible
because the recommendation always looks reasonable.
"""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fpl_dof.config.models import EntryConfig, OptimiserConfig, TransferConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.optimise.transfer import hit_cost, recommend_transfers
from fpl_dof.rules.legality import Squad, SquadPlayer, validate_squad
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.squad.selection import Candidate, SelectionError, select_team, verify
from fpl_dof.squad.state import SquadState, load_squad_state
from squads import COMPOSITION, legal_declaration
from squads import players as _players


def _forecast(players: pd.DataFrame, xp: dict[int, float] | None = None) -> pd.DataFrame:
    """The forecast columns the optimisers require, with a controllable expected-points column."""
    frame = players.copy()
    overrides = xp or {}
    frame["xp_next"] = [overrides.get(int(pid), 2.0) for pid in frame["player_id"]]
    frame["xp_horizon"] = frame["xp_next"] * 6
    frame["xp_next_sd"] = 1.0
    frame["xp_horizon_sd"] = 2.0
    frame["start_probability"] = 0.9
    frame["start_floor"] = 0.6
    frame["confidence"] = "medium"
    return frame


def _state(game_rules: GameRules, players: pd.DataFrame, bank: float = 0.0) -> SquadState:
    return load_squad_state(
        entry_config=EntryConfig(
            team_id=1, declared_squad=legal_declaration(players), declared_bank=bank
        ),
        rules=game_rules,
        players=players,
        next_gameweek=2,
    )


CONFIG = OptimiserConfig(enforce_start_probability_floor=False)


def test_doing_nothing_is_always_an_option_with_a_number_on_it(game_rules: GameRules) -> None:
    """FR-24. The roll is ranked, not implied by the absence of a recommendation."""
    players = _players()
    state = _state(game_rules, players)
    recommendation = recommend_transfers(
        _forecast(players), state, game_rules, TransferConfig(), CONFIG
    )

    assert any(option.transfers == 0 for option in recommendation.options)
    assert recommendation.roll.transfers == 0
    assert recommendation.roll.hit_points == 0
    assert recommendation.rationale


def test_an_equal_squad_is_left_alone(game_rules: GameRules) -> None:
    """Every player is worth the same, so no transfer can gain anything. Rolling must win."""
    players = _players()
    state = _state(game_rules, players)
    recommendation = recommend_transfers(
        _forecast(players), state, game_rules, TransferConfig(), CONFIG
    )

    assert recommendation.is_roll()
    assert recommendation.recommended.transfers == 0


def test_a_clearly_better_player_is_bought_with_a_free_transfer(game_rules: GameRules) -> None:
    players = _players()
    state = _state(game_rules, players)
    held = state.player_ids()
    target = next(
        as_int(row.player_id)
        for row in players.itertuples()
        if as_int(row.player_id) not in held and str(row.position) == "MID"
    )

    forecast = _forecast(players, {target: 20.0})
    recommendation = recommend_transfers(forecast, state, game_rules, TransferConfig(), CONFIG)

    assert recommendation.recommended.transfers == 1
    assert target in recommendation.recommended.squad_after
    assert recommendation.recommended.gain_over(recommendation.roll) > 0


def test_a_marginal_gain_never_justifies_a_hit(game_rules: GameRules) -> None:
    """The acceptance criterion that costs points every week if it is wrong.

    One free transfer, and two candidates each worth a little more than what they replace. Taking
    both costs 4 points; the gain from the second is far below that, so the second must not be
    taken — even though it improves the squad.
    """
    players = _players()
    state = _state(game_rules, players)
    assert state.free_transfers == 1
    held = state.player_ids()
    spare = [
        as_int(row.player_id)
        for row in players.itertuples()
        if as_int(row.player_id) not in held and str(row.position) == "MID"
    ][:2]

    # Held midfielders are worth 2.0; these are worth 2.5. Two transfers gain 1.0 and cost 4.
    forecast = _forecast(players, dict.fromkeys(spare, 2.5))
    recommendation = recommend_transfers(forecast, state, game_rules, TransferConfig(), CONFIG)

    assert recommendation.recommended.transfers <= state.free_transfers
    two = next((o for o in recommendation.options if o.transfers == 2), None)
    assert two is not None
    assert two.hit_points == -4
    assert two.gain_over(recommendation.roll) < 0, "the hit must be priced into the ranking"


def test_a_large_gain_does_justify_a_hit(game_rules: GameRules) -> None:
    players = _players()
    state = _state(game_rules, players)
    held = state.player_ids()
    spare = [
        as_int(row.player_id)
        for row in players.itertuples()
        if as_int(row.player_id) not in held and str(row.position) == "MID"
    ][:2]

    forecast = _forecast(players, dict.fromkeys(spare, 30.0))
    recommendation = recommend_transfers(forecast, state, game_rules, TransferConfig(), CONFIG)

    assert recommendation.recommended.transfers == 2
    assert recommendation.recommended.hit_points == -4
    assert recommendation.recommended.gain_over(recommendation.roll) > 4


def test_the_margin_setting_only_restrains_transfers_that_cost_a_hit(
    game_rules: GameRules,
) -> None:
    """``min_gain_over_hit`` is the honest knob: how much to distrust a small forecast difference.

    It applies to hits and to nothing else, deliberately. A free transfer that improves the squad
    costs nothing to make, so demanding a margin from it would leave value on the table for no
    reason — the margin exists to price *doubt about the forecast against a known 4-point cost*.
    """
    players = _players()
    state = _state(game_rules, players)
    held = state.player_ids()
    spare = [
        as_int(row.player_id)
        for row in players.itertuples()
        if as_int(row.player_id) not in held and str(row.position) == "MID"
    ][:2]
    # The captain doubles the best player, so the *first* transfer captures a bonus the second
    # cannot. Against a held value of 2.0, the second transfer only pays its own hit once the
    # target is worth more than 6.0 — which is why 5.0 would leave one transfer ahead of two.
    forecast = _forecast(players, dict.fromkeys(spare, 10.0))

    lenient = recommend_transfers(
        forecast, state, game_rules, TransferConfig(min_gain_over_hit=0.0), CONFIG
    )
    strict = recommend_transfers(
        forecast, state, game_rules, TransferConfig(min_gain_over_hit=50.0), CONFIG
    )

    assert state.free_transfers == 1
    assert lenient.recommended.transfers == 2
    assert lenient.recommended.hit_points == -4
    assert strict.recommended.transfers == 1
    assert strict.recommended.hit_points == 0


def test_every_option_leaves_a_legal_squad(game_rules: GameRules) -> None:
    """Checked against the E0-S4 validator rather than trusted (DP-13)."""
    players = _players()
    state = _state(game_rules, players, bank=5.0)
    forecast = _forecast(players, {31: 12.0, 32: 11.0})
    recommendation = recommend_transfers(forecast, state, game_rules, TransferConfig(), CONFIG)

    indexed = players.set_index("player_id")
    for option in recommendation.options:
        squad = _rebuild(option.squad_after, option.starting, indexed, state, game_rules)
        assert validate_squad(squad, game_rules, budget=state.budget(game_rules)) == []


def _rebuild(
    squad_after: tuple[int, ...],
    starting: tuple[int, ...],
    indexed: pd.DataFrame,
    state: SquadState,
    rules: GameRules,
) -> Squad:
    selling = {p.player_id: p.selling_price(rules) for p in state.players}
    return Squad(
        players=tuple(
            SquadPlayer(
                player_id=pid,
                position=Position(str(indexed.loc[pid, "position"])),
                team_id=as_int(indexed.loc[pid, "team_id"]),
                price=selling.get(pid, as_float(indexed.loc[pid, "price"])),
            )
            for pid in squad_after
        ),
        starting=tuple(starting),
    )


@pytest.mark.parametrize(
    ("transfers", "free", "expected"),
    [(0, 1, 0), (1, 1, 0), (2, 1, -4), (3, 1, -8), (2, 2, 0), (5, 5, 0), (6, 5, -4)],
)
def test_hit_arithmetic(transfers: int, free: int, expected: int, game_rules: GameRules) -> None:
    assert hit_cost(transfers, free, game_rules) == expected


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(free=st.integers(min_value=1, max_value=5), made=st.integers(min_value=0, max_value=8))
def test_a_hit_is_never_charged_for_a_free_transfer(
    free: int, made: int, game_rules: GameRules
) -> None:
    cost = hit_cost(made, free, game_rules)
    assert cost <= 0
    if made <= free:
        assert cost == 0
    else:
        assert cost == (made - free) * game_rules.transfers.extra_transfer_cost


# --- E1-S3 team selection ---------------------------------------------------------------------


def _candidates(
    players: pd.DataFrame, squad: tuple[int, ...], xp: dict[int, float]
) -> dict[int, Candidate]:
    indexed = players.set_index("player_id")
    return {
        pid: Candidate(
            player_id=pid,
            position=Position(str(indexed.loc[pid, "position"])),
            expected_points=xp.get(pid, 2.0),
            start_probability=1.0,
            web_name=str(indexed.loc[pid, "web_name"]),
        )
        for pid in squad
    }


def test_selection_produces_a_legal_xi_and_a_captain(game_rules: GameRules) -> None:
    players = _players()
    squad = tuple(pick.player_id for pick in legal_declaration(players))
    selection = select_team(_candidates(players, squad, {}), game_rules)

    assert len(selection.starting) == game_rules.squad.starting_size
    assert selection.captain in selection.starting
    assert selection.vice_captain in selection.starting
    assert selection.captain != selection.vice_captain
    assert len(selection.bench_order) == 3
    assert selection.reserve_goalkeeper is not None


def test_the_captain_is_the_highest_expected_scorer(game_rules: GameRules) -> None:
    players = _players()
    squad = tuple(pick.player_id for pick in legal_declaration(players))
    star = squad[6]
    selection = select_team(_candidates(players, squad, {star: 99.0}), game_rules)

    assert selection.captain == star
    assert selection.vice_captain != star


def test_bench_order_prefers_reliability_over_upside(game_rules: GameRules) -> None:
    """A substitute only scores if someone ahead fails to play, so P(plays) x xP is the ranking.

    Ordering the bench by expected points alone puts an explosive doubtful player above a dependable
    one, which is backwards: the bench is insurance, and insurance that might not turn up is worth
    less than insurance that will.
    """
    players = _players()
    squad = tuple(pick.player_id for pick in legal_declaration(players))
    indexed = players.set_index("player_id")
    by_position: dict[Position, list[int]] = {position: [] for position in Position}
    for pid in squad:
        by_position[Position(str(indexed.loc[pid, "position"]))].append(pid)

    # Force the bench composition rather than hoping for it: start 1-4-4-2, which benches exactly
    # one defender, one midfielder and one forward alongside the reserve keeper.
    starters = (
        by_position[Position.GKP][:1]
        + by_position[Position.DEF][:4]
        + by_position[Position.MID][:4]
        + by_position[Position.FWD][:2]
    )
    benched_outfield = (
        by_position[Position.DEF][4:]
        + by_position[Position.MID][4:]
        + by_position[Position.FWD][2:]
    )
    assert len(starters) == 11 and len(benched_outfield) == 3

    flaky, steady, filler = benched_outfield
    candidates = {
        pid: Candidate(pid, Position(str(indexed.loc[pid, "position"])), 50.0, 1.0)
        for pid in starters
    }
    # Both substitutes are far below any starter, so neither can displace one. Between them, the
    # flaky player scores twice as much when they play and play a tenth as often.
    candidates[flaky] = Candidate(flaky, Position(str(indexed.loc[flaky, "position"])), 4.0, 0.1)
    candidates[steady] = Candidate(steady, Position(str(indexed.loc[steady, "position"])), 2.0, 1.0)
    candidates[filler] = Candidate(filler, Position(str(indexed.loc[filler, "position"])), 0.1, 0.1)
    candidates[by_position[Position.GKP][1]] = Candidate(
        by_position[Position.GKP][1], Position.GKP, 0.1, 1.0
    )

    selection = select_team(candidates, game_rules)
    order = list(selection.bench_order)
    assert set(order) == {flaky, steady, filler}
    assert order.index(steady) < order.index(flaky), (
        "the dependable substitute must come on first: ranking the bench by expected points alone "
        "puts the higher-scoring but unlikely player ahead, which is backwards for insurance"
    )


def test_selection_is_checked_against_the_shared_validator(game_rules: GameRules) -> None:
    players = _players()
    squad = tuple(pick.player_id for pick in legal_declaration(players))
    indexed = players.set_index("player_id")
    selection = select_team(_candidates(players, squad, {}), game_rules)

    members = tuple(
        SquadPlayer(
            player_id=pid,
            position=Position(str(indexed.loc[pid, "position"])),
            team_id=as_int(indexed.loc[pid, "team_id"]),
            price=as_float(indexed.loc[pid, "price"]),
        )
        for pid in squad
    )
    verify(selection, members, game_rules)  # raises if illegal


def test_selection_says_so_when_the_floor_makes_an_xi_impossible(game_rules: GameRules) -> None:
    players = _players()
    squad = tuple(pick.player_id for pick in legal_declaration(players))
    indexed = players.set_index("player_id")
    candidates = {
        pid: Candidate(
            player_id=pid,
            position=Position(str(indexed.loc[pid, "position"])),
            expected_points=2.0,
            start_probability=0.1,
        )
        for pid in squad
    }

    with pytest.raises(SelectionError, match="start-probability floor"):
        select_team(candidates, game_rules, start_probability_floor=0.6)


def test_composition_is_the_squad_the_rules_publish() -> None:
    """Guards the test helper itself: if COMPOSITION drifts, every test above tests nothing."""
    assert sum(count for _, count in COMPOSITION) == 15
