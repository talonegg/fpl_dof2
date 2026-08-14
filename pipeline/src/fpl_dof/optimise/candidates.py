"""E4-S1 — candidate pruning.

Roughly 700 players over a 5-8 gameweek horizon is not solvable inside a CI time budget (CON-4,
R-07). The shortlist has to be smaller. The whole difficulty is making it smaller **without making
it biased**, and the bias that matters is not the obvious one.

A pure expected-points ranking keeps the premiums and drops the £4.0m defender who never plays. That
looks harmless and is not: cheap enablers are what *pays* for the premiums, so a pool without them
is a pool in which the best squad is unaffordable and the solver silently returns the second-best
one. Design §6.1 names them explicitly for that reason, and so does this module.

Five inclusion rules, unioned:

* everything currently owned — or the model cannot evaluate keeping it;
* everything user-locked — an explicit human instruction outranks any ranking;
* the top N per position on horizon expected points;
* the top N per position on expected points per £m;
* the best of the **cheap band** per position, taken on merit *within* the band.

**The pruning rule is itself validated** (Design §6.1): :func:`pruning_matches_full_pool` re-solves
on the unpruned set and reports whether the answer moved. It is deliberately a function rather than
a scheduled job, because it is slow and belongs in an offline check rather than the deadline path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from fpl_dof.config.models import CandidateConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import Position

log = get_logger(__name__)

REASON_OWNED = "owned"
REASON_LOCKED = "locked"
REASON_POINTS = "top_by_points"
REASON_VALUE = "top_by_value"
REASON_ENABLER = "cheap_enabler"


@dataclass(frozen=True, slots=True)
class PruningReport:
    """What the pool is, and why each player is in it. Reported so bias is visible (DP-09)."""

    pool_size: int
    full_size: int
    counts_by_reason: dict[str, int]
    counts_by_position: dict[str, int]
    target_size: int

    @property
    def within_target(self) -> bool:
        """Whether the pool is near the size the configured rules are tuned to produce."""
        return self.pool_size <= self.target_size

    def as_dict(self) -> dict[str, object]:
        return {
            "pool_size": self.pool_size,
            "full_size": self.full_size,
            "target_size": self.target_size,
            "within_target": self.within_target,
            "by_reason": dict(self.counts_by_reason),
            "by_position": dict(self.counts_by_position),
        }


def prune_candidates(
    players: pd.DataFrame,
    config: CandidateConfig,
    *,
    owned: Iterable[int] = (),
    locked: Iterable[int] = (),
    banned: Iterable[int] = (),
    excluded_team_ids: Iterable[int] = (),
) -> tuple[pd.DataFrame, PruningReport]:
    """Reduce ``players`` to a tractable pool, and say how it was built.

    Bans and club exclusions are applied here rather than left to the solver, with one exception
    that is not negotiable: **an owned or locked player is never dropped**. A ban on a player you
    already hold is an instruction to sell him, and the model cannot decide to sell a player it
    cannot see.
    """
    frame = players.reset_index(drop=True).copy()
    owned_ids = {int(i) for i in owned}
    locked_ids = {int(i) for i in locked}
    protected = owned_ids | locked_ids
    banned_ids = {int(i) for i in banned} - protected
    excluded = {int(i) for i in excluded_team_ids}

    eligible = frame[
        ~frame["player_id"].isin(banned_ids)
        & (~frame["team_id"].isin(excluded) | frame["player_id"].isin(protected))
    ].copy()

    reasons: dict[int, str] = {}

    def keep(ids: Iterable[int], reason: str) -> None:
        for player_id in ids:
            reasons.setdefault(int(player_id), reason)

    keep(sorted(owned_ids & set(frame["player_id"])), REASON_OWNED)
    keep(sorted(locked_ids & set(frame["player_id"])), REASON_LOCKED)

    merit = eligible[eligible["xp_horizon"] >= config.minimum_expected_points].copy()
    merit["value"] = merit["xp_horizon"] / merit["price"].clip(lower=0.1)

    for position in Position:
        members = merit[merit["position"] == position.value]
        keep(
            _head_ids(members, "xp_horizon", config.top_n_per_position_by_points),
            REASON_POINTS,
        )
        keep(_head_ids(members, "value", config.top_n_per_position_by_value), REASON_VALUE)
        keep(_cheap_band(members, config), REASON_ENABLER)

    pool = frame[frame["player_id"].isin(reasons)].reset_index(drop=True)
    counts_by_reason: dict[str, int] = {}
    for reason in reasons.values():
        counts_by_reason[reason] = counts_by_reason.get(reason, 0) + 1
    counts_by_position = {
        str(position): int(count) for position, count in pool["position"].value_counts().items()
    }

    report = PruningReport(
        pool_size=len(pool),
        full_size=len(frame),
        counts_by_reason=counts_by_reason,
        counts_by_position=counts_by_position,
        target_size=config.target_pool_size,
    )
    log.info("candidates.pruned", extra=report.as_dict())
    return pool, report


def _head_ids(members: pd.DataFrame, column: str, count: int) -> list[int]:
    """Top ``count`` by ``column``. Ties broken by player id, so the pool is reproducible."""
    if members.empty or count <= 0:
        return []
    ordered = members.sort_values([column, "player_id"], ascending=[False, True])
    return [as_int(value) for value in ordered.head(count)["player_id"]]


def _cheap_band(members: pd.DataFrame, config: CandidateConfig) -> list[int]:
    """The best players in the cheap band, on merit *within* the band.

    Taken on expected points inside the band rather than on cheapness alone: the enabler that
    matters is the cheapest player who will actually appear, not the cheapest player.
    """
    if members.empty or config.cheap_enablers_per_position <= 0:
        return []
    threshold = as_float(members["price"].quantile(config.cheap_enabler_price_quantile))
    band = members[members["price"] <= threshold]
    return _head_ids(band, "xp_horizon", config.cheap_enablers_per_position)


def pruning_matches_full_pool(
    solve: object,
    *,
    pruned: pd.DataFrame,
    full: pd.DataFrame,
) -> bool:
    """Design §6.1's validation of the pruning rule itself, as a comparison of two squads.

    ``solve`` is any callable taking a player frame and returning the chosen player ids. Kept
    solver-agnostic so this can check the single-gameweek squad optimiser, the multi-gameweek plan,
    or a future one, without this module importing any of them.
    """
    if not callable(solve):
        raise TypeError("solve must be callable")
    chosen_pruned = frozenset(int(i) for i in solve(pruned))
    chosen_full = frozenset(int(i) for i in solve(full))
    if chosen_pruned != chosen_full:
        log.warning(
            "candidates.pruning_diverged",
            extra={
                "only_in_pruned": sorted(chosen_pruned - chosen_full),
                "only_in_full": sorted(chosen_full - chosen_pruned),
            },
        )
    return chosen_pruned == chosen_full


__all__ = [
    "REASON_ENABLER",
    "REASON_LOCKED",
    "REASON_OWNED",
    "REASON_POINTS",
    "REASON_VALUE",
    "PruningReport",
    "prune_candidates",
    "pruning_matches_full_pool",
]
