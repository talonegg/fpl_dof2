"""Squad legality, and the selling-price arithmetic.

:func:`validate_squad` returns **every** violation rather than the first. A squad with three
problems should tell you about three problems: the optimiser's job is to produce something legal in
one pass, and a validator that stops at the first failure makes debugging it a game of whack-a-mole.

This module is the thing everything else trusts. The optimiser's output is checked against it
rather than asserted to be correct by construction — a solver bug or a mis-stated constraint that
produces an illegal squad is exactly the class of error that would otherwise reach the deadline
unnoticed (DP-13).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from fpl_dof.rules.models import GameRules, Position, SquadRules


class ViolationCode(StrEnum):
    SQUAD_SIZE = "squad_size"
    DUPLICATE_PLAYER = "duplicate_player"
    COMPOSITION = "composition"
    BUDGET = "budget"
    CLUB_LIMIT = "club_limit"
    STARTING_SIZE = "starting_size"
    STARTER_NOT_IN_SQUAD = "starter_not_in_squad"
    FORMATION = "formation"
    CAPTAIN_NOT_STARTING = "captain_not_starting"
    VICE_NOT_STARTING = "vice_not_starting"
    CAPTAIN_IS_VICE = "captain_is_vice"
    BENCH_ORDER = "bench_order"


@dataclass(frozen=True, slots=True)
class Violation:
    code: ViolationCode
    message: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SquadPlayer:
    player_id: int
    position: Position
    team_id: int
    price: float
    """The price at which this player counts against the budget."""


@dataclass(frozen=True, slots=True)
class Squad:
    """A full squad, plus how it is set up for a gameweek."""

    players: tuple[SquadPlayer, ...]
    starting: tuple[int, ...] = ()
    captain: int | None = None
    vice_captain: int | None = None
    bench_order: tuple[int, ...] = ()

    def by_id(self) -> dict[int, SquadPlayer]:
        return {player.player_id: player for player in self.players}

    @property
    def total_price(self) -> float:
        return round(sum(player.price for player in self.players), 1)

    def bench(self) -> tuple[int, ...]:
        starting = set(self.starting)
        return tuple(p.player_id for p in self.players if p.player_id not in starting)


def validate_squad(
    squad: Squad, rules: GameRules, *, budget: float | None = None
) -> list[Violation]:
    """Every way this squad breaks the rules, in a stable order.

    ``budget`` overrides the rules' initial budget — from E1 onward the relevant figure is squad
    value plus bank, not £100.0m.

    A squad with no starting XI set is checked for squad-level legality only. That is the E0 case:
    the optimiser picks 15 and a captain, and lineup checks apply once a lineup exists.
    """
    violations: list[Violation] = []
    squad_rules = rules.squad
    limit = squad_rules.budget if budget is None else budget

    violations.extend(_check_squad(squad, squad_rules, limit))
    if squad.starting:
        violations.extend(_check_lineup(squad, squad_rules))
    return violations


def _check_squad(squad: Squad, rules: SquadRules, budget: float) -> list[Violation]:
    violations: list[Violation] = []

    if len(squad.players) != rules.size:
        violations.append(
            Violation(
                ViolationCode.SQUAD_SIZE,
                f"squad has {len(squad.players)} players, expected {rules.size}",
                {"actual": len(squad.players), "expected": rules.size},
            )
        )

    ids = Counter(player.player_id for player in squad.players)
    duplicates = sorted(pid for pid, count in ids.items() if count > 1)
    if duplicates:
        violations.append(
            Violation(
                ViolationCode.DUPLICATE_PLAYER,
                f"player(s) selected more than once: {duplicates}",
                {"player_ids": duplicates},
            )
        )

    counts = Counter(player.position for player in squad.players)
    for position in Position:
        required = rules.composition[position]
        actual = counts.get(position, 0)
        if actual != required:
            violations.append(
                Violation(
                    ViolationCode.COMPOSITION,
                    f"{position.value}: {actual} selected, exactly {required} required",
                    {"position": position.value, "actual": actual, "expected": required},
                )
            )

    # Compare in tenths: 0.1 is not representable in binary, and a squad costing exactly the budget
    # must not be rejected because the sum came to 100.00000000000001.
    spend_tenths = sum(round(player.price * 10) for player in squad.players)
    budget_tenths = round(budget * 10)
    if spend_tenths > budget_tenths:
        violations.append(
            Violation(
                ViolationCode.BUDGET,
                f"squad costs £{spend_tenths / 10:.1f}m, budget is £{budget_tenths / 10:.1f}m",
                {"spend": spend_tenths / 10, "budget": budget_tenths / 10},
            )
        )

    per_club = Counter(player.team_id for player in squad.players)
    for team_id, count in sorted(per_club.items()):
        if count > rules.club_limit:
            violations.append(
                Violation(
                    ViolationCode.CLUB_LIMIT,
                    f"{count} players from club {team_id}, maximum is {rules.club_limit}",
                    {"team_id": team_id, "actual": count, "limit": rules.club_limit},
                )
            )

    return violations


def _check_lineup(squad: Squad, rules: SquadRules) -> list[Violation]:
    violations: list[Violation] = []
    members = squad.by_id()

    if len(squad.starting) != rules.starting_size:
        violations.append(
            Violation(
                ViolationCode.STARTING_SIZE,
                f"{len(squad.starting)} players starting, expected {rules.starting_size}",
                {"actual": len(squad.starting), "expected": rules.starting_size},
            )
        )

    outside = sorted(set(squad.starting) - set(members))
    if outside:
        violations.append(
            Violation(
                ViolationCode.STARTER_NOT_IN_SQUAD,
                f"starting player(s) not in the squad: {outside}",
                {"player_ids": outside},
            )
        )

    counts = Counter(members[pid].position for pid in squad.starting if pid in members)
    for position in Position:
        actual = counts.get(position, 0)
        low, high = rules.formation_min[position], rules.formation_max[position]
        if not low <= actual <= high:
            violations.append(
                Violation(
                    ViolationCode.FORMATION,
                    f"{position.value}: {actual} starting, must be between {low} and {high}",
                    {"position": position.value, "actual": actual, "min": low, "max": high},
                )
            )

    starting = set(squad.starting)
    if squad.captain is not None and squad.captain not in starting:
        violations.append(
            Violation(
                ViolationCode.CAPTAIN_NOT_STARTING,
                f"captain {squad.captain} is not in the starting XI",
                {"player_id": squad.captain},
            )
        )
    if squad.vice_captain is not None and squad.vice_captain not in starting:
        violations.append(
            Violation(
                ViolationCode.VICE_NOT_STARTING,
                f"vice-captain {squad.vice_captain} is not in the starting XI",
                {"player_id": squad.vice_captain},
            )
        )
    if (
        squad.captain is not None
        and squad.vice_captain is not None
        and squad.captain == squad.vice_captain
    ):
        violations.append(
            Violation(
                ViolationCode.CAPTAIN_IS_VICE,
                "captain and vice-captain are the same player",
                {"player_id": squad.captain},
            )
        )

    if squad.bench_order:
        expected = {
            pid
            for pid in squad.bench()
            if pid in members and members[pid].position is not Position.GKP
        }
        if set(squad.bench_order) != expected:
            violations.append(
                Violation(
                    ViolationCode.BENCH_ORDER,
                    "bench order must list exactly the outfield substitutes",
                    {"given": sorted(squad.bench_order), "expected": sorted(expected)},
                )
            )

    return violations


def is_legal(squad: Squad, rules: GameRules, *, budget: float | None = None) -> bool:
    return not validate_squad(squad, rules, budget=budget)


def selling_price(purchase_price: float, current_price: float, rules: SquadRules) -> float:
    """What a player sells for.

    Profit is shared with the game: you keep ``1 - sell_on_fee`` of any rise, rounded **down** to
    the nearest £0.1. A price fall is borne in full.

    Unused in E0 — a preseason squad has no purchase history — and needed from E1, which is why it
    is written and tested now rather than under deadline pressure later.
    """
    if rules.sell_at_purchase_price:
        return purchase_price

    purchase_tenths = round(purchase_price * 10)
    current_tenths = round(current_price * 10)
    if current_tenths <= purchase_tenths:
        return current_tenths / 10

    profit = current_tenths - purchase_tenths
    kept = math.floor(profit * (1.0 - rules.sell_on_fee))
    return (purchase_tenths + kept) / 10
