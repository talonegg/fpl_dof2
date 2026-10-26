"""E1-S1 — the squad state service.

The tests that matter here are about **arithmetic nobody can eyeball**: the sell-on fee, the
path-dependent free-transfer count, and the reconstruction that overlays transfers onto picks. Each
of those is wrong in a way that produces a perfectly plausible-looking squad with the wrong budget,
which is precisely the failure DP-13 says to test hardest for.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from fpl_dof.config import Config
from fpl_dof.config.models import DeclaredPick, EntryConfig
from fpl_dof.gameweek import chips_by_gameweek, chips_played
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.rules.legality import selling_price
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import write_table
from fpl_dof.silver.tables import Table
from fpl_dof.squad.state import (
    Provenance,
    SquadState,
    SquadStateError,
    _free_transfers,
    free_transfers_after,
    gameweek_price_index,
    load_squad_state,
)
from fpl_dof.stages import week
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
        [
            {"season": "2026/27", "gameweek": 1, "player_id": player_id, "price": 4.0}
            for player_id in held
        ]
        # A prior season reuses the ids and the gameweek number at another price.
        + [
            {"season": "2025/26", "gameweek": 1, "player_id": player_id, "price": 9.0}
            for player_id in held
        ]
    )

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=2,
        picks=_picks_frame(held),
        entry=pd.DataFrame([{"bank": 0.0}]),
        gameweek_prices=gameweek_price_index(player_gameweek, "2026/27"),
    )

    assert all(player.purchase_price == 4.0 for player in state.players)
    assert not any("no purchase price" in w for w in state.warnings)


def test_purchase_price_is_what_was_paid_not_the_price_at_the_latest_picks(
    game_rules: GameRules,
) -> None:
    """Production GW8, 2026-10-23: picks ran to GW7, but the per-gameweek prices (element
    summaries, refreshed in a weekly sweep) stopped at GW6. Looking up the price at the latest picks
    found nothing, every player fell back to the current price, and the budget was overstated.
    What was paid is the transfer cost for a player bought in, and the price at the first held
    gameweek for one held since the start — neither depends on the latest week's prices."""
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]
    sold, bought = same_position_swap(players, held)
    after = [bought if player_id == sold else player_id for player_id in held]
    transfers = pd.DataFrame(
        [
            {
                "entry_id": 1234,
                "gameweek": 2,
                "player_in_id": bought,
                "player_in_cost": 3.7,
                "player_out_id": sold,
                "player_out_cost": 4.0,
                "made_at": pd.Timestamp("2026-08-25T10:00:00Z"),
            }
        ]
    )
    # Only GW1 is known, at a price below today's for everyone.
    player_gameweek = pd.DataFrame(
        [
            {"season": "2026/27", "gameweek": 1, "player_id": player_id, "price": 3.5}
            for player_id in held
        ]
    )

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=3,
        picks=pd.concat([_picks_frame(held, 1), _picks_frame(after, 2)]),
        transfers=transfers,
        entry=pd.DataFrame([{"bank": 0.0}]),
        gameweek_prices=gameweek_price_index(player_gameweek, "2026/27"),
    )

    assert state.as_of_gameweek == 2
    paid = {player.player_id: player.purchase_price for player in state.players}
    assert paid.pop(bought) == 3.7, "the transfer log is what was paid"
    assert set(paid.values()) == {3.5}, "held since GW1: the GW1 price"
    assert not any("no purchase price" in w for w in state.warnings)


def test_an_unknown_purchase_price_never_overstates_the_budget(game_rules: GameRules) -> None:
    """When what was paid is unknowable, assume the lowest price seen this season: the sell-on fee
    can then only be overstated, so the budget never claims money the squad cannot raise."""
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]
    current = players.set_index("player_id")["price"]
    # GW2 is the first held gameweek, but only GW1 and GW3 prices are known.
    player_gameweek = pd.DataFrame(
        [
            {"season": "2026/27", "gameweek": gw, "player_id": player_id, "price": price}
            for player_id in held
            for gw, price in ((1, current[player_id] - 0.6), (3, current[player_id] - 0.2))
        ]
    )

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=4,
        picks=pd.concat([_picks_frame(held, 2), _picks_frame(held, 3)]),
        entry=pd.DataFrame([{"bank": 0.0}]),
        gameweek_prices=gameweek_price_index(player_gameweek, "2026/27"),
    )

    for player in state.players:
        assert player.purchase_price == pytest.approx(current[player.player_id] - 0.6)
    assert state.sell_value(game_rules) < round(sum(current[p] for p in held), 1)
    assert sum("no purchase price" in w for w in state.warnings) == SQUAD_SIZE


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


def _transfer(gameweek: int, bought: int, cost: float, sold: int, at: str) -> dict[str, object]:
    return {
        "entry_id": 1234,
        "gameweek": gameweek,
        "player_in_id": bought,
        "player_in_cost": cost,
        "player_out_id": sold,
        "player_out_cost": cost,
        "made_at": pd.Timestamp(at),
    }


FREE_HIT_IN_GW2 = pd.DataFrame([{"entry_id": 1234, "name": "freehit", "gameweek": 2}])


def test_a_player_bought_during_a_free_hit_keeps_what_was_first_paid_after_the_revert(
    game_rules: GameRules,
) -> None:
    """D-33: DL-92 takes the latest transfer in, and the transfer log does not mark Free Hit
    transfers. A player sold and bought back on a Free Hit returns with the squad at what was
    first paid, not at the Free Hit's price."""
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]
    sold, other = same_position_swap(players, held)
    transfers = pd.DataFrame(
        [
            _transfer(2, other, 4.0, sold, "2026-08-27T10:00:00Z"),
            _transfer(2, sold, 4.6, other, "2026-08-27T11:00:00Z"),  # bought back on the Free Hit
        ]
    )
    player_gameweek = pd.DataFrame(
        [{"season": "2026/27", "gameweek": 1, "player_id": pid, "price": 3.5} for pid in held]
    )

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=3,
        picks=pd.concat([_picks_frame(held, 1), _picks_frame(held, 2)]),
        transfers=transfers,
        entry=pd.DataFrame([{"bank": 0.0}]),
        chips=FREE_HIT_IN_GW2,
        gameweek_prices=gameweek_price_index(player_gameweek, "2026/27"),
    )

    paid = {player.player_id: player.purchase_price for player in state.players}
    assert paid[sold] == 3.5, "the Free Hit's 4.6 is not what was paid for the squad he returns to"


def test_the_squad_after_a_free_hit_is_the_one_it_reverts_to(game_rules: GameRules) -> None:
    """The Free Hit gameweek's picks are not the base; a transfer made after it applies to the
    squad from before it."""
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]
    sold, bought = same_position_swap(players, held)
    on_free_hit = [bought if pid == sold else pid for pid in held]

    state = load_squad_state(
        entry_config=EntryConfig(team_id=1234),
        rules=game_rules,
        players=players,
        next_gameweek=3,
        picks=pd.concat([_picks_frame(held, 1), _picks_frame(on_free_hit, 2)]),
        transfers=pd.DataFrame([_transfer(2, bought, 3.7, sold, "2026-08-27T10:00:00Z")]),
        entry=pd.DataFrame([{"bank": 0.0}]),
        chips=FREE_HIT_IN_GW2,
    )

    assert state.player_ids() == frozenset(held)
    assert state.as_of_gameweek == 1
    assert state.provenance is Provenance.FROM_PICKS


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


#: One real entry's 2026/27 history as FPL scored it (D-36): gameweek -> (event_transfers,
#: event_transfers_cost). Two transfers in GW4 cost 4 points, so GW4 had one free transfer.
FPL_HISTORY = {1: (0, 0), 2: (0, 0), 3: (2, 0), 4: (2, 4), 5: (0, 0), 6: (0, 0), 7: (3, 0)}


def test_the_free_transfer_walk_reproduces_fpls_hits(game_rules: GameRules) -> None:
    """GW1's transfers are unlimited and carry nothing: GW2 starts on one. Each week's derived
    allowance must explain FPL's own charge: cost = hit x max(0, transfers - free)."""
    transfers = pd.DataFrame(
        [
            {"entry_id": 4529900, "gameweek": gw, "player_in_id": 0, "player_out_id": 0}
            for gw, (made, _) in FPL_HISTORY.items()
            for _ in range(made)
        ]
    )
    hit = abs(game_rules.transfers.extra_transfer_cost)
    free = {gw: _free_transfers(transfers, gw - 1, gw, game_rules, None) for gw in range(2, 9)}
    for gw, (made, cost) in FPL_HISTORY.items():
        if gw > 1:
            assert cost == hit * max(0, made - free[gw]), gw
    assert free == {2: 1, 3: 2, 4: 1, 5: 1, 6: 2, 7: 3, 8: 1}


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


# --- a Free Hit in the gameweek in play (LIVE-01, D-33) -----------------------------------------


def test_the_chip_in_force_adds_the_in_play_picks_chip_only_where_history_has_none() -> None:
    live = pd.DataFrame(
        [
            {"entry_id": 1234, "gameweek": 2, "chip": "freehit"},
            {"entry_id": 1234, "gameweek": 3, "chip": None},
            {"entry_id": 99, "gameweek": 3, "chip": "bboost"},  # a rival's: not the owner's chip
        ]
    )
    assert chips_by_gameweek(chips_played(None, live, 1234)) == {2: "freehit"}
    assert chips_by_gameweek(chips_played(FREE_HIT_IN_GW2, live, 1234)) == {2: "freehit"}
    assert len(chips_played(FREE_HIT_IN_GW2, live, 1234)) == 1, "listed once"  # type: ignore[arg-type]
    assert chips_played(FREE_HIT_IN_GW2, live, None) is FREE_HIT_IN_GW2


class _BuiltError(Exception):
    """Raised by the spy once the week stage has built its squad state: the rest is not tested."""


def test_a_free_hit_in_play_is_not_the_squad_the_next_gameweeks_advice_starts_from(
    config: Config, layout: DataLayout, game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GW2 is in play on a Free Hit. Its picks are in silver from the deadline (LIVE-01), and the
    owner's history, captured before the deadline, does not list the chip yet; the in-play picks'
    own active chip does. The advice for GW3 starts from the squad the Free Hit reverts to, the
    Free Hit's transfer is no purchase and costs no allowance, and the chip is spent."""
    season = config.rules.season
    players = _players()
    held = [pick.player_id for pick in legal_declaration(players)]
    sold, bought = same_position_swap(players, held)
    on_free_hit = [bought if pid == sold else pid for pid in held]
    deadlines = {1: "2026-08-14T17:30:00Z", 2: "2026-08-21T17:30:00Z", 3: "2026-08-28T17:30:00Z"}
    frames = {
        Table.GAMEWEEK: pd.DataFrame(
            {
                "gameweek": gw,
                "name": f"Gameweek {gw}",
                "deadline_time": pd.Timestamp(deadline),
                "finished": gw == 1,
                "is_next": gw == 3,
                "data_checked": gw == 1,
            }
            for gw, deadline in deadlines.items()
        ),
        Table.PLAYER: players.assign(
            code=players["player_id"] + 1000, full_name=players["web_name"]
        ),
        Table.ENTRY_PICK: pd.concat([_picks_frame(held, 1), _picks_frame(on_free_hit, 2)]),
        Table.ENTRY_TRANSFER: pd.DataFrame(
            [_transfer(2, bought, 3.7, sold, "2026-08-21T10:00:00Z")]
        ),
        Table.ENTRY: pd.DataFrame(
            [
                {
                    "entry_id": 1234,
                    "name": "Owner FC",
                    "started_event": 1,
                    "current_event": 2,
                    "bank": 0.0,
                    "squad_value": 100.0,
                    "total_transfers": 1,
                    "summary_overall_points": 50,
                    "summary_overall_rank": 1000,
                }
            ]
        ),
        # Entry history captured before the deadline: no chip played yet.
        Table.ENTRY_CHIP: pd.DataFrame(columns=["entry_id", "name", "gameweek"]),
        # The in-play picks, captured after it: the Free Hit is their active chip.
        Table.ENTRY_LIVE: pd.DataFrame(
            [
                {
                    "gameweek": 2,
                    "observed_at": pd.Timestamp("2026-08-21T18:00:00Z"),
                    "provisional": True,
                    "entry_id": 1234,
                    "points": 0,
                    "transfers_cost": 0,
                    "total_points": 50,
                    "chip": "freehit",
                }
            ]
        ),
    }
    for table, frame in frames.items():
        write_table(layout.silver, season, table, frame)

    built: list[SquadState] = []

    def spy(**kwargs: Any) -> SquadState:
        built.append(load_squad_state(**kwargs))
        raise _BuiltError

    monkeypatch.setattr(
        week, "read_rules", lambda *_: game_rules.model_copy(update={"season": season})
    )
    monkeypatch.setattr(week, "evaluate", lambda *_: [])
    monkeypatch.setattr(week, "load_squad_state", spy)
    owned = config.model_copy(update={"entry": EntryConfig(team_id=1234)})
    as_of = pd.Timestamp("2026-08-23T12:00:00Z").to_pydatetime()
    with pytest.raises(_BuiltError):
        week.run(StageContext(config=owned, layout=layout, run_id="r", as_of=as_of))

    [state] = built
    assert state.gameweek == 3
    assert state.player_ids() == frozenset(held), "the squad the Free Hit reverts to"
    assert state.as_of_gameweek == 1
    assert "freehit" in state.chips_used
    assert state.free_transfers == 2, "a Free Hit's transfer uses none of the allowance"
