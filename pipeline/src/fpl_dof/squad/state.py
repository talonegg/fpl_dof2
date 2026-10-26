"""What the owner's squad actually is, right now.

This is the awkward story in E1, and the awkwardness is real rather than incidental: **FPL publishes
no endpoint that says "here is your squad as it stands"**. The public API exposes picks for
gameweeks that have *finished*, and a transfer log. The state that matters — the squad you will take
into the next deadline, and what each player would sell for — has to be reconstructed from those two
things, or declared by hand.

Three provenances, in descending order of how much they should be trusted:

``FROM_PICKS``
    A finished gameweek's picks with no transfers made since. Nothing is inferred.

``RECONSTRUCTED``
    Picks, plus transfers applied in order. Under both, purchase prices come from the transfer log
    for players bought in, and from the price in the first held gameweek for players held since
    the start.

    A Free Hit gameweek's squad reverts at the next deadline, so its picks are never the base and
    its transfers never a purchase (D-33): the chip in force comes from entry history and from the
    gameweek in play's own picks, whose Free Hit history may not list yet
    (:func:`fpl_dof.gameweek.chips_played`), read as the gameweek state reads it
    (:func:`fpl_dof.gameweek.chips_by_gameweek`).

``DECLARED``
    Stated in configuration. Before GW1 is scored this is the *only* possible answer (DL-20), so it
    is a first-class input and not a degraded mode. It is validated on entry, because a typo in a
    hand-written squad otherwise becomes an illegal recommendation.

**Selling price is why purchase price cannot be skipped.** The sell-on fee means a player who has
risen £0.4m sells for £0.2m more than you paid, not £0.4m — so a squad valued at current prices
overstates what it can actually raise, and an optimiser told the wrong budget will confidently
recommend a transfer that cannot be made.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from fpl_dof.config.models import EntryConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.gameweek import chips_by_gameweek
from fpl_dof.rules.legality import Squad, SquadPlayer, Violation, selling_price, validate_squad
from fpl_dof.rules.models import GameRules, Position

#: The game's name for the chip whose squad reverts after one gameweek.
FREE_HIT = "freehit"


class SquadStateError(RuntimeError):
    """The squad state could not be established at all, and guessing is not an option."""


class Provenance(StrEnum):
    """How much of this squad was read versus inferred. Reported, never hidden."""

    FROM_PICKS = "from_picks"
    RECONSTRUCTED = "reconstructed"
    DECLARED = "declared"


@dataclass(frozen=True, slots=True)
class HeldPlayer:
    player_id: int
    position: Position
    team_id: int
    current_price: float
    purchase_price: float
    web_name: str = ""
    slot: int | None = None
    is_captain: bool = False
    is_vice_captain: bool = False

    def selling_price(self, rules: GameRules) -> float:
        return selling_price(self.purchase_price, self.current_price, rules.squad)


@dataclass(frozen=True, slots=True)
class SquadState:
    """The squad as it stands going into ``gameweek``."""

    entry_id: int | None
    gameweek: int
    players: tuple[HeldPlayer, ...]
    bank: float
    free_transfers: int
    chips_used: tuple[str, ...]
    provenance: Provenance
    warnings: tuple[str, ...] = ()
    as_of_gameweek: int | None = None
    """The gameweek whose picks this was built from, when there was one."""

    def sell_value(self, rules: GameRules) -> float:
        """What the squad would raise if sold today. Not the same as its value at current prices."""
        return round(sum(player.selling_price(rules) for player in self.players), 1)

    def budget(self, rules: GameRules) -> float:
        """Everything available to spend: what the squad would raise, plus the bank."""
        return round(self.sell_value(rules) + self.bank, 1)

    def player_ids(self) -> frozenset[int]:
        return frozenset(player.player_id for player in self.players)

    def as_squad(self, rules: GameRules) -> Squad:
        """A :class:`~fpl_dof.rules.legality.Squad` priced at *selling* value.

        Priced this way on purpose: the legality question from E1 onward is "could this squad exist
        given what I could raise", and that is a selling-price question. Validating at current
        prices would reject perfectly legal squads whose players have risen.
        """
        return Squad(
            players=tuple(
                SquadPlayer(
                    player_id=held.player_id,
                    position=held.position,
                    team_id=held.team_id,
                    price=held.selling_price(rules),
                )
                for held in self.players
            )
        )

    def validate(self, rules: GameRules) -> list[Violation]:
        return validate_squad(self.as_squad(rules), rules, budget=self.budget(rules))


def free_transfers_after(
    previous: int, transfers_made: int, rules: GameRules, *, chip_played: str | None = None
) -> int:
    """Free transfers going into the next gameweek.

    ``free_transfers_per_gameweek`` is earned per gameweek, unused ones accumulate to the
    configured maximum, and using more than you had does not put you in debt — you simply start
    the next week on one week's allowance.

    A chip that makes the week's transfers free (Wildcard, Free Hit) does not consume the
    allowance, which is why the chip has to be passed in rather than inferred from the transfer
    count. Getting this wrong understates next week's flexibility and quietly biases the tool
    toward taking hits.
    """
    earned = rules.transfers.free_transfers_per_gameweek
    free_week = chip_played in rules.chips.transfers_free_with
    remaining = previous if free_week else previous - transfers_made
    return max(earned, min(rules.transfers.max_free_transfers, remaining + earned))


def load_squad_state(
    *,
    entry_config: EntryConfig,
    rules: GameRules,
    players: pd.DataFrame,
    next_gameweek: int,
    picks: pd.DataFrame | None = None,
    transfers: pd.DataFrame | None = None,
    entry: pd.DataFrame | None = None,
    chips: pd.DataFrame | None = None,
    gameweek_prices: Mapping[tuple[int, int], float] | None = None,
) -> SquadState:
    """Establish the current squad, preferring what was read over what was inferred.

    ``gameweek_prices`` maps ``(gameweek, player_id)`` to the price at that gameweek, and is how a
    player held since the start gets a purchase price: the price in the first gameweek they were
    held. A player bought in is priced from the transfer log. Where neither is known the lowest
    price seen this season is assumed, recorded as a warning rather than passed off as fact: it
    can understate the sell value, never overstate it.
    """
    catalogue = _player_catalogue(players)

    if entry_config.prefer_declared or picks is None or picks.empty:
        reason = (
            "declared squad forced by configuration"
            if entry_config.prefer_declared
            else "no published picks are available"
        )
        return _from_declaration(entry_config, rules, catalogue, next_gameweek, reason)

    return _from_picks(
        entry_config=entry_config,
        rules=rules,
        catalogue=catalogue,
        next_gameweek=next_gameweek,
        picks=picks,
        transfers=transfers,
        entry=entry,
        chips=chips,
        gameweek_prices=gameweek_prices or {},
    )


@dataclass(frozen=True, slots=True)
class _CataloguedPlayer:
    position: Position
    team_id: int
    price: float
    web_name: str


def _player_catalogue(players: pd.DataFrame) -> dict[int, _CataloguedPlayer]:
    return {
        as_int(row["player_id"]): _CataloguedPlayer(
            position=Position(str(row["position"])),
            team_id=as_int(row["team_id"]),
            price=as_float(row["price"]),
            web_name=str(row["web_name"]),
        )
        for _, row in players.iterrows()
    }


def _require(catalogue: Mapping[int, _CataloguedPlayer], player_id: int) -> _CataloguedPlayer:
    found = catalogue.get(player_id)
    if found is None:
        raise SquadStateError(
            f"player {player_id} is in the squad but not in the player table; the squad cannot be "
            "priced, and a squad that cannot be priced must not be silently dropped"
        )
    return found


def _from_declaration(
    entry_config: EntryConfig,
    rules: GameRules,
    catalogue: Mapping[int, _CataloguedPlayer],
    next_gameweek: int,
    reason: str,
) -> SquadState:
    if not entry_config.declared_squad:
        raise SquadStateError(
            f"{reason}, and no squad is declared in configuration. Set entry.declared_squad "
            "(player_id and purchase_price for all 15) in config/local.yaml — before the first "
            "gameweek is scored there is no endpoint that can answer this (DL-20)."
        )

    held = []
    for pick in entry_config.declared_squad:
        found = _require(catalogue, pick.player_id)
        held.append(
            HeldPlayer(
                player_id=pick.player_id,
                position=found.position,
                team_id=found.team_id,
                current_price=found.price,
                purchase_price=pick.purchase_price,
                web_name=found.web_name,
            )
        )

    state = SquadState(
        entry_id=entry_config.team_id,
        gameweek=next_gameweek,
        players=tuple(held),
        bank=entry_config.declared_bank,
        free_transfers=entry_config.declared_free_transfers,
        chips_used=entry_config.declared_chips_used,
        provenance=Provenance.DECLARED,
        warnings=(f"squad declared by hand: {reason}",),
    )

    # Validate immediately. A hand-typed squad is exactly where a duplicated player or a fourth
    # Arsenal defender comes from, and finding out at solve time makes the error look like an
    # optimiser bug.
    violations = state.validate(rules)
    if violations:
        detail = "; ".join(v.message for v in violations)
        raise SquadStateError(f"the declared squad is not legal: {detail}")
    return state


def _from_picks(
    *,
    entry_config: EntryConfig,
    rules: GameRules,
    catalogue: Mapping[int, _CataloguedPlayer],
    next_gameweek: int,
    picks: pd.DataFrame,
    transfers: pd.DataFrame | None,
    entry: pd.DataFrame | None,
    chips: pd.DataFrame | None,
    gameweek_prices: Mapping[tuple[int, int], float],
) -> SquadState:
    warnings: list[str] = []
    free_hits = {gw for gw, chip in chips_by_gameweek(chips).items() if chip == FREE_HIT}
    # shortcut: when every pick is a Free Hit's, the squad it reverts to is unknown; they are kept.
    if not picks["gameweek"].isin(free_hits).all():
        picks = picks[~picks["gameweek"].isin(free_hits)]
    bought = transfers
    if transfers is not None and not transfers.empty:
        bought = transfers[~transfers["gameweek"].isin(free_hits)]
    latest = as_int(picks["gameweek"].max())
    base = picks[picks["gameweek"] == latest]

    bought_for = _transfer_costs(bought)
    first_held = picks.groupby("player_id")["gameweek"].min()

    holdings: dict[int, float] = {}
    slots: dict[int, int] = {}
    captain: int | None = None
    vice: int | None = None
    for _, row in base.iterrows():
        player_id = as_int(row["player_id"])
        slots[player_id] = as_int(row["slot"])
        holdings[player_id] = _purchase_price(
            player_id,
            row,
            bought_for,
            as_int(first_held[player_id]),
            gameweek_prices,
            catalogue,
            warnings,
        )
        if bool(row["is_captain"]):
            captain = player_id
        if bool(row["is_vice_captain"]):
            vice = player_id

    since = _transfers_since(bought, latest)
    for _, row in since.iterrows():
        out_id = as_int(row["player_out_id"])
        in_id = as_int(row["player_in_id"])
        if out_id not in holdings:
            warnings.append(
                f"transfer log sells player {out_id}, who is not in the gameweek {latest} squad; "
                "the reconstruction is incomplete"
            )
        holdings.pop(out_id, None)
        slots.pop(out_id, None)
        holdings[in_id] = as_float(row["player_in_cost"])

    provenance = Provenance.FROM_PICKS if since.empty else Provenance.RECONSTRUCTED

    held = tuple(
        HeldPlayer(
            player_id=player_id,
            position=_require(catalogue, player_id).position,
            team_id=_require(catalogue, player_id).team_id,
            current_price=_require(catalogue, player_id).price,
            purchase_price=purchase,
            web_name=_require(catalogue, player_id).web_name,
            slot=slots.get(player_id),
            is_captain=player_id == captain,
            is_vice_captain=player_id == vice,
        )
        for player_id, purchase in holdings.items()
    )

    bank = _bank(entry, warnings)
    free = _free_transfers(transfers, latest, next_gameweek, rules, chips)
    chips_used = _chips_used(chips)

    state = SquadState(
        entry_id=entry_config.team_id,
        gameweek=next_gameweek,
        players=held,
        bank=bank,
        free_transfers=free,
        chips_used=chips_used,
        provenance=provenance,
        warnings=tuple(warnings),
        as_of_gameweek=latest,
    )

    # A reconstruction that produces an illegal squad has reconstructed something wrong. Say so
    # loudly rather than optimising from it — this is the "warns rather than guesses silently"
    # acceptance criterion, and it is the difference between a bad week and a bad season.
    violations = state.validate(rules)
    if violations:
        detail = "; ".join(v.message for v in violations)
        raise SquadStateError(
            f"the reconstructed squad for gameweek {next_gameweek} is not legal: {detail}. "
            "Reconstruction is unreliable here — declare the squad explicitly via "
            "entry.declared_squad and set entry.prefer_declared."
        )
    return state


def _transfer_costs(transfers: pd.DataFrame | None) -> dict[int, float]:
    """``player_id -> player_in_cost`` of the most recent transfer that brought each player in."""
    if transfers is None or transfers.empty:
        return {}
    ordered = transfers.sort_values(["gameweek", "made_at"], na_position="first")
    return {
        as_int(row["player_in_id"]): as_float(row["player_in_cost"])
        for _, row in ordered.iterrows()
    }


def _purchase_price(
    player_id: int,
    row: pd.Series,
    bought_for: Mapping[int, float],
    first_held: int,
    gameweek_prices: Mapping[tuple[int, int], float],
    catalogue: Mapping[int, _CataloguedPlayer],
    warnings: list[str],
) -> float:
    """What this player cost: published, else the transfer that bought him, else the price in the
    first gameweek he was held (held since the start, never bought in). Warned about where none is
    known, and then the lowest price seen this season — no higher than what was paid, so the sell
    value is understated rather than overstated (a current-price fallback overstates it for anyone
    who has risen)."""
    published = row.get("purchase_price")
    if published is not None and not pd.isna(published):
        return as_float(published)
    if player_id in bought_for:
        return bought_for[player_id]
    at_start = gameweek_prices.get((first_held, player_id))
    if at_start is not None:
        return at_start
    current = _require(catalogue, player_id).price
    lowest = min(
        (price for (_, pid), price in gameweek_prices.items() if pid == player_id),
        default=current,
    )
    warnings.append(
        f"no purchase price for player {player_id}; assuming £{lowest:.1f}m, the lowest price "
        "seen this season, so the sell value is understated rather than overstated"
    )
    return lowest


def _transfers_since(transfers: pd.DataFrame | None, gameweek: int) -> pd.DataFrame:
    if transfers is None or transfers.empty:
        return pd.DataFrame(columns=["player_in_id", "player_in_cost", "player_out_id"])
    since = transfers[transfers["gameweek"] > gameweek]
    return since.sort_values("made_at", na_position="last")


def _bank(entry: pd.DataFrame | None, warnings: list[str]) -> float:
    if entry is None or entry.empty:
        warnings.append("no entry record; assuming an empty bank")
        return 0.0
    value = entry.iloc[0]["bank"]
    if pd.isna(value):
        warnings.append("the entry publishes no bank balance yet; assuming empty")
        return 0.0
    return as_float(value)


def _free_transfers(
    transfers: pd.DataFrame | None,
    latest: int,
    next_gameweek: int,
    rules: GameRules,
    chips: pd.DataFrame | None,
) -> int:
    """Recompute the allowance from the transfer log rather than assuming it.

    Walked forward from GW2 because the count is path-dependent: two transfers in one week and
    none in the next does not leave you where none-then-two does. GW2 starts on one week's
    allowance: transfers before the GW1 deadline are unlimited and none carries over (D-36).
    """
    by_gameweek: dict[int, int] = {}
    if transfers is not None and not transfers.empty:
        counts = transfers.groupby("gameweek").size()
        by_gameweek = {as_int(gw): as_int(n) for gw, n in counts.items()}
    chip_by_gameweek = chips_by_gameweek(chips)

    available = rules.transfers.free_transfers_per_gameweek
    for gameweek in range(2, max(next_gameweek, latest + 1)):
        available = free_transfers_after(
            available,
            by_gameweek.get(gameweek, 0),
            rules,
            chip_played=chip_by_gameweek.get(gameweek),
        )
    return available


def _chips_used(chips: pd.DataFrame | None) -> tuple[str, ...]:
    if chips is None or chips.empty:
        return ()
    return tuple(str(name) for name in chips["name"])


def gameweek_price_index(
    player_gameweek: pd.DataFrame | None, season: str
) -> dict[tuple[int, int], float]:
    """``(gameweek, player_id) -> price``, for reconstructing purchase prices.

    Built from per-gameweek history, which records what a player was worth in each week. This is
    the only route to the purchase price of a player held since the start, because the public picks
    endpoint does not publish one. Only ``season``'s rows: the table also holds backfilled seasons,
    and FPL reuses ``player_id`` across them, so an unfiltered index would price a player at
    another player's old value.
    """
    if player_gameweek is None or player_gameweek.empty:
        return {}
    current = player_gameweek[player_gameweek["season"] == season]
    return {
        (as_int(row["gameweek"]), as_int(row["player_id"])): as_float(row["price"])
        for _, row in current.iterrows()
    }


def describe(state: SquadState, rules: GameRules) -> Sequence[str]:
    """Human-readable summary lines for the weekly output."""
    lines = [
        f"Squad for gameweek {state.gameweek} ({state.provenance.value})",
        f"  sell value £{state.sell_value(rules):.1f}m + bank £{state.bank:.1f}m "
        f"= £{state.budget(rules):.1f}m",
        f"  free transfers: {state.free_transfers}",
    ]
    if state.chips_used:
        lines.append(f"  chips used: {', '.join(state.chips_used)}")
    lines.extend(f"  warning: {warning}" for warning in state.warnings)
    return lines


__all__ = [
    "HeldPlayer",
    "Provenance",
    "SquadState",
    "SquadStateError",
    "describe",
    "free_transfers_after",
    "gameweek_price_index",
    "load_squad_state",
]
