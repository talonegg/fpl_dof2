"""The squad optimiser.

The property test is the acceptance criterion that matters: for arbitrary randomised inputs, the
returned squad never violates any FPL rule. The optimiser is checked against the E0-S4 validator
rather than assumed correct by construction, because a mis-stated constraint produces a squad that
looks entirely reasonable and is illegal (DP-13).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fpl_dof.config.models import OptimiserConfig
from fpl_dof.optimise.squad import (
    InfeasibleError,
    SolveStatus,
    optimise_squad,
)
from fpl_dof.rules.legality import validate_squad
from fpl_dof.rules.models import GameRules, Position

TEAM_COUNT = 20


def make_pool(
    *,
    seed: int = 0,
    per_position: int = 30,
    price_low: float = 4.0,
    price_high: float = 13.0,
) -> pd.DataFrame:
    """A player pool wide enough that a legal squad certainly exists."""
    rng = np.random.default_rng(seed)
    rows = []
    player_id = 0
    for position in Position:
        for index in range(per_position):
            player_id += 1
            price = round(float(rng.uniform(price_low, price_high)), 1)
            rows.append(
                {
                    "player_id": player_id,
                    "web_name": f"{position.value}{index}",
                    "position": position.value,
                    "team_id": 1 + (player_id % TEAM_COUNT),
                    "price": price,
                    "xp_next": float(rng.uniform(0.5, 6.0)),
                    "xp_horizon": float(rng.uniform(3.0, 30.0)),
                    "start_probability": float(rng.uniform(0.2, 1.0)),
                }
            )
    return pd.DataFrame(rows)


def config(**overrides: object) -> OptimiserConfig:
    return OptimiserConfig(**overrides)


def test_the_squad_is_legal_and_optimal(game_rules: GameRules) -> None:
    squad, report = optimise_squad(make_pool(), game_rules, config())
    assert report.status is SolveStatus.OPTIMAL
    assert validate_squad(squad, game_rules) == [], "the validator, not inspection, is the check"
    assert len(squad.players) == game_rules.squad.size
    assert len(squad.starting) == game_rules.squad.starting_size


def test_it_solves_well_inside_the_time_limit(game_rules: GameRules) -> None:
    _, report = optimise_squad(make_pool(per_position=150), game_rules, config())
    assert report.solve_seconds < 60


def test_the_budget_is_respected_and_largely_used(game_rules: GameRules) -> None:
    _, report = optimise_squad(make_pool(), game_rules, config())
    assert report.total_price <= game_rules.squad.budget
    assert report.total_price > game_rules.squad.budget * 0.9, "a big underspend is a wasted squad"


def test_the_formation_is_legal(game_rules: GameRules) -> None:
    _, report = optimise_squad(make_pool(), game_rules, config())
    legal = {
        (f[Position.DEF], f[Position.MID], f[Position.FWD])
        for f in game_rules.squad.legal_formations()
    }
    shape = (report.formation["DEF"], report.formation["MID"], report.formation["FWD"])
    assert shape in legal


def test_exactly_one_captain_and_a_different_vice(game_rules: GameRules) -> None:
    squad, report = optimise_squad(make_pool(), game_rules, config())
    assert report.captain_id in squad.starting
    assert report.vice_captain_id in squad.starting
    assert report.captain_id != report.vice_captain_id


def test_the_captain_is_a_high_scorer(game_rules: GameRules) -> None:
    """Captaincy doubles a single gameweek, so it should land on the best xp_next in the XI."""
    pool = make_pool()
    squad, report = optimise_squad(pool, game_rules, config())
    starting = pool[pool["player_id"].isin(squad.starting)]
    best = float(starting["xp_next"].max())
    captain = float(starting[starting["player_id"] == report.captain_id]["xp_next"].iloc[0])
    assert captain == pytest.approx(best)


# --- overrides ------------------------------------------------------------------------------


def test_a_locked_player_is_always_selected(game_rules: GameRules) -> None:
    pool = make_pool()
    worst = int(pool.nsmallest(1, "xp_horizon")["player_id"].iloc[0])
    squad, _ = optimise_squad(pool, game_rules, config(locked_player_ids=(worst,)))
    assert worst in {player.player_id for player in squad.players}


def test_a_banned_player_is_never_selected(game_rules: GameRules) -> None:
    pool = make_pool()
    unbanned, _ = optimise_squad(pool, game_rules, config())
    best = max(unbanned.players, key=lambda p: p.player_id)
    banned_ids = tuple(p.player_id for p in unbanned.players)
    squad, _ = optimise_squad(pool, game_rules, config(banned_player_ids=banned_ids))
    assert not set(banned_ids) & {p.player_id for p in squad.players}
    assert best.player_id not in {p.player_id for p in squad.players}


def test_an_excluded_club_contributes_nobody(game_rules: GameRules) -> None:
    squad, _ = optimise_squad(make_pool(), game_rules, config(excluded_team_ids=(1, 2, 3)))
    assert not {p.team_id for p in squad.players} & {1, 2, 3}


def test_locks_and_bans_can_be_combined(game_rules: GameRules) -> None:
    pool = make_pool()
    lock = int(pool[pool["position"] == "FWD"]["player_id"].iloc[0])
    ban = int(pool[pool["position"] == "FWD"]["player_id"].iloc[1])
    squad, _ = optimise_squad(
        pool, game_rules, config(locked_player_ids=(lock,), banned_player_ids=(ban,))
    )
    ids = {p.player_id for p in squad.players}
    assert lock in ids
    assert ban not in ids


def test_players_below_the_start_floor_do_not_start(game_rules: GameRules) -> None:
    """E0-S5's floor is enforced here: cheap enablers may be owned, never fielded."""
    pool = make_pool()
    pool["start_floor"] = 0.6
    squad, _ = optimise_squad(pool, game_rules, config())
    probabilities = pool.set_index("player_id")["start_probability"]
    assert all(float(probabilities[player_id]) >= 0.6 for player_id in squad.starting)


def test_a_lock_overrides_the_start_floor(game_rules: GameRules) -> None:
    """An explicit human override outranks the heuristic — that is what the review gate is for."""
    pool = make_pool()
    pool["start_floor"] = 0.6
    doubtful = pool[pool["start_probability"] < 0.3].sort_values("xp_horizon", ascending=False)
    assert not doubtful.empty
    target = int(doubtful["player_id"].iloc[0])
    squad, _ = optimise_squad(pool, game_rules, config(locked_player_ids=(target,)))
    assert target in {p.player_id for p in squad.players}


def test_the_floor_can_be_switched_off(game_rules: GameRules) -> None:
    pool = make_pool()
    pool["start_floor"] = 0.95
    squad, _ = optimise_squad(pool, game_rules, config(enforce_start_probability_floor=False))
    probabilities = pool.set_index("player_id")["start_probability"]
    assert any(float(probabilities[player_id]) < 0.95 for player_id in squad.starting)


# --- infeasibility, explained ----------------------------------------------------------------


def test_locking_too_many_of_one_position_says_so(game_rules: GameRules) -> None:
    pool = make_pool()
    keepers = tuple(int(i) for i in pool[pool["position"] == "GKP"]["player_id"].head(4))
    with pytest.raises(InfeasibleError, match="fit in the squad"):
        optimise_squad(pool, game_rules, config(locked_player_ids=keepers))


def test_locking_an_unaffordable_set_says_so(game_rules: GameRules) -> None:
    pool = make_pool(price_low=13.0, price_high=15.0)
    expensive = tuple(int(i) for i in pool.nlargest(12, "price")["player_id"])
    with pytest.raises(InfeasibleError, match=r"budget|limit|fit in the squad"):
        optimise_squad(pool, game_rules, config(locked_player_ids=expensive))


def test_excluding_almost_every_club_says_so(game_rules: GameRules) -> None:
    with pytest.raises(InfeasibleError, match="available after bans"):
        optimise_squad(
            make_pool(per_position=5),
            game_rules,
            config(excluded_team_ids=tuple(range(1, TEAM_COUNT + 1))),
        )


def test_an_unaffordable_pool_says_so(game_rules: GameRules) -> None:
    with pytest.raises(InfeasibleError, match="cheapest legal squad"):
        optimise_squad(make_pool(price_low=20.0, price_high=24.0), game_rules, config())


def test_a_missing_column_is_rejected_early(game_rules: GameRules) -> None:
    pool = make_pool().drop(columns=["xp_horizon"])
    with pytest.raises(ValueError, match="missing columns"):
        optimise_squad(pool, game_rules, config())


# --- the property test -----------------------------------------------------------------------


@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    seed=st.integers(min_value=0, max_value=10_000),
    per_position=st.integers(min_value=8, max_value=40),
    price_low=st.floats(min_value=3.8, max_value=5.0),
    price_spread=st.floats(min_value=1.0, max_value=9.0),
    bench_weight=st.floats(min_value=0.0, max_value=1.0),
)
def test_the_returned_squad_never_violates_any_rule(
    game_rules: GameRules,
    seed: int,
    per_position: int,
    price_low: float,
    price_spread: float,
    bench_weight: float,
) -> None:
    pool = make_pool(
        seed=seed,
        per_position=per_position,
        price_low=price_low,
        price_high=price_low + price_spread,
    )
    try:
        squad, report = optimise_squad(pool, game_rules, config(bench_weight=bench_weight))
    except InfeasibleError as exc:
        # Refusing with a reason is a correct outcome, and a randomly generated pool can genuinely
        # have too few players above the start-probability floor to field a legal XI. What must
        # never happen is returning an illegal squad.
        assert "unsatisfiable" not in str(exc), f"infeasible without an explanation: {exc}"
        return

    violations = validate_squad(squad, game_rules)
    assert violations == [], [v.message for v in violations]
    assert report.total_price <= game_rules.squad.budget
    assert len({p.player_id for p in squad.players}) == game_rules.squad.size
