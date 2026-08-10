"""Single-shot squad MILP.

Prediction and decision are separate concerns (DP-02): this module takes expected points as given
and never adjusts them. If the forecast is wrong, the answer is wrong, and that is the forecast's
problem — which is exactly why the model card and the review gate exist.

**The output is checked, not trusted.** Every solve is validated against
:func:`fpl_dof.rules.legality.validate_squad` before it is returned. A mis-stated constraint or a
solver quirk that produces an illegal squad is precisely the failure that would otherwise be
invisible until submission (DP-13).

Formulation
-----------
Binary ``x_i`` selects player *i* into the 15; ``y_i`` starts them; ``c_i`` captains them.

* exactly ``squad.size`` selected, and exactly ``composition[p]`` in each position
* total price within budget
* at most ``club_limit`` from any one club
* ``y_i <= x_i``, exactly ``starting_size`` starters, formation bounds per position
* ``c_i <= y_i``, exactly one captain
* locks force ``x_i = 1``; bans and excluded clubs force ``x_i = 0``
* players below the start-probability floor may be selected but not started, unless locked

The objective is horizon expected points for starters, the same discounted by ``bench_weight`` for
the bench, plus the captain's *next-gameweek* expected points times ``captain_multiplier - 1``.
Captaincy is a single-gameweek decision, so it is scored on a single gameweek; the squad is a
multi-gameweek asset, so it is scored on the horizon.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd
import pulp

from fpl_dof.config.models import OptimiserConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.legality import Squad, SquadPlayer, Violation, validate_squad
from fpl_dof.rules.models import GameRules, Position

log = get_logger(__name__)

REQUIRED_COLUMNS = (
    "player_id",
    "position",
    "team_id",
    "price",
    "xp_next",
    "xp_horizon",
    "start_probability",
)


class SolveStatus(StrEnum):
    OPTIMAL = "optimal"
    GREEDY_FALLBACK = "greedy_fallback"


class InfeasibleError(RuntimeError):
    """No legal squad exists under these constraints, with an explanation of why."""


@dataclass(frozen=True, slots=True)
class SolveReport:
    status: SolveStatus
    objective: float
    solve_seconds: float
    formation: dict[str, int]
    captain_id: int
    vice_captain_id: int
    total_price: float
    violations: list[Violation] = field(default_factory=list)


def _diagnose_infeasibility(
    players: pd.DataFrame, rules: GameRules, config: OptimiserConfig
) -> list[str]:
    """Say *why* it cannot be done, rather than reporting a solver status code."""
    reasons: list[str] = []
    squad_rules = rules.squad
    locked = players[players["player_id"].isin(config.locked_player_ids)]

    missing = set(config.locked_player_ids) - set(players["player_id"])
    if missing:
        reasons.append(f"locked player(s) not in the player pool: {sorted(missing)}")

    if len(locked) > squad_rules.size:
        reasons.append(f"{len(locked)} players locked, but the squad holds {squad_rules.size}")

    locked_cost = float(locked["price"].sum())
    if locked_cost > squad_rules.budget:
        reasons.append(
            f"locked players alone cost £{locked_cost:.1f}m, over the £{squad_rules.budget:.1f}m "
            "budget"
        )

    for position, count in locked["position"].value_counts().items():
        allowed = squad_rules.composition[Position(str(position))]
        if int(count) > allowed:
            reasons.append(f"{count} {position} locked, but only {allowed} fit in the squad")

    for team_id, count in locked["team_id"].value_counts().items():
        if int(count) > squad_rules.club_limit:
            reasons.append(
                f"{count} players locked from club {team_id}, above the "
                f"{squad_rules.club_limit}-player limit"
            )

    available = players[
        ~players["player_id"].isin(config.banned_player_ids)
        & ~players["team_id"].isin(config.excluded_team_ids)
    ]
    for position in Position:
        needed = squad_rules.composition[position]
        have = int((available["position"] == position.value).sum())
        if have < needed:
            reasons.append(
                f"only {have} {position.value} available after bans and club exclusions, "
                f"but {needed} are required"
            )

    cheapest = (
        available.sort_values("price").groupby("position", observed=True)["price"].apply(list)
    )
    minimum = 0.0
    for position in Position:
        prices = cheapest.get(position.value, [])
        need = squad_rules.composition[position]
        if len(prices) >= need:
            minimum += float(sum(prices[:need]))
    if minimum > squad_rules.budget:
        reasons.append(
            f"the cheapest legal squad costs £{minimum:.1f}m, over the "
            f"£{squad_rules.budget:.1f}m budget"
        )

    if config.enforce_start_probability_floor:
        floor = _start_floor(players)
        eligible = available[
            (available["start_probability"] >= floor)
            | available["player_id"].isin(config.locked_player_ids)
        ]
        # Per position first: a formation minimum is the tightest constraint the floor can break,
        # and it breaks it silently — there is nothing wrong with any individual player.
        for position in Position:
            have = int((eligible["position"] == position.value).sum())
            required = squad_rules.formation_min[position]
            if have < required:
                reasons.append(
                    f"only {have} {position.value} clear the {floor:.0%} start-probability floor, "
                    f"but at least {required} must be in the starting XI"
                )

        # Then in aggregate, bounded by the formation maximum rather than the squad allocation: a
        # squad holds two goalkeepers but only ever starts one, so eligible keepers beyond the
        # first cannot help fill the XI.
        capacity = sum(
            min(
                squad_rules.formation_max[position],
                squad_rules.composition[position],
                int((eligible["position"] == position.value).sum()),
            )
            for position in Position
        )
        if capacity < squad_rules.starting_size:
            reasons.append(
                f"only {capacity} players clear the {floor:.0%} start-probability floor within the "
                f"squad's positional allocation, but {squad_rules.starting_size} must start; "
                "lock a player to override the floor, or lower it in configuration"
            )

    if not reasons:
        reasons.append("the constraints are jointly unsatisfiable, but no single cause stands out")
    return reasons


def optimise_squad(
    players: pd.DataFrame, rules: GameRules, config: OptimiserConfig
) -> tuple[Squad, SolveReport]:
    """Solve for the best legal squad. Raises :class:`InfeasibleError` when none exists."""
    missing = [column for column in REQUIRED_COLUMNS if column not in players.columns]
    if missing:
        raise ValueError(f"player frame is missing columns: {', '.join(missing)}")

    pool = players.reset_index(drop=True)
    squad_rules = rules.squad
    started = time.monotonic()

    problem = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    ids = [as_int(value) for value in pool["player_id"]]
    select = pulp.LpVariable.dicts("select", ids, cat="Binary")
    start = pulp.LpVariable.dicts("start", ids, cat="Binary")
    captain = pulp.LpVariable.dicts("captain", ids, cat="Binary")

    by_id = {as_int(row.player_id): row for row in pool.itertuples()}
    locked = set(config.locked_player_ids)
    banned = set(config.banned_player_ids)
    excluded_clubs = set(config.excluded_team_ids)

    # --- objective ---
    problem += pulp.lpSum(
        as_float(by_id[i].xp_horizon) * (start[i] + config.bench_weight * (select[i] - start[i]))
        + as_float(by_id[i].xp_next) * (config.captain_multiplier - 1) * captain[i]
        for i in ids
    )

    # --- squad composition ---
    problem += pulp.lpSum(select[i] for i in ids) == squad_rules.size, "squad_size"
    for position in Position:
        members = [i for i in ids if by_id[i].position == position.value]
        problem += (
            pulp.lpSum(select[i] for i in members) == squad_rules.composition[position],
            f"composition_{position.value}",
        )

    # Money in tenths: comparing floats against a budget is how a squad costing exactly £100.0m
    # gets rejected for costing £100.00000000000001.
    problem += (
        pulp.lpSum(round(as_float(by_id[i].price) * 10) * select[i] for i in ids)
        <= round(squad_rules.budget * 10),
        "budget",
    )

    for team_id in sorted({as_int(by_id[i].team_id) for i in ids}):
        members = [i for i in ids if as_int(by_id[i].team_id) == team_id]
        problem += (
            pulp.lpSum(select[i] for i in members) <= squad_rules.club_limit,
            f"club_limit_{team_id}",
        )

    # --- lineup ---
    problem += pulp.lpSum(start[i] for i in ids) == squad_rules.starting_size, "starting_size"
    for i in ids:
        problem += start[i] <= select[i], f"start_implies_select_{i}"
        problem += captain[i] <= start[i], f"captain_implies_start_{i}"
    problem += pulp.lpSum(captain[i] for i in ids) == 1, "one_captain"

    for position in Position:
        members = [i for i in ids if by_id[i].position == position.value]
        problem += (
            pulp.lpSum(start[i] for i in members) >= squad_rules.formation_min[position],
            f"formation_min_{position.value}",
        )
        problem += (
            pulp.lpSum(start[i] for i in members) <= squad_rules.formation_max[position],
            f"formation_max_{position.value}",
        )

    # --- user overrides and the start-probability floor ---
    for i in ids:
        if i in locked:
            problem += select[i] == 1, f"lock_{i}"
        if i in banned or as_int(by_id[i].team_id) in excluded_clubs:
            problem += select[i] == 0, f"ban_{i}"

    if config.enforce_start_probability_floor:
        floor = _start_floor(pool)
        for i in ids:
            if i not in locked and as_float(by_id[i].start_probability) < floor:
                problem += start[i] == 0, f"start_floor_{i}"

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=config.solve_time_limit_seconds)
    problem.solve(solver)
    elapsed = time.monotonic() - started
    status = pulp.LpStatus[problem.status]

    if status != "Optimal":
        log.warning(
            "optimise.not_optimal",
            extra={"status": status, "seconds": round(elapsed, 2)},
        )
        if status == "Infeasible":
            reasons = _diagnose_infeasibility(pool, rules, config)
            raise InfeasibleError("no legal squad exists: " + "; ".join(reasons))
        return _greedy_fallback(pool, rules, config, elapsed)

    chosen = [i for i in ids if select[i].value() and round(select[i].value()) == 1]
    starting = [i for i in chosen if start[i].value() and round(start[i].value()) == 1]
    captain_id = next(i for i in starting if captain[i].value() and round(captain[i].value()) == 1)

    squad = _build_squad(pool, chosen, starting, captain_id)
    report = _report(
        squad, pool, SolveStatus.OPTIMAL, float(pulp.value(problem.objective)), elapsed, rules
    )
    log.info(
        "optimise.solved",
        extra={
            "objective": round(report.objective, 3),
            "seconds": round(elapsed, 2),
            "price": report.total_price,
            "formation": report.formation,
        },
    )
    return squad, report


def _start_floor(pool: pd.DataFrame) -> float:
    """The floor travels with the forecast, so the optimiser cannot disagree with the model card."""
    if "start_floor" in pool.columns:
        return as_float(pool["start_floor"].iloc[0])
    from fpl_dof.config.models import ForecastConfig

    return ForecastConfig().minimum_start_probability_for_xi


def _build_squad(
    pool: pd.DataFrame, chosen: list[int], starting: list[int], captain_id: int
) -> Squad:
    rows = pool[pool["player_id"].isin(chosen)]
    players = tuple(
        SquadPlayer(
            player_id=as_int(row.player_id),
            position=Position(str(row.position)),
            team_id=as_int(row.team_id),
            price=as_float(row.price),
        )
        for row in rows.itertuples()
    )
    starting_rows = pool[pool["player_id"].isin(starting)].sort_values("xp_next", ascending=False)
    vice = next(
        (
            as_int(row.player_id)
            for row in starting_rows.itertuples()
            if as_int(row.player_id) != captain_id
        ),
        captain_id,
    )
    bench_rows = pool[
        pool["player_id"].isin(set(chosen) - set(starting))
        & (pool["position"] != Position.GKP.value)
    ].sort_values("xp_next", ascending=False)

    return Squad(
        players=players,
        starting=tuple(starting),
        captain=captain_id,
        vice_captain=vice,
        bench_order=tuple(as_int(row.player_id) for row in bench_rows.itertuples()),
    )


def _report(
    squad: Squad,
    pool: pd.DataFrame,
    status: SolveStatus,
    objective: float,
    elapsed: float,
    rules: GameRules,
) -> SolveReport:
    formation: dict[str, int] = {}
    members = squad.by_id()
    for player_id in squad.starting:
        position = members[player_id].position.value
        formation[position] = formation.get(position, 0) + 1

    violations = validate_squad(squad, rules)
    if violations:
        # Not a warning. The solver produced something illegal, which means a constraint is wrong.
        raise AssertionError(
            "the optimiser returned an illegal squad, which is a defect in the formulation: "
            + "; ".join(v.message for v in violations)
        )

    return SolveReport(
        status=status,
        objective=objective,
        solve_seconds=elapsed,
        formation=formation,
        captain_id=squad.captain or 0,
        vice_captain_id=squad.vice_captain or 0,
        total_price=squad.total_price,
        violations=violations,
    )


def _greedy_fallback(
    pool: pd.DataFrame, rules: GameRules, config: OptimiserConfig, elapsed: float
) -> tuple[Squad, SolveReport]:
    """A legal squad when the solver could not finish. Worse, but on time (DP-15).

    Fills each position by expected points per pound, respecting budget and club limit. It does not
    pretend to be optimal, and the report says so.
    """
    log.warning("optimise.greedy_fallback", extra={"reason": "solver did not reach optimality"})
    squad_rules = rules.squad
    available = pool[
        ~pool["player_id"].isin(config.banned_player_ids)
        & ~pool["team_id"].isin(config.excluded_team_ids)
    ].copy()
    available["value"] = available["xp_horizon"] / available["price"].clip(lower=0.1)

    chosen: list[int] = []
    spend = 0.0
    per_club: dict[int, int] = {}

    forced = available[available["player_id"].isin(config.locked_player_ids)]
    for row in forced.itertuples():
        chosen.append(as_int(row.player_id))
        spend += as_float(row.price)
        per_club[as_int(row.team_id)] = per_club.get(as_int(row.team_id), 0) + 1

    for position in Position:
        needed = squad_rules.composition[position] - sum(
            1
            for i in chosen
            if str(available.loc[available["player_id"] == i, "position"].iloc[0]) == position.value
        )
        candidates = available[
            (available["position"] == position.value) & ~available["player_id"].isin(chosen)
        ].sort_values("value", ascending=False)
        for row in candidates.itertuples():
            if needed <= 0:
                break
            team_id = as_int(row.team_id)
            if per_club.get(team_id, 0) >= squad_rules.club_limit:
                continue
            if spend + as_float(row.price) > squad_rules.budget:
                continue
            chosen.append(as_int(row.player_id))
            spend += as_float(row.price)
            per_club[team_id] = per_club.get(team_id, 0) + 1
            needed -= 1
        if needed > 0:
            raise InfeasibleError(
                f"greedy fallback could not fill {needed} more {position.value} within the budget"
            )

    selected = pool[pool["player_id"].isin(chosen)].sort_values("xp_next", ascending=False)
    starting = _greedy_lineup(selected, rules)
    captain_id = as_int(selected[selected["player_id"].isin(starting)].iloc[0]["player_id"])
    squad = _build_squad(pool, chosen, starting, captain_id)
    objective = float(selected[selected["player_id"].isin(starting)]["xp_horizon"].sum())
    return squad, _report(squad, pool, SolveStatus.GREEDY_FALLBACK, objective, elapsed, rules)


def _greedy_lineup(selected: pd.DataFrame, rules: GameRules) -> list[int]:
    """Best legal formation by expected points, chosen by enumerating the legal shapes."""
    best: list[int] = []
    best_value = float("-inf")
    for formation in rules.squad.legal_formations():
        lineup: list[int] = []
        value = 0.0
        for position, count in formation.items():
            members = selected[selected["position"] == position.value].head(count)
            if len(members) < count:
                break
            lineup.extend(as_int(row.player_id) for row in members.itertuples())
            value += float(members["xp_next"].sum())
        else:
            if value > best_value:
                best_value, best = value, lineup
    if not best:
        raise InfeasibleError("no legal formation could be built from the selected squad")
    return best
