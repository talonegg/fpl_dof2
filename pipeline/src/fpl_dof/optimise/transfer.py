"""The weekly transfer decision.

A different question from E0's, and the difference matters. E0 asks *what is the best squad*. This
asks *given the squad I have, is any change worth making* — which is a question about a **margin**,
not a total, and the margin is usually small enough to be inside the forecast's own error bars. That
is why the honest answer is so often "do nothing", and why doing nothing is presented here as an
option with a number attached rather than as the absence of a recommendation (FR-24).

Formulation
-----------
One MILP per transfer count *k* in ``0..max_transfers``. Binary ``sell_i`` over the current squad
and ``buy_j`` over everyone else, plus the E0 lineup variables over the resulting 15.

* exactly *k* sold and *k* bought, and position-for-position so composition is preserved
* the club limit applies to the squad you end up with, not the one you started from
* money is the **selling** value of what you sell plus the bank — not the current price, because
  the sell-on fee means those differ for any player who has risen
* the objective subtracts the hit: transfers beyond the free allowance cost 4 points each

Solving each *k* separately rather than penalising transfers inside one model is deliberate. It
costs a handful of extra solves and it produces the thing the weekly output actually needs: a
ranked list where each option carries its own expected gain, so the decision is legible rather than
delivered (DP-10).

**The 4-point hit is not a tunable.** It is read from the rules, which read it from configuration
seeded against the game (Invariant 2). ``min_gain_over_hit`` is the separate, honest knob: how much
margin you demand *beyond* break-even before believing a forecast difference that small.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd
import pulp

from fpl_dof.config.models import OptimiserConfig, TransferConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.squad import REQUIRED_COLUMNS, InfeasibleError, _start_floor
from fpl_dof.rules.legality import Squad, SquadPlayer, validate_squad
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.squad.state import SquadState

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TransferMove:
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    selling_price: float
    buying_price: float

    def describe(self) -> str:
        return (
            f"{self.player_out_name} (£{self.selling_price:.1f}m) -> "
            f"{self.player_in_name} (£{self.buying_price:.1f}m)"
        )


@dataclass(frozen=True, slots=True)
class TransferOption:
    """One candidate course of action for the week, with its own arithmetic attached."""

    transfers: int
    moves: tuple[TransferMove, ...]
    hit_points: int
    """Always <= 0. The cost of transfers beyond the free allowance."""

    gross_expected_points: float
    """Expected points from the resulting XI, captain included, before the hit."""

    starting: tuple[int, ...]
    bench_order: tuple[int, ...]
    captain_id: int
    vice_captain_id: int
    formation: dict[str, int]
    bank_after: float
    squad_after: tuple[int, ...]

    @property
    def net_expected_points(self) -> float:
        return round(self.gross_expected_points + self.hit_points, 4)

    def gain_over(self, baseline: TransferOption) -> float:
        """Net gain against doing nothing. The number the decision actually turns on."""
        return round(self.net_expected_points - baseline.net_expected_points, 4)


@dataclass(frozen=True, slots=True)
class TransferRecommendation:
    """Every option considered, and which one wins.

    ``options`` always contains the zero-transfer roll, and it is always ranked alongside the rest
    rather than being treated as a fallback.
    """

    recommended: TransferOption
    options: tuple[TransferOption, ...]
    free_transfers: int
    solve_seconds: float
    rationale: str
    warnings: tuple[str, ...] = field(default=())

    @property
    def roll(self) -> TransferOption:
        return next(option for option in self.options if option.transfers == 0)

    def is_roll(self) -> bool:
        return self.recommended.transfers == 0


def hit_cost(transfers: int, free_transfers: int, rules: GameRules) -> int:
    """Points charged for making ``transfers`` this week. Never positive."""
    paid = max(0, transfers - free_transfers)
    return paid * rules.transfers.extra_transfer_cost


def recommend_transfers(
    players: pd.DataFrame,
    state: SquadState,
    rules: GameRules,
    transfer_config: TransferConfig,
    optimiser_config: OptimiserConfig,
) -> TransferRecommendation:
    """Rank doing nothing against every affordable transfer, and say which wins and why."""
    missing = [column for column in REQUIRED_COLUMNS if column not in players.columns]
    if missing:
        raise ValueError(f"player frame is missing columns: {', '.join(missing)}")

    pool = players.reset_index(drop=True)
    held = state.player_ids()
    unknown = held - {as_int(value) for value in pool["player_id"]}
    if unknown:
        raise InfeasibleError(
            f"squad contains player(s) absent from the forecast: {sorted(unknown)}; "
            "the transfer decision cannot be priced without them"
        )

    started = time.monotonic()
    warnings: list[str] = []
    options: list[TransferOption] = []
    for count in range(transfer_config.max_transfers + 1):
        option = _solve_for(count, pool, state, rules, optimiser_config)
        if option is None:
            if count == 0:
                raise InfeasibleError(
                    "no legal starting XI exists for the current squad; the squad itself is the "
                    "problem, not the transfer decision"
                )
            warnings.append(f"no legal {count}-transfer option exists within the budget")
            continue
        options.append(option)

    baseline = next(option for option in options if option.transfers == 0)
    recommended, rationale = _choose(options, baseline, state, transfer_config, rules)
    elapsed = time.monotonic() - started

    log.info(
        "transfer.recommended",
        extra={
            "transfers": recommended.transfers,
            "net_xp": recommended.net_expected_points,
            "gain": recommended.gain_over(baseline),
            "seconds": round(elapsed, 2),
        },
    )
    return TransferRecommendation(
        recommended=recommended,
        options=tuple(options),
        free_transfers=state.free_transfers,
        solve_seconds=elapsed,
        rationale=rationale,
        warnings=tuple(warnings),
    )


def _choose(
    options: list[TransferOption],
    baseline: TransferOption,
    state: SquadState,
    transfer_config: TransferConfig,
    rules: GameRules,
) -> tuple[TransferOption, str]:
    """Pick the winner, and say in one sentence why it won.

    A transfer that costs a hit must clear the hit **and** the configured margin. That is the
    "never recommends a hit whose expected gain is below the cost" acceptance criterion, and it is
    enforced here rather than left to the objective, so the reason is reportable.
    """
    best = baseline
    reason = "no transfer improves on rolling"
    for option in options:
        if option.transfers == 0:
            continue
        gain = option.gain_over(baseline)
        takes_hit = option.transfers > state.free_transfers
        required = transfer_config.min_gain_over_hit if takes_hit else 0.0
        if gain <= required:
            continue
        if gain > best.gain_over(baseline):
            best = option
            if takes_hit:
                cost = -option.hit_points
                reason = (
                    f"{option.transfers} transfers gain {gain:.2f} expected points after a "
                    f"{cost}-point hit"
                )
            else:
                reason = f"{option.transfers} free transfer(s) gain {gain:.2f} expected points"

    if best is baseline:
        rolled = min(state.free_transfers + 1, rules.transfers.max_free_transfers)
        reason = (
            f"{reason}; roll to {rolled} free transfer(s) next week"
            if state.free_transfers < rules.transfers.max_free_transfers
            else f"{reason}, and the free-transfer allowance is already at its maximum"
        )
    return best, reason


def _solve_for(
    transfers: int,
    pool: pd.DataFrame,
    state: SquadState,
    rules: GameRules,
    config: OptimiserConfig,
) -> TransferOption | None:
    """Best XI achievable by making exactly ``transfers`` changes. ``None`` when none is legal."""
    squad_rules = rules.squad
    held = state.player_ids()
    by_id = {as_int(row.player_id): row for row in pool.itertuples()}
    ids = list(by_id)

    selling = {player.player_id: player.selling_price(rules) for player in state.players}
    banned = set(config.banned_player_ids)
    locked = set(config.locked_player_ids)
    excluded_clubs = set(config.excluded_team_ids)

    problem = pulp.LpProblem(f"fpl_transfer_{transfers}", pulp.LpMaximize)
    select = pulp.LpVariable.dicts("select", ids, cat="Binary")
    start = pulp.LpVariable.dicts("start", ids, cat="Binary")
    captain = pulp.LpVariable.dicts("captain", ids, cat="Binary")

    problem += pulp.lpSum(
        as_float(by_id[i].xp_next) * (start[i] + captain[i] * (config.captain_multiplier - 1))
        + config.bench_weight * as_float(by_id[i].xp_next) * (select[i] - start[i])
        for i in ids
    )

    # --- the squad you end up with is still a legal squad ---
    problem += pulp.lpSum(select[i] for i in ids) == squad_rules.size, "squad_size"
    for position in Position:
        members = [i for i in ids if by_id[i].position == position.value]
        problem += (
            pulp.lpSum(select[i] for i in members) == squad_rules.composition[position],
            f"composition_{position.value}",
        )
    for team_id in sorted({as_int(by_id[i].team_id) for i in ids}):
        members = [i for i in ids if as_int(by_id[i].team_id) == team_id]
        problem += (
            pulp.lpSum(select[i] for i in members) <= squad_rules.club_limit,
            f"club_limit_{team_id}",
        )

    # --- exactly this many changes ---
    problem += (
        pulp.lpSum(1 - select[i] for i in held) == transfers,
        "transfers_out",
    )

    # --- money: sell value of what leaves, plus bank, buys what arrives ---
    # In tenths throughout, for the same reason as the squad optimiser.
    bank_tenths = round(state.bank * 10)
    problem += (
        pulp.lpSum(round(as_float(by_id[i].price) * 10) * select[i] for i in ids if i not in held)
        <= bank_tenths + pulp.lpSum(round(selling[i] * 10) * (1 - select[i]) for i in held),
        "budget",
    )

    # --- lineup, exactly as E0 states it ---
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

    # --- overrides ---
    for i in ids:
        if i in locked:
            problem += select[i] == 1, f"lock_{i}"
        elif i not in held and (i in banned or as_int(by_id[i].team_id) in excluded_clubs):
            problem += select[i] == 0, f"ban_{i}"

    if config.enforce_start_probability_floor:
        floor = _start_floor(pool)
        for i in ids:
            if i not in locked and as_float(by_id[i].start_probability) < floor:
                problem += start[i] == 0, f"start_floor_{i}"

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=config.solve_time_limit_seconds)
    problem.solve(solver)
    if pulp.LpStatus[problem.status] != "Optimal":
        return None

    chosen = [i for i in ids if select[i].value() and round(select[i].value()) == 1]
    starting = [i for i in chosen if start[i].value() and round(start[i].value()) == 1]
    captain_id = next(i for i in starting if captain[i].value() and round(captain[i].value()) == 1)

    option = _build_option(
        transfers=transfers,
        pool=pool,
        state=state,
        rules=rules,
        chosen=chosen,
        starting=starting,
        captain_id=captain_id,
        config=config,
    )

    # Check the result rather than trusting the formulation, exactly as the squad optimiser does.
    squad = Squad(
        players=tuple(
            SquadPlayer(
                player_id=i,
                position=Position(str(by_id[i].position)),
                team_id=as_int(by_id[i].team_id),
                price=selling.get(i, as_float(by_id[i].price)),
            )
            for i in chosen
        ),
        starting=tuple(starting),
        captain=captain_id,
        vice_captain=option.vice_captain_id,
        bench_order=option.bench_order,
    )
    violations = validate_squad(squad, rules, budget=state.budget(rules))
    if violations:
        raise AssertionError(
            f"the {transfers}-transfer solution is not a legal squad, which is a defect in the "
            "formulation: " + "; ".join(v.message for v in violations)
        )
    return option


def _build_option(
    *,
    transfers: int,
    pool: pd.DataFrame,
    state: SquadState,
    rules: GameRules,
    chosen: list[int],
    starting: list[int],
    captain_id: int,
    config: OptimiserConfig,
) -> TransferOption:
    by_id = {as_int(row.player_id): row for row in pool.itertuples()}
    held = state.player_ids()
    names = {player.player_id: player.web_name for player in state.players}

    sold = sorted(held - set(chosen))
    bought = sorted(set(chosen) - held)
    selling = {player.player_id: player.selling_price(rules) for player in state.players}

    moves = tuple(
        TransferMove(
            player_out_id=out_id,
            player_out_name=names.get(out_id, str(out_id)),
            player_in_id=in_id,
            player_in_name=str(by_id[in_id].web_name) if "web_name" in pool.columns else str(in_id),
            selling_price=selling[out_id],
            buying_price=as_float(by_id[in_id].price),
        )
        # Paired by position: composition is preserved, so the k sold and k bought match up
        # position for position, and pairing them makes the recommendation readable.
        for out_id, in_id in _pair_by_position(
            sold, bought, {i: str(by_id[i].position) for i in sold + bought}
        )
    )

    raised = sum(selling[i] for i in sold)
    spent = sum(as_float(by_id[i].price) for i in bought)
    bank_after = round(state.bank + raised - spent, 1)

    starting_rows = sorted(starting, key=lambda i: (-as_float(by_id[i].xp_next), i))
    vice = next((i for i in starting_rows if i != captain_id), captain_id)
    bench = sorted(
        (i for i in chosen if i not in set(starting) and by_id[i].position != Position.GKP.value),
        key=lambda i: (
            -as_float(by_id[i].xp_next) * as_float(by_id[i].start_probability),
            i,
        ),
    )

    formation: dict[str, int] = {}
    for i in starting:
        position = str(by_id[i].position)
        formation[position] = formation.get(position, 0) + 1

    gross = sum(as_float(by_id[i].xp_next) for i in starting)
    gross += as_float(by_id[captain_id].xp_next) * (config.captain_multiplier - 1)

    return TransferOption(
        transfers=transfers,
        moves=moves,
        hit_points=hit_cost(transfers, state.free_transfers, rules),
        gross_expected_points=round(gross, 4),
        starting=tuple(starting_rows),
        bench_order=tuple(bench),
        captain_id=captain_id,
        vice_captain_id=vice,
        formation=formation,
        bank_after=bank_after,
        squad_after=tuple(sorted(chosen)),
    )


def _pair_by_position(
    sold: list[int], bought: list[int], positions: dict[int, str]
) -> list[tuple[int, int]]:
    remaining = list(bought)
    pairs: list[tuple[int, int]] = []
    for out_id in sold:
        position = positions[out_id]
        match = next((i for i in remaining if positions[i] == position), None)
        if match is None:
            # Cannot happen while composition is constrained equal, but pairing is presentation
            # and must not throw if the formulation ever loosens.
            match = remaining[0]
        remaining.remove(match)
        pairs.append((out_id, match))
    return pairs


def describe(recommendation: TransferRecommendation) -> list[str]:
    """The weekly output, as lines. Every option, not only the winner."""
    lines = [f"Recommendation: {recommendation.rationale}"]
    baseline = recommendation.roll
    for option in sorted(recommendation.options, key=lambda o: o.transfers):
        gain = option.gain_over(baseline)
        label = "roll (no transfer)" if option.transfers == 0 else f"{option.transfers} transfer(s)"
        marker = " <-- recommended" if option is recommendation.recommended else ""
        lines.append(
            f"  {label}: net {option.net_expected_points:.2f} xP "
            f"(gain {gain:+.2f}, hit {option.hit_points}){marker}"
        )
        lines.extend(f"      {move.describe()}" for move in option.moves)
    lines.extend(f"  warning: {warning}" for warning in recommendation.warnings)
    return lines


__all__ = [
    "TransferMove",
    "TransferOption",
    "TransferRecommendation",
    "describe",
    "hit_cost",
    "recommend_transfers",
]
