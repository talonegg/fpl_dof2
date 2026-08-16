"""E4-S2 — the multi-gameweek MILP. FR-18, repays D-03.

E1 asked "given the squad I have, is any change worth making *this week*". That is structurally
short-sighted: it churns transfers, it cannot bank one for a week that needs two, and it has no view
at all on chips. This is the same question asked over a rolling 5-8 gameweek horizon, per Design
§6.2.

What is actually hard here
--------------------------
Not the squad constraints — those are E0's, repeated per gameweek. The two that bite are:

**Free-transfer accrual.** ``ft[w] = min(5, remaining + 1)`` is a ``min`` inside an integer program,
so it needs linearising with an auxiliary binary. An off-by-one in that linearisation compounds over
eight weeks into a plan built on transfers that do not exist, and nothing about the output looks
wrong. It is property-tested, not eyeballed.

**Chips must not consume free transfers (C15).** A Wildcard costing no *hit* is the obvious half of
the rule. The half that gets missed is that a Wildcard or Free Hit does not *spend* the balance
either. Without it the model believes a Wildcard burns up to five banked transfers and plays chips
too late or never. So the transfer count is split in two: ``made[w]``, the transfers actually
performed, and ``charged[w]``, the ones that count against the allowance. On a chip week the second
is zero while the first is not.

Chips are parameters, not variables
-----------------------------------
Each solve is conditional on one :class:`~fpl_dof.optimise.chips.ChipScenario` (DL-15). That is what
makes this model an ordinary transfer MILP rather than the C10-C14 formulation: the triple-captain
bilinear term ``z[p,w]`` disappears entirely, because with the chip fixed the captain multiplier is
a constant, and Free Hit needs a parallel squad set only in the one gameweek that plays it.

Solver
------
**HiGHS** (DL-15), not CBC. E0 validated CBC against the single-gameweek problem, which is a far
easier one. When the solver does not converge inside its budget the answer is a legal plan flagged
as fallback quality — a worse recommendation beats no recommendation at a deadline (DP-15).

The output is checked, not trusted: every gameweek's fielded squad is validated against
:func:`fpl_dof.rules.legality.validate_squad` before the plan is returned, because a mis-stated
constraint that produces an illegal squad in gameweek four and a legal one in gameweek one is
exactly the failure that stays invisible (DP-13).
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd
import pulp

from fpl_dof.config.models import DecisionConfig, OptimiserConfig
from fpl_dof.frames import as_float, as_int, gameweek_column
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.chips import ChipScenario
from fpl_dof.optimise.squad import InfeasibleError, SolveStatus, _start_floor
from fpl_dof.rules.legality import Squad, SquadPlayer, validate_squad
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.squad.state import SquadState

log = get_logger(__name__)

#: Money is carried in tenths of £m throughout, for the reason E0 states: comparing floats against a
#: budget is how a squad costing exactly £100.0m gets rejected for costing £100.00000000000001.
TENTHS = 10


@dataclass(frozen=True, slots=True)
class PlannedWeek:
    """One gameweek of a plan: what is owned, what is fielded, and what it cost to get there."""

    gameweek: int
    chip: str | None
    squad: tuple[int, ...]
    """The persistent 15. Under a Free Hit this is what you keep, not what you field."""

    fielded: tuple[int, ...]
    starting: tuple[int, ...]
    bench_order: tuple[int, ...]
    captain_id: int
    vice_captain_id: int
    formation: dict[str, int]
    transfers_in: tuple[int, ...]
    transfers_out: tuple[int, ...]
    free_transfers: int
    charged_transfers: int
    hit_points: int
    bank_after: float
    expected_points: float
    """Fielded expected points including the captain multiplier and any bench weighting."""

    @property
    def net_expected_points(self) -> float:
        return round(self.expected_points + self.hit_points, 4)


@dataclass(frozen=True, slots=True)
class HorizonPlan:
    """A whole plan over the horizon, conditional on one chip scenario."""

    scenario: ChipScenario
    weeks: tuple[PlannedWeek, ...]
    objective: float
    status: SolveStatus
    solve_seconds: float
    warnings: tuple[str, ...] = field(default=())

    @property
    def gameweeks(self) -> tuple[int, ...]:
        return tuple(week.gameweek for week in self.weeks)

    @property
    def first(self) -> PlannedWeek:
        return self.weeks[0]

    @property
    def total_hit_points(self) -> int:
        return sum(week.hit_points for week in self.weeks)

    @property
    def total_expected_points(self) -> float:
        return round(sum(week.net_expected_points for week in self.weeks), 4)

    @property
    def is_fallback(self) -> bool:
        return self.status is SolveStatus.GREEDY_FALLBACK


@dataclass(frozen=True, slots=True)
class HorizonInputs:
    """Everything the multi-gameweek model reads. Assembled once and reused across scenarios."""

    players: pd.DataFrame
    state: SquadState
    rules: GameRules
    gameweeks: tuple[int, ...]


def solve_horizon(
    inputs: HorizonInputs,
    scenario: ChipScenario,
    decision: DecisionConfig,
    optimiser: OptimiserConfig,
) -> HorizonPlan:
    """Best plan over the horizon, conditional on ``scenario``.

    Raises :class:`InfeasibleError` when no legal plan exists at all, with an explanation of why
    rather than a solver status code.
    """
    model = _Model(inputs, scenario, decision, optimiser)
    return model.solve()


def _solver(decision: DecisionConfig) -> object:
    """PuLP handle for the configured solver.

    HiGHS from E4 onward (DL-15). If it is not installed the run does not silently drop to CBC and
    keep claiming HiGHS — it says so, because "solved on HiGHS" is a claim about how much the answer
    can be trusted at this size, and quietly substituting a weaker solver makes that claim false.
    """
    limit = decision.horizon.solve_time_limit_seconds
    if decision.horizon.solver == "CBC":
        return pulp.PULP_CBC_CMD(msg=False, timeLimit=limit)
    try:
        return pulp.HiGHS(msg=False, timeLimit=limit)
    except pulp.PulpSolverError as exc:  # pragma: no cover - environment dependent
        raise InfeasibleError(
            "the multi-gameweek model is configured to solve on HiGHS (DL-15) and HiGHS is not "
            "available: install `highspy`, or set decision.horizon.solver to 'CBC' and accept that "
            "CBC was never validated against a problem this size (R-07)"
        ) from exc


class _Model:
    """The MILP itself, kept as a class so the variable sets stay readable rather than threaded."""

    def __init__(
        self,
        inputs: HorizonInputs,
        scenario: ChipScenario,
        decision: DecisionConfig,
        optimiser: OptimiserConfig,
    ) -> None:
        self.inputs = inputs
        self.scenario = scenario
        self.decision = decision
        self.optimiser = optimiser
        self.rules = inputs.rules
        self.squad_rules = inputs.rules.squad
        self.weeks = tuple(int(w) for w in inputs.gameweeks)

        pool = inputs.players.reset_index(drop=True)
        self.pool = pool
        self.by_id = {as_int(row.player_id): row for row in pool.itertuples()}
        self.ids = sorted(self.by_id)
        self.held = sorted(inputs.state.player_ids())
        self.clubs = sorted({as_int(self.by_id[i].team_id) for i in self.ids})

        self.price = {i: round(as_float(self.by_id[i].price) * TENTHS) for i in self.ids}
        selling = {p.player_id: p.selling_price(self.rules) for p in inputs.state.players}
        # A player bought inside the horizon sells for what he cost: the model holds prices fixed,
        # so a modelled sell-on fee would be inventing a rise the model does not predict.
        self.sell = {
            i: round(selling.get(i, as_float(self.by_id[i].price)) * TENTHS) for i in self.ids
        }
        self.mu = self._expected_points()
        self.ownership = {
            i: as_float(getattr(self.by_id[i], "selected_by_percent", 0.0) or 0.0) for i in self.ids
        }

        self.locked = {i for i in optimiser.locked_player_ids if i in self.by_id}
        self.banned = {i for i in optimiser.banned_player_ids if i in self.by_id}
        self.excluded_clubs = set(optimiser.excluded_team_ids)
        self.floor = _start_floor(pool) if optimiser.enforce_start_probability_floor else 0.0

    # ------------------------------------------------------------------ inputs

    def _expected_points(self) -> dict[tuple[int, int], float]:
        """``μ[p,w]``, read from the forecast rather than recomputed here (DP-02).

        A gameweek the forecast does not carry — beyond its own horizon, or a blank — reads zero,
        which is the correct value for a player with no fixture and the honest value for a gameweek
        nobody has forecast.
        """
        table: dict[tuple[int, int], float] = {}
        for gameweek in self.weeks:
            column = gameweek_column(gameweek)
            if column in self.pool.columns:
                values = {
                    as_int(row.player_id): as_float(getattr(row, column))
                    for row in self.pool.itertuples()
                }
            else:
                values = dict.fromkeys(self.ids, 0.0)
            for player_id in self.ids:
                table[(player_id, gameweek)] = values.get(player_id, 0.0)
        return table

    # ------------------------------------------------------------------ solve

    def solve(self) -> HorizonPlan:
        started = time.monotonic()
        self._reject_contradictory_overrides()
        problem = pulp.LpProblem("fpl_horizon", pulp.LpMaximize)
        self._build(problem)

        try:
            problem.solve(_solver(self.decision))
        except pulp.PulpSolverError as exc:  # pragma: no cover - environment dependent
            log.warning("horizon.solver_error", extra={"error": str(exc)})
            return self._greedy(time.monotonic() - started, reason=str(exc))

        elapsed = time.monotonic() - started
        status = pulp.LpStatus[problem.status]
        if status == "Infeasible":
            raise InfeasibleError(
                "no legal plan exists over the horizon: " + "; ".join(self._diagnose())
            )
        if status != "Optimal":
            log.warning(
                "horizon.not_optimal", extra={"status": status, "seconds": round(elapsed, 2)}
            )
            return self._greedy(elapsed, reason=f"solver returned {status}")

        plan = self._read_solution(float(pulp.value(problem.objective)), elapsed)
        self._verify(plan)
        log.info(
            "horizon.solved",
            extra={
                "scenario": self.scenario.label,
                "objective": round(plan.objective, 3),
                "seconds": round(elapsed, 2),
                "hits": plan.total_hit_points,
            },
        )
        return plan

    # ------------------------------------------------------------------ model

    def _reject_contradictory_overrides(self) -> None:
        """E4-S5. Two overrides that cannot both hold are a mistake, not a preference to resolve.

        Checked before the model is built rather than left to the solver, because a lock and a ban
        on the same player is satisfiable *if* one of them silently wins — and a constraint system
        that quietly picks a winner is one nobody can reason about. Say which two instructions
        conflict, and stop.
        """
        reasons = [
            reason
            for reason in self._diagnose()
            if "locked and banned" in reason or "forced formation" in reason
        ]
        conflict = self.locked & self.banned
        excluded_locks = {
            i for i in self.locked if as_int(self.by_id[i].team_id) in self.excluded_clubs
        }
        if excluded_locks:
            reasons.append(
                f"player(s) {sorted(excluded_locks)} are locked but their club is excluded, which "
                "cannot both be satisfied"
            )
        if (conflict or excluded_locks or reasons) and reasons:
            raise InfeasibleError(
                "the constraint overrides contradict each other: " + "; ".join(reasons)
            )

    def _build(self, problem: pulp.LpProblem) -> None:
        ids, weeks = self.ids, self.weeks
        max_ft = self.rules.transfers.max_free_transfers

        self.own = pulp.LpVariable.dicts("own", (ids, list(weeks)), cat="Binary")
        self.tin = pulp.LpVariable.dicts("tin", (ids, list(weeks)), cat="Binary")
        self.tout = pulp.LpVariable.dicts("tout", (ids, list(weeks)), cat="Binary")
        self.start = pulp.LpVariable.dicts("start", (ids, list(weeks)), cat="Binary")
        self.cap = pulp.LpVariable.dicts("cap", (ids, list(weeks)), cat="Binary")

        # The fielded squad is the owned squad except under a Free Hit, which is the only rule that
        # separates the two (C13). Allocating a second variable set only when a scenario actually
        # plays a Free Hit keeps every other scenario the size it would have been.
        self.free_hit_weeks = {w for w in weeks if self.scenario.chip_in(w) == "freehit"}
        if self.free_hit_weeks:
            self.field = pulp.LpVariable.dicts("field", (ids, list(weeks)), cat="Binary")
        else:
            self.field = self.own

        self.ft = pulp.LpVariable.dicts(
            "ft", list(weeks), lowBound=1, upBound=max_ft, cat="Integer"
        )
        self.hits = pulp.LpVariable.dicts("hits", list(weeks), lowBound=0, cat="Integer")
        self.charged = pulp.LpVariable.dicts("charged", list(weeks), lowBound=0, cat="Integer")
        self.remaining = pulp.LpVariable.dicts(
            "remaining", list(weeks), lowBound=0, upBound=max_ft, cat="Integer"
        )
        self.at_cap = pulp.LpVariable.dicts("at_cap", list(weeks), cat="Binary")
        self.bank = pulp.LpVariable.dicts("bank", list(weeks), lowBound=0, cat="Continuous")

        self._objective(problem)
        for index, week in enumerate(weeks):
            self._squad_constraints(problem, week)
            self._lineup_constraints(problem, week)
            self._continuity(problem, index, week)
            self._overrides(problem, week)
        self._transfer_accounting(problem, max_ft)

    def _objective(self, problem: pulp.LpProblem) -> None:
        horizon = self.decision.horizon
        risk = self.decision.risk
        ownership_weight = risk.ownership_weight.get(risk.dial, 0.0)
        extra_cost = self.rules.transfers.extra_transfer_cost
        incumbent = set(self.held)

        terms = []
        for index, week in enumerate(self.weeks):
            discount = horizon.discount**index
            chip = self.scenario.chip_in(week)
            multiplier = self._captain_multiplier(chip)
            bench = 1.0 if chip == "bboost" else horizon.bench_weight

            weekly = []
            for i in self.ids:
                mu = self.mu[(i, week)]
                weekly.append(mu * self.start[i][week])
                weekly.append(mu * (multiplier - 1) * self.cap[i][week])
                weekly.append(bench * mu * (self.field[i][week] - self.start[i][week]))
                # The risk term (Design §7): a signed, linear function of `selected_by_percent`
                # over the starting XI. A linear proxy for a quadratic quantity, and the UI says so.
                weekly.append(ownership_weight * self.ownership[i] * self.start[i][week])
            weekly.append(extra_cost * self.hits[week])
            terms.append(discount * pulp.lpSum(weekly))

            # The tie-break (Design §6.2). Undiscounted and outside the risk term on purpose: its
            # whole job is to make an otherwise-degenerate choice deterministic, and discounting it
            # would make the same tie break differently depending on which week it fell in.
            terms.append(
                horizon.incumbency_bonus * pulp.lpSum(self.own[i][week] for i in incumbent)
            )

        problem += pulp.lpSum(terms)

    def _captain_multiplier(self, chip: str | None) -> int:
        """The captain multiplier in force. Configuration, never a literal (Invariant 2)."""
        if chip is None:
            return self.optimiser.captain_multiplier
        return self.decision.chips.captain_multiplier_by_chip.get(
            chip, self.optimiser.captain_multiplier
        )

    def _squad_constraints(self, problem: pulp.LpProblem, week: int) -> None:
        rules = self.squad_rules
        ids = self.ids
        problem += pulp.lpSum(self.own[i][week] for i in ids) == rules.size, f"size_{week}"
        for position in Position:
            members = self._in_position(position)
            problem += (
                pulp.lpSum(self.own[i][week] for i in members) == rules.composition[position],
                f"composition_{position.value}_{week}",
            )
        for club in self.clubs:
            members = self._in_club(club)
            problem += (
                pulp.lpSum(self.own[i][week] for i in members) <= rules.club_limit,
                f"club_limit_{club}_{week}",
            )
        cap = self.decision.maximum_spend
        if cap is not None:
            problem += (
                pulp.lpSum(self.price[i] * self.own[i][week] for i in ids) <= round(cap * TENTHS),
                f"max_spend_{week}",
            )

        if week not in self.free_hit_weeks:
            if self.field is not self.own:
                # Every other gameweek in a Free Hit scenario: what you field *is* what you own.
                # Without this the second variable set floats free and the "plan" fields the whole
                # candidate pool, which is caught by the per-gameweek legality check and would
                # otherwise be a silently enormous overcount.
                for i in ids:
                    problem += self.field[i][week] == self.own[i][week], f"field_is_own_{i}_{week}"
            return

        # C13 — the Free Hit squad. A separate legal 15 for this gameweek only, bought at current
        # prices out of what the persistent squad would raise plus the bank, and discarded after.
        problem += pulp.lpSum(self.field[i][week] for i in ids) == rules.size, f"fh_size_{week}"
        for position in Position:
            members = self._in_position(position)
            problem += (
                pulp.lpSum(self.field[i][week] for i in members) == rules.composition[position],
                f"fh_composition_{position.value}_{week}",
            )
        for club in self.clubs:
            members = self._in_club(club)
            problem += (
                pulp.lpSum(self.field[i][week] for i in members) <= rules.club_limit,
                f"fh_club_limit_{club}_{week}",
            )
        previous = self._previous_bank(self.weeks.index(week))
        problem += (
            pulp.lpSum(self.price[i] * self.field[i][week] for i in ids)
            <= previous + pulp.lpSum(self.sell[i] * self.own[i][week] for i in ids),
            f"fh_budget_{week}",
        )

    def _lineup_constraints(self, problem: pulp.LpProblem, week: int) -> None:
        rules = self.squad_rules
        ids = self.ids
        problem += (
            pulp.lpSum(self.start[i][week] for i in ids) == rules.starting_size,
            f"starting_size_{week}",
        )
        for i in ids:
            problem += self.start[i][week] <= self.field[i][week], f"start_in_squad_{i}_{week}"
            problem += self.cap[i][week] <= self.start[i][week], f"captain_starts_{i}_{week}"
        problem += pulp.lpSum(self.cap[i][week] for i in ids) == 1, f"one_captain_{week}"

        forced = self.decision.forced_formation
        for position in Position:
            members = self._in_position(position)
            if forced is not None and position.value in forced:
                problem += (
                    pulp.lpSum(self.start[i][week] for i in members) == forced[position.value],
                    f"forced_formation_{position.value}_{week}",
                )
                continue
            problem += (
                pulp.lpSum(self.start[i][week] for i in members) >= rules.formation_min[position],
                f"formation_min_{position.value}_{week}",
            )
            problem += (
                pulp.lpSum(self.start[i][week] for i in members) <= rules.formation_max[position],
                f"formation_max_{position.value}_{week}",
            )

        # C16 — the same-club cap on the starting XI. One linear constraint per club, aimed at the
        # dominant correlation a MILP cannot otherwise express. Relaxable per club (E4-S5).
        limit = self.decision.risk.same_club_starting_limit
        exempt = set(self.decision.risk.relax_club_cap_team_ids)
        for club in self.clubs:
            if club in exempt or limit >= rules.starting_size:
                continue
            members = self._in_club(club)
            problem += (
                pulp.lpSum(self.start[i][week] for i in members) <= limit,
                f"same_club_xi_{club}_{week}",
            )

    def _continuity(self, problem: pulp.LpProblem, index: int, week: int) -> None:
        """C6 and C7 — the squad carries forward, and the money has to add up."""
        held = set(self.held)
        for i in self.ids:
            previous = self.own[i][self.weeks[index - 1]] if index else (1 if i in held else 0)
            problem += (
                self.own[i][week] == previous + self.tin[i][week] - self.tout[i][week],
                f"continuity_{i}_{week}",
            )
            problem += self.tin[i][week] + self.tout[i][week] <= 1, f"one_way_{i}_{week}"

        opening = self._previous_bank(index)
        problem += (
            self.bank[week]
            == opening
            + pulp.lpSum(self.sell[i] * self.tout[i][week] for i in self.ids)
            - pulp.lpSum(self.price[i] * self.tin[i][week] for i in self.ids),
            f"bank_{week}",
        )

        made = pulp.lpSum(self.tin[i][week] for i in self.ids)
        chip = self.scenario.chip_in(week)
        if chip == "freehit":
            # The persistent squad is frozen: a Free Hit changes what you field, not what you own.
            problem += made == 0, f"freehit_no_transfers_{week}"
        elif chip != "wildcard":
            problem += (
                made <= self.decision.horizon.max_transfers_per_gameweek,
                f"transfer_cap_{week}",
            )

    def _previous_bank(self, index: int) -> object:
        if index == 0:
            return round(self.inputs.state.bank * TENTHS)
        return self.bank[self.weeks[index - 1]]

    def _transfer_accounting(self, problem: pulp.LpProblem, max_ft: int) -> None:
        """C8, C9 and **C15** — the free-transfer ledger, and the half of C15 that gets missed.

        ``made[w]`` is what you actually did. ``charged[w]`` is what it costs you from the
        allowance, and on a Wildcard or Free Hit gameweek it is **zero while ``made`` is not**. That
        single distinction is the whole of C15, and without it the model believes a Wildcard burns
        up to five banked transfers.
        """
        for index, week in enumerate(self.weeks):
            made = pulp.lpSum(self.tin[i][week] for i in self.ids)
            if self.scenario.chip_in(week) in {"wildcard", "freehit"}:
                problem += self.charged[week] == 0, f"chip_free_transfers_{week}"
            else:
                problem += self.charged[week] == made, f"charged_{week}"

            if index == 0:
                problem += (
                    self.ft[week] == min(max_ft, max(1, self.inputs.state.free_transfers)),
                    f"opening_ft_{week}",
                )
            problem += self.hits[week] >= self.charged[week] - self.ft[week], f"hit_{week}"
            # `remaining` is max(0, ft - charged) at the optimum: hits are penalised, so `hits`
            # takes its lower bound, and the two expressions coincide. Written this way rather than
            # with a second binary because one fewer binary per gameweek is worth having.
            problem += (
                self.remaining[week] == self.ft[week] - self.charged[week] + self.hits[week],
                f"remaining_{week}",
            )

            if index + 1 >= len(self.weeks):
                continue
            following = self.weeks[index + 1]
            # C8 linearised: ft[w+1] = min(max_ft, remaining[w] + 1). Both upper bounds, plus one
            # binary choosing which of them is tight, which is what turns `<= min` into `= min`.
            big_m = max_ft + 1
            problem += self.ft[following] <= max_ft, f"ft_cap_{following}"
            problem += self.ft[following] <= self.remaining[week] + 1, f"ft_accrual_{following}"
            problem += (
                self.ft[following] >= max_ft - big_m * self.at_cap[week],
                f"ft_min_a_{following}",
            )
            problem += (
                self.ft[following] >= self.remaining[week] + 1 - big_m * (1 - self.at_cap[week]),
                f"ft_min_b_{following}",
            )

    def _overrides(self, problem: pulp.LpProblem, week: int) -> None:
        """E4-S5 — locks, bans, club exclusions and the start-probability floor."""
        for i in self.ids:
            if i in self.locked:
                problem += self.own[i][week] == 1, f"lock_{i}_{week}"
                if week in self.free_hit_weeks:
                    problem += self.field[i][week] == 1, f"lock_field_{i}_{week}"
                continue
            if i in self.banned or as_int(self.by_id[i].team_id) in self.excluded_clubs:
                problem += self.own[i][week] == 0, f"ban_{i}_{week}"
                if week in self.free_hit_weeks:
                    problem += self.field[i][week] == 0, f"ban_field_{i}_{week}"
                continue
            if self.floor and as_float(self.by_id[i].start_probability) < self.floor:
                problem += self.start[i][week] == 0, f"start_floor_{i}_{week}"

    def _in_position(self, position: Position) -> list[int]:
        return [i for i in self.ids if str(self.by_id[i].position) == position.value]

    def _in_club(self, club: int) -> list[int]:
        return [i for i in self.ids if as_int(self.by_id[i].team_id) == club]

    # ------------------------------------------------------------------ output

    def _read_solution(self, objective: float, elapsed: float) -> HorizonPlan:
        weeks: list[PlannedWeek] = []
        previous_squad = set(self.held)
        for index, week in enumerate(self.weeks):
            owned = tuple(sorted(i for i in self.ids if _is_set(self.own[i][week])))
            fielded = tuple(sorted(i for i in self.ids if _is_set(self.field[i][week])))
            starting = tuple(sorted(i for i in fielded if _is_set(self.start[i][week])))
            captain = next(i for i in starting if _is_set(self.cap[i][week]))
            chip = self.scenario.chip_in(week)
            weeks.append(
                self._planned_week(
                    index=index,
                    week=week,
                    chip=chip,
                    owned=owned,
                    fielded=fielded,
                    starting=starting,
                    captain=captain,
                    previous_squad=previous_squad,
                )
            )
            previous_squad = set(owned)
        return HorizonPlan(
            scenario=self.scenario,
            weeks=tuple(weeks),
            objective=round(objective, 4),
            status=SolveStatus.OPTIMAL,
            solve_seconds=round(elapsed, 3),
        )

    def _planned_week(
        self,
        *,
        index: int,
        week: int,
        chip: str | None,
        owned: tuple[int, ...],
        fielded: tuple[int, ...],
        starting: tuple[int, ...],
        captain: int,
        previous_squad: set[int],
    ) -> PlannedWeek:
        multiplier = self._captain_multiplier(chip)
        bench_weight = 1.0 if chip == "bboost" else self.decision.horizon.bench_weight
        bench = [i for i in fielded if i not in set(starting)]

        points = sum(self.mu[(i, week)] for i in starting)
        points += self.mu[(captain, week)] * (multiplier - 1)
        points += bench_weight * sum(self.mu[(i, week)] for i in bench)

        ordered_start = sorted(starting, key=lambda i: (-self.mu[(i, week)], i))
        vice = next((i for i in ordered_start if i != captain), captain)
        bench_order = tuple(
            sorted(
                (i for i in bench if str(self.by_id[i].position) != Position.GKP.value),
                # Bench order is not a MILP variable: sorting on P(plays) x μ is optimal in
                # practice and removes a large block of binaries for no real loss (Design §6.2).
                key=lambda i: (
                    -self.mu[(i, week)] * as_float(self.by_id[i].start_probability),
                    i,
                ),
            )
        )
        formation: dict[str, int] = {}
        for i in starting:
            position = str(self.by_id[i].position)
            formation[position] = formation.get(position, 0) + 1

        return PlannedWeek(
            gameweek=week,
            chip=chip,
            squad=owned,
            fielded=fielded,
            starting=tuple(ordered_start),
            bench_order=bench_order,
            captain_id=captain,
            vice_captain_id=vice,
            formation=formation,
            transfers_in=tuple(sorted(set(owned) - previous_squad)),
            transfers_out=tuple(sorted(previous_squad - set(owned))),
            free_transfers=_as_int(self.ft[week]),
            charged_transfers=_as_int(self.charged[week]),
            hit_points=_as_int(self.hits[week]) * self.rules.transfers.extra_transfer_cost,
            bank_after=round(_as_int(self.bank[week]) / TENTHS, 1),
            expected_points=round(points, 4),
        )

    def _verify(self, plan: HorizonPlan) -> None:
        """Squad legality at **every** gameweek of the horizon, not only the first.

        E1's property tests only ever saw one gameweek. A formulation that is right in week one and
        wrong in week four produces a plan that validates on the day and quietly falls apart, which
        is the definition of a failure worth testing hardest for (DP-13).
        """
        budget = self.inputs.state.budget(self.rules)
        for week in plan.weeks:
            squad = self.as_squad(week)
            violations = validate_squad(squad, self.rules, budget=budget)
            if violations:
                raise AssertionError(
                    f"the plan is illegal in gameweek {week.gameweek}, which is a defect in the "
                    "formulation: " + "; ".join(v.message for v in violations)
                )

    def as_squad(self, week: PlannedWeek) -> Squad:
        selling = {p.player_id: p.selling_price(self.rules) for p in self.inputs.state.players}
        return Squad(
            players=tuple(
                SquadPlayer(
                    player_id=i,
                    position=Position(str(self.by_id[i].position)),
                    team_id=as_int(self.by_id[i].team_id),
                    price=selling.get(i, as_float(self.by_id[i].price)),
                )
                for i in week.fielded
            ),
            starting=week.starting,
            captain=week.captain_id,
            vice_captain=week.vice_captain_id,
            bench_order=week.bench_order,
        )

    # ------------------------------------------------------------------ fallback

    def _greedy(self, elapsed: float, *, reason: str) -> HorizonPlan:
        """A legal plan when the solver could not finish: hold, and field the best XI each week.

        Deliberately the most conservative legal answer rather than a greedy transfer search. The
        squad you already own is known-legal, so this cannot fail for a reason the solver has
        already shown is hard; and a fallback that quietly *makes transfers* it cannot prove are
        worth it is worse than one that does nothing and says so (DP-15).
        """
        log.warning("horizon.greedy_fallback", extra={"reason": reason})
        held = sorted(self.inputs.state.player_ids())
        missing = [i for i in held if i not in self.by_id]
        if missing:
            raise InfeasibleError(
                f"the fallback cannot price the current squad: player(s) {missing} are absent "
                "from the candidate pool"
            )

        weeks: list[PlannedWeek] = []
        objective = 0.0
        free = min(
            self.rules.transfers.max_free_transfers, max(1, self.inputs.state.free_transfers)
        )
        for index, week in enumerate(self.weeks):
            starting, captain = self._greedy_lineup(held, week)
            planned = self._planned_week(
                index=index,
                week=week,
                chip=self.scenario.chip_in(week),
                owned=tuple(held),
                fielded=tuple(held),
                starting=tuple(starting),
                captain=captain,
                previous_squad=set(held),
            )
            planned = _replace_ledger(
                planned,
                free_transfers=free,
                bank_after=round(self.inputs.state.bank, 1),
            )
            free = min(self.rules.transfers.max_free_transfers, free + 1)
            objective += (self.decision.horizon.discount**index) * planned.expected_points
            weeks.append(planned)

        plan = HorizonPlan(
            scenario=self.scenario,
            weeks=tuple(weeks),
            objective=round(objective, 4),
            status=SolveStatus.GREEDY_FALLBACK,
            solve_seconds=round(elapsed, 3),
            warnings=(f"fallback plan: {reason}; this holds the squad and makes no transfers",),
        )
        self._verify(plan)
        return plan

    def _greedy_lineup(self, held: Sequence[int], week: int) -> tuple[list[int], int]:
        best: list[int] = []
        best_value = float("-inf")
        eligible = {
            i: self.mu[(i, week)]
            for i in held
            if i in self.locked
            or not self.floor
            or as_float(self.by_id[i].start_probability) >= self.floor
        }
        for formation in self.squad_rules.legal_formations():
            lineup: list[int] = []
            value = 0.0
            for position, count in formation.items():
                members = sorted(
                    (i for i in held if str(self.by_id[i].position) == position.value),
                    key=lambda i: (-eligible.get(i, float("-inf")), i),
                )[:count]
                if len(members) < count:
                    break
                lineup.extend(members)
                value += sum(self.mu[(i, week)] for i in members)
            else:
                if value > best_value:
                    best_value, best = value, lineup
        if not best:
            raise InfeasibleError(
                f"no legal formation can be built from the current squad in gameweek {week}"
            )
        captain = max(best, key=lambda i: (self.mu[(i, week)], -i))
        return best, captain

    # ------------------------------------------------------------------ diagnosis

    def _diagnose(self) -> list[str]:
        """Say *why* no plan exists, in the same shape as the single-gameweek diagnosis."""
        reasons: list[str] = []
        rules = self.squad_rules
        pool = self.pool

        missing = set(self.held) - set(self.by_id)
        if missing:
            reasons.append(
                f"the current squad contains player(s) absent from the candidate pool: "
                f"{sorted(missing)}"
            )
        absent_locks = set(self.optimiser.locked_player_ids) - set(self.by_id)
        if absent_locks:
            reasons.append(f"locked player(s) not in the candidate pool: {sorted(absent_locks)}")
        if len(self.locked) > rules.size:
            reasons.append(f"{len(self.locked)} players locked, but the squad holds {rules.size}")
        locked_and_banned = self.locked & self.banned
        if locked_and_banned:
            reasons.append(
                f"player(s) {sorted(locked_and_banned)} are both locked and banned, which cannot "
                "both be satisfied"
            )

        forced = self.decision.forced_formation
        if forced is not None:
            total = sum(forced.values())
            if total != rules.starting_size:
                reasons.append(
                    f"the forced formation names {total} starters, but exactly "
                    f"{rules.starting_size} must start"
                )
            for name, count in forced.items():
                position = Position(name)
                if count < rules.formation_min[position] or count > rules.formation_max[position]:
                    reasons.append(
                        f"the forced formation asks for {count} {name}, outside the legal "
                        f"{rules.formation_min[position]}-{rules.formation_max[position]}"
                    )

        available = pool[
            ~pool["player_id"].isin(self.banned) & ~pool["team_id"].isin(self.excluded_clubs)
        ]
        for position in Position:
            needed = rules.composition[position]
            have = int((available["position"] == position.value).sum())
            if have < needed:
                reasons.append(
                    f"only {have} {position.value} remain after bans and club exclusions, but "
                    f"{needed} are required"
                )

        limit = self.decision.risk.same_club_starting_limit
        exempt = set(self.decision.risk.relax_club_cap_team_ids)
        reachable = sum(
            limit if club not in exempt else rules.starting_size
            for club in {as_int(self.by_id[i].team_id) for i in self.ids}
        )
        if reachable < rules.starting_size:
            reasons.append(
                f"the same-club starting cap of {limit} allows at most {reachable} starters across "
                "the clubs in the pool, but "
                f"{rules.starting_size} must start; relax it via "
                "decision.risk.relax_club_cap_team_ids or widen the pool"
            )

        cap = self.decision.maximum_spend
        if cap is not None:
            cheapest = 0.0
            for position in Position:
                prices = sorted(
                    as_float(row.price)
                    for row in available.itertuples()
                    if str(row.position) == position.value
                )
                cheapest += sum(prices[: rules.composition[position]])
            if cheapest > cap:
                reasons.append(
                    f"the spend cap of £{cap:.1f}m is below the £{cheapest:.1f}m cheapest legal "
                    "squad in the pool"
                )

        if not reasons:
            reasons.append(
                "the constraints are jointly unsatisfiable across the horizon, but no single cause "
                "stands out; the usual interaction is the budget against the start-probability "
                "floor — the players who clear the floor are the ones who play, who are the "
                "expensive ones"
            )
        return reasons


def _is_set(variable: object) -> bool:
    value = pulp.value(variable)
    return bool(value is not None and round(float(value)) == 1)


def _as_int(variable: object) -> int:
    value = pulp.value(variable)
    return 0 if value is None else round(float(value))


def _replace_ledger(week: PlannedWeek, *, free_transfers: int, bank_after: float) -> PlannedWeek:
    return PlannedWeek(
        gameweek=week.gameweek,
        chip=week.chip,
        squad=week.squad,
        fielded=week.fielded,
        starting=week.starting,
        bench_order=week.bench_order,
        captain_id=week.captain_id,
        vice_captain_id=week.vice_captain_id,
        formation=week.formation,
        transfers_in=(),
        transfers_out=(),
        free_transfers=free_transfers,
        charged_transfers=0,
        hit_points=0,
        bank_after=bank_after,
        expected_points=week.expected_points,
    )


def plan_gameweeks(
    state: SquadState, decision: DecisionConfig, last: int | None = None
) -> tuple[int, ...]:
    """The rolling window, starting at the gameweek the squad is going into."""
    first = state.gameweek
    weeks = range(first, first + decision.horizon.gameweeks)
    if last is None:
        return tuple(weeks)
    return tuple(week for week in weeks if week <= last)


def free_transfer_ledger(plan: HorizonPlan) -> Mapping[int, int]:
    """Free transfers going into each gameweek of a plan. Extracted for the property tests."""
    return {week.gameweek: week.free_transfers for week in plan.weeks}


__all__ = [
    "HorizonInputs",
    "HorizonPlan",
    "PlannedWeek",
    "free_transfer_ledger",
    "plan_gameweeks",
    "solve_horizon",
]
