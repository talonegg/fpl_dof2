"""E4 — candidate pruning, chips, the risk dial, the simulation re-rank and the explanation.

The tests here are chosen for what fails *quietly*. A plan that recommends a slightly worse chip
week is a bad week; a chip recommendation that has silently dropped its D-13 caveat, or an ownership
figure relabelled as something it is not, is a tool that has stopped being honest — and neither
shows up as a broken output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pandas as pd
import pytest

from decisions import (
    OPTIMISER,
    chip_table,
    decision,
    fixture_table,
    forecast,
    pool,
    state,
)
from fpl_dof.config.models import CandidateConfig, DecisionConfig, RiskConfig
from fpl_dof.optimise.candidates import (
    REASON_ENABLER,
    REASON_LOCKED,
    REASON_OWNED,
    prune_candidates,
    pruning_matches_full_pool,
)
from fpl_dof.optimise.chips import (
    ChipScenario,
    available_chips,
    build_calendar,
    chip_windows,
    enumerate_scenarios,
    gameweek_shapes,
)
from fpl_dof.optimise.explain import D13_CAVEAT, D21_CAVEAT, caveats_for
from fpl_dof.optimise.plan import DecisionPlan, as_dict, build_plan
from fpl_dof.optimise.risk import OWNERSHIP_LABEL, ownership_bet
from fpl_dof.publish.contract import Contract, find_contracts_root
from fpl_dof.rules.models import GameRules

GAMEWEEKS = (2, 3, 4)


@pytest.fixture(scope="module")
def bootstrap() -> dict[str, object]:
    path = Path(__file__).parent / "fixtures" / "bootstrap_static.json"
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _plan(
    game_rules: GameRules,
    bootstrap: dict[str, object],
    *,
    players: pd.DataFrame | None = None,
    config: DecisionConfig | None = None,
) -> DecisionPlan:
    squad = pool()
    return build_plan(
        players=players if players is not None else forecast(squad, GAMEWEEKS),
        state=state(game_rules, squad, gameweek=GAMEWEEKS[0]),
        rules=game_rules,
        decision=config if config is not None else decision(gameweeks=len(GAMEWEEKS)),
        optimiser=OPTIMISER,
        fixtures=fixture_table(squad, GAMEWEEKS),
        chips=chip_table(bootstrap),
    )


# --------------------------------------------------------------------------- E4-S1


def test_pruning_never_drops_the_squad_you_already_own(game_rules: GameRules) -> None:
    """Or the model cannot evaluate keeping it, which is the decision it is usually making."""
    players = forecast(pool(), GAMEWEEKS)
    owned = {1, 2, 20, 30}
    pruned, report = prune_candidates(
        players,
        CandidateConfig(top_n_per_position_by_points=1, top_n_per_position_by_value=1),
        owned=owned,
    )
    assert owned <= set(pruned["player_id"])
    assert report.counts_by_reason[REASON_OWNED] == len(owned)


def test_pruning_keeps_a_locked_player_even_when_he_is_also_banned(game_rules: GameRules) -> None:
    """A ban on a player you hold is an instruction to sell him, and the model must be able to see
    him in order to sell him."""
    players = forecast(pool(), GAMEWEEKS)
    pruned, report = prune_candidates(
        players,
        CandidateConfig(top_n_per_position_by_points=1, top_n_per_position_by_value=1),
        locked={5},
        banned={5},
    )
    assert 5 in set(pruned["player_id"])
    assert report.counts_by_reason[REASON_LOCKED] == 1


def test_pruning_keeps_cheap_enablers_a_points_ranking_would_drop(game_rules: GameRules) -> None:
    """The bias that matters. A pure expected-points ranking keeps the premiums and drops the
    players who *pay* for them, so the best squad becomes unaffordable and the solver silently
    returns the second-best one."""
    players = forecast(pool(), GAMEWEEKS)
    # A spread of prices, with expected points rising strictly with price — so on both a points
    # ranking and a points-per-pound ranking the cheap end is last, and only the enabler rule can
    # rescue it.
    players["price"] = 4.0 + players.groupby("position").cumcount() * 0.5
    players["xp_horizon"] = players["price"] * 2

    pruned, report = prune_candidates(
        players,
        CandidateConfig(
            top_n_per_position_by_points=2,
            top_n_per_position_by_value=1,
            cheap_enablers_per_position=3,
        ),
    )
    assert report.counts_by_reason.get(REASON_ENABLER, 0) > 0
    assert float(players["price"].min()) in set(pruned["price"])


def test_the_pruning_rule_is_itself_validated_against_the_full_pool(game_rules: GameRules) -> None:
    """Design 6.1's own check: re-solve on the unpruned set and confirm the answer did not move."""
    players = forecast(pool(), GAMEWEEKS)
    pruned, _ = prune_candidates(players, CandidateConfig())

    def solve(frame: pd.DataFrame) -> list[int]:
        best = frame.sort_values(["xp_horizon", "player_id"], ascending=[False, True])
        return [int(value) for value in best.head(5)["player_id"]]

    assert pruning_matches_full_pool(solve, pruned=pruned, full=players)


# --------------------------------------------------------------------------- E4-S3


def test_set_one_chips_are_gone_after_their_published_expiry(bootstrap: dict[str, object]) -> None:
    """Expiry is enforced, not advisory — and it is read from the game rather than written down
    here, because "set one expires at GW19" is exactly the sort of fact that quietly stops being
    true (Invariant 2)."""
    windows = chip_windows(chip_table(bootstrap))
    first_set = {window.name: window for window in windows if window.start_gameweek < 20}
    expiry = {window.stop_gameweek for window in first_set.values()}
    assert len(expiry) == 1, "the fixture's first chip set shares one expiry gameweek"
    stop = expiry.pop()

    before = available_chips(windows, chips_used=(), gameweek=stop)
    after = available_chips(windows, chips_used=(), gameweek=stop + 1)
    assert all(window.stop_gameweek == stop for window in before.values())
    assert all(window.stop_gameweek > stop for window in after.values())


def test_a_chip_already_played_is_not_enumerated_again(bootstrap: dict[str, object]) -> None:
    windows = chip_windows(chip_table(bootstrap))
    players = pool()
    shapes = gameweek_shapes(fixture_table(players, GAMEWEEKS), players["team_id"])
    scenarios = enumerate_scenarios(
        horizon=GAMEWEEKS,
        windows=windows,
        chips_used=("bboost",),
        shapes=shapes,
        squad_team_ids=sorted({int(t) for t in players["team_id"]}),
        config=decision().chips,
    )
    played = {chip for scenario in scenarios for chip in scenario.chips}
    assert "bboost" not in played
    assert ChipScenario() in scenarios, "playing nothing is always a candidate"


def test_a_forced_chip_removes_the_do_nothing_scenario(bootstrap: dict[str, object]) -> None:
    """E4-S5. Forcing a chip is an instruction, so "play no chip" must stop being an answer."""
    windows = chip_windows(chip_table(bootstrap))
    players = pool()
    shapes = gameweek_shapes(fixture_table(players, GAMEWEEKS), players["team_id"])
    config = decision(force_chip={"wildcard": 3}).chips
    scenarios = enumerate_scenarios(
        horizon=GAMEWEEKS,
        windows=windows,
        chips_used=(),
        shapes=shapes,
        squad_team_ids=sorted({int(t) for t in players["team_id"]}),
        config=config,
    )
    assert scenarios
    assert all(scenario.assignments == ((3, "wildcard"),) for scenario in scenarios)


def test_a_forbidden_gameweek_is_never_enumerated(bootstrap: dict[str, object]) -> None:
    windows = chip_windows(chip_table(bootstrap))
    players = pool()
    shapes = gameweek_shapes(fixture_table(players, GAMEWEEKS), players["team_id"])
    config = decision(forbid_chip={"wildcard": (2, 3, 4)}).chips
    scenarios = enumerate_scenarios(
        horizon=GAMEWEEKS,
        windows=windows,
        chips_used=(),
        shapes=shapes,
        squad_team_ids=sorted({int(t) for t in players["team_id"]}),
        config=config,
    )
    assert not any("wildcard" in scenario.chips for scenario in scenarios)


def test_the_calendar_finds_a_double_gameweek_and_carries_the_expiry(
    bootstrap: dict[str, object],
) -> None:
    players = pool()
    shapes = gameweek_shapes(fixture_table(players, GAMEWEEKS), players["team_id"])
    calendar = build_calendar(
        from_gameweek=2,
        windows=chip_windows(chip_table(bootstrap)),
        chips_used=(),
        shapes=shapes,
        config=decision().chips,
    )
    doubles = [entry for entry in calendar.entries if entry.is_double]
    assert doubles, "a gameweek where two clubs play twice must appear as a window"
    assert all(entry.expires_gameweek > 0 for entry in calendar.entries)
    assert calendar.expiring, "unused chips must carry the gameweek they expire at"


# --------------------------------------------------------------------------- E4-S4


def test_every_ownership_figure_is_labelled_selected_by_and_never_effective_ownership() -> None:
    """DL-24. The label is the whole of the honesty: captaincy share is published by no endpoint,
    so a figure presented as effective ownership would be claiming to know something it does not."""
    bet = ownership_bet(
        squad=[1, 2],
        starting=[1],
        ownership={1: 40.0, 2: 5.0, 9: 62.5},
        names={1: "A", 2: "B", 9: "C"},
        config=RiskConfig(),
    )
    assert bet.ownership_label == OWNERSHIP_LABEL == "selected by"
    assert "selected_by_percent" in bet.source_statement
    assert "effective ownership" not in " ".join(bet.statements)
    assert any("underweight on C" in line for line in bet.statements)


def test_the_most_captained_callout_says_so_when_it_is_not_available() -> None:
    """An absent callout reads as "nobody stands out", which is a different and wrong claim."""
    bet = ownership_bet(
        squad=[1],
        starting=[1],
        ownership={1: 40.0},
        names={1: "A"},
        config=RiskConfig(),
        most_captained_id=None,
    )
    assert bet.most_captained is not None
    assert bet.most_captained.player_id is None
    assert "not available" in bet.most_captained.statement


def test_the_most_captained_player_is_a_separate_plain_callout() -> None:
    bet = ownership_bet(
        squad=[1],
        starting=[1],
        ownership={1: 40.0, 9: 62.5},
        names={1: "A", 9: "Haaland"},
        config=RiskConfig(),
        most_captained_id=9,
    )
    assert bet.most_captained is not None
    assert bet.most_captained.player_id == 9
    assert "most-captained" in bet.most_captained.statement
    assert "selected by Haaland" in bet.most_captained.statement


def test_the_dial_defaults_to_balanced() -> None:
    """OD-05, resolved at DL-25: Balanced by default, in the absence of a stated target rank."""
    assert RiskConfig().dial == "balanced"
    assert RiskConfig().ownership_weight["balanced"] < RiskConfig().ownership_weight["safe"]
    assert RiskConfig().ownership_weight["aggressive"] < 0


def test_the_same_club_starting_cap_defaults_to_two() -> None:
    """C16. Q-12 asks whether 2 or 3 is better; 2 is the documented default."""
    assert RiskConfig().same_club_starting_limit == 2


# --------------------------------------------------------------------------- E4-S4a


def test_the_simulation_re_rank_changes_a_chip_recommendation(
    game_rules: GameRules, bootstrap: dict[str, object]
) -> None:
    """E4-S4a's acceptance criterion, and the direction of the change is explicable.

    Every player is worth the same in every gameweek and the discount is switched off, so the three
    Bench Boost timings are **exactly tied** on expected points — an expectation-maximiser cannot
    tell them apart and picks the first. Gameweek 4 is the volatile one. The aggressive dial, which
    ranks on the upside percentile, therefore moves the chip to gameweek 4; the safe dial, which
    ranks on a downside percentile, moves it away from gameweek 4. That is the whole argument for
    the re-rank: Bench Boost and Triple Captain are variance plays, and the mean cannot see them.
    """
    players = pool()
    steady = {int(pid): 0.5 for pid in players["player_id"]}
    volatile = {int(pid): 7.0 for pid in players["player_id"]}
    frame = forecast(
        players,
        GAMEWEEKS,
        mean=3.0,
        sd=steady,
        sd_by_gameweek={2: steady, 3: steady, 4: volatile},
    )

    def run(dial: Literal["safe", "balanced", "aggressive"], simulate: bool) -> str:
        config = decision(
            gameweeks=len(GAMEWEEKS),
            dial=dial,
            simulate=simulate,
            draws=4000,
            max_scenarios=30,
            discount=1.0,
        )
        return str(_plan(game_rules, bootstrap, players=frame, config=config).recommended.label)

    without = run("balanced", False)
    aggressive = run("aggressive", True)
    safe = run("safe", True)

    assert "Bench Boost" in without
    assert aggressive != without, "the re-rank must be able to change a chip recommendation"
    assert "GW4" in aggressive, "the aggressive dial should take the volatile gameweek"
    assert "GW4" not in safe, "the safe dial should avoid it — the direction has to be explicable"


def test_the_simulation_is_reproducible_across_runs(
    game_rules: GameRules, bootstrap: dict[str, object]
) -> None:
    """R-16. A recommendation that changes on refresh for no stated reason is not one."""
    first = _plan(game_rules, bootstrap)
    second = _plan(game_rules, bootstrap)
    assert first.recommended.key == second.recommended.key
    assert first.recommended.plan.first.squad == second.recommended.plan.first.squad
    assert first.recommended.plan.first.starting == second.recommended.plan.first.starting
    assert first.rationale == second.rationale


def test_a_tied_alternative_does_not_beat_the_incumbent_squad(
    game_rules: GameRules, bootstrap: dict[str, object]
) -> None:
    """The margin, not the objective. Every player is worth the same, so no transfer can gain
    anything — and the plan must therefore be to roll, with the reason stated."""
    players = pool()
    frame = forecast(players, GAMEWEEKS, mean=2.0)
    config = decision(gameweeks=len(GAMEWEEKS), simulate=False, max_scenarios=1)
    plan = _plan(game_rules, bootstrap, players=frame, config=config)

    assert plan.is_hold
    assert "margin" in plan.rationale
    assert plan.recommended.plan.first.transfers_in == ()


# --------------------------------------------------------------------------- E4-S6


def test_the_d13_caveat_is_attached_to_any_hit_chip_or_wildcard() -> None:
    """E4 §0. The caveat is a field on the recommendation, not a footnote, so that the explanation
    layer and the UI cannot render the advice without it."""
    assert caveats_for(takes_hit=True) == (D13_CAVEAT,)
    assert caveats_for(takes_hit=False, chips_played=("wildcard",)) == (D13_CAVEAT, D21_CAVEAT)
    assert caveats_for(takes_hit=False, chips_played=()) == ()
    assert set(D13_CAVEAT.applies_to) == {"hit", "chip", "wildcard"}
    assert "top-20 precision" in D13_CAVEAT.detail
    assert D21_CAVEAT.applies_to == ("chip",)
    assert "eight real historical deadlines" in D21_CAVEAT.detail


def test_a_chip_recommendation_carries_the_caveat_through_to_the_payload(
    game_rules: GameRules, bootstrap: dict[str, object]
) -> None:
    players = pool()
    frame = forecast(players, GAMEWEEKS, mean=3.0)
    plan = _plan(game_rules, bootstrap, players=frame)
    payload = as_dict(plan)
    explanation = payload["explanation"]
    assert isinstance(explanation, dict)

    if plan.chips_recommended or plan.recommended.plan.total_hit_points < 0:
        codes = {caveat["code"] for caveat in explanation["caveats"]}
        assert "D-13" in codes
    else:  # pragma: no cover - the fixture pool normally recommends a chip
        assert explanation["caveats"] == []


def test_rolling_everything_is_always_a_ranked_runner_up(
    game_rules: GameRules, bootstrap: dict[str, object]
) -> None:
    """FR-24. A recommendation to hold is a decision, not the absence of one."""
    players = pool()
    frame = forecast(players, GAMEWEEKS, mean={pid: 1.0 + (pid % 6) for pid in range(1, 40)})
    plan = _plan(game_rules, bootstrap, players=frame)
    labels = {item.label for item in plan.explanation.runners_up}
    assert any("roll everything" in label for label in labels)


def test_the_explanation_carries_decomposition_marginal_gain_and_assumptions(
    game_rules: GameRules, bootstrap: dict[str, object]
) -> None:
    plan = _plan(game_rules, bootstrap)
    explanation = plan.explanation
    assert explanation.decomposition, "where the points came from"
    assert any(item.label.startswith("GW") for item in explanation.decomposition)
    assert explanation.price_exposure is not None
    assert explanation.assumptions
    assert any("discounted" in line for line in explanation.assumptions)
    assert isinstance(explanation.marginal_gain_over_doing_nothing, float)


# --------------------------------------------------------------------------- the contract


def test_the_published_plan_matches_its_schema(
    game_rules: GameRules, bootstrap: dict[str, object]
) -> None:
    """Validated on the way out, because publishing a shape the app cannot read breaks it in a
    browser, which is the slowest possible place to find out."""
    plan = _plan(game_rules, bootstrap)
    payload: dict[str, object] = {
        "contract_version": 1,
        "run_id": "test-run",
        "skipped": False,
        "deadline": {
            "gameweek": 2,
            "name": "Gameweek 2",
            "deadline_utc": "2026-08-28T17:30:00Z",
            "decide_by_utc": "2026-08-28T05:30:00Z",
            "local_zone": "Australia/Sydney",
            "uk_zone": "Europe/London",
        },
        **as_dict(plan),
    }
    contract = Contract(root=find_contracts_root(Path(__file__).resolve()))
    contract.validate("plan", payload)
