"""What was advised, what was played, and why they differ.

Lineage records what the system *advised*. Nothing until now records what was actually **played**,
and the two diverge routinely — the human overrules, which is correct and expected (ASM-6), and
occasionally a deadline is missed or a substitution is mis-clicked at 03:00 local.

Without this, E8's season-long "model versus intuition" comparison grades the forecast against a
*memory* of what was done. That is rationalisation with a spreadsheet attached, and it reliably
flatters whichever side is doing the remembering.

The classification that matters is the third one. A difference with a logged reason is an
**override** and is evidence about judgement. A difference with no logged reason is
**unexplained** — and in practice that usually means a submission error, which is worth catching in
GW3 rather than discovering in May.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from fpl_dof.frames import as_int


class DivergenceKind(StrEnum):
    SQUAD = "squad"
    STARTING = "starting"
    CAPTAIN = "captain"
    VICE_CAPTAIN = "vice_captain"
    BENCH_ORDER = "bench_order"


class DivergenceStatus(StrEnum):
    OVERRIDE = "override"
    """Deliberate, with a recorded reason. Evidence about the owner's judgement."""

    UNEXPLAINED = "unexplained"
    """No recorded reason. Usually a submission error, and surfaced rather than absorbed."""


@dataclass(frozen=True, slots=True)
class Divergence:
    kind: DivergenceKind
    status: DivergenceStatus
    message: str
    advised: tuple[int, ...] = ()
    played: tuple[int, ...] = ()
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "status": self.status.value,
            "message": self.message,
            "advised": list(self.advised),
            "played": list(self.played),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """The stored triple for one gameweek: advised, played, and the difference."""

    gameweek: int
    entry_id: int
    advised_squad: tuple[int, ...]
    played_squad: tuple[int, ...]
    advised_starting: tuple[int, ...]
    played_starting: tuple[int, ...]
    advised_captain: int | None
    played_captain: int | None
    divergences: tuple[Divergence, ...] = field(default=())

    @property
    def followed(self) -> bool:
        return not self.divergences

    @property
    def unexplained(self) -> tuple[Divergence, ...]:
        return tuple(d for d in self.divergences if d.status is DivergenceStatus.UNEXPLAINED)

    def as_dict(self) -> dict[str, object]:
        return {
            "gameweek": self.gameweek,
            "entry_id": self.entry_id,
            "advised": {
                "squad": list(self.advised_squad),
                "starting": list(self.advised_starting),
                "captain": self.advised_captain,
            },
            "played": {
                "squad": list(self.played_squad),
                "starting": list(self.played_starting),
                "captain": self.played_captain,
            },
            "followed": self.followed,
            "divergences": [d.as_dict() for d in self.divergences],
        }


def reconcile(
    *,
    gameweek: int,
    entry_id: int,
    advised: Mapping[str, object],
    picks: pd.DataFrame,
    overrides: Mapping[str, str] | None = None,
) -> Reconciliation:
    """Diff a stored recommendation against the picks the game actually recorded.

    ``advised`` is the recommendation as it was published — squad, starting XI, captain and bench
    order. ``overrides`` maps a reason to each deliberately changed player ID, as a string key so it
    can be written by hand into configuration or a notes file without ceremony.

    ``picks`` must be the picks for **this** gameweek. Reconciling against a later gameweek's picks
    would silently attribute the next week's transfers to this week's advice.
    """
    reasons = {str(k): v for k, v in (overrides or {}).items()}

    for_gameweek = picks[picks["gameweek"] == gameweek]
    if for_gameweek.empty:
        raise ValueError(
            f"no picks recorded for gameweek {gameweek}; reconciliation runs after the deadline "
            "has passed and the gameweek's picks have been published"
        )

    played_squad = tuple(sorted(as_int(v) for v in for_gameweek["player_id"]))
    played_starting = tuple(
        sorted(as_int(row.player_id) for row in for_gameweek.itertuples() if as_int(row.slot) <= 11)
    )
    played_captain = next(
        (as_int(row.player_id) for row in for_gameweek.itertuples() if bool(row.is_captain)),
        None,
    )
    played_vice = next(
        (as_int(row.player_id) for row in for_gameweek.itertuples() if bool(row.is_vice_captain)),
        None,
    )

    advised_squad = tuple(sorted(_as_id(v) for v in _sequence(advised, "squad")))
    advised_starting = tuple(sorted(_as_id(v) for v in _sequence(advised, "starting")))
    advised_captain = _optional_int(advised.get("captain"))
    advised_vice = _optional_int(advised.get("vice_captain"))

    divergences: list[Divergence] = []
    divergences.extend(_set_divergence(DivergenceKind.SQUAD, advised_squad, played_squad, reasons))
    divergences.extend(
        _set_divergence(DivergenceKind.STARTING, advised_starting, played_starting, reasons)
    )
    divergences.extend(
        _scalar_divergence(DivergenceKind.CAPTAIN, advised_captain, played_captain, reasons)
    )
    divergences.extend(
        _scalar_divergence(DivergenceKind.VICE_CAPTAIN, advised_vice, played_vice, reasons)
    )

    return Reconciliation(
        gameweek=gameweek,
        entry_id=entry_id,
        advised_squad=advised_squad,
        played_squad=played_squad,
        advised_starting=advised_starting,
        played_starting=played_starting,
        advised_captain=advised_captain,
        played_captain=played_captain,
        divergences=tuple(divergences),
    )


def _sequence(advised: Mapping[str, object], key: str) -> list[object]:
    value = advised.get(key)
    if value is None:
        return []
    if not isinstance(value, list | tuple):
        raise TypeError(f"advised[{key!r}] must be a sequence of player IDs, got {type(value)}")
    return list(value)


def _as_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"player IDs must be numeric, got {value!r}")
    return int(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else _as_id(value)


def _set_divergence(
    kind: DivergenceKind,
    advised: tuple[int, ...],
    played: tuple[int, ...],
    reasons: Mapping[str, str],
) -> list[Divergence]:
    missing = tuple(sorted(set(advised) - set(played)))
    extra = tuple(sorted(set(played) - set(advised)))
    if not missing and not extra:
        return []

    # One divergence per changed player, not one per gameweek: a reason attaches to a decision
    # about a player, and lumping three unrelated changes together makes all three unexplainable.
    divergences = []
    for player_id in missing + extra:
        reason = reasons.get(str(player_id), "")
        what = "advised but not played" if player_id in missing else "played but not advised"
        divergences.append(
            Divergence(
                kind=kind,
                status=DivergenceStatus.OVERRIDE if reason else DivergenceStatus.UNEXPLAINED,
                message=f"{kind.value}: player {player_id} was {what}",
                advised=advised,
                played=played,
                reason=reason,
            )
        )
    return divergences


def _scalar_divergence(
    kind: DivergenceKind,
    advised: int | None,
    played: int | None,
    reasons: Mapping[str, str],
) -> list[Divergence]:
    if advised == played:
        return []
    reason = reasons.get(str(played), "") or reasons.get(kind.value, "")
    return [
        Divergence(
            kind=kind,
            status=DivergenceStatus.OVERRIDE if reason else DivergenceStatus.UNEXPLAINED,
            message=f"{kind.value}: advised {advised}, played {played}",
            advised=() if advised is None else (advised,),
            played=() if played is None else (played,),
            reason=reason,
        )
    ]


def describe(reconciliation: Reconciliation) -> list[str]:
    if reconciliation.followed:
        return [f"Gameweek {reconciliation.gameweek}: advice followed exactly."]
    lines = [f"Gameweek {reconciliation.gameweek}: {len(reconciliation.divergences)} difference(s)"]
    for divergence in reconciliation.divergences:
        suffix = f" — {divergence.reason}" if divergence.reason else ""
        lines.append(f"  [{divergence.status.value}] {divergence.message}{suffix}")
    unexplained = reconciliation.unexplained
    if unexplained:
        lines.append(
            f"  {len(unexplained)} difference(s) have no recorded reason. If they were not "
            "deliberate, this is a submission error worth investigating now."
        )
    return lines


__all__ = [
    "Divergence",
    "DivergenceKind",
    "DivergenceStatus",
    "Reconciliation",
    "describe",
    "reconcile",
]
