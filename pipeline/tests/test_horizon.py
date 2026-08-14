"""E4-S2 — the multi-gameweek MILP, and the three property tests the epic makes mandatory.

Each of the three catches a failure that is **silent**: the plan still looks like a plan, the
numbers still look like numbers, and the recommendation is wrong for weeks before anybody notices.

* **Chips do not consume free transfers (C15)** - without it the model believes a Wildcard burns up
  to five banked transfers, and plays chips too late or never.
* **Accrual caps at five and never goes negative** - an off-by-one in the ``min`` linearisation
  compounds into a plan built on transfers that do not exist.
* **Legality at every gameweek of the horizon** - E1's property tests only ever saw one gameweek.
"""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from decisions import OPTIMISER, chip_table, decision, forecast, pool, state
from fpl_dof.optimise.chips import ChipScenario
from fpl_dof.optimise.horizon import (
    HorizonInputs,
    free_transfer_ledger,
    plan_gameweeks,
    solve_horizon,
)
from fpl_dof.optimise.squad import InfeasibleError, SolveStatus
from fpl_dof.rules.legality import Squad, SquadPlayer, validate_squad
from fpl_dof.rules.models import GameRules, Position

SLOW = settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


def _inputs(
    game_rules: GameRules,
    *,
    gameweeks: tuple[int, ...],
    mean: dict[int, float] | float = 2.0,
    free_transfers: int = 1,
    bank: float = 2.0,
) -> HorizonInputs:
    players = pool()
    squad_state = state(
        game_rules, players, bank=bank, free_transfers=free_transfers, gameweek=gameweeks[0]
    )
    return HorizonInputs(
        players=forecast(players, gameweeks, mean=mean),
        state=squad_state,
        rules=game_rules,
        gameweeks=gameweeks,
    )


# --------------------------------------------------------------------------- C15


@pytest.mark.parametrize("chip", ["wildcard", "freehit"])
def test_chips_do_not_consume_free_transfers(game_rules: GameRules, chip: str) -> None:
    """C15, and the half of it that gets missed.

    A Wildcard costing no *hit* is obvious. That it also does not *spend* the balance is not, and
    without it the free-transfer ledger silently punishes exactly the gameweek the chip was played
    in — which is how a chip planner learns to play chips too late, or never.
    """
    gameweeks = (2, 3, 4)
    # A steep gradient in expected points, so the solver genuinely wants to use the chip's
    # unlimited transfers rather than sitting still and passing the test for the wrong reason.
    mean = {player_id: 1.0 + (player_id % 7) for player_id in range(1, 40)}
    inputs = _inputs(game_rules, gameweeks=gameweeks, mean=mean, free_transfers=3, bank=5.0)
    scenario = ChipScenario(assignments=((2, chip),))

    plan = solve_horizon(inputs, scenario, decision(gameweeks=3), OPTIMISER)
    chip_week = plan.weeks[0]

    assert chip_week.chip == chip
    assert chip_week.charged_transfers == 0, "a chip gameweek must charge nothing to the allowance"
    assert chip_week.hit_points == 0, "a chip gameweek can never take a hit"

    ledger = free_transfer_ledger(plan)
    maximum = game_rules.transfers.max_free_transfers
    assert ledger[3] == min(maximum, ledger[2] + 1), (
        "the balance must carry forward untouched and keep accruing through a chip gameweek"
    )


def test_a_wildcard_actually_transfers_while_charging_nothing(game_rules: GameRules) -> None:
    """The other side of C15: charging nothing must not be achieved by doing nothing.

    Without this, a formulation that simply forbade transfers on a chip week would pass the test
    above while making the Wildcard worthless.
    """
    gameweeks = (2, 3)
    mean = {player_id: 0.5 + 2.0 * (player_id % 5) for player_id in range(1, 40)}
    inputs = _inputs(game_rules, gameweeks=gameweeks, mean=mean, free_transfers=1, bank=8.0)

    plan = solve_horizon(
        inputs, ChipScenario(assignments=((2, "wildcard"),)), decision(gameweeks=2), OPTIMISER
    )
    week = plan.weeks[0]
    assert len(week.transfers_in) > 1, "a Wildcard should buy more than a free transfer could"
    assert week.charged_transfers == 0
    assert week.hit_points == 0


# --------------------------------------------------------------------------- accrual


@given(opening=st.integers(min_value=1, max_value=5))
@SLOW
def test_free_transfer_accrual_caps_at_five_and_never_goes_negative(
    game_rules: GameRules, opening: int
) -> None:
    """C8's ``min`` linearisation, over enough weeks to reach the cap.

    Held deliberately still — no transfers permitted — because that isolates the accrual arithmetic
    from the transfer decision. If the ledger is wrong here it is wrong everywhere, and it is
    wrong in a way that only shows up as a plan spending transfers it never had.
    """
    gameweeks = (2, 3, 4, 5, 6, 7)
    inputs = _inputs(game_rules, gameweeks=gameweeks, free_transfers=opening)
    plan = solve_horizon(inputs, ChipScenario(), decision(gameweeks=6, max_transfers=0), OPTIMISER)

    maximum = game_rules.transfers.max_free_transfers
    ledger = free_transfer_ledger(plan)
    assert ledger[gameweeks[0]] == min(maximum, opening)

    previous = ledger[gameweeks[0]]
    for gameweek in gameweeks[1:]:
        current = ledger[gameweek]
        assert 0 <= current <= maximum, "the balance is bounded below by zero and above by the cap"
        assert current == min(maximum, previous + 1), "one earned per week, capped, never negative"
        previous = current


def test_spending_transfers_reduces_the_balance_without_taking_it_negative(
    game_rules: GameRules,
) -> None:
    """Using more than you had does not put you in debt; it starts you on one next week."""
    gameweeks = (2, 3, 4)
    mean = {player_id: 0.5 + 2.0 * (player_id % 5) for player_id in range(1, 40)}
    inputs = _inputs(game_rules, gameweeks=gameweeks, mean=mean, free_transfers=1, bank=8.0)
    plan = solve_horizon(inputs, ChipScenario(), decision(gameweeks=3, max_transfers=3), OPTIMISER)

    maximum = game_rules.transfers.max_free_transfers
    for index, week in enumerate(plan.weeks):
        assert week.free_transfers >= 1
        assert week.free_transfers <= maximum
        assert week.charged_transfers >= 0
        assert week.hit_points <= 0
        if index == 0:
            continue
        previous = plan.weeks[index - 1]
        remaining = max(0, previous.free_transfers - previous.charged_transfers)
        assert week.free_transfers == min(maximum, remaining + 1)


def test_hits_are_charged_only_beyond_the_free_allowance(game_rules: GameRules) -> None:
    gameweeks = (2, 3)
    mean = {player_id: 0.5 + 3.0 * (player_id % 5) for player_id in range(1, 40)}
    inputs = _inputs(game_rules, gameweeks=gameweeks, mean=mean, free_transfers=1, bank=8.0)
    plan = solve_horizon(inputs, ChipScenario(), decision(gameweeks=2, max_transfers=3), OPTIMISER)

    cost = game_rules.transfers.extra_transfer_cost
    for week in plan.weeks:
        expected = max(0, week.charged_transfers - week.free_transfers) * cost
        assert week.hit_points == expected


# --------------------------------------------------------------------------- legality


@given(
    seed=st.lists(
        st.floats(min_value=0.0, max_value=9.0, allow_nan=False), min_size=39, max_size=39
    )
)
@SLOW
def test_squad_legality_holds_at_every_gameweek_of_the_horizon(
    game_rules: GameRules, seed: list[float]
) -> None:
    """Not only the first. E1's property tests only ever saw one gameweek.

    A formulation that is right in week one and wrong in week four produces a plan that validates
    on the day and quietly falls apart, which is the definition of a failure worth testing hardest
    for (DP-13).
    """
    gameweeks = (2, 3, 4)
    mean = {index + 1: value for index, value in enumerate(seed)}
    inputs = _inputs(game_rules, gameweeks=gameweeks, mean=mean, free_transfers=2, bank=6.0)
    plan = solve_horizon(inputs, ChipScenario(), decision(gameweeks=3), OPTIMISER)

    assert len(plan.weeks) == len(gameweeks)
    prices = inputs.players.set_index("player_id")["price"]
    positions = inputs.players.set_index("player_id")["position"]
    teams = inputs.players.set_index("player_id")["team_id"]

    for week in plan.weeks:
        squad = Squad(
            players=tuple(
                SquadPlayer(
                    player_id=player_id,
                    position=Position(str(positions.loc[player_id])),
                    team_id=int(teams.loc[player_id]),
                    price=float(prices.loc[player_id]),
                )
                for player_id in week.fielded
            ),
            starting=week.starting,
            captain=week.captain_id,
            vice_captain=week.vice_captain_id,
            bench_order=week.bench_order,
        )
        violations = validate_squad(squad, game_rules, budget=inputs.state.budget(game_rules))
        assert not violations, f"gameweek {week.gameweek}: " + "; ".join(
            v.message for v in violations
        )


def test_a_free_hit_fields_a_different_squad_and_gives_it_back(game_rules: GameRules) -> None:
    """C13. The persistent squad is untouched; only the gameweek's fielded XI changes."""
    gameweeks = (2, 3)
    mean = {player_id: 0.5 + 2.5 * (player_id % 5) for player_id in range(1, 40)}
    inputs = _inputs(game_rules, gameweeks=gameweeks, mean=mean, free_transfers=1, bank=8.0)
    plan = solve_horizon(
        inputs, ChipScenario(assignments=((2, "freehit"),)), decision(gameweeks=2), OPTIMISER
    )

    free_hit_week, following = plan.weeks
    assert set(free_hit_week.squad) == inputs.state.player_ids(), (
        "a Free Hit changes what you field, never what you own"
    )
    assert not free_hit_week.transfers_in and not free_hit_week.transfers_out
    assert set(following.squad) >= set(inputs.state.player_ids()) - set(following.transfers_out)


# --------------------------------------------------------------------------- reproducibility


def test_the_same_inputs_produce_the_same_squad_twice_running(game_rules: GameRules) -> None:
    """R-16, and the epic's own definition of done.

    The FPL squad problem is densely degenerate: many different fifteens share an objective value
    identical to within floating-point noise, and which one a solver returns is an implementation
    detail that can change between runs on unchanged inputs. The incumbency tie-break exists to
    make that choice deterministic; this is the test that says it does.
    """
    gameweeks = (2, 3, 4)
    mean = {player_id: 2.0 + 0.1 * (player_id % 4) for player_id in range(1, 40)}
    inputs = _inputs(game_rules, gameweeks=gameweeks, mean=mean, free_transfers=2, bank=4.0)
    config = decision(gameweeks=3)

    first = solve_horizon(inputs, ChipScenario(), config, OPTIMISER)
    second = solve_horizon(inputs, ChipScenario(), config, OPTIMISER)

    assert [week.squad for week in first.weeks] == [week.squad for week in second.weeks]
    assert [week.starting for week in first.weeks] == [week.starting for week in second.weeks]
    assert [week.captain_id for week in first.weeks] == [week.captain_id for week in second.weeks]
    assert first.objective == pytest.approx(second.objective)


def test_the_incumbency_bonus_keeps_a_tied_squad_rather_than_churning_it(
    game_rules: GameRules,
) -> None:
    """A transfer must clear a margin, not merely tie.

    Every player is worth exactly the same, so every legal fifteen has the same expected points and
    the solver has no reason to prefer any of them. Without the tie-break it would return whichever
    one the branch-and-bound happened to reach, and the recommendation would churn on refresh for
    no stated reason — which erodes trust faster than being wrong for a reason.
    """
    gameweeks = (2, 3)
    inputs = _inputs(game_rules, gameweeks=gameweeks, mean=2.0, free_transfers=2, bank=5.0)
    plan = solve_horizon(inputs, ChipScenario(), decision(gameweeks=2), OPTIMISER)

    for week in plan.weeks:
        assert set(week.squad) == inputs.state.player_ids(), (
            "with nothing to gain, the incumbent squad must be kept"
        )
        assert week.transfers_in == ()


# --------------------------------------------------------------------------- fallback


def test_the_greedy_fallback_produces_a_legal_plan_and_says_it_is_a_fallback(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DP-15. A worse recommendation beats no recommendation at a deadline.

    The solver is made to fail rather than merely made slow, because a time limit that happens to
    be met on a fast machine is a test that passes for the wrong reason.
    """
    import pulp

    import fpl_dof.optimise.horizon as horizon_module

    class _Failing:
        def actualSolve(self, problem: object) -> int:  # noqa: N802 - PuLP's own interface
            raise pulp.PulpSolverError("solver unavailable")

    monkeypatch.setattr(horizon_module, "_solver", lambda config: _Failing())

    gameweeks = (2, 3)
    inputs = _inputs(game_rules, gameweeks=gameweeks, free_transfers=1)
    plan = solve_horizon(inputs, ChipScenario(), decision(gameweeks=2), OPTIMISER)

    assert plan.status is SolveStatus.GREEDY_FALLBACK
    assert plan.warnings and "fallback" in plan.warnings[0]
    for week in plan.weeks:
        assert set(week.fielded) == inputs.state.player_ids()
        assert len(week.starting) == game_rules.squad.starting_size
        assert week.hit_points == 0


# --------------------------------------------------------------------------- overrides


def test_an_impossible_lock_says_why_rather_than_reporting_a_status_code(
    game_rules: GameRules,
) -> None:
    """E4-S5. An infeasible combination must explain itself."""
    gameweeks = (2, 3)
    inputs = _inputs(game_rules, gameweeks=gameweeks)
    config = decision(gameweeks=2)
    optimiser = OPTIMISER.model_copy(update={"locked_player_ids": (1,), "banned_player_ids": (1,)})

    with pytest.raises(InfeasibleError) as caught:
        solve_horizon(inputs, ChipScenario(), config, optimiser)
    assert "both locked and banned" in str(caught.value)


def test_an_impossible_forced_formation_says_why(game_rules: GameRules) -> None:
    gameweeks = (2, 3)
    inputs = _inputs(game_rules, gameweeks=gameweeks)
    config = decision(gameweeks=2).model_copy(
        update={"forced_formation": {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}}
    )

    with pytest.raises(InfeasibleError) as caught:
        solve_horizon(inputs, ChipScenario(), config, OPTIMISER)
    assert "forced formation names 14 starters" in str(caught.value)


def test_a_spend_cap_below_the_cheapest_legal_squad_says_so(game_rules: GameRules) -> None:
    gameweeks = (2, 3)
    inputs = _inputs(game_rules, gameweeks=gameweeks)
    config = decision(gameweeks=2).model_copy(update={"maximum_spend": 20.0})

    with pytest.raises(InfeasibleError) as caught:
        solve_horizon(inputs, ChipScenario(), config, OPTIMISER)
    assert "spend cap" in str(caught.value)


def test_the_same_club_starting_cap_is_enforced_and_relaxable(game_rules: GameRules) -> None:
    """C16, and the override that lets a deliberate triple-up through (E4-S5)."""
    gameweeks = (2, 3)
    inputs = _inputs(game_rules, gameweeks=gameweeks, free_transfers=1)

    with pytest.raises(InfeasibleError):
        # Six clubs and a cap of one allows at most six starters, and eleven must start.
        solve_horizon(inputs, ChipScenario(), decision(gameweeks=2, club_cap=1), OPTIMISER)

    relaxed = decision(gameweeks=2, club_cap=1).model_copy(
        update={
            "risk": decision(gameweeks=2, club_cap=1).risk.model_copy(
                update={"relax_club_cap_team_ids": tuple(range(1, 7))}
            )
        }
    )
    plan = solve_horizon(inputs, ChipScenario(), relaxed, OPTIMISER)
    assert len(plan.weeks) == 2


# --------------------------------------------------------------------------- horizon window


def test_the_horizon_stops_at_the_end_of_the_season(game_rules: GameRules) -> None:
    players = pool()
    squad_state = state(game_rules, players, gameweek=36)
    weeks = plan_gameweeks(squad_state, decision(gameweeks=5), last=38)
    assert weeks == (36, 37, 38)


def test_a_chip_table_carries_its_own_expiry(game_rules: GameRules) -> None:
    """Read from the game, never written down here (Invariant 2)."""
    import json
    from pathlib import Path

    bootstrap = json.loads(
        (Path(__file__).parent / "fixtures" / "bootstrap_static.json").read_text(encoding="utf-8")
    )
    chips = chip_table(bootstrap)
    assert not chips.empty
    assert isinstance(chips, pd.DataFrame)
    assert set(chips.columns) >= {"name", "start_event", "stop_event"}
