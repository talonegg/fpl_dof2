"""Penalty and set-piece duty: the committed reference table, as the model sees it (E10-S3, DL-50).

The table itself is ``config/defaults/duty.yaml`` — curated knowledge with an owner-maintenance note
in it, like the rules seed and unlike a feed. This module is the only thing that reads it, and all
it does is answer one question: **did this player hold this duty at this deadline?**

Two properties matter more than anything else here.

**The date is not decoration.** A hand-maintained table is written in the present and a backtest
runs in the past, so applying today's duty to a 2024 gameweek is look-ahead — Invariant 5 broken by
a config file rather than by a feature, and just as fatal. Every entry carries the date its
assignment became publicly knowable and the lookup is against the deadline being scored, so a spell
that had not started yet simply is not there.

**Absence means unknown, not "no duty."** Most players have no entry and never will. The term the
table feeds is additive, so a player with no entry gets nothing added rather than something taken
away, and the coverage figures below exist so that a thin table is visible in the report rather than
looking like a confident statement that nobody takes penalties (DP-09, DP-15).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from fpl_dof.config.models import DutyConfig, DutyEntryConfig, PenaltyDutyConfig

#: The duty the E10-S3 term models. The others are accepted by the table and consumed by nothing.
PENALTIES = "penalties"

#: Only the first taker contributes. See ``DutyEntryConfig.order`` for why a second one does not.
FIRST_TAKER = 1


@dataclass(frozen=True, slots=True)
class DutyAssignment:
    """One player's active duty at one moment, with the weight its evidence earns.

    Carries ``weight`` rather than the confidence label alone so that the scorer never has to hold
    an opinion about what "likely" is worth — that mapping is configuration, in one place.
    """

    player_code: int
    duty: str
    order: int
    confidence: str
    weight: float

    @property
    def contributes(self) -> bool:
        """Whether this assignment can move a forecast at all.

        False for an unknown confidence tier, which weighs zero deliberately: a tier nobody has
        priced is not a licence to price it at full.
        """
        return self.weight > 0.0


class DutyTable:
    """The reference table, indexed for lookup by player and date.

    Built once per fit and read per row. Built from the configuration rather than from a file path,
    so this class does no I/O and a test can hand it three entries (DP-03).
    """

    def __init__(self, config: DutyConfig, penalties: PenaltyDutyConfig) -> None:
        self._weights = dict(penalties.confidence_weights)
        self._by_player: dict[int, list[DutyEntryConfig]] = {}
        for entry in config.entries:
            self._by_player.setdefault(entry.player_code, []).append(entry)

    def penalty_duty(self, player_code: int, as_of: object) -> DutyAssignment | None:
        """The player's first-taker penalty duty at ``as_of``, or ``None``.

        ``as_of`` is the deadline being scored, and a row that cannot say when it is being scored
        gets nothing: a missing date is not permission to apply an undated assertion to an
        unknown moment, which is precisely how a table like this leaks the future into a backtest.
        """
        moment = _as_date(as_of)
        if moment is None:
            return None
        for entry in self._by_player.get(player_code, ()):
            if entry.duty != PENALTIES or entry.order != FIRST_TAKER:
                continue
            if entry.known_from > moment:
                continue
            if entry.known_until is not None and entry.known_until <= moment:
                continue
            return DutyAssignment(
                player_code=entry.player_code,
                duty=entry.duty,
                order=entry.order,
                confidence=entry.confidence,
                weight=float(self._weights.get(entry.confidence, 0.0)),
            )
        return None

    def describe(self) -> dict[str, object]:
        """What the model card and the backtest card say about how much this table knows.

        Reported because a table that has quietly emptied — an override that replaced the list, a
        season whose spells have all lapsed — produces a term that is silently inert, and a silently
        inert candidate is one that gets graded as "no effect" for the wrong reason (DP-15).
        """
        entries = [entry for spells in self._by_player.values() for entry in spells]
        by_confidence: dict[str, int] = {}
        for entry in entries:
            by_confidence[entry.confidence] = by_confidence.get(entry.confidence, 0) + 1
        return {
            "entries": len(entries),
            "players": len(self._by_player),
            "penalty_takers": sum(
                1 for entry in entries if entry.duty == PENALTIES and entry.order == FIRST_TAKER
            ),
            "by_confidence": dict(sorted(by_confidence.items())),
            "confidence_weights": dict(sorted(self._weights.items())),
        }


def _as_date(value: object) -> dt.date | None:
    """A date from whatever the feature store put in ``as_of``, or ``None`` when there is none."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        # Null-checked *inside* the datetime branch, because ``pd.NaT`` is a ``datetime`` as far as
        # ``isinstance`` is concerned. Calling ``.date()`` on it returns another null, which
        # compares as neither before nor after any spell — a date check that silently answers no.
        return None if pd.isna(value) else value.date()
    if isinstance(value, dt.date):
        return value
    try:
        stamp = pd.Timestamp(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None
    return None if pd.isna(stamp) else stamp.date()


__all__ = ["FIRST_TAKER", "PENALTIES", "DutyAssignment", "DutyTable"]
