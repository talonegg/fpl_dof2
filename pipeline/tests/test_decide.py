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
import hashlib
import json
import pickle
from pathlib import Path
from typing import Any, get_args

import pandas as pd
import pytest

from decisions import OPTIMISER, decision, fixture_table, forecast, pool, state
from fpl_dof.config.loader import load_config
from fpl_dof.config.models import Config, ForecastConfig
from fpl_dof.decision import Decision, decide, engine
from fpl_dof.factory import registry
from fpl_dof.factory.registry import (
    Forecast,
    ForecastInputs,
    Role,
    Strategy,
    champion,
    load_strategy,
    published_strategies,
)
from fpl_dof.forecast.entry import publishable
from fpl_dof.frames import as_float, as_int
from fpl_dof.optimise.captain import PricePositionLine
from fpl_dof.optimise.frame import STRATEGY_COLUMN, STRATEGY_DIGEST_COLUMN, ForecastFrameError
from fpl_dof.paths import DataLayout
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.strategies import artefact_paths
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.tables import Table
from fpl_dof.sources import supplying
from fpl_dof.stages import week
from fpl_dof.week.deadline import DeadlineView, next_deadline
from fpl_dof.week.ledger import PREDICTION_COLUMNS, advice_path, predictions_path, read_advice

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
                        "kickoff_time": pd.Timestamp("2026-08-15T14:00:00Z")
                        + pd.Timedelta(weeks=as_int(fx.gameweek) - 1),
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
                        "bonus": (as_int(p.player_id) + as_int(fx.gameweek)) % 4 // 3,
                        "bps": 10,
                        # The counts A models (shadow/a.py), in deterministic patterns.
                        "goals_scored": int(minutes >= 60 and as_int(p.player_id) % 4 == 0),
                        "assists": int(minutes > 0 and as_int(p.player_id) % 5 == 1),
                        "saves": (as_int(p.player_id) + as_int(fx.gameweek)) % 5 if minutes else 0,
                        "goals_conceded": as_int(fx.gameweek) % 3,
                        "defensive_contribution": (as_int(p.player_id) * 7) % 15,
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
    team_ids = sorted(set(players["team_id"]))
    teams = pd.DataFrame(
        {
            "team_id": team_ids,
            "code": [100 + t for t in team_ids],
            "name": [_club(t) for t in team_ids],
        }
    )
    as_of = deadlines + pd.Timedelta(weeks=HORIZON[0] - 1, hours=-1)
    inputs = ForecastInputs(
        players=players,
        teams=teams,
        fixtures=fixtures,
        gameweeks=gameweeks,
        history=pd.DataFrame(),
        as_of=as_of.to_pydatetime(),
        player_gameweek=_history(players, fixtures, rules.season),
        match_odds=match_odds(
            fixtures[fixtures["gameweek"] == HORIZON[0]], rules.season, as_of - pd.Timedelta(days=1)
        ),
    )
    frame = forecast(players, HORIZON, mean=_mean(players))
    return inputs, Forecast(frame=frame, model="xp_v1", fallback_reason=None, captain_line=LINE)


def _club(team_id: int) -> str:
    """A club name club resolution can tell apart: it compares letters only."""
    return f"Club {chr(ord('A') + int(team_id) - 1)}"


def match_odds(
    fixtures: pd.DataFrame,
    season: str,
    captured_at: pd.Timestamp,
    *,
    home_goals: float = 1.5,
    away_goals: float = 1.1,
) -> pd.DataFrame:
    """Silver ``team_match_expectation`` rows for ``fixtures``, clubs by name only, as the odds
    source writes the current season's (what A_odds reads)."""
    import math

    return pd.DataFrame(
        {
            "season": season,
            "source": "market",
            "captured_at": captured_at,
            "kickoff_time": pd.to_datetime(fixtures["kickoff_time"], utc=True).to_numpy(),
            "home_team": [_club(t) for t in fixtures["home_team_id"]],
            "away_team": [_club(t) for t in fixtures["away_team_id"]],
            "home_team_id": pd.array([None] * len(fixtures), dtype="Int64"),
            "away_team_id": pd.array([None] * len(fixtures), dtype="Int64"),
            "expected_goals_home": home_goals,
            "expected_goals_away": away_goals,
            "clean_sheet_probability_home": math.exp(-away_goals),
            "clean_sheet_probability_away": math.exp(-home_goals),
            "home_win_probability": 0.45,
            "draw_probability": 0.27,
            "away_win_probability": 0.28,
            "total_goals": home_goals + away_goals,
        }
    )


def _forecast_config() -> Config:
    return _config().model_copy(update={"forecast": ForecastConfig()})


def _c1(rules: GameRules) -> tuple[ForecastInputs, Forecast, Forecast]:
    inputs, champ = _snapshot(rules)
    c1 = load_strategy("c1").forecast(inputs, rules, _forecast_config())
    return inputs, champ, c1


def test_c1_forecasts_through_the_registry_with_nothing_borrowed(game_rules: GameRules) -> None:
    _, champ, c1 = _c1(game_rules)
    assert set(c1.frame["strategy"]) == {"c1"}
    assert not c1.frame["xp_next"].equals(champ.frame["xp_next"])  # its own next-gameweek mean
    assert c1.frame["xp_gw_5"].equals(c1.frame["xp_next"])
    for own in ("xp_next_sd", "xp_horizon_sd", "start_probability"):
        assert not c1.frame[own].equals(champ.frame[own]), (
            own
        )  # MOD-05: its own, not the champion's
    assert "xp_gw_6" not in c1.frame.columns  # one gameweek, so plan: false (test_c1.py)
    assert c1.captain_line is not None and c1.captain_line != champ.captain_line


def test_engine_is_the_publishable_forecast_with_minutes_v2_off_and_the_solvers_captain(
    game_rules: GameRules,
) -> None:
    inputs, _ = _snapshot(game_rules)
    on = ForecastConfig().discrimination.model_copy(update={"minutes_v2": True})  # as shipped
    cfg = _config().model_copy(update={"forecast": ForecastConfig(discrimination=on)})
    got = load_strategy("engine").forecast(inputs, game_rules, cfg)
    flags = cfg.forecast.discrimination.model_copy(update={"minutes_v2": False})
    expected = publishable(
        inputs, game_rules, cfg.forecast.model_copy(update={"discrimination": flags})
    )
    assert got.model == expected.model == "xp_v1"
    stamps = [STRATEGY_COLUMN, STRATEGY_DIGEST_COLUMN]
    pd.testing.assert_frame_equal(got.frame.drop(columns=stamps), expected.frame)
    assert set(got.frame[STRATEGY_COLUMN]) == {"engine"}
    policy = load_strategy("engine").decision_policy(cfg, got.captain_line)
    assert policy.captain_line is None  # the solver's xp-maximising captain, not B0's line


def _with_prior_season(inputs: ForecastInputs) -> ForecastInputs:
    history = inputs.player_gameweek
    assert history is not None
    return dataclasses.replace(
        inputs, player_gameweek=pd.concat([history.assign(season="2025-26"), history])
    )


@pytest.mark.parametrize(
    ("strategy_id", "window", "seasons"),
    [
        ("c3", "current_season", 1),
        ("engine", "current_season", 1),
        ("c1", "current_season", 1),
        ("c1", "all_seasons", 2),
        ("c3", "all_seasons", 2),
    ],
)
def test_training_window_decides_which_seasons_the_forecaster_is_fitted_on(
    game_rules: GameRules,
    monkeypatch: pytest.MonkeyPatch,
    strategy_id: str,
    window: str,
    seasons: int,
) -> None:
    # The guard that stops enabling the archive from silently changing the champion's training set.
    inputs, champ = _snapshot(game_rules)
    seen: list[int] = []

    def spy(i: ForecastInputs, *_: Any, **__: Any) -> Forecast:
        assert i.player_gameweek is not None
        seen.append(i.player_gameweek["season"].nunique())
        return champ

    monkeypatch.setattr(registry, "publishable", spy)
    monkeypatch.setattr("fpl_dof.shadow.c1.forecast", spy)
    strategy = load_strategy(strategy_id)
    strategy = strategy.model_copy(
        update={"forecaster": strategy.forecaster.model_copy(update={"training_window": window})}
    )
    strategy.forecast(_with_prior_season(inputs), game_rules, _forecast_config())
    assert seen == [seasons]


def test_the_archive_changes_no_champion_output(game_rules: GameRules) -> None:
    """DL-89 items 4 and 6, end to end: last season's rows, reusing this season's player ids at
    other points and prices, change neither c3's forecast frame nor the squad's selling prices."""
    from fpl_dof.config.models import EntryConfig
    from fpl_dof.squad.state import gameweek_price_index, load_squad_state
    from squads import legal_declaration
    from test_squad_state import _picks_frame

    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    prior = history.assign(
        season="2025/26",
        kickoff_time=history["kickoff_time"] - pd.Timedelta(days=364),
        total_points=history["total_points"] + 5,
        price=history["price"] - 1.0,  # cheaper: a leaked purchase price raises the sell value
    )
    # Last season after this one: an unfiltered (gameweek, player_id) index would keep its price.
    both = pd.concat([history, prior])
    archived = dataclasses.replace(inputs, player_gameweek=both)
    c3 = load_strategy("c3")
    pd.testing.assert_frame_equal(
        c3.forecast(archived, game_rules, _forecast_config()).frame,
        c3.forecast(inputs, game_rules, _forecast_config()).frame,
    )

    held = [pick.player_id for pick in legal_declaration(inputs.players)]

    def selling(player_gameweek: pd.DataFrame) -> list[float]:
        state = load_squad_state(
            entry_config=EntryConfig(team_id=1234),
            rules=game_rules,
            players=inputs.players,
            next_gameweek=HORIZON[0],
            picks=_picks_frame(held),
            entry=pd.DataFrame([{"bank": 0.0}]),
            gameweek_prices=gameweek_price_index(player_gameweek, game_rules.season),
        )
        return [p.selling_price(game_rules) for p in state.players]

    assert selling(both) == selling(history)


def test_c1_with_no_played_history_is_refused_by_its_requires(game_rules: GameRules) -> None:
    inputs, _ = _snapshot(game_rules)
    with pytest.raises(ValueError, match="player_gameweek"):
        load_strategy("c1").forecast(
            dataclasses.replace(inputs, player_gameweek=None), game_rules, _forecast_config()
        )


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
        # Plan on for both at the policy level: production C1 runs `plan: false` (it forecasts one
        # gameweek), but the one function plans for either.
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
        clock=lambda: inputs.as_of,  # before the deadline: the ledger is open (ORC-03)
    )


#: Forecasts already made in this process, by the content of everything they were made from.
_FORECASTS: dict[str, Forecast] = {}


def _reuse_forecasts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each strategy forecasts a given snapshot once per process rather than once per test.

    For the orchestration tests, which are about what ``advise_all`` does with the forecasts, not
    the forecasts themselves; fitting four strategies again in each was most of this file's time.
    Keyed by the pickled strategy, inputs, rules and config, so a test that changes any of them
    (a later ``as_of``, no odds, a strategy with a new ``requires``) forecasts afresh. A forecast
    that raises is not kept, and every caller gets its own copy of the frame.
    """
    real = Strategy.forecast

    def reused(
        self: Strategy, inputs: ForecastInputs, rules: GameRules, config: Config
    ) -> Forecast:
        key = hashlib.sha256(pickle.dumps((self, inputs, rules, config))).hexdigest()
        if key not in _FORECASTS:
            _FORECASTS[key] = real(self, inputs, rules, config)
        kept = _FORECASTS[key]
        return dataclasses.replace(kept, frame=kept.frame.copy())

    monkeypatch.setattr(Strategy, "forecast", reused)


@pytest.fixture
def reused_forecasts(monkeypatch: pytest.MonkeyPatch) -> None:
    _reuse_forecasts(monkeypatch)


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


@pytest.fixture(scope="session")
def advised(
    game_rules: GameRules, tmp_path_factory: pytest.TempPathFactory
) -> tuple[dict[str, week.Advice], Path]:
    """Every published strategy advised once on the snapshot, for the tests that only read it."""
    root = tmp_path_factory.mktemp("advised")
    with pytest.MonkeyPatch.context() as monkeypatch:
        _reuse_forecasts(monkeypatch)
        return _advise_all(game_rules, root), root


def test_every_published_strategy_gets_a_valid_week_and_plan(
    advised: tuple[dict[str, week.Advice], Path],
) -> None:
    advice, _ = advised
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


def test_every_published_strategy_publishes_and_records_the_options_it_weighed(
    advised: tuple[dict[str, week.Advice], Path],
) -> None:
    """ORC-11: roll, best single and best overall on the model's own xP, in the hindsight's shape,
    in its week file and in the ledger's advice of record, so Last gameweek can read them later."""
    advice, root = advised
    gameweek = _deadline().gameweek
    recorded = read_advice(DataLayout(root=root), gameweek)
    assert recorded is not None
    for s in published_strategies():
        recommendation = advice[s.id][0]["recommendation"]
        options = recommendation["option_set"]
        assert options["gameweek"] == gameweek
        assert options["baseline_roll"]["transfers_count"] == 0
        assert len(options["all_options"]) == len(recommendation["options"])
        chosen = next(
            o for o in options["all_options"] if o["transfers_count"] == recommendation["transfers"]
        )
        assert chosen["net_points"] == pytest.approx(
            recommendation["net_expected_points"], abs=0.01
        )
        assert recorded["models"][s.id]["recommendation"]["option_set"] == options
        # One home: the older `options` shape is derived from the option set, in its rounding.
        assert [
            (o["transfers"], o["hit_points"], o["net_expected_points"], o["gain_over_roll"])
            for o in recommendation["options"]
        ] == [
            (p["transfers_count"], p["hit_points"], p["net_points"], p["gain_over_roll"])
            for p in options["all_options"]
        ]


def _fail_c1(monkeypatch: pytest.MonkeyPatch) -> None:
    real = Strategy.forecast

    def failing(self: Strategy, *args: Any, **kwargs: Any) -> Forecast:
        if self.id == "c1":
            raise RuntimeError("c1 fit exploded")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Strategy, "forecast", failing)


@pytest.mark.usefixtures("reused_forecasts")
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


@pytest.mark.usefixtures("reused_forecasts")
def test_a_challenger_failing_after_an_earlier_success_keeps_that_success_as_the_record(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ORC-03 (DL-94): the second run's failure is noted beside the first run's advice."""
    first = _advise_all(game_rules, tmp_path)
    _fail_c1(monkeypatch)
    snapshot = _orchestration(game_rules)
    later = dataclasses.replace(
        snapshot,
        inputs=dataclasses.replace(
            snapshot.inputs, as_of=snapshot.inputs.as_of + pd.Timedelta(minutes=10)
        ),
    )
    second, _ = week.advise_all(
        later, published_strategies(), gold=tmp_path / "gold", layout=DataLayout(root=tmp_path)
    )

    recorded = read_advice(DataLayout(root=tmp_path), HORIZON[0])
    assert recorded is not None
    c1 = recorded["models"]["c1"]
    assert c1["advised"] == first["c1"][0]["advised"]
    assert "c1 fit exploded" in c1["last_failure"]["reason"]
    assert "last_failure" not in recorded["models"]["c3"]

    # The published file shows the advice of record, not "no advice", with the failure beside it.
    written = json.loads((tmp_path / "gold" / "week_c1.json").read_text(encoding="utf-8"))
    assert written == second["c1"][0]
    assert not written["skipped"] and "skipped_reason" not in written
    assert written["advised"] == first["c1"][0]["advised"]
    assert written["recommendation"] == first["c1"][0]["recommendation"]
    assert written["strategy"] == first["c1"][0]["strategy"]
    assert written["as_of"] == first["c1"][0]["as_of"] != c1["last_failure"]["as_of"]
    assert written["last_failure"] == c1["last_failure"]
    Contract(root=find_contracts_root()).validate(
        "week", written | {"contract_version": CONTRACT_VERSION}
    )


@pytest.mark.usefixtures("reused_forecasts")
def test_a_challenger_that_never_succeeded_publishes_no_advice(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fail_c1(monkeypatch)
    advice = _advise_all(game_rules, tmp_path)
    assert advice["c1"][0]["skipped"] and "last_failure" not in advice["c1"][0]


@pytest.mark.usefixtures("reused_forecasts")
def test_a_run_that_ends_after_the_deadline_records_nothing(
    game_rules: GameRules, tmp_path: Path
) -> None:
    """ORC-03: the snapshot was before the deadline, but the write would land after it."""
    snapshot = _orchestration(game_rules)
    late = dataclasses.replace(
        snapshot, clock=lambda: snapshot.deadline.deadline_utc + pd.Timedelta(minutes=1)
    )
    layout = DataLayout(root=tmp_path)
    week.advise_all(late, published_strategies(), gold=tmp_path / "gold", layout=layout)
    assert (tmp_path / "gold" / "week.json").exists()  # the artefacts are still written
    assert not advice_path(layout, HORIZON[0]).exists()


@pytest.mark.usefixtures("reused_forecasts")
def test_every_payload_and_ledger_entry_carries_as_of_and_trigger(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fail_c1(monkeypatch)  # a "no advice" payload is stamped too
    advice = _advise_all(game_rules, tmp_path)
    as_of = "2026-09-11T16:30:00Z"  # the snapshot's, not the wall clock's
    for week_payload, plan_payload in advice.values():
        for payload in (week_payload, plan_payload):
            if payload is not None:
                assert (payload["as_of"], payload["trigger"]) == (as_of, "manual")
    recorded = read_advice(DataLayout(root=tmp_path), HORIZON[0])
    assert recorded is not None and recorded["trigger"] == "manual"
    assert all(m["as_of"] == as_of for m in recorded["models"].values())


@pytest.mark.usefixtures("reused_forecasts")
def test_a_strategy_missing_a_required_table_records_no_advice_and_the_others_run(
    game_rules: GameRules, tmp_path: Path
) -> None:
    needy = load_strategy("engine").model_copy(update={"requires": (Table.PLAYER_METRIC,)})
    advice = _advise_all(game_rules, tmp_path, (champion(), needy, load_strategy("c1")))
    assert advice["engine"][0]["skipped"]
    assert "player_metric" in advice["engine"][0]["skipped_reason"]
    assert not advice["c3"][0]["skipped"] and not advice["c1"][0]["skipped"]


def test_a_strategy_whose_odds_arrive_says_so_once_whatever_started_the_run(
    game_rules: GameRules, tmp_path: Path
) -> None:
    """ORC-07: offline for its odds in the held record, advising now, in a run the daily
    schedule started rather than a change: the week file says the source arrived and when, and
    its trigger says what started the run; a later run says nothing more."""
    layout, gold = DataLayout(root=tmp_path), tmp_path / "gold"
    lineup = (champion(), load_strategy("a_odds"))
    snapshot = _orchestration(game_rules)
    no_odds = dataclasses.replace(
        snapshot, inputs=dataclasses.replace(snapshot.inputs, match_odds=None)
    )
    first, _ = week.advise_all(no_odds, lineup, gold=gold, layout=layout)
    assert first["a_odds"][0]["skipped"]
    held = (read_advice(layout, HORIZON[0]) or {})["models"]["a_odds"]
    assert held["missing"] == [Table.TEAM_MATCH_EXPECTATION.value]

    config = snapshot.config
    scheduled = config.model_copy(
        update={"runtime": config.runtime.model_copy(update={"trigger": "schedule"})}
    )
    later = snapshot.inputs.as_of + pd.Timedelta(minutes=10)
    arriving = dataclasses.replace(
        snapshot, config=scheduled, inputs=dataclasses.replace(snapshot.inputs, as_of=later)
    )
    second, _ = week.advise_all(arriving, lineup, gold=gold, layout=layout)
    a_odds = second["a_odds"][0]
    sources = supplying([Table.TEAM_MATCH_EXPECTATION.value], config.sources)
    assert sources and a_odds["arrived"] == {"sources": sources, "at": a_odds["as_of"]}
    assert a_odds["trigger"] == "schedule"
    assert not a_odds["skipped"] and "arrived" not in second["c3"][0]
    Contract(root=find_contracts_root()).validate(
        "week", a_odds | {"contract_version": CONTRACT_VERSION}
    )
    assert "arrived" not in (read_advice(layout, HORIZON[0]) or {})["models"]["a_odds"]

    third, _ = week.advise_all(arriving, lineup, gold=gold, layout=layout)
    assert "arrived" not in third["a_odds"][0]  # the held record now advises


def test_the_engine_strategy_writes_its_own_week_file(
    advised: tuple[dict[str, week.Advice], Path],
) -> None:
    advice, tmp_path = advised
    assert not advice["engine"][0]["skipped"] and advice["engine"][1] is None
    written = json.loads((tmp_path / "gold" / "week_engine.json").read_text(encoding="utf-8"))
    assert written["strategy"]["id"] == "engine"
    Contract(root=find_contracts_root()).validate(
        "week", written | {"contract_version": CONTRACT_VERSION}
    )


@pytest.mark.usefixtures("reused_forecasts")
def test_a_failing_champion_fails_the_run(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(*_: Any, **__: Any) -> Decision:
        raise RuntimeError("the engine fell over")

    monkeypatch.setattr(week, "decide", broken)
    with pytest.raises(RuntimeError, match="engine fell over"):
        _advise_all(game_rules, tmp_path)


@pytest.mark.usefixtures("reused_forecasts")
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


@pytest.mark.usefixtures("reused_forecasts")
def test_the_champion_is_the_registrys_whatever_order_the_strategies_arrive_in(
    game_rules: GameRules, tmp_path: Path
) -> None:
    advice = _advise_all(game_rules, tmp_path, tuple(reversed(published_strategies())))
    recorded = read_advice(DataLayout(root=tmp_path), HORIZON[0])
    assert recorded is not None
    assert recorded["advised"] == advice[champion().id][0]["advised"]
    written = json.loads((tmp_path / "gold" / "week.json").read_text(encoding="utf-8"))
    assert written["strategy"]["id"] == champion().id


def test_the_ledger_carries_every_published_strategy(
    advised: tuple[dict[str, week.Advice], Path],
) -> None:
    advice, tmp_path = advised
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
    payload, _ = week._no_advice(
        "run-mod04", _deadline(), strategy, "no advice: test", cfg, _deadline().now_utc
    )
    assert payload["model"]["role"] == "experiment"
    Contract(root=find_contracts_root()).validate(
        "week", payload | {"contract_version": CONTRACT_VERSION}
    )


def test_each_strategy_has_its_own_week_and_plan_file() -> None:
    assert artefact_paths(champion()) == {"week": "week.json", "plan": "plan.json"}
    # C1 plans only once MOD-05 gives it its own means beyond the next gameweek.
    assert artefact_paths(load_strategy("c1")) == {"week": "week_c1.json", "plan": None}
    assert artefact_paths(load_strategy("a")) == {"week": "week_a.json", "plan": None}


# --- ORC-08: what each strategy predicted ---------------------------------------------


@pytest.mark.usefixtures("reused_forecasts")
def test_every_advising_strategy_leaves_its_frame_in_the_ledger(
    game_rules: GameRules, tmp_path: Path
) -> None:
    advice = _advise_all(game_rules, tmp_path)
    layout = DataLayout(root=tmp_path)
    for strategy_id in advice:
        stored = pd.read_parquet(predictions_path(layout, HORIZON[0], strategy_id))
        assert list(stored.columns) == list(PREDICTION_COLUMNS)  # the sd, so variance, is kept
        assert stored["player_id"].is_unique and len(stored) == len(pool())


@pytest.mark.usefixtures("reused_forecasts")
def test_a_failed_strategy_keeps_its_earlier_predictions(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _advise_all(game_rules, tmp_path)
    path = predictions_path(DataLayout(root=tmp_path), HORIZON[0], "c1")
    before = path.read_bytes()
    _fail_c1(monkeypatch)
    _advise_all(game_rules, tmp_path)
    assert path.read_bytes() == before


@pytest.mark.usefixtures("reused_forecasts")
def test_an_older_write_the_ledger_ignores_leaves_no_predictions(
    game_rules: GameRules, tmp_path: Path
) -> None:
    """ORC-08: predictions follow the advice of record, so a write older than the held entry,
    which record_advice ignores, writes no predictions either."""
    layout = DataLayout(root=tmp_path)
    newer = {"gameweek": HORIZON[0], "recorded_at": "2099-01-01T00:00:00Z", "models": {}}
    path = advice_path(layout, HORIZON[0])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(newer), encoding="utf-8")
    _advise_all(game_rules, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == newer
    assert not (layout.ledger / "predictions").exists()


@pytest.mark.usefixtures("reused_forecasts")
def test_predictions_after_the_deadline_are_refused(game_rules: GameRules, tmp_path: Path) -> None:
    snapshot = _orchestration(game_rules)
    late = dataclasses.replace(
        snapshot, clock=lambda: snapshot.deadline.deadline_utc + pd.Timedelta(minutes=1)
    )
    layout = DataLayout(root=tmp_path)
    week.advise_all(late, published_strategies(), gold=tmp_path / "gold", layout=layout)
    assert not (layout.ledger / "predictions").exists()
