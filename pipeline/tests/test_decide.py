"""MOD-04 — one decision path for every strategy.

``decide(frame, squad_state, rules, policy)`` is the only way a forecast becomes advice: transfers
and hits, XI and bench, captain and vice, and — unless the policy says ``plan: false`` — the
multi-gameweek plan with its chips. Pinned here at that seam: the champion's week is what the
pre-MOD-04 week stage chose on the same fixture, champion and C1 differ only through their registry
entries, and a failing challenger costs its own advice and nothing else (NFR-15). The champion's
week and its ledger entry are on disk before its plan or any challenger runs: neither can cost it.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, get_args

import pandas as pd
import pytest

from decisions import OPTIMISER, decision, fixture_table, forecast, pool, state
from fpl_dof.config.loader import load_config
from fpl_dof.config.models import Config, ForecastConfig
from fpl_dof.decision import Decision, decide, engine
from fpl_dof.factory.registry import (
    Forecast,
    ForecastInputs,
    Role,
    Strategy,
    champion,
    load_strategy,
    published_strategies,
)
from fpl_dof.frames import as_float, as_int
from fpl_dof.optimise.captain import PricePositionLine
from fpl_dof.optimise.frame import ForecastFrameError
from fpl_dof.paths import DataLayout
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.strategies import artefact_paths
from fpl_dof.rules.models import GameRules
from fpl_dof.stages import week
from fpl_dof.week.deadline import DeadlineView, next_deadline
from fpl_dof.week.ledger import advice_path, read_advice

LINE = PricePositionLine(
    intercept_by_position={"GKP": 1.0, "DEF": 1.5, "MID": 2.0, "FWD": 2.5},
    slope_by_position={"GKP": 0.1, "DEF": 0.2, "MID": 0.4, "FWD": 0.3},
    fallback=2.0,
)
HORIZON = (5, 6, 7)
PLAYED = (1, 2, 3, 4)


def _config() -> Config:
    """The shipped config with a small, fast plan: three gameweeks and no simulation."""
    cfg, _ = load_config(environ={})
    return cfg.model_copy(
        update={
            "decision": decision(gameweeks=len(HORIZON), simulate=False),
            "optimiser": OPTIMISER,
        }
    )


def _deadline() -> DeadlineView:
    gameweek = pd.DataFrame(
        [
            {
                "gameweek": HORIZON[0],
                "name": f"Gameweek {HORIZON[0]}",
                "deadline_time": pd.Timestamp("2026-09-11T17:30:00Z"),
                "finished": False,
            }
        ]
    )
    return next_deadline(
        gameweek,
        now=pd.Timestamp("2026-09-10T12:00:00Z").to_pydatetime(),
        local_zone="Australia/Sydney",
        decide_by_hours=12,
    )


def _mean(players: pd.DataFrame) -> dict[int, float]:
    return {int(p): 1.0 + (int(p) * 7 % 11) / 2 for p in players["player_id"]}


# --- the seam ------------------------------------------------------------------------------------


def test_the_champions_week_is_unchanged_from_the_pre_change_path(game_rules: GameRules) -> None:
    """Pinned from the week stage before MOD-04 (recommend, relabel, select with the floor, relabel)
    on this fixture: shipped config, the floor on, and the reserve keeper below it."""
    players = pool()
    frame = forecast(players, (2, 3, 4), mean=_mean(players))
    frame.loc[frame["player_id"] == 1, "start_probability"] = 0.3
    cfg, _ = load_config(environ={})
    policy = dataclasses.replace(champion().decision_policy(cfg, LINE), plan=False)

    got = decide(frame, state(game_rules, players, gameweek=2), game_rules, policy)

    chosen = got.recommendation.recommended
    assert [(m.player_out_id, m.player_in_id) for m in chosen.moves] == [(8, 14), (33, 36)]
    assert (chosen.transfers, chosen.hit_points, chosen.net_expected_points) == (2, -4, 46.0)
    assert got.selection.starting == (14, 36, 9, 20, 23, 34, 7, 10, 21, 2, 35)
    assert got.selection.bench_order == (19, 11, 22)
    assert got.selection.reserve_goalkeeper == 1
    assert (got.selection.captain, got.selection.vice_captain) == (34, 35)
    assert got.selection.expected_points == 50.0
    assert got.warnings == ()
    assert got.plan is None and got.plan_skipped_reason is None  # plan: false skips the solve


def test_a_policy_with_a_plan_gets_the_plan_and_its_chips(game_rules: GameRules) -> None:
    players = pool()
    frame = forecast(players, HORIZON, mean=_mean(players))
    got = decide(
        frame,
        state(game_rules, players, gameweek=HORIZON[0]),
        game_rules,
        champion().decision_policy(_config(), LINE),
        fixtures=fixture_table(players, HORIZON),
        last_gameweek=HORIZON[-1],
    )
    assert got.plan is not None and got.plan_skipped_reason is None
    assert tuple(got.plan.gameweeks) == HORIZON


def test_an_infeasible_plan_is_a_stated_reason_and_the_week_still_stands(
    game_rules: GameRules,
) -> None:
    players = pool()
    got = decide(
        forecast(players, HORIZON, mean=_mean(players)),
        state(game_rules, players, gameweek=HORIZON[0]),
        game_rules,
        champion().decision_policy(_config(), LINE),
        last_gameweek=HORIZON[0] - 1,  # the season is over: nothing left to plan
    )
    assert got.plan is None
    assert got.plan_skipped_reason is not None and "horizon is empty" in got.plan_skipped_reason
    assert len(got.selection.starting) == 11


def test_an_xi_below_the_floor_is_fielded_with_the_floor_relaxed_and_said(
    game_rules: GameRules,
) -> None:
    players = pool()
    frame = forecast(players, (2, 3, 4), mean=_mean(players))
    frame.loc[frame["position"] == "GKP", "start_probability"] = 0.3  # no keeper clears it
    cfg, _ = load_config(environ={})
    policy = dataclasses.replace(champion().decision_policy(cfg, None), plan=False)
    got = decide(frame, state(game_rules, players, gameweek=2), game_rules, policy)
    assert len(got.selection.starting) == 11
    assert any("floor relaxed" in w for w in got.warnings)


def test_the_captain_rule_is_read_from_each_strategys_policy() -> None:
    cfg = _config()
    assert champion().decision_policy(cfg, LINE).captain_line == LINE
    assert champion().decision_policy(cfg, None).captain_line is None  # nothing to fit: solver's
    assert load_strategy("engine").decision_policy(cfg, LINE).captain_line is None  # rule: model
    assert champion().decision_policy(cfg, LINE).plan is champion().policy.plan


# --- C1 behind the registry ----------------------------------------------------------------------


def _history(players: pd.DataFrame, fixtures: pd.DataFrame, season: str) -> pd.DataFrame:
    """Per-gameweek rows for the played weeks, in the columns C1 learns from."""
    rows = []
    for fx in fixtures[fixtures["gameweek"].isin(PLAYED)].itertuples():
        for team, opponent, home in (
            (fx.home_team_id, fx.away_team_id, True),
            (fx.away_team_id, fx.home_team_id, False),
        ):
            for p in players[players["team_id"] == team].itertuples():
                minutes = (as_int(p.player_id) * as_int(fx.gameweek) * 13) % 91
                rows.append(
                    {
                        "season": season,
                        "gameweek": as_int(fx.gameweek),
                        "player_id": as_int(p.player_id),
                        "player_code": as_int(p.code),
                        "position": p.position,
                        "team_id": as_int(team),
                        "opponent_team_id": as_int(opponent),
                        "fixture_id": as_int(fx.fixture_id),
                        "was_home": home,
                        "price": as_float(p.price),
                        "minutes": minutes,
                        "starts": int(minutes >= 60),
                        "total_points": float((as_int(p.player_id) + as_int(fx.gameweek)) % 7),
                        "expected_goals": 0.1 * (as_int(p.player_id) % 3),
                        "expected_assists": 0.05,
                        "expected_goals_conceded": 1.0,
                        "bonus": 0,
                        "bps": 10,
                    }
                )
    return pd.DataFrame(rows)


def _snapshot(rules: GameRules) -> tuple[ForecastInputs, Forecast]:
    """One input snapshot, and the champion's forecast of it as the forecast stage wrote it."""
    players = pool().assign(code=lambda f: 1000 + f["player_id"])
    fixtures = fixture_table(players, (*PLAYED, *HORIZON))
    deadlines = pd.Timestamp("2026-08-14T17:30:00Z")
    gameweeks = pd.DataFrame(
        {
            "gameweek": list(PLAYED + HORIZON),
            "name": [f"Gameweek {g}" for g in PLAYED + HORIZON],
            "deadline_time": [deadlines + pd.Timedelta(weeks=g - 1) for g in PLAYED + HORIZON],
            "finished": [g in PLAYED for g in PLAYED + HORIZON],
        }
    )
    inputs = ForecastInputs(
        players=players,
        teams=pd.DataFrame({"team_id": sorted(set(players["team_id"]))}),
        fixtures=fixtures,
        gameweeks=gameweeks,
        history=pd.DataFrame(),
        as_of=(deadlines + pd.Timedelta(weeks=HORIZON[0] - 1, hours=-1)).to_pydatetime(),
        player_gameweek=_history(players, fixtures, rules.season),
    )
    frame = forecast(players, HORIZON, mean=_mean(players))
    return inputs, Forecast(frame=frame, model="xp_v1", fallback_reason=None, captain_line=LINE)


def _forecast_config() -> Config:
    return _config().model_copy(update={"forecast": ForecastConfig()})


def _c1(rules: GameRules) -> tuple[ForecastInputs, Forecast, Forecast]:
    inputs, champ = _snapshot(rules)
    c1 = load_strategy("c1").forecast(inputs, rules, _forecast_config(), variance_from=champ)
    return inputs, champ, c1


def test_c1_forecasts_through_the_registry_and_borrows_only_what_it_declares(
    game_rules: GameRules,
) -> None:
    _, champ, c1 = _c1(game_rules)
    assert set(c1.frame["strategy"]) == {"c1"}
    assert not c1.frame["xp_next"].equals(champ.frame["xp_next"])  # its own next-gameweek mean
    assert c1.frame["xp_gw_5"].equals(c1.frame["xp_next"])
    for borrowed in ("xp_next_sd", "xp_horizon_sd", "xp_gw_5_sd", "xp_gw_6", "xp_gw_6_sd"):
        assert c1.frame[borrowed].equals(champ.frame[borrowed]), borrowed  # MOD-05 removes these
    assert c1.captain_line == champ.captain_line


def test_c1_without_the_champions_forecast_to_borrow_from_is_refused(
    game_rules: GameRules,
) -> None:
    inputs, _ = _snapshot(game_rules)
    with pytest.raises(ValueError, match="variance"):
        load_strategy("c1").forecast(inputs, game_rules, _forecast_config())


def test_champion_and_c1_produce_full_weeks_and_plans_through_one_function(
    game_rules: GameRules,
) -> None:
    _, champ, c1 = _c1(game_rules)
    held = state(game_rules, pool(), gameweek=HORIZON[0])
    cfg = _config()
    calendar: dict[str, Any] = {
        "fixtures": fixture_table(pool(), HORIZON),
        "last_gameweek": HORIZON[-1],
    }
    got: dict[str, Decision] = {}
    for s, fc in ((champion(), champ), (load_strategy("c1"), c1)):
        # Plan on for both at the policy level: production C1 runs `plan: false` until MOD-05 gives
        # it means of its own beyond the next gameweek, but the one function plans for either.
        policy = dataclasses.replace(s.decision_policy(cfg, fc.captain_line), plan=True)
        got[s.id] = decide(fc.frame, held, game_rules, policy, **calendar)
        assert len(got[s.id].selection.starting) == 11
        assert got[s.id].selection.captain in got[s.id].selection.starting
        assert got[s.id].plan is not None, s.id

    # The same frame through either strategy's policy is the same advice: what separates them is
    # the forecaster their registry entries name, and nothing in the decision path.
    same = decide(
        champ.frame, held, game_rules, load_strategy("c1").decision_policy(cfg, LINE), **calendar
    )
    assert dataclasses.replace(same.recommendation, solve_seconds=0.0) == dataclasses.replace(
        got["c3"].recommendation, solve_seconds=0.0
    )
    assert same.selection == got["c3"].selection


# --- the orchestrator: every published strategy, isolated ----------------------------------------


def _orchestration(rules: GameRules) -> week.Snapshot:
    inputs, champ = _snapshot(rules)
    return week.Snapshot(
        config=_config(),
        run_id="run-mod04",
        rules=rules,
        state=state(rules, pool(), gameweek=HORIZON[0]),
        inputs=inputs,
        champion=champ,
        fixtures=fixture_table(pool(), HORIZON),
        chips=None,
        last_gameweek=HORIZON[-1],
        deadline=_deadline(),
        alerts=[],
        reconciliation=None,
        form=None,
    )


def _advise_all(
    rules: GameRules, tmp_path: Path, strategies: tuple[Strategy, ...] | None = None
) -> dict[str, week.Advice]:
    advice, _ = week.advise_all(
        _orchestration(rules),
        published_strategies() if strategies is None else strategies,
        gold=tmp_path / "gold",
        layout=DataLayout(root=tmp_path),
    )
    return advice


def test_every_published_strategy_gets_a_valid_week_and_plan(
    game_rules: GameRules, tmp_path: Path
) -> None:
    advice = _advise_all(game_rules, tmp_path)
    contract = Contract(root=find_contracts_root())
    assert set(advice) == {s.id for s in published_strategies()}
    for s in published_strategies():
        week_payload, plan_payload = advice[s.id]
        assert week_payload["strategy"]["id"] == s.id and not week_payload["skipped"]
        contract.validate("week", week_payload | {"contract_version": CONTRACT_VERSION})
        assert (plan_payload is not None) is s.policy.plan
        assert (artefact_paths(s)["plan"] is not None) is s.policy.plan
        if plan_payload is not None:
            assert plan_payload["strategy"]["id"] == s.id and not plan_payload["skipped"]
            contract.validate("plan", plan_payload | {"contract_version": CONTRACT_VERSION})


def _fail_c1(monkeypatch: pytest.MonkeyPatch) -> None:
    real = Strategy.forecast

    def failing(self: Strategy, *args: Any, **kwargs: Any) -> Forecast:
        if self.id == "c1":
            raise RuntimeError("c1 fit exploded")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Strategy, "forecast", failing)


def test_a_failing_challenger_records_no_advice_and_stops_nothing_else(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fail_c1(monkeypatch)
    advice = _advise_all(game_rules, tmp_path)

    c1_week, c1_plan = advice["c1"]
    assert c1_week["skipped"] and "c1 fit exploded" in c1_week["skipped_reason"]
    assert c1_week["strategy"]["id"] == "c1"
    assert (c1_plan is not None) is load_strategy("c1").policy.plan
    Contract(root=find_contracts_root()).validate(
        "week", c1_week | {"contract_version": CONTRACT_VERSION}
    )
    assert not advice["c3"][0]["skipped"]  # the champion published regardless

    models = week.ledger_models(advice, published_strategies())
    assert models["c1"]["no_advice"] == c1_week["skipped_reason"]
    assert models["c3"]["advised"] == advice["c3"][0]["advised"]
    assert models["c3"]["role"] == "champion"


def test_a_failing_champion_fails_the_run(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(*_: Any, **__: Any) -> Decision:
        raise RuntimeError("the engine fell over")

    monkeypatch.setattr(week, "decide", broken)
    with pytest.raises(RuntimeError, match="engine fell over"):
        _advise_all(game_rules, tmp_path)


def test_a_champion_plan_that_raises_leaves_this_weeks_advice_written(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Before MOD-04 the week was on disk before the decision stage planned; so it is again. A plan
    # failure of any kind, not only an infeasible horizon, costs the plan and nothing else (NFR-15).
    gold, layout = tmp_path / "gold", DataLayout(root=tmp_path)
    on_disk: list[tuple[bool, bool]] = []

    def failing(**_: Any) -> Any:
        on_disk.append(((gold / "week.json").exists(), advice_path(layout, HORIZON[0]).exists()))
        raise ForecastFrameError("the plan's frame is short a column")

    monkeypatch.setattr(engine, "build_plan", failing)
    advice, _ = week.advise_all(
        _orchestration(game_rules), published_strategies(), gold=gold, layout=layout
    )

    assert on_disk and on_disk[0] == (True, True)  # written before the plan was attempted
    written = json.loads((gold / "week.json").read_text(encoding="utf-8"))
    assert not written["skipped"] and written["strategy"]["id"] == champion().id
    plan = json.loads((gold / "plan.json").read_text(encoding="utf-8"))
    assert plan["skipped"] and plan["skipped_reason"].startswith("no plan: ForecastFrameError")
    recorded = read_advice(layout, HORIZON[0])
    assert recorded is not None and recorded["advised"] == written["advised"]
    assert recorded["models"][champion().id]["advised"] == written["advised"]
    assert set(recorded["models"]) == {s.id for s in published_strategies()}
    assert advice[champion().id][0] == written


def test_the_champion_is_the_registrys_whatever_order_the_strategies_arrive_in(
    game_rules: GameRules, tmp_path: Path
) -> None:
    advice = _advise_all(game_rules, tmp_path, tuple(reversed(published_strategies())))
    recorded = read_advice(DataLayout(root=tmp_path), HORIZON[0])
    assert recorded is not None
    assert recorded["advised"] == advice[champion().id][0]["advised"]
    written = json.loads((tmp_path / "gold" / "week.json").read_text(encoding="utf-8"))
    assert written["strategy"]["id"] == champion().id


def test_the_ledger_carries_every_published_strategy(game_rules: GameRules, tmp_path: Path) -> None:
    advice = _advise_all(game_rules, tmp_path)
    recorded = read_advice(DataLayout(root=tmp_path), HORIZON[0])
    assert recorded is not None
    models = recorded["models"]
    assert models == week.ledger_models(advice, published_strategies())
    assert set(models) == {s.id for s in published_strategies()}
    for s in published_strategies():
        entry = models[s.id]
        assert entry["strategy"]["id"] == s.id
        assert entry["advised"]["starting"] == advice[s.id][0]["advised"]["starting"]
        assert entry["transfers"] == advice[s.id][0]["recommendation"]["transfers"]


def test_the_week_schema_knows_every_registry_role() -> None:
    schema = Contract(root=find_contracts_root()).schema("week")
    roles = schema["properties"]["model"]["properties"]["role"]["enum"]
    assert roles == list(get_args(Role))


def test_an_experiment_strategys_week_validates() -> None:
    cfg = _config()
    strategy = load_strategy("c1").model_copy(update={"role": "experiment"})
    payload, _ = week._no_advice("run-mod04", _deadline(), strategy, "no advice: test", cfg)
    assert payload["model"]["role"] == "experiment"
    Contract(root=find_contracts_root()).validate(
        "week", payload | {"contract_version": CONTRACT_VERSION}
    )


def test_each_strategy_has_its_own_week_and_plan_file() -> None:
    assert artefact_paths(champion()) == {"week": "week.json", "plan": "plan.json"}
    # C1 plans only once MOD-05 gives it its own means beyond the next gameweek.
    assert artefact_paths(load_strategy("c1")) == {"week": "week_c1.json", "plan": None}
    assert artefact_paths(load_strategy("a")) == {"week": None, "plan": None}  # unpublished
