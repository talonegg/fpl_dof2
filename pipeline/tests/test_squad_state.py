"""E1-S1 — the squad state service.

The tests that matter here are about **arithmetic nobody can eyeball**: the sell-on fee, the
path-dependent free-transfer count, and the reconstruction that overlays transfers onto picks. Each
of those is wrong in a way that produces a perfectly plausible-looking squad with the wrong budget,
which is precisely the failure DP-13 says to test hardest for.
"""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from fpl_dof.config.models import DeclaredPick, EntryConfig
from fpl_dof.rules.legality import selling_price
from fpl_dof.rules.models import GameRules
from fpl_dof.squad.state import (
    Provenance,
    SquadStateError,
    free_transfers_after,
    gameweek_price_index,
    load_squad_state,
)
from squads import legal_declaration, same_position_swap
from squads import players as _players

SQUAD_SIZE = 15


def test_a_declared_squad_is_a_first_class_input(game_rules: GameRules) -> None:
    """DL-20: before GW1 is scored there is no picks endpoint, so this is *the* path."""
    players = _players()
    config = EntryConfig(team_id=1234, declared_squad=legal_declaration(players), declared_bank=1.5)

    state = load_squad_state(
        entry_config=config, rules=game_rules, players=players, next_gameweek=2
    )

    assert state.provenance is Provenance.DECLARED
    assert len(state.players) == SQUAD_SIZE
    assert state.bank == 1.5
    assert state.warnings, "a declared squad must say that it was declared"


def test_a_declared_squad_that_is_illegal_is_rejected_immediately(game_rules: GameRules) -> None:
    """A typo in a hand-written squad must not become an illegal recommendation."""
    players = _players()
    legal = list(legal_declaration(players))
    # Duplicate the first pick over the last: still 15 entries, but one player twice.
    broken = (*legal[:-1], legal[0])
    config = EntryConfig(team_id=1234, declared_squad=broken)

    with pytest.raises(SquadStateError, match="not legal"):
        load_squad_state(entry_config=config, rules=game_rules, players=players, next_gameweek=2)


def test_no_squad_at_all_says_what_to_do_about_it(game_rules: GameRules) -> None:
    with pytest.raises(SquadStateError, match="declared_squad"):
        load_squad_state(
            entry_config=EntryConfig(team_id=1234),
            rules=game_rules,
            players=_players(),
            next_gameweek=2,
        )


def _picks_frame(player_ids: list[int], gameweek: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entry_id": 1234,
                "gameweek": gameweek,
                "player_id": player_id,
                "slot": index + 1,
                "multiplier": 1 if index < 11 else 0,
                "is_captain": index == 0,
                "is_vice_captain": index == 1,
                "purchase_price": None,
                "selling_price": None,
            }
            for index, player_id in enumerate(player_ids)
        ]
    )


def test_picks_with_no_transfers_since_are_not_called_a_reconstruction(
    game_rules: GameRules,
) -> None:
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=2,
        picks=_picks_frame(held),
        entry=pd.DataFrame([{"bank": 0.5}]),
    )

    assert state.provenance is Provenance.FROM_PICKS
    assert state.as_of_gameweek == 1
    assert state.player_ids() == frozenset(held)


def test_transfers_since_the_last_picks_are_applied_in_order(game_rules: GameRules) -> None:
    """The pre-deadline reconstruction: last finished picks, overlaid with what happened after."""
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]
    sold, bought = same_position_swap(players, held)

    transfers = pd.DataFrame(
        [
            {
                "entry_id": 1234,
                "gameweek": 2,
                "player_in_id": bought,
                "player_in_cost": 5.5,
                "player_out_id": sold,
                "player_out_cost": 5.5,
                "made_at": pd.Timestamp("2026-08-25T10:00:00Z"),
            }
        ]
    )

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=3,
        picks=_picks_frame(held),
        transfers=transfers,
        entry=pd.DataFrame([{"bank": 0.0}]),
    )

    assert state.provenance is Provenance.RECONSTRUCTED
    assert bought in state.player_ids()
    assert sold not in state.player_ids()
    bought_player = next(p for p in state.players if p.player_id == bought)
    assert bought_player.purchase_price == 5.5, "the transfer log is the purchase price"


def test_purchase_price_comes_from_the_gameweek_price_when_held_from_the_start(
    game_rules: GameRules,
) -> None:
    """The sell-on fee needs what was paid, and picks do not publish it (Invariant 4)."""
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]
    player_gameweek = pd.DataFrame(
        [{"gameweek": 1, "player_id": player_id, "price": 4.0} for player_id in held]
    )

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=2,
        picks=_picks_frame(held),
        entry=pd.DataFrame([{"bank": 0.0}]),
        gameweek_prices=gameweek_price_index(player_gameweek),
    )

    assert all(player.purchase_price == 4.0 for player in state.players)
    assert not any("no purchase price" in w for w in state.warnings)


def test_a_missing_purchase_price_warns_rather_than_pretending(game_rules: GameRules) -> None:
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=2,
        picks=_picks_frame(held),
        entry=pd.DataFrame([{"bank": 0.0}]),
    )

    assert any("no purchase price" in warning for warning in state.warnings)


def test_sell_value_applies_the_sell_on_fee_not_the_current_price(
    game_rules: GameRules,
) -> None:
    """The whole reason purchase price is tracked.

    A player bought at 4.0 who is now worth 4.4 sells for 4.2, not 4.4. A squad valued at current
    prices claims money it cannot raise, and the optimiser then recommends a transfer that will not
    go through.
    """
    players = _players()
    players.loc[:, "price"] = players["price"] + 0.4
    declaration = tuple(
        DeclaredPick(player_id=pick.player_id, purchase_price=pick.purchase_price)
        for pick in legal_declaration(_players())
    )

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1, declared_squad=declaration),
        rules=game_rules,
        players=players,
        next_gameweek=2,
    )

    at_current = sum(player.current_price for player in state.players)
    assert state.sell_value(game_rules) < at_current
    for player in state.players:
        assert player.selling_price(game_rules) == selling_price(
            player.purchase_price, player.current_price, game_rules.squad
        )


# --- free transfers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("previous", "made", "expected"),
    [
        (1, 0, 2),  # rolled
        (1, 1, 1),  # used it, back to one
        (2, 0, 3),
        (1, 3, 1),  # took a hit; you do not go into debt
        (5, 0, 5),  # capped
        (5, 1, 5),
        (4, 0, 5),
    ],
)
def test_free_transfer_accumulation(
    previous: int, made: int, expected: int, game_rules: GameRules
) -> None:
    assert free_transfers_after(previous, made, game_rules) == expected


def test_a_wildcard_week_does_not_consume_the_allowance(game_rules: GameRules) -> None:
    """Ten transfers on a wildcard still leaves next week's allowance intact.

    Reading the transfer count alone would conclude the manager is deep in the red and would then
    refuse every sensible hit for weeks.
    """
    assert free_transfers_after(2, 10, game_rules, chip_played="wildcard") == 3
    assert free_transfers_after(2, 10, game_rules) == 1


@given(
    previous=st.integers(min_value=1, max_value=5),
    made=st.integers(min_value=0, max_value=15),
)
def test_free_transfers_stay_inside_the_published_bounds(
    previous: int, made: int, game_rules: GameRules
) -> None:
    """Whatever happened last week, the allowance is between one and the published maximum."""
    result = free_transfers_after(previous, made, game_rules)
    assert 1 <= result <= game_rules.transfers.max_free_transfers
