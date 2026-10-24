"""The live season as if each model had played it, in-sample (ORC-13, DL-97).

The replay's seam is :func:`fpl_dof.factory.as_if_played.replay`: a strategy, fitted once today,
replayed at every finished deadline. These tests drive it with a stand-in forecaster on a small
fixture season, so what each deadline was shown, and what it decided, can be read off directly.
"""

from __future__ import annotations

import dataclasses
import json
import pickle
import re
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
import pytest
import yaml

import test_xp_v1_live as live
from conftest import before_next_deadline
from fpl_dof.artefacts import AS_IF_PLAYED_DIRNAME
from fpl_dof.config.models import Config, ForecastConfig
from fpl_dof.decision import decide
from fpl_dof.factory import as_if_played as module
from fpl_dof.factory.as_if_played import as_if_played, inputs_at, replay
from fpl_dof.factory.registry import Strategy, load_strategy
from fpl_dof.forecast import publishable
from fpl_dof.forecast.entry import Forecast
from fpl_dof.forecast.inputs import ForecastInputs, MissingInputError
from fpl_dof.frames import as_int, gameweek_column, gameweek_sd_column
from fpl_dof.gameweek import current_gameweek
from fpl_dof.optimise.frame import validate_forecast_frame
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.models_history import build_models_history
from fpl_dof.rules.legality import validate_squad
from fpl_dof.rules.models import GameRules
from fpl_dof.rules.realised import score_lineup
from fpl_dof.silver.tables import Table
from fpl_dof.stages import as_if_played as stage
from fpl_dof.stages import publish
from test_models_history import WORKFLOW

SEASON = "2026/27"
CLUBS = 10
#: Per club: position and price. Two keepers, three defenders, three midfielders, two forwards.
ROSTER: tuple[tuple[str, float], ...] = (
    ("GKP", 4.5),
    ("GKP", 4.0),
    ("DEF", 5.0),
    ("DEF", 4.5),
    ("DEF", 4.0),
)
ROSTER += (("MID", 7.5), ("MID", 6.0), ("MID", 5.0), ("FWD", 7.0), ("FWD", 5.5))
FIRST_DEADLINE = pd.Timestamp("2026-08-21T17:30:00Z")
FINISHED = (1, 2, 3, 4)  # GW5 is open
LAST = 5
#: Every price observed after GW4's deadline is this much higher: reading it is looking ahead.
LATER_RISE = 1.0
#: The current player table's price, never right at any past deadline.
TODAY_RISE = 2.0


def _deadline(gw: int) -> pd.Timestamp:
    return FIRST_DEADLINE + pd.Timedelta(days=7 * (gw - 1))


def _league() -> list[dict[str, Any]]:
    return [
        {"player_id": club * 100 + slot, "team_id": club, "position": position, "price": price}
        for club in range(1, CLUBS + 1)
        for slot, (position, price) in enumerate(ROSTER)
    ]


def _points(player_id: int, gw: int) -> int:
    return (player_id * 7 + gw * 3) % 11


def _season(rules: GameRules) -> tuple[ForecastInputs, pd.DataFrame, pd.DataFrame]:
    """Ten clubs, four finished gameweeks, prices observed before each deadline and after GW4's."""
    league = _league()
    played = pd.DataFrame(
        [
            {
                "season": SEASON,
                "gameweek": gw,
                "player_id": p["player_id"],
                "player_code": 10_000 + p["player_id"],
                "web_name": f"P{p['player_id']}",
                "position": p["position"],
                "team_id": p["team_id"],
                "kickoff_time": _deadline(gw) + pd.Timedelta(days=1),
                "minutes": 90 if _points(p["player_id"], gw) else 0,
                "total_points": _points(p["player_id"], gw),
                "price": p["price"],
            }
            for gw in FINISHED
            for p in league
        ]
    )
    prices = pd.DataFrame(
        [
            {
                "observed_at": _deadline(gw) - pd.Timedelta(hours=2),
                "player_id": p["player_id"],
                "player_code": 10_000 + p["player_id"],
                "price": p["price"] + 0.1 * (gw - 1),
                "selected_by_percent": 5.0,
            }
            for gw in FINISHED
            for p in league
        ]
        + [
            {
                "observed_at": _deadline(4) + pd.Timedelta(days=2),
                "player_id": p["player_id"],
                "player_code": 10_000 + p["player_id"],
                "price": p["price"] + LATER_RISE,
                "selected_by_percent": 50.0,
            }
            for p in league
        ]
    )
    players = pd.DataFrame(
        [
            {
                **p,
                "price": p["price"] + TODAY_RISE,
                "code": 10_000 + p["player_id"],
                "web_name": f"P{p['player_id']}",
                "full_name": f"Player {p['player_id']}",
                "status": "i",  # injured today: news a past deadline did not have
                "chance_of_playing_next_round": 0,
                "selected_by_percent": 90.0,
                "news": "Knee",
            }
            for p in league
        ]
    )
    pairs = [
        (gw, home, home % CLUBS + 1)
        for gw in range(1, LAST + 1)
        for home in range(1 + (gw % 2), CLUBS + 1, 2)
    ]
    fixtures = pd.DataFrame(
        [
            {
                "fixture_id": i + 1,
                "gameweek": gw,
                "kickoff_time": _deadline(gw) + pd.Timedelta(days=1),
                "home_team_id": home,
                "away_team_id": away,
                "home_difficulty": 3,
                "away_difficulty": 3,
                "finished": gw in FINISHED,
            }
            for i, (gw, home, away) in enumerate(pairs)
        ]
    )
    gameweeks = pd.DataFrame(
        {
            "gameweek": range(1, LAST + 1),
            "deadline_time": [_deadline(gw) for gw in range(1, LAST + 1)],
            "finished": [gw in FINISHED for gw in range(1, LAST + 1)],
            "data_checked": [gw in FINISHED for gw in range(1, LAST + 1)],
            "is_next": [gw == LAST for gw in range(1, LAST + 1)],
        }
    )
    windows = [
        (rules.chips.bench_scores_with[0], "team"),
        *((name, "transfer") for name in rules.chips.transfers_free_with),
        *((name, "team") for name in rules.chips.captain_multiplier_by_chip),
    ]
    chips = pd.DataFrame(
        [
            {"chip_id": i + 1, "name": n, "chip_type": t, "start_event": 1, "stop_event": LAST}
            for i, (n, t) in enumerate(windows)
        ]
    )
    inputs = ForecastInputs(
        players=players,
        teams=pd.DataFrame({"team_id": range(1, CLUBS + 1), "code": range(1, CLUBS + 1)}),
        fixtures=fixtures,
        gameweeks=gameweeks,
        history=pd.DataFrame(),
        as_of=(_deadline(LAST) - pd.Timedelta(hours=1)).to_pydatetime(),
        player_gameweek=played,
    )
    return inputs, prices, chips


#: Every call each stand-in forecaster received: (inputs, fitted).
CALLS: list[tuple[ForecastInputs, Any]] = []
TODAY = "today's weights"


class Echo(Strategy):
    """A forecaster that rates each player by his mean points so far, whatever it is shown."""

    fail_at: ClassVar[frozenset[int]] = frozenset()

    def forecast(
        self, inputs: ForecastInputs, rules: GameRules, config: Config, *, fitted: Any = None
    ) -> Forecast:
        CALLS.append((inputs, fitted))
        gw = current_gameweek(inputs.gameweeks, inputs.as_of)
        if fitted is not None and gw in self.fail_at:
            raise MissingInputError(f"{self.id}: no odds before GW{gw}", ("odds",))
        seen = inputs.player_gameweek
        mean = seen.groupby("player_id")["total_points"].mean() if seen is not None else None
        players = inputs.players
        xp = players["player_id"].map(mean) if mean is not None else None
        xp = (xp if xp is not None else pd.Series(0.0, index=players.index)).fillna(2.0)
        xp = xp.astype(float) + players["player_id"] / 1e5  # no ties
        frame = players[["player_id", "web_name", "position", "team_id", "price"]].assign(
            xp_next=xp, xp_next_sd=1.0, start_probability=1.0
        )
        horizon = range(gw, min(gw + config.decision.horizon.gameweeks, LAST + 1))
        for week in horizon:
            frame[gameweek_column(week)] = xp
            frame[gameweek_sd_column(week)] = 1.0
        frame = frame.assign(xp_horizon=xp * len(horizon), xp_horizon_sd=1.0)
        return Forecast(
            validate_forecast_frame(frame), "echo", None, fitted=fitted if fitted else TODAY
        )


class Flaky(Echo):
    fail_at: ClassVar[frozenset[int]] = frozenset({3})


def _echo(strategy_id: str, kind: type[Echo] = Echo) -> Echo:
    return kind.model_validate(load_strategy(strategy_id).model_dump())


def _config(rules: GameRules, *, chip_at: int | None = None) -> Config:
    """One worker, a two-gameweek plan; with ``chip_at``, the bench chip forced there and every
    other chip forbidden, so the plan's choice is known."""
    config = Config()
    decision = config.decision
    chips = decision.chips
    if chip_at is not None:
        bench = rules.chips.bench_scores_with[0]
        others = (*rules.chips.transfers_free_with, *rules.chips.captain_multiplier_by_chip)
        chips = chips.model_copy(
            update={
                "force_chip_gameweek": {bench: chip_at},
                "forbid_chip_gameweeks": {c: tuple(range(1, LAST + 1)) for c in others},
            }
        )
    decision = decision.model_copy(
        update={
            "horizon": decision.horizon.model_copy(update={"gameweeks": 2}),
            "chips": chips,
            "simulation": decision.simulation.model_copy(update={"enabled": False}),
        }
    )
    backtest = config.backtest.model_copy(update={"strategy_workers": 1})
    return config.model_copy(update={"decision": decision, "backtest": backtest})


@pytest.fixture(autouse=True)
def _calls() -> None:
    CALLS.clear()


def test_a_deadline_is_shown_nothing_kicked_off_after_it_nor_a_later_price(
    game_rules: GameRules,
) -> None:
    """Invariant 5 at the seam: GW3's inputs hold no GW3 row and no price observed after it."""
    inputs, prices, _ = _season(game_rules)
    at = inputs_at(inputs, SEASON, 3, prices)
    deadline = _deadline(3)
    assert pd.Timestamp(at.as_of) < deadline
    assert current_gameweek(at.gameweeks, at.as_of) == 3
    assert at.player_gameweek is not None
    assert at.player_gameweek["kickoff_time"].max() < deadline
    assert sorted(at.player_gameweek["gameweek"].unique()) == [1, 2]
    expected = {p["player_id"]: round(p["price"] + 0.2, 1) for p in _league()}  # GW3's observation
    assert dict(zip(at.players["player_id"], at.players["price"].round(1), strict=True)) == expected
    assert set(at.players["status"]) == {"a"} and set(at.players["news"]) == {""}  # no news then
    assert not at.fixtures.loc[at.fixtures["gameweek"] >= 3, "finished"].any()
    assert at.fixtures.loc[at.fixtures["gameweek"] < 3, "finished"].all()
    late = inputs_at(inputs, SEASON, 4, prices)
    assert late.players["price"].max() < max(p for _, p in ROSTER) + LATER_RISE


def test_each_model_replays_every_finished_gameweek_with_todays_weights(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, prices, chips = _season(game_rules)
    states: list[Any] = []
    real = decide

    def spy(frame: pd.DataFrame, state: Any, *a: Any, **k: Any) -> Any:
        states.append(state)
        return real(frame, state, *a, **k)

    monkeypatch.setattr("fpl_dof.factory.as_if_played.decide", spy)
    rows, skipped = replay(
        _echo("engine"), inputs, game_rules, _config(game_rules), finished=FINISHED,
        prices=prices, chips=chips,
    )  # fmt: skip
    assert skipped == {}
    assert [r["gw"] for r in rows] == list(FINISHED)  # from GW1
    assert rows[0]["n_transfers"] == 0  # a from-scratch squad, not a transfer
    assert all(r["chip"] is None for r in rows)  # engine does not plan, so plays no chip

    first = states[0]
    assert len(first.players) == game_rules.squad.size
    assert validate_squad(first.as_squad(game_rules), game_rules) == []  # legal, under the budget
    assert first.bank >= 0

    # Fitted once, today; every past deadline predicts with those weights and sees only its past.
    today, *past = CALLS
    assert today[1] is None and all(fitted == TODAY for _, fitted in past)
    for gw, (shown, _) in zip(FINISHED, past, strict=True):
        assert shown.player_gameweek is not None
        assert (shown.player_gameweek["kickoff_time"] < _deadline(gw)).all()


def test_a_gameweeks_decision_cannot_see_its_own_outcome(game_rules: GameRules) -> None:
    """Rewriting GW3's points changes what GW3 scored, never what was decided at its deadline."""
    inputs, prices, chips = _season(game_rules)
    before, _ = replay(
        _echo("engine"), inputs, game_rules, _config(game_rules), finished=FINISHED,
        prices=prices, chips=chips,
    )  # fmt: skip
    history = inputs.player_gameweek
    assert history is not None
    rewritten = history.assign(
        total_points=history["total_points"].where(history["gameweek"] != 3, 20)
    )
    after, _ = replay(
        _echo("engine"), dataclasses.replace(inputs, player_gameweek=rewritten), game_rules,
        _config(game_rules), finished=(1, 2, 3), prices=prices, chips=chips,
    )  # fmt: skip
    decided = ("n_transfers", "transfers", "captain", "vice_captain")
    assert before[:2] == after[:2]
    assert {k: before[2][k] for k in decided} == {k: after[2][k] for k in decided}
    assert before[2]["points"] != after[2]["points"]


def test_the_plans_chip_is_played_once_and_scored(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A planning model follows its plan's week when the plan plays a chip in it."""
    inputs, prices, chips = _season(game_rules)
    scored: list[Any] = []
    real = score_lineup

    def spy(lineup: Any, *a: Any) -> Any:
        scored.append(lineup)
        return real(lineup, *a)

    monkeypatch.setattr("fpl_dof.factory.as_if_played.score_lineup", spy)
    bench = game_rules.chips.bench_scores_with[0]
    rows, skipped = replay(
        _echo("c3"), inputs, game_rules, _config(game_rules, chip_at=2), finished=FINISHED,
        prices=prices, chips=chips,
    )  # fmt: skip
    assert skipped == {}
    assert [r["chip"] for r in rows] == [None, bench, None, None]
    assert scored[1].chip == bench  # all fifteen scored by the one realised scorer
    fielded = (*scored[1].starting, scored[1].bench_gkp, *scored[1].bench_order)
    assert len(set(fielded)) == game_rules.squad.size


def test_a_model_that_cannot_run_at_a_deadline_is_unavailable_that_gameweek(
    game_rules: GameRules,
) -> None:
    inputs, prices, chips = _season(game_rules)
    rows, unavailable, skipped = as_if_played(
        inputs, [_echo("engine"), _echo("a_odds", Flaky)], game_rules, _config(game_rules),
        finished=FINISHED, prices=prices, chips=chips,
    )  # fmt: skip
    assert unavailable == {}
    assert [r["gw"] for r in rows["a_odds"]] == [1, 2, 4]  # its squad carries over GW3
    assert skipped == {"a_odds": {3: "MissingInputError: a_odds: no odds before GW3"}}

    document = build_models_history(
        season=SEASON, rows=rows, unavailable=unavailable, provenance=module.SETTINGS,
        contract_version=CONTRACT_VERSION, in_sample=True, skipped=skipped,
    )  # fmt: skip
    Contract(root=find_contracts_root()).validate("as_if_played", document)
    assert document["kind"] == "in_sample"
    assert document["caveat"].startswith(
        "In-sample: today's models replayed on past gameweeks; not evidence of skill."
    )
    gw3 = next(g for g in document["gameweeks"] if g["gameweek"] == 3)
    assert set(gw3["models"]) == {"engine"}
    assert gw3["unavailable"] == {"a_odds": skipped["a_odds"][3]}
    assert [g["gameweek"] for g in document["gameweeks"]] == list(FINISHED)
    # Only published models, each ranked; one never replayed says so.
    ids = {m["id"] for m in document["models"]}
    assert ids == {s for s in ids if load_strategy(s).published}
    c3 = next(m for m in document["models"] if m["id"] == "c3")
    assert c3["available"] is False


def test_a_model_whose_fit_today_fails_is_unavailable_for_the_season(
    game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, prices, chips = _season(game_rules)

    def broken(*_a: Any, **_k: Any) -> Forecast:
        raise MissingInputError("a_odds: no odds", ("odds",))

    monkeypatch.setattr(Echo, "forecast", broken)
    rows, unavailable, _ = as_if_played(
        inputs, [_echo("a_odds")], game_rules, _config(game_rules), finished=FINISHED,
        prices=prices, chips=chips,
    )  # fmt: skip
    assert rows == {}
    assert unavailable == {
        "a_odds": "today's fit could not be replayed: MissingInputError: a_odds: no odds"
    }


def test_absent_inputs_cross_the_worker_boundary_intact() -> None:
    """Replays run in worker processes (run_isolated): an error that cannot be unpickled breaks
    the pool, and every strategy still pending is rerun serially."""
    error = pickle.loads(pickle.dumps(MissingInputError("a_odds: no odds", ("odds",))))
    assert isinstance(error, MissingInputError)
    assert (str(error), error.tables) == ("a_odds: no odds", ("odds",))


def test_the_live_forecast_predicts_an_earlier_deadline_with_its_fitted_weights(
    game_rules: GameRules,
) -> None:
    """xp_v1 through the live path: the weights come back unrefitted, the features are GW4's."""
    history = live._player_gameweek()
    live_inputs = ForecastInputs(
        players=live._players(history),
        teams=pd.DataFrame({"team_id": live.TEAMS}),
        fixtures=live._fixtures(),
        gameweeks=live._gameweeks(),
        as_of=before_next_deadline(live._gameweeks()),
        history=live._season_history(history),
        player_gameweek=history,
    )
    config = ForecastConfig()
    today = publishable(live_inputs, game_rules, config)
    assert today.fitted is not None
    at = inputs_at(live_inputs, game_rules.season, 4, None)
    earlier = publishable(at, game_rules, config, fitted=today.fitted)
    assert earlier.fitted.models is today.fitted.models
    assert earlier.fitted.deadline < today.fitted.deadline
    assert (earlier.fitted.past["kickoff_time"] < earlier.fitted.deadline).all()
    assert as_int(earlier.frame["next_gameweek"].iloc[0]) == 4
    assert not earlier.frame["xp_next"].equals(today.frame["xp_next"])


def test_nothing_that_picks_or_promotes_the_champion_reads_it() -> None:
    """DL-97: in-sample, so only the stage that records it and the one that publishes it read it."""
    root = Path(module.__file__).resolve().parents[1]
    pattern = re.compile(r"as_if_played|AS_IF_PLAYED")
    readers = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert readers == {
        "artefacts.py",
        "factory/as_if_played.py",
        "pipeline.py",
        "publish/contract.py",
        "publish/models_history.py",
        "stages/as_if_played.py",
        "stages/publish.py",
    }


def test_the_stage_records_it_and_the_pipeline_publishes_the_newest(
    game_rules: GameRules, layout: DataLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``fpl-dof as-if-played`` writes ``ledger/as_if_played/<run_id>.json``; publish serves the
    newest as ``as_if_played.json``, labelled in-sample."""
    ctx = _stage(game_rules, layout, monkeypatch, _echo("engine"))
    result = stage.run(ctx)
    assert result.metrics["finished"] == len(FINISHED)  # GW5, still open, is not replayed
    recorded = layout.ledger / "as_if_played" / f"{ctx.run_id}.json"
    (document,) = json.loads(recorded.read_text("utf-8"))
    assert document["provenance"]["run_id"] == ctx.run_id
    assert [g["gameweek"] for g in document["gameweeks"]] == list(FINISHED)

    (recorded.parent / "20261020T161700Z-a.json").write_text(json.dumps([{"season": "older"}]))
    published = publish._models_history(ctx, AS_IF_PLAYED_DIRNAME)
    assert published is not None and published["kind"] == "in_sample"
    Contract(root=find_contracts_root()).validate("as_if_played", published)


class Buggy(Echo):
    """A forecaster with a bug at GW3: not absent inputs, so not a reason to show."""

    def forecast(self, inputs: ForecastInputs, *a: Any, fitted: Any = None) -> Forecast:
        if fitted is not None and current_gameweek(inputs.gameweeks, inputs.as_of) == 3:
            raise KeyError("player_id")
        return super().forecast(inputs, *a, fitted=fitted)


def test_an_unexpected_error_fails_the_stage_rather_than_reading_as_unavailable(
    game_rules: GameRules, layout: DataLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only absent inputs make a model unavailable; a bug fails the job, so its alert fires."""
    ctx = _stage(game_rules, layout, monkeypatch, _echo("engine", Buggy))
    with pytest.raises(KeyError, match="player_id"):
        stage.run(ctx)
    assert not (layout.ledger / "as_if_played").exists()  # nothing recorded for publish to serve


def _stage(
    game_rules: GameRules, layout: DataLayout, monkeypatch: pytest.MonkeyPatch, strategy: Echo
) -> StageContext:
    """The stage on the fixture season, with ``strategy`` the only published one."""
    inputs, prices, chips = _season(game_rules)
    tables = {
        Table.PLAYER: inputs.players,
        Table.TEAM: inputs.teams,
        Table.FIXTURE: inputs.fixtures,
        Table.GAMEWEEK: inputs.gameweeks,
        Table.PLAYER_SEASON_HISTORY: inputs.history,
        Table.PLAYER_GAMEWEEK: inputs.player_gameweek,
        Table.PRICE_HISTORY: prices,
        Table.CHIP: chips,
    }
    monkeypatch.setattr(stage, "read_rules", lambda *_a: game_rules)
    monkeypatch.setattr(stage, "read_table", lambda _s, _y, t: tables[t])
    monkeypatch.setattr(stage, "read_table_optional", lambda _s, _y, t: tables.get(t))
    monkeypatch.setattr(stage, "published_strategies", lambda: [strategy])
    return StageContext(
        config=_config(game_rules), layout=layout, run_id="20261027T161700Z-b",
        as_of=inputs.as_of,
    )  # fmt: skip


def test_its_own_weekly_job_records_it_and_the_pipeline_restores_it() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text("utf-8"))["jobs"]
    job = jobs["as-if-played"]
    assert "needs" not in job  # beside the backtest, on its own runner and budget
    runs = [s.get("run", "") for s in job["steps"]]
    assert any("fpl-dof as-if-played" in r and "As-if-played replay not built" in r for r in runs)
    assert any("--source as_if_played" in r for r in runs)
    assert set(jobs["alert"]["needs"]) == {"backtest", "as-if-played"}
    # The backtest's own failure check is for the models history only.
    backtest_runs = " ".join(s.get("run", "") for s in jobs["backtest"]["steps"])
    assert "as_if_played" not in backtest_runs and "as-if-played" not in backtest_runs
    pipeline = WORKFLOW.with_name("pipeline.yml").read_text("utf-8")
    assert "experiments models_history as_if_played" in pipeline


def test_the_published_artefact_is_labelled_in_sample() -> None:
    schema = json.loads(
        (find_contracts_root() / "v1" / "models_history.schema.json").read_text("utf-8")
    )
    assert schema["properties"]["kind"]["enum"] == ["backtest", "in_sample"]
