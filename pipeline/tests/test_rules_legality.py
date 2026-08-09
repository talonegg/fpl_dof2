"""Legality: the module everything else trusts.

The property tests are the point. E0-S4 requires that *any* legal squad validates and *any*
perturbation of a legal squad fails, because the optimiser is checked against this validator rather
than assumed correct — so a validator that is merely right about the cases I thought of is not
enough.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fpl_dof.rules.legality import (
    Squad,
    SquadPlayer,
    ViolationCode,
    is_legal,
    selling_price,
    validate_squad,
)
from fpl_dof.rules.models import GameRules, Position

TEAM_COUNT = 20


def legal_squad(rules: GameRules, *, price: float = 4.5) -> Squad:
    """A minimal legal squad: correct composition, cheap, and spread across clubs."""
    players: list[SquadPlayer] = []
    next_id = 1
    team_slots = [team for team in range(1, TEAM_COUNT + 1) for _ in range(rules.squad.club_limit)]
    slot = 0
    for position in Position:
        for _ in range(rules.squad.composition[position]):
            players.append(
                SquadPlayer(
                    player_id=next_id,
                    position=position,
                    team_id=team_slots[slot],
                    price=price,
                )
            )
            next_id += 1
            slot += 1
    return Squad(players=tuple(players))


def with_lineup(squad: Squad, rules: GameRules) -> Squad:
    """Add a legal starting XI, captain and vice to a legal squad."""
    formation = rules.squad.legal_formations()[0]
    starting: list[int] = []
    for position, count in formation.items():
        matching = [p.player_id for p in squad.players if p.position is position]
        starting.extend(matching[:count])
    bench = [
        p.player_id
        for p in squad.players
        if p.player_id not in starting and p.position is not Position.GKP
    ]
    return Squad(
        players=squad.players,
        starting=tuple(starting),
        captain=starting[-1],
        vice_captain=starting[-2],
        bench_order=tuple(bench),
    )


def test_the_baseline_squad_is_legal(game_rules: GameRules) -> None:
    assert validate_squad(legal_squad(game_rules), game_rules) == []
    assert is_legal(legal_squad(game_rules), game_rules)


def test_a_full_lineup_is_legal(game_rules: GameRules) -> None:
    squad = with_lineup(legal_squad(game_rules), game_rules)
    assert validate_squad(squad, game_rules) == []


def _codes(squad: Squad, rules: GameRules, **kwargs: float) -> set[ViolationCode]:
    return {v.code for v in validate_squad(squad, rules, **kwargs)}


def test_too_few_players_is_reported(game_rules: GameRules) -> None:
    squad = legal_squad(game_rules)
    short = Squad(players=squad.players[:-1])
    codes = _codes(short, game_rules)
    assert ViolationCode.SQUAD_SIZE in codes
    assert ViolationCode.COMPOSITION in codes


def test_wrong_composition_is_reported_per_position(game_rules: GameRules) -> None:
    squad = legal_squad(game_rules)
    swapped = list(squad.players)
    swapped[0] = SquadPlayer(swapped[0].player_id, Position.MID, swapped[0].team_id, 4.5)
    violations = validate_squad(Squad(players=tuple(swapped)), game_rules)
    positions = {v.detail.get("position") for v in violations}
    assert positions == {"GKP", "MID"}


def test_duplicate_selection_is_reported(game_rules: GameRules) -> None:
    squad = legal_squad(game_rules)
    duplicated = (*squad.players[:-1], squad.players[0])
    assert ViolationCode.DUPLICATE_PLAYER in _codes(Squad(players=duplicated), game_rules)


def test_exceeding_the_budget_is_reported(game_rules: GameRules) -> None:
    squad = legal_squad(game_rules, price=15.0)
    assert ViolationCode.BUDGET in _codes(squad, game_rules)


def test_spending_exactly_the_budget_is_legal(game_rules: GameRules) -> None:
    """Floating point must not reject a squad that costs precisely £100.0m."""
    squad = legal_squad(game_rules, price=0.1)
    players = list(squad.players)
    players[0] = SquadPlayer(players[0].player_id, players[0].position, players[0].team_id, 98.6)
    exact = Squad(players=tuple(players))
    assert exact.total_price == game_rules.squad.budget
    assert validate_squad(exact, game_rules) == []


def test_budget_can_be_overridden(game_rules: GameRules) -> None:
    squad = legal_squad(game_rules, price=4.5)
    assert ViolationCode.BUDGET in _codes(squad, game_rules, budget=50.0)


def test_club_limit_is_reported(game_rules: GameRules) -> None:
    squad = legal_squad(game_rules)
    all_one_club = tuple(SquadPlayer(p.player_id, p.position, 1, p.price) for p in squad.players)
    violations = validate_squad(Squad(players=all_one_club), game_rules)
    club = [v for v in violations if v.code is ViolationCode.CLUB_LIMIT]
    assert len(club) == 1
    assert club[0].detail["actual"] == 15


def test_all_violations_are_returned_not_just_the_first(game_rules: GameRules) -> None:
    broken = Squad(players=tuple(SquadPlayer(i, Position.MID, 1, 20.0) for i in range(1, 17)))
    codes = _codes(broken, game_rules)
    assert {
        ViolationCode.SQUAD_SIZE,
        ViolationCode.COMPOSITION,
        ViolationCode.BUDGET,
        ViolationCode.CLUB_LIMIT,
    } <= codes


def test_lineup_size_is_checked(game_rules: GameRules) -> None:
    squad = with_lineup(legal_squad(game_rules), game_rules)
    short = Squad(players=squad.players, starting=squad.starting[:-1], captain=squad.captain)
    assert ViolationCode.STARTING_SIZE in _codes(short, game_rules)


def test_illegal_formation_is_reported(game_rules: GameRules) -> None:
    squad = legal_squad(game_rules)
    keepers = [p.player_id for p in squad.players if p.position is Position.GKP]
    mids = [p.player_id for p in squad.players if p.position is Position.MID]
    defs = [p.player_id for p in squad.players if p.position is Position.DEF]
    fwds = [p.player_id for p in squad.players if p.position is Position.FWD]
    # Two keepers and only two defenders: both bounds broken at once.
    starting = (*keepers, *defs[:2], *mids, *fwds[:2])
    violations = validate_squad(Squad(players=squad.players, starting=starting), game_rules)
    positions = {v.detail.get("position") for v in violations if v.code is ViolationCode.FORMATION}
    assert {"GKP", "DEF"} <= positions


def test_a_starter_outside_the_squad_is_reported(game_rules: GameRules) -> None:
    squad = with_lineup(legal_squad(game_rules), game_rules)
    starting = (*squad.starting[:-1], 9999)
    assert ViolationCode.STARTER_NOT_IN_SQUAD in _codes(
        Squad(players=squad.players, starting=starting), game_rules
    )


def test_captain_must_be_starting(game_rules: GameRules) -> None:
    squad = with_lineup(legal_squad(game_rules), game_rules)
    bench_player = squad.bench()[0]
    broken = Squad(
        players=squad.players,
        starting=squad.starting,
        captain=bench_player,
        vice_captain=squad.vice_captain,
    )
    assert ViolationCode.CAPTAIN_NOT_STARTING in _codes(broken, game_rules)


def test_vice_captain_must_be_starting(game_rules: GameRules) -> None:
    squad = with_lineup(legal_squad(game_rules), game_rules)
    broken = Squad(
        players=squad.players,
        starting=squad.starting,
        captain=squad.captain,
        vice_captain=squad.bench()[0],
    )
    assert ViolationCode.VICE_NOT_STARTING in _codes(broken, game_rules)


def test_captain_and_vice_must_differ(game_rules: GameRules) -> None:
    squad = with_lineup(legal_squad(game_rules), game_rules)
    broken = Squad(
        players=squad.players,
        starting=squad.starting,
        captain=squad.captain,
        vice_captain=squad.captain,
    )
    assert ViolationCode.CAPTAIN_IS_VICE in _codes(broken, game_rules)


def test_bench_order_must_list_the_outfield_substitutes(game_rules: GameRules) -> None:
    squad = with_lineup(legal_squad(game_rules), game_rules)
    broken = Squad(
        players=squad.players,
        starting=squad.starting,
        captain=squad.captain,
        vice_captain=squad.vice_captain,
        bench_order=squad.bench_order[:-1],
    )
    assert ViolationCode.BENCH_ORDER in _codes(broken, game_rules)


# --- property tests ------------------------------------------------------------------------


@st.composite
def arbitrary_legal_squad(draw: st.DrawFn, rules: GameRules) -> Squad:
    """Any squad the rules permit: any club spread, any price under budget."""
    # Each club contributes at most `club_limit` slots, so drawing distinct slots guarantees the
    # club limit is respected by construction rather than by rejection.
    club_slots = [t for t in range(1, TEAM_COUNT + 1) for _ in range(rules.squad.club_limit)]
    slot_indices = draw(
        st.lists(
            st.integers(min_value=0, max_value=len(club_slots) - 1),
            min_size=rules.squad.size,
            max_size=rules.squad.size,
            unique=True,
        )
    )
    chosen = [club_slots[i] for i in slot_indices]

    # Prices in tenths, guaranteed to fit the budget.
    budget_tenths = round(rules.squad.budget * 10)
    prices = draw(
        st.lists(
            st.integers(min_value=1, max_value=budget_tenths // rules.squad.size),
            min_size=rules.squad.size,
            max_size=rules.squad.size,
        )
    )

    players: list[SquadPlayer] = []
    index = 0
    for position in Position:
        for _ in range(rules.squad.composition[position]):
            players.append(
                SquadPlayer(
                    player_id=index + 1,
                    position=position,
                    team_id=chosen[index],
                    price=prices[index] / 10,
                )
            )
            index += 1
    return Squad(players=tuple(players))


@settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_any_legal_squad_validates(game_rules: GameRules, data: st.DataObject) -> None:
    squad = data.draw(arbitrary_legal_squad(game_rules))
    assert validate_squad(squad, game_rules) == []


@settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data(), index=st.integers(min_value=0, max_value=14))
def test_changing_any_players_position_breaks_the_squad(
    game_rules: GameRules, data: st.DataObject, index: int
) -> None:
    squad = data.draw(arbitrary_legal_squad(game_rules))
    original = squad.players[index]
    replacement = data.draw(st.sampled_from([p for p in Position if p is not original.position]))
    perturbed = list(squad.players)
    perturbed[index] = SquadPlayer(
        original.player_id, replacement, original.team_id, original.price
    )
    assert validate_squad(Squad(players=tuple(perturbed)), game_rules) != []


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data(), extra=st.integers(min_value=1, max_value=500))
def test_pushing_a_squad_over_budget_always_fails(
    game_rules: GameRules, data: st.DataObject, extra: int
) -> None:
    squad = data.draw(arbitrary_legal_squad(game_rules))
    headroom = round(game_rules.squad.budget * 10) - sum(round(p.price * 10) for p in squad.players)
    players = list(squad.players)
    first = players[0]
    players[0] = SquadPlayer(
        first.player_id,
        first.position,
        first.team_id,
        (round(first.price * 10) + headroom + extra) / 10,
    )
    assert ViolationCode.BUDGET in _codes(Squad(players=tuple(players)), game_rules)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_moving_everyone_to_one_club_always_fails(
    game_rules: GameRules, data: st.DataObject
) -> None:
    squad = data.draw(arbitrary_legal_squad(game_rules))
    same = tuple(SquadPlayer(p.player_id, p.position, 7, p.price) for p in squad.players)
    assert ViolationCode.CLUB_LIMIT in _codes(Squad(players=same), game_rules)


# --- selling price -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("purchase", "current", "expected"),
    [
        (5.0, 5.0, 5.0),  # unchanged
        (5.0, 4.7, 4.7),  # a fall is borne in full
        (5.0, 5.1, 5.0),  # 0.1 rise: half of one tenth rounds down to nothing
        (5.0, 5.2, 5.1),  # 0.2 rise: keep 0.1
        (5.0, 5.3, 5.1),  # 0.3 rise: keep 0.1, remainder rounds down
        (5.0, 5.4, 5.2),
        (4.5, 6.1, 5.3),  # 1.6 rise: keep 0.8
        (10.0, 12.0, 11.0),
    ],
)
def test_selling_price_shares_profit_and_rounds_down(
    game_rules: GameRules, purchase: float, current: float, expected: float
) -> None:
    assert selling_price(purchase, current, game_rules.squad) == pytest.approx(expected)


@given(
    purchase=st.integers(min_value=35, max_value=150),
    rise=st.integers(min_value=0, max_value=60),
)
def test_selling_price_never_exceeds_the_current_price(
    game_rules: GameRules, purchase: int, rise: int
) -> None:
    price = selling_price(purchase / 10, (purchase + rise) / 10, game_rules.squad)
    assert purchase / 10 <= price <= (purchase + rise) / 10


def test_selling_at_purchase_price_ignores_movement(game_rules: GameRules) -> None:
    rules = game_rules.squad.model_copy(update={"sell_at_purchase_price": True})
    assert selling_price(5.0, 9.9, rules) == 5.0
