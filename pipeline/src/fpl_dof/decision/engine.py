"""The decision engine's one entry point: :func:`decide` (MOD-04, DL-86).

Every strategy's advice comes from here — the champion's and every challenger's — so two strategies
on screen differ only by the forecast frame and the policy their registry entries name (05 §5.1).
It produces the week (transfers and hits, XI and bench, captain and vice) and, unless the policy
says ``plan: false``, the multi-gameweek plan with its chip calendar.

Pure: frames and values in, a :class:`Decision` out. No file is read and no config is loaded here;
the policy arrives resolved (DP-03).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fpl_dof.config.models import DecisionConfig, OptimiserConfig, TransferConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.captain import (
    PricePositionLine,
    apply_price_position_captain,
    relabel_selection,
)
from fpl_dof.optimise.plan import DecisionPlan, build_plan
from fpl_dof.optimise.squad import InfeasibleError
from fpl_dof.optimise.transfer import TransferRecommendation, recommend_transfers
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.squad.selection import Candidate, Selection, SelectionError, select_team
from fpl_dof.squad.state import SquadState

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """A strategy's decision policy, resolved against the run's config by the model factory."""

    plan: bool
    """Whether the multi-gameweek plan and chips are solved."""
    captain_line: PricePositionLine | None
    """B0 for the price-and-position captain rule; ``None`` means the solver's own captain."""
    transfers: TransferConfig
    optimiser: OptimiserConfig
    decision: DecisionConfig
    start_probability_floor: float
    """Players below this start probability are kept out of the XI, where the optimiser says so."""


@dataclass(frozen=True, slots=True)
class Decision:
    """One strategy's advice for one snapshot."""

    recommendation: TransferRecommendation
    selection: Selection
    """The XI, bench, captain and vice for the squad after the recommended transfers."""
    warnings: tuple[str, ...]
    """What the week's advice had to give up, beyond the recommendation's own warnings."""
    plan: DecisionPlan | None
    plan_skipped_reason: str | None
    """Why a policy that plans has no plan (an infeasible horizon); ``None`` otherwise."""


def decide(
    frame: pd.DataFrame,
    squad_state: SquadState,
    rules: GameRules,
    policy: DecisionPolicy,
    *,
    fixtures: pd.DataFrame | None = None,
    chips: pd.DataFrame | None = None,
    last_gameweek: int | None = None,
) -> Decision:
    """The week, and the plan unless the policy skips it, from one forecast frame.

    ``fixtures``, ``chips`` and ``last_gameweek`` feed the plan's chip calendar only. An infeasible
    plan is a stated reason, not a failure: the week stands without it (DP-15). Anything else that
    goes wrong raises, and the caller decides what a failure costs.
    """
    frame = frame.assign(start_floor=policy.start_probability_floor)
    recommendation = recommend_transfers(
        frame, squad_state, rules, policy.transfers, policy.optimiser
    )
    scores = policy.captain_line.scores(frame) if policy.captain_line is not None else None
    if scores is not None:
        recommendation = apply_price_position_captain(
            recommendation, frame, scores, rules.chips.captain_multiplier
        )
    selection, warnings = _select(frame, recommendation, rules, policy)
    if scores is not None:
        pairs = zip(frame["player_id"], frame["xp_next"], strict=True)
        xp_next = {as_int(i): as_float(v) for i, v in pairs}
        selection = relabel_selection(selection, scores, xp_next, rules.chips.captain_multiplier)

    plan: DecisionPlan | None = None
    reason: str | None = None
    if policy.plan:
        plan, reason = solve_plan(
            frame,
            squad_state,
            rules,
            policy,
            fixtures=fixtures,
            chips=chips,
            last_gameweek=last_gameweek,
        )
    return Decision(
        recommendation=recommendation,
        selection=selection,
        warnings=warnings,
        plan=plan,
        plan_skipped_reason=reason,
    )


def solve_plan(
    frame: pd.DataFrame,
    squad_state: SquadState,
    rules: GameRules,
    policy: DecisionPolicy,
    *,
    fixtures: pd.DataFrame | None = None,
    chips: pd.DataFrame | None = None,
    last_gameweek: int | None = None,
) -> tuple[DecisionPlan | None, str | None]:
    """The plan step of :func:`decide` on its own: the plan, or ``None`` and why it is infeasible.

    The week does not depend on it, so an orchestrator may publish the week before planning.
    """
    try:
        plan = build_plan(
            players=frame.assign(start_floor=policy.start_probability_floor),
            state=squad_state,
            rules=rules,
            decision=policy.decision,
            optimiser=policy.optimiser,
            fixtures=fixtures,
            chips=chips,
            last_gameweek=last_gameweek,
            # The most-captained player id is published upstream but the silver gameweek table
            # does not carry it yet (D-15). None rather than guessed: DL-24's callout says what it
            # knows, and "not available" is one of the things it can know.
            most_captained_id=None,
        )
    except InfeasibleError as exc:
        log.warning("decide.plan_infeasible", extra={"reason": str(exc)})
        return None, str(exc)
    return plan, None


def _select(
    frame: pd.DataFrame,
    recommendation: TransferRecommendation,
    rules: GameRules,
    policy: DecisionPolicy,
) -> tuple[Selection, tuple[str, ...]]:
    """The XI for the squad after the recommended transfers; the floor relaxed only if it must."""
    lookup = frame.set_index("player_id")
    candidates = {
        player_id: Candidate(
            player_id=player_id,
            position=Position(str(lookup.loc[player_id, "position"])),
            expected_points=as_float(lookup.loc[player_id, "xp_next"]),
            start_probability=as_float(lookup.loc[player_id, "start_probability"]),
            web_name=str(lookup.loc[player_id, "web_name"]),
        )
        for player_id in recommendation.recommended.squad_after
    }
    optimiser = policy.optimiser
    floor = policy.start_probability_floor if optimiser.enforce_start_probability_floor else 0.0
    locked = frozenset(optimiser.locked_player_ids)
    try:
        selection = select_team(
            candidates,
            rules,
            start_probability_floor=floor,
            locked_player_ids=locked,
        )
        return selection, ()
    except SelectionError as exc:
        # The advised squad cannot field an XI above the floor. Pick the best XI it *can* field
        # and say so, rather than publishing nothing in the week it matters (DP-15).
        log.warning("decide.floor_relaxed", extra={"reason": str(exc)})
        selection = select_team(
            candidates,
            rules,
            start_probability_floor=0.0,
            locked_player_ids=locked,
        )
        return selection, (
            f"the advised XI is chosen with the start-probability floor relaxed: {exc}",
        )


__all__ = ["Decision", "DecisionPolicy", "decide", "solve_plan"]
