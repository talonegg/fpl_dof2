"""The decision engine, assembled. E4-S1 through E4-S6.

One function, :func:`build_plan`, in the order the epic builds it:

1. **Prune** ~700 players to a tractable pool without dropping the cheap enablers (E4-S1).
2. **Enumerate** the plausible ``(chip, gameweek)`` scenarios, expiry read from the game (E4-S3).
3. **Solve** the multi-gameweek MILP conditional on each, on HiGHS (E4-S2), plus a *hold everything*
   baseline so that "do nothing" is a ranked option with a number on it rather than a fallback.
4. **Simulate** each surviving plan with draws correlated within a match, and re-rank on the
   percentile the risk dial asks for (E4-S4a).
5. **Choose**, subject to the incumbency margin: a transfer clears a margin or it does not happen.
6. **Explain** — decomposition, marginal gain, runners-up and why they lost, the ownership bet, the
   price exposure, the assumptions, and the D-13 caveat wherever a hit, chip or wildcard appears
   (E4-S4, E4-S6).

The order matters in one non-obvious way. The re-rank runs **after** the MILP and **before** the
choice, so the simulation can overturn a chip decision the expectation-maximiser got wrong, but
cannot overturn the incumbency margin — a plan that only wins on a simulated percentile by 0.1
points is still churn.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from fpl_dof.config.models import DecisionConfig, OptimiserConfig
from fpl_dof.frames import as_float, as_int, gameweek_column, gameweek_sd_column
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.candidates import PruningReport, prune_candidates
from fpl_dof.optimise.chips import (
    ChipCalendar,
    ChipScenario,
    GameweekShape,
    build_calendar,
    chip_label,
    chip_windows,
    enumerate_scenarios,
    gameweek_shapes,
)
from fpl_dof.optimise.explain import (
    Contribution,
    Explanation,
    RunnerUp,
    caveats_for,
    chip_margin_sentence,
    price_exposure,
    start_probability_assumptions,
)
from fpl_dof.optimise.horizon import (
    HorizonInputs,
    HorizonPlan,
    PlannedWeek,
    plan_gameweeks,
    solve_horizon,
)
from fpl_dof.optimise.risk import OwnershipBet, ownership_bet
from fpl_dof.optimise.simulate import PlayerDraw, SimulationResult, match_key, rank, simulate
from fpl_dof.optimise.squad import InfeasibleError
from fpl_dof.rules.models import GameRules
from fpl_dof.squad.state import SquadState

log = get_logger(__name__)

BASELINE_KEY = "hold"


@dataclass(frozen=True, slots=True)
class ScoredPlan:
    """One candidate plan and what the simulation made of it."""

    key: str
    plan: HorizonPlan
    simulation: SimulationResult | None

    @property
    def label(self) -> str:
        return (
            "roll everything (no transfer, no chip)"
            if self.key == BASELINE_KEY
            else (self.plan.scenario.label)
        )

    @property
    def score(self) -> float:
        """What the plan is ranked on: the simulated percentile where there is one."""
        if self.simulation is None:
            return self.plan.total_expected_points
        return self.simulation.score


@dataclass(frozen=True, slots=True)
class DecisionPlan:
    """The whole E4 output: a multi-gameweek plan, a chip calendar, and the argument for both."""

    gameweeks: tuple[int, ...]
    recommended: ScoredPlan
    baseline: ScoredPlan
    alternatives: tuple[ScoredPlan, ...]
    calendar: ChipCalendar
    explanation: Explanation
    ownership: OwnershipBet
    pruning: PruningReport
    solver: str
    solve_seconds: float
    rationale: str
    warnings: tuple[str, ...] = field(default=())

    @property
    def is_hold(self) -> bool:
        return self.recommended.key == BASELINE_KEY

    @property
    def chips_recommended(self) -> tuple[tuple[int, str], ...]:
        return self.recommended.plan.scenario.assignments


def build_plan(
    *,
    players: pd.DataFrame,
    state: SquadState,
    rules: GameRules,
    decision: DecisionConfig,
    optimiser: OptimiserConfig,
    fixtures: pd.DataFrame | None = None,
    chips: pd.DataFrame | None = None,
    last_gameweek: int | None = None,
    most_captained_id: int | None = None,
) -> DecisionPlan:
    """Produce the multi-gameweek plan, the chip calendar, and the explanation for both."""
    started = time.monotonic()
    weeks = plan_gameweeks(state, decision, last_gameweek)
    if not weeks:
        raise InfeasibleError("the horizon is empty: the season has no gameweeks left to plan for")

    pool, pruning = prune_candidates(
        players,
        decision.candidates,
        owned=state.player_ids(),
        locked=optimiser.locked_player_ids,
        banned=optimiser.banned_player_ids,
        excluded_team_ids=optimiser.excluded_team_ids,
    )
    inputs = HorizonInputs(players=pool, state=state, rules=rules, gameweeks=weeks)
    decision, cap_warnings = _relax_impossible_club_cap(state, rules, decision)

    shapes = _shapes(fixtures, players)
    windows = chip_windows(chips)
    scenarios = enumerate_scenarios(
        horizon=weeks,
        windows=windows,
        chips_used=state.chips_used,
        shapes=shapes,
        squad_team_ids=_squad_clubs(players, state),
        config=decision.chips,
    )

    warnings: list[str] = list(cap_warnings)
    baseline = _solve_baseline(inputs, decision, optimiser)
    scored: dict[str, ScoredPlan] = {BASELINE_KEY: ScoredPlan(BASELINE_KEY, baseline, None)}
    order = [BASELINE_KEY]

    budget = decision.horizon.scenario_time_budget_seconds
    for index, scenario in enumerate(scenarios):
        if time.monotonic() - started > budget:
            warnings.append(
                f"the {budget}s scenario budget was reached after {index} of {len(scenarios)} "
                "chip scenarios; the remainder were not solved and cannot have been recommended"
            )
            break
        key = _scenario_key(scenario)
        if key in scored:
            continue
        try:
            plan = solve_horizon(inputs, scenario, decision, optimiser)
        except InfeasibleError as exc:
            warnings.append(f"{scenario.label or 'no chip'} is infeasible: {exc}")
            continue
        scored[key] = ScoredPlan(key, plan, None)
        order.append(key)

    scored = _simulate_all(scored, pool, decision, weeks)
    ordered = _order(scored, order)

    recommended, rationale = _choose(ordered, scored[BASELINE_KEY], decision)
    calendar = build_calendar(
        from_gameweek=weeks[0],
        windows=windows,
        chips_used=state.chips_used,
        shapes=shapes,
        config=decision.chips,
    )
    bet = _ownership(players, state, recommended, decision, most_captained_id)
    explanation = _explain(
        recommended=recommended,
        baseline=scored[BASELINE_KEY],
        alternatives=ordered,
        players=players,
        state=state,
        decision=decision,
        bet=bet,
        rationale=rationale,
    )

    elapsed = time.monotonic() - started
    if recommended.plan.is_fallback:
        warnings.append(
            "the recommended plan came from the greedy fallback, not the solver: it is legal and "
            "on time, and it is not optimal (DP-15)"
        )
    warnings.extend(recommended.plan.warnings)

    log.info(
        "plan.built",
        extra={
            "gameweeks": list(weeks),
            "scenarios": len(scored),
            "recommended": recommended.label,
            "seconds": round(elapsed, 2),
            "solver": decision.horizon.solver,
        },
    )
    return DecisionPlan(
        gameweeks=weeks,
        recommended=recommended,
        baseline=scored[BASELINE_KEY],
        alternatives=tuple(plan for plan in ordered if plan.key != recommended.key),
        calendar=calendar,
        explanation=explanation,
        ownership=bet,
        pruning=pruning,
        solver=decision.horizon.solver,
        solve_seconds=round(elapsed, 3),
        rationale=rationale,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------- solving


def _solve_baseline(
    inputs: HorizonInputs, decision: DecisionConfig, optimiser: OptimiserConfig
) -> HorizonPlan:
    """ "Do nothing" as an option with a number on it, not as the absence of a recommendation.

    Solved rather than assumed, because holding the squad still involves picking a starting XI and a
    captain every week, and those are real decisions worth several points across a horizon.
    """
    held = decision.model_copy(
        update={"horizon": decision.horizon.model_copy(update={"max_transfers_per_gameweek": 0})}
    )
    return solve_horizon(inputs, ChipScenario(), held, optimiser)


def _order(scored: Mapping[str, ScoredPlan], milp_order: Sequence[str]) -> list[ScoredPlan]:
    """Rank the candidates, by the simulated percentile where there is one.

    With the simulation turned off this falls back to the discounted expected points the MILP
    itself produced, with the solve order as the tie-break. Falling back rather than returning
    nothing matters: a configuration that disables the re-rank must still rank the chip scenarios,
    or turning off an enhancement would quietly turn off the chip planner with it.
    """
    simulations = {key: value.simulation for key, value in scored.items() if value.simulation}
    if simulations and len(simulations) == len(scored):
        return [scored[key] for key in rank(simulations, milp_order)]
    position = {key: index for index, key in enumerate(milp_order)}
    return sorted(
        scored.values(),
        key=lambda item: (
            -item.plan.total_expected_points,
            position.get(item.key, len(position)),
            item.key,
        ),
    )


def _relax_impossible_club_cap(
    state: SquadState, rules: GameRules, decision: DecisionConfig
) -> tuple[DecisionConfig, list[str]]:
    """Raise C16 to the tightest value the *current* squad can actually field an XI under.

    C16 caps the starting XI at two players per club. A squad concentrated in few clubs can fail
    that outright — five clubs at three players each can field ten, not eleven — and then *doing
    nothing* becomes infeasible, which is the one option that must always exist. Degrading the
    constraint with a stated reason is right; refusing to produce a plan is not (DP-15).

    Raised rather than dropped: the smallest value that works keeps as much of C16 as the squad
    permits, and the warning says exactly which clubs forced it.
    """
    limit = decision.risk.same_club_starting_limit
    exempt = set(decision.risk.relax_club_cap_team_ids)
    counts: dict[int, int] = {}
    for player in state.players:
        counts[player.team_id] = counts.get(player.team_id, 0) + 1

    def reachable(value: int) -> int:
        return sum(count if club in exempt else min(count, value) for club, count in counts.items())

    if not counts or reachable(limit) >= rules.squad.starting_size:
        return decision, []

    needed = limit
    while needed < rules.squad.size and reachable(needed) < rules.squad.starting_size:
        needed += 1
    crowded = sorted(club for club, count in counts.items() if count > limit)
    relaxed = decision.model_copy(
        update={"risk": decision.risk.model_copy(update={"same_club_starting_limit": needed})}
    )
    return relaxed, [
        f"the same-club starting cap (C16) was relaxed from {limit} to {needed}: the current squad "
        f"holds more than {limit} players at club(s) {crowded} and could not otherwise field a "
        f"legal XI, which would have made doing nothing infeasible"
    ]


def _scenario_key(scenario: ChipScenario) -> str:
    if scenario.is_empty:
        return "no_chip"
    return "+".join(f"{name}@{week}" for week, name in scenario.assignments)


def _choose(
    ordered: list[ScoredPlan], baseline: ScoredPlan, decision: DecisionConfig
) -> tuple[ScoredPlan, str]:
    """Pick the winner, and say in one sentence why it won.

    **The incumbency margin lives here, not in the objective.** The ε term inside the MILP breaks
    ties between equally good squads so the same inputs return the same answer; this is the
    separate,
    reportable rule that a transfer must clear a *margin* rather than merely tie. Enforcing it here
    is what lets the reason be stated rather than inferred from a number nobody can see.
    """
    margin = decision.horizon.transfer_margin
    reference = baseline.score
    for candidate in ordered:
        if candidate.key == BASELINE_KEY:
            continue
        gain = candidate.score - reference
        if gain <= margin:
            continue
        chips = candidate.plan.scenario.chips
        transfers = sum(len(week.transfers_in) for week in candidate.plan.weeks)
        detail = []
        if chips:
            detail.append(candidate.plan.scenario.label)
        if transfers:
            detail.append(f"{transfers} transfer(s) over the horizon")
        return candidate, (
            f"{' with '.join(detail) or 'this plan'} gains {gain:.2f} points over holding, "
            f"clearing the {margin:.2f}-point margin a change has to beat"
        )

    return baseline, (
        f"nothing clears the {margin:.2f}-point margin over holding the squad, so the plan is to "
        "roll: a transfer has to beat doing nothing by a margin, not merely tie it"
    )


# ---------------------------------------------------------------------- simulation


def _simulate_all(
    scored: Mapping[str, ScoredPlan],
    pool: pd.DataFrame,
    decision: DecisionConfig,
    weeks: tuple[int, ...],
) -> dict[str, ScoredPlan]:
    if not decision.simulation.enabled:
        return dict(scored)

    lookup = {as_int(row.player_id): row for row in pool.itertuples()}
    result: dict[str, ScoredPlan] = {}
    for offset, (key, candidate) in enumerate(sorted(scored.items())):
        entries: list[PlayerDraw] = []
        for week in candidate.plan.weeks:
            entries.extend(_draws(week, lookup, decision, weeks))
        simulation = simulate(
            entries, decision.simulation, dial=decision.risk.dial, seed_offset=offset
        )
        result[key] = ScoredPlan(key=key, plan=candidate.plan, simulation=simulation)
    return result


def _draws(
    week: PlannedWeek,
    lookup: Mapping[int, object],
    decision: DecisionConfig,
    weeks: tuple[int, ...],
) -> list[PlayerDraw]:
    """One gameweek of a plan, as sampling entries. Discounted exactly as the objective is."""
    discount = decision.horizon.discount ** weeks.index(week.gameweek)
    captain_multiplier = decision.chips.captain_multiplier_by_chip.get(week.chip or "", 2)
    bench_weight = 1.0 if week.chip == "bboost" else decision.horizon.bench_weight
    starting = set(week.starting)

    entries: list[PlayerDraw] = []
    for player_id in week.fielded:
        row = lookup.get(player_id)
        if row is None:
            continue
        mean = _column(row, gameweek_column(week.gameweek))
        sd = _column(row, gameweek_sd_column(week.gameweek))
        if player_id == week.captain_id:
            weight = float(captain_multiplier)
        elif player_id in starting:
            weight = 1.0
        else:
            weight = bench_weight
        entries.append(
            PlayerDraw(
                player_id=player_id,
                mean=mean,
                standard_deviation=sd,
                match_key=match_key(as_int(getattr(row, "team_id", 0)), week.gameweek),
                multiplier=weight * discount,
            )
        )
    return entries


def _column(row: object, name: str) -> float:
    value = getattr(row, name, 0.0)
    try:
        return as_float(value)
    except TypeError, ValueError:  # pragma: no cover - defensive
        return 0.0


# ---------------------------------------------------------------------- explanation


def _ownership(
    players: pd.DataFrame,
    state: SquadState,
    recommended: ScoredPlan,
    decision: DecisionConfig,
    most_captained_id: int | None,
) -> OwnershipBet:
    first = recommended.plan.first
    names = {
        as_int(row.player_id): str(getattr(row, "web_name", row.player_id))
        for row in players.itertuples()
    }
    shares = {
        as_int(row.player_id): as_float(getattr(row, "selected_by_percent", 0.0) or 0.0)
        for row in players.itertuples()
    }
    # Only the part of the field worth talking about: everybody at 0.2% is noise, and listing them
    # buries the 45%-owned forward you have left out, which is the only exposure that moves rank.
    material = {
        player_id: share
        for player_id, share in shares.items()
        if share >= 5.0 or player_id in set(first.fielded) | state.player_ids()
    }
    return ownership_bet(
        squad=first.fielded,
        starting=first.starting,
        ownership=material,
        names=names,
        config=decision.risk,
        most_captained_id=most_captained_id,
    )


def _explain(
    *,
    recommended: ScoredPlan,
    baseline: ScoredPlan,
    alternatives: list[ScoredPlan],
    players: pd.DataFrame,
    state: SquadState,
    decision: DecisionConfig,
    bet: OwnershipBet,
    rationale: str,
) -> Explanation:
    first = recommended.plan.first
    lookup = {as_int(row.player_id): row for row in players.itertuples()}
    names = {
        player_id: str(getattr(row, "web_name", player_id)) for player_id, row in lookup.items()
    }
    starts = {
        player_id: as_float(getattr(row, "start_probability", 1.0))
        for player_id, row in lookup.items()
    }

    decomposition = _decompose(recommended.plan, decision)
    runners_up = _runners_up(recommended, baseline, alternatives)
    bought = [as_float(lookup[i].price) for i in first.transfers_in if i in lookup]
    held_prices = {player.player_id: player.current_price for player in state.players}
    sold = [
        held_prices.get(
            player_id, as_float(lookup[player_id].price) if player_id in lookup else 0.0
        )
        for player_id in first.transfers_out
    ]

    chips = recommended.plan.scenario.chips
    takes_hit = any(week.hit_points < 0 for week in recommended.plan.weeks)
    caveats = caveats_for(takes_hit=takes_hit, chips_played=chips)

    headline = rationale
    if chips:
        chip_runner = next((item for item in runners_up if item.label != baseline_label()), None)
        versus_nothing = round(recommended.score - baseline.score, 2)
        week, name = recommended.plan.scenario.assignments[0]
        headline = chip_margin_sentence(
            chip=name, gameweek=week, runner_up=chip_runner, versus_nothing=versus_nothing
        )

    assumptions = [
        f"The plan is judged over gameweeks {recommended.plan.gameweeks[0]}-"
        f"{recommended.plan.gameweeks[-1]}, discounted {decision.horizon.discount:.2f} per week: "
        "later weeks are less knowable and count for less.",
        "Prices are held fixed across the horizon; a player bought inside it is assumed to sell "
        "for what he cost.",
        f"Starting XI at most {decision.risk.same_club_starting_limit} player(s) per club (C16), "
        "which is the only part of match correlation a linear model can express.",
    ]
    assumptions.extend(
        start_probability_assumptions(first.starting, names=names, start_probability=starts)
    )
    if recommended.simulation is not None:
        quantile = decision.simulation.percentile_by_dial.get(decision.risk.dial, 0.5)
        assumptions.append(
            f"Plans are re-ranked on the {quantile:.0%} percentile of {decision.simulation.draws} "
            "simulated outcomes with draws correlated within a match, not on expected points alone."
        )

    return Explanation(
        headline=headline,
        marginal_gain_over_doing_nothing=round(recommended.score - baseline.score, 3),
        decomposition=decomposition,
        runners_up=runners_up,
        ownership_bet=bet,
        price_exposure=price_exposure(bought=bought, sold=sold, bank_after=first.bank_after),
        assumptions=tuple(assumptions),
        caveats=caveats,
    )


def baseline_label() -> str:
    return "roll everything (no transfer, no chip)"


def _decompose(plan: HorizonPlan, decision: DecisionConfig) -> tuple[Contribution, ...]:
    """Where the plan's points come from, week by week and in aggregate."""
    items = [
        Contribution(
            label=f"GW{week.gameweek}",
            points=week.net_expected_points,
            detail=(
                f"XI and captain {week.expected_points:.2f}"
                + (f", hit {week.hit_points}" if week.hit_points else "")
                + (f", {chip_label(week.chip)}" if week.chip else "")
                + (
                    f", {len(week.transfers_in)} transfer(s) in"
                    if week.transfers_in
                    else ", no transfer"
                )
            ),
        )
        for week in plan.weeks
    ]
    items.append(
        Contribution(
            label="Hits",
            points=float(plan.total_hit_points),
            detail="Points paid for transfers beyond the free allowance.",
        )
    )
    items.append(
        Contribution(
            label="Discounted objective",
            points=plan.objective,
            detail=(
                f"What the solver maximised: expected points discounted "
                f"{decision.horizon.discount:.2f} per gameweek, less hits, plus the risk and "
                "incumbency terms."
            ),
        )
    )
    return tuple(items)


def _runners_up(
    recommended: ScoredPlan, baseline: ScoredPlan, alternatives: list[ScoredPlan]
) -> tuple[RunnerUp, ...]:
    """Every option that lost, and by how much. The margin is the argument (FR-24)."""
    items: list[RunnerUp] = []
    for candidate in alternatives:
        if candidate.key == recommended.key:
            continue
        margin = round(candidate.score - recommended.score, 3)
        if candidate.key == BASELINE_KEY:
            reason = "holding the squad and making no transfer — always ranked, never assumed"
        elif candidate.plan.scenario.chips:
            reason = f"the same plan with {candidate.plan.scenario.label}"
        else:
            reason = "transfers without a chip"
        items.append(
            RunnerUp(
                label=baseline_label() if candidate.key == BASELINE_KEY else candidate.label,
                total_expected_points=candidate.plan.total_expected_points,
                margin=margin,
                simulated_score=(
                    None if candidate.simulation is None else candidate.simulation.score
                ),
                reason=reason,
            )
        )
    if baseline.key != recommended.key and not any(
        item.label == baseline_label() for item in items
    ):
        items.append(
            RunnerUp(
                label=baseline_label(),
                total_expected_points=baseline.plan.total_expected_points,
                margin=round(baseline.score - recommended.score, 3),
                simulated_score=None if baseline.simulation is None else baseline.simulation.score,
                reason="holding the squad and making no transfer — always ranked, never assumed",
            )
        )
    return tuple(items)


# ---------------------------------------------------------------------- inputs


def _shapes(fixtures: pd.DataFrame | None, players: pd.DataFrame) -> dict[int, GameweekShape]:
    if fixtures is None or fixtures.empty:
        return {}
    return gameweek_shapes(fixtures, {as_int(value) for value in players["team_id"]})


def _squad_clubs(players: pd.DataFrame, state: SquadState) -> list[int]:
    held = state.player_ids()
    return sorted(
        {as_int(row.team_id) for row in players.itertuples() if as_int(row.player_id) in held}
    )


def as_dict(plan: DecisionPlan) -> dict[str, object]:
    """The plan as the web contract carries it."""
    return {
        "gameweeks": list(plan.gameweeks),
        "solver": plan.solver,
        "solve_seconds": plan.solve_seconds,
        "status": plan.recommended.plan.status.value,
        "is_hold": plan.is_hold,
        "rationale": plan.rationale,
        "recommended": _plan_dict(plan.recommended),
        "baseline": _plan_dict(plan.baseline),
        "alternatives": [_plan_dict(item) for item in plan.alternatives],
        "chip_calendar": plan.calendar.as_dict(),
        "explanation": plan.explanation.as_dict(),
        "ownership": plan.ownership.as_dict(),
        "pruning": plan.pruning.as_dict(),
        "warnings": list(plan.warnings),
    }


def _plan_dict(scored: ScoredPlan) -> dict[str, object]:
    plan = scored.plan
    return {
        "key": scored.key,
        "label": scored.label,
        "chips": [
            {"gameweek": week, "chip": name, "chip_label": chip_label(name)}
            for week, name in plan.scenario.assignments
        ],
        "status": plan.status.value,
        "objective": plan.objective,
        "total_expected_points": plan.total_expected_points,
        "total_hit_points": plan.total_hit_points,
        "score": round(scored.score, 3),
        "simulation": None if scored.simulation is None else scored.simulation.as_dict(),
        "weeks": [
            {
                "gameweek": week.gameweek,
                "chip": week.chip,
                "chip_label": None if week.chip is None else chip_label(week.chip),
                "squad": list(week.squad),
                "fielded": list(week.fielded),
                "starting": list(week.starting),
                "bench_order": list(week.bench_order),
                "captain": week.captain_id,
                "vice_captain": week.vice_captain_id,
                "formation": dict(week.formation),
                "transfers_in": list(week.transfers_in),
                "transfers_out": list(week.transfers_out),
                "free_transfers": week.free_transfers,
                "charged_transfers": week.charged_transfers,
                "hit_points": week.hit_points,
                "bank_after": week.bank_after,
                "expected_points": round(week.expected_points, 3),
                "net_expected_points": week.net_expected_points,
            }
            for week in plan.weeks
        ],
    }


__all__ = [
    "BASELINE_KEY",
    "DecisionPlan",
    "ScoredPlan",
    "as_dict",
    "build_plan",
]
