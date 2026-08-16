"""Picking the starting XI, the captain and the bench order from a fixed 15.

This is a small enough problem to solve exactly by enumeration, and doing so is worth more than the
milliseconds it costs. FPL's legal formations number in the low tens; within a formation the choice
is "take the highest expected points at each position", which is a sort. So the optimum is reachable
by trying every formation, and the result needs no solver, no tolerance and no interpretation.

**Bench order is ranked by ``P(plays) x xP``, not by xP.** A substitute only ever scores if someone
ahead of them fails to play, so a reliable 3-point player is worth more on the bench than an
explosive one who is doubtful — the opposite of the starting-XI ordering. This is a heuristic and is
labelled as one: it becomes a real calculation when E3 supplies a minutes model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fpl_dof.rules.legality import Squad, SquadPlayer, validate_squad
from fpl_dof.rules.models import GameRules, Position


@dataclass(frozen=True, slots=True)
class Candidate:
    """One player, as the selector sees them."""

    player_id: int
    position: Position
    expected_points: float
    start_probability: float
    web_name: str = ""

    @property
    def bench_value(self) -> float:
        """What this player is worth *as a substitute*: points, discounted by the chance of
        appearing at all."""
        return self.expected_points * self.start_probability


@dataclass(frozen=True, slots=True)
class Selection:
    starting: tuple[int, ...]
    bench_order: tuple[int, ...]
    """Outfield substitutes, in the order they should come on. The reserve keeper is automatic."""

    reserve_goalkeeper: int | None
    captain: int
    vice_captain: int
    formation: str
    expected_points: float
    """Starting XI plus the captain's doubled contribution. Bench points are excluded: they only
    score under a bench boost, which is E4."""

    def as_squad(self, players: tuple[SquadPlayer, ...]) -> Squad:
        return Squad(
            players=players,
            starting=self.starting,
            captain=self.captain,
            vice_captain=self.vice_captain,
            bench_order=self.bench_order,
        )


class SelectionError(RuntimeError):
    """No legal XI exists in this squad. Almost always an upstream problem, not a selection one."""


def select_team(
    candidates: Mapping[int, Candidate],
    rules: GameRules,
    *,
    captain_multiplier: int = 2,
    start_probability_floor: float = 0.0,
    locked_player_ids: frozenset[int] = frozenset(),
) -> Selection:
    """The best legal XI, captain, vice-captain and bench order for this squad.

    ``start_probability_floor`` bars players unlikely to feature from the XI. A locked player is
    exempt, for the same reason as in the squad optimiser: an explicit human decision outranks a
    heuristic about who is probably playing.
    """
    if not candidates:
        raise SelectionError("no candidates were supplied")

    by_position: dict[Position, list[Candidate]] = {position: [] for position in Position}
    for candidate in candidates.values():
        by_position[candidate.position].append(candidate)
    for group in by_position.values():
        # Ties broken by player_id so the same squad always yields the same XI. A selection that
        # silently changes between runs makes the advised-versus-played diff meaningless.
        group.sort(key=lambda c: (-c.expected_points, c.player_id))

    eligible = {
        position: [
            candidate
            for candidate in group
            if candidate.start_probability >= start_probability_floor
            or candidate.player_id in locked_player_ids
        ]
        for position, group in by_position.items()
    }

    best: tuple[float, tuple[int, ...], dict[Position, int]] | None = None
    for formation in rules.squad.legal_formations():
        if any(len(eligible[position]) < count for position, count in formation.items()):
            continue
        chosen: list[Candidate] = []
        for position, count in formation.items():
            chosen.extend(eligible[position][:count])
        total = sum(candidate.expected_points for candidate in chosen)
        ids = tuple(sorted(candidate.player_id for candidate in chosen))
        if best is None or total > best[0]:
            best = (total, ids, formation)

    if best is None:
        raise SelectionError(
            "no legal formation can be filled from this squad above the start-probability floor "
            f"of {start_probability_floor:.2f}; the squad itself is the problem"
        )

    total, starting_ids, formation = best
    starting = [candidates[pid] for pid in starting_ids]
    starting.sort(key=lambda c: (-c.expected_points, c.player_id))

    captain = starting[0]
    vice = starting[1] if len(starting) > 1 else starting[0]

    bench = [candidates[pid] for pid in candidates if pid not in set(starting_ids)]
    outfield = [c for c in bench if c.position is not Position.GKP]
    keepers = [c for c in bench if c.position is Position.GKP]
    outfield.sort(key=lambda c: (-c.bench_value, c.player_id))

    selection = Selection(
        starting=tuple(c.player_id for c in starting),
        bench_order=tuple(c.player_id for c in outfield),
        reserve_goalkeeper=keepers[0].player_id if keepers else None,
        captain=captain.player_id,
        vice_captain=vice.player_id,
        formation=_formation_label(formation),
        # The captain's points count once as a starter and again for each extra multiplier.
        expected_points=round(
            total + captain.expected_points * (captain_multiplier - 1),
            4,
        ),
    )
    return selection


def _formation_label(formation: Mapping[Position, int]) -> str:
    return "-".join(str(formation[position]) for position in Position)


def verify(selection: Selection, players: tuple[SquadPlayer, ...], rules: GameRules) -> None:
    """Check the selection against the shared validator rather than trusting the enumeration.

    The enumeration and the validator are independent implementations of the same rules, which is
    the only reason checking is worth anything (DP-13).
    """
    violations = validate_squad(selection.as_squad(players), rules)
    if violations:
        detail = "; ".join(v.message for v in violations)
        raise SelectionError(f"the selected team is not legal: {detail}")


__all__ = [
    "Candidate",
    "Selection",
    "SelectionError",
    "select_team",
    "verify",
]
