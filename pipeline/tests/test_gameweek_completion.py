"""LIVE-07: a gameweek marked data-checked is evaluated by the run its change started.

One gameweek's last three days, end to end through the real adapter, the real transform and the
real stages, from the bronze each step leaves (DP-13: where being wrong is silent, the test walks
the whole path rather than a seam):

* **Before the deadline** (A): the whole pipeline runs and the week stage records GW1's advice.
* **Finished, not checked** (B): a full ingest, then the run it would start. FPL has marked GW1
  finished and every player's row is in. The gameweek is Playing (ORC-01), so nothing is
  evaluated, however complete the evidence looks, and ``live.json`` reads ``complete``.
* **Data-checked** (C): FPL checks the gameweek and corrects a point. The fast ingest sees the flag
  flip, and with it fetches the final rows (LIVE-07). Its change manifest moves ``results`` and
  nothing else, the pipeline guard lets the ``change:results`` run go ahead, and in that run, with
  no ingest of its own, the evaluation is written on the corrected figure, the season log holds
  GW1 and ``live.json`` reads ``final`` (LIVE-04): not at the next daily refresh.

The world is a trimmed league (the recorded fixtures' eight clubs) with two fixtures added to GW1 so
every club plays once; every player plays 90 minutes and scores 2, and the owner's captain's armband
makes the owner's gameweek 24. FPL's check gives one of his defenders a bonus point: 25.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
import respx
import yaml

from conftest import FIXTURES, TEST_ENTRY_ID, built_once
from fpl_dof.cli import EXIT_OK, main
from fpl_dof.config.models import HttpConfig, RateLimitConfig, RetryConfig
from fpl_dof.factory.registry import published_strategies
from fpl_dof.frames import as_int
from fpl_dof.gameweek import Due, Phase, SilverTables, season_states
from fpl_dof.schedule_cli import main as schedule_main
from fpl_dof.silver.store import read_table, write_table
from fpl_dof.silver.tables import Table
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fpl.adapter import FplApiAdapter
from fpl_dof.stages import publish as publish_stage
from fpl_dof.stages import week as week_stage
from fpl_dof.week.ledger import record_advice, record_predictions
from squads import legal_declaration

GW = 1
SEASON = "2026/27"
#: Before GW1's deadline (21 August 17:30), after both finish, and the morning FPL checks it.
BEFORE_DEADLINE = "2026-08-20T12:00:00+00:00"
FINISHED = "2026-08-24T12:00:00+00:00"
CHECKED = "2026-08-25T12:00:00+00:00"
#: Two fixtures beside the recorded GW1 pair, so all eight clubs play.
EXTRA_FIXTURES = (
    {"id": 100, "code": 2645300, "team_h": 3, "team_a": 8, "kickoff_time": "2026-08-22T14:00:00Z"},
    {"id": 101, "code": 2645301, "team_h": 4, "team_a": 6, "kickoff_time": "2026-08-22T16:30:00Z"},
)
#: Every player's 90 minutes, and what FPL says they are worth.
MINUTES, APPEARANCE = 90, 2
#: The owner's gameweek: the eleven starters' 2 each, and the captain's armband for 2 more; and
#: once FPL has checked it, one defender's bonus point.
OWNER_POINTS = 24
CHECKED_POINTS = OWNER_POINTS + 1
#: Everything after ingest: the run `pipeline.yml` does for any trigger.
RUN = ["transform", "quality", "forecast", "optimise", "week", "publish"]


def _json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class World:
    """What the game says at one moment: the stage of GW1, read by every mocked endpoint."""

    def __init__(self) -> None:
        self.stage = "before"  # before | finished | checked
        self.bootstrap = _json("bootstrap_static.json")
        self.summaries = _json("element_summary.json")
        positions = {t["id"]: t["singular_name_short"] for t in self.bootstrap["element_types"]}
        pool = pd.DataFrame(
            {
                "player_id": e["id"],
                "position": positions[e["element_type"]],
                "team_id": e["team"],
                "price": e["now_cost"] / 10,
            }
            for e in sorted(self.bootstrap["elements"], key=lambda e: e["now_cost"])
        )
        self.squad = legal_declaration(pool)
        # The owner's team: the declared squad, the first eleven in play (a 4-4-2), a forward the
        # captain and a midfielder his deputy.
        held = {pick.player_id for pick in self.squad}
        by_position = {
            position: [int(i) for i in pool[pool["position"] == position]["player_id"] if i in held]
            for position in ("GKP", "DEF", "MID", "FWD")
        }
        self.starting = (
            by_position["GKP"][:1]
            + by_position["DEF"][:4]
            + by_position["MID"][:4]
            + by_position["FWD"][:2]
        )
        self.bench = sorted(held - set(self.starting))
        self.captain, self.vice = by_position["FWD"][0], by_position["MID"][0]
        #: The defender FPL's check gives a bonus point.
        self.corrected = by_position["DEF"][0]

    @property
    def played(self) -> bool:
        return self.stage != "before"

    @property
    def owner_points(self) -> int:
        return CHECKED_POINTS if self.stage == "checked" else OWNER_POINTS

    def bonus(self, element_id: int) -> int:
        return int(self.stage == "checked" and element_id == self.corrected)

    def points(self, element_id: int) -> int:
        return APPEARANCE + self.bonus(element_id)

    # --- the game ---------------------------------------------------------------------------

    def bootstrap_static(self) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(json.dumps(self.bootstrap))
        first, second = payload["events"][:2]
        first.update(
            finished=self.played,
            data_checked=self.stage == "checked",
            is_next=not self.played,
            is_current=self.played,
        )
        second["is_next"] = self.played
        return payload

    def fixtures(self) -> list[dict[str, Any]]:
        recorded = _json("fixtures.json")
        extra = [{**recorded[0], **fixture, "event": GW} for fixture in EXTRA_FIXTURES]
        rows = [*recorded, *extra]
        for row in rows:
            if row["event"] == GW:
                row.update(
                    started=self.played,
                    finished_provisional=self.played,
                    finished=self.played,
                    minutes=MINUTES if self.played else 0,
                    team_h_score=1 if self.played else None,
                    team_a_score=0 if self.played else None,
                )
        return rows

    def gameweek_fixtures(self) -> dict[int, dict[str, Any]]:
        """Each club's GW1 fixture, from its side."""
        by_club: dict[int, dict[str, Any]] = {}
        for fixture in self.fixtures():
            if fixture["event"] == GW:
                by_club[fixture["team_h"]] = {
                    **fixture,
                    "opponent": fixture["team_a"],
                    "home": True,
                }
                by_club[fixture["team_a"]] = {
                    **fixture,
                    "opponent": fixture["team_h"],
                    "home": False,
                }
        return by_club

    def element_summary(self, element_id: str) -> dict[str, Any]:
        summary: dict[str, Any] = json.loads(json.dumps(self.summaries[element_id]))
        if not self.played:
            return summary
        element = next(e for e in self.bootstrap["elements"] if str(e["id"]) == element_id)
        fixture = self.gameweek_fixtures()[element["team"]]
        counts = [
            "assists",
            "clean_sheets",
            "own_goals",
            "penalties_saved",
            "penalties_missed",
            "yellow_cards",
            "red_cards",
            "saves",
            "bps",
        ]
        summary["history"] = [
            {
                "element": element["id"],
                "fixture": fixture["id"],
                "opponent_team": fixture["opponent"],
                "was_home": fixture["home"],
                "kickoff_time": fixture["kickoff_time"],
                "round": GW,
                "minutes": MINUTES,
                "starts": 1,
                "goals_scored": 0,
                "goals_conceded": 1,
                "bonus": self.bonus(element["id"]),
                "total_points": self.points(element["id"]),
                "value": element["now_cost"],
                "selected": 1000,
                **dict.fromkeys(counts, 0),
            }
        ]
        return summary

    def event_live(self) -> dict[str, Any]:
        if not self.played:
            return {"elements": []}
        clubs = self.gameweek_fixtures()
        return {
            "elements": [
                {
                    "id": e["id"],
                    "stats": {
                        "minutes": MINUTES,
                        "total_points": self.points(e["id"]),
                        "bonus": self.bonus(e["id"]),
                        "bps": 20,
                    },
                    "explain": [
                        {
                            "fixture": clubs[e["team"]]["id"],
                            "stats": [
                                {"identifier": "minutes", "points": APPEARANCE, "value": MINUTES},
                                *(
                                    [{"identifier": "bonus", "points": 1, "value": 1}]
                                    if self.bonus(e["id"])
                                    else []
                                ),
                            ],
                        }
                    ],
                }
                for e in self.bootstrap["elements"]
            ]
        }

    # --- the owner ---------------------------------------------------------------------------

    def picks(self) -> dict[str, Any] | None:
        """The owner's GW1 team. Public from the deadline; FPL's own figures in it are the
        deadline's (nothing scored) until the gameweek is checked."""
        if self.stage == "before":
            return None
        checked = self.stage == "checked"
        return {
            "active_chip": None,
            "entry_history": {
                "event": GW,
                "points": self.owner_points if checked else 0,
                "total_points": self.owner_points if checked else 0,
                "event_transfers_cost": 0,
            },
            "picks": [
                {
                    "element": element,
                    "position": slot,
                    "multiplier": 0
                    if element in self.bench
                    else (2 if element == self.captain else 1),
                    "is_captain": element == self.captain,
                    "is_vice_captain": element == self.vice,
                }
                for slot, element in enumerate([*self.starting, *self.bench], start=1)
            ],
        }

    def history(self) -> dict[str, Any]:
        current = []
        if self.played:
            current = [
                {
                    "event": GW,
                    "points": self.owner_points,
                    "total_points": self.owner_points,
                    "rank": 1000,
                    "overall_rank": 1000,
                    "bank": 5,
                    "value": 1000,
                    "event_transfers": 0,
                    "event_transfers_cost": 0,
                    "points_on_bench": 8,
                }
            ]
        return {"current": current, "past": [], "chips": []}


def _json_response(build: Callable[[], Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(200, json=build())


#: The models these walks advise and evaluate: the champion, which plans, the engine and one that
#: advises a gameweek at a time. What is asserted is the evaluation, the log and ``live.json``,
#: which every model reaches the same way; the other published models only multiplied each run's
#: forecasts and solves (ORC-09's test budget).
WALKED = {"c3", "c3_e2", "engine"}


@pytest.fixture(autouse=True)
def _two_models(monkeypatch: pytest.MonkeyPatch) -> None:
    walked = tuple(s for s in published_strategies() if s.id in WALKED)
    assert {s.id for s in walked} == WALKED
    for stage in (week_stage, publish_stage):
        monkeypatch.setattr(stage, "published_strategies", lambda: walked)


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def api(world: World) -> Iterator[respx.MockRouter]:
    """The FPL API as ``world`` has it now, whichever stage the test has moved it to."""
    base = FplApiAdapter.base_url

    def picks(_request: httpx.Request) -> httpx.Response:
        body = world.picks()
        if body is None:
            return httpx.Response(404, json={"detail": "Not found."})
        return httpx.Response(200, json=body)

    def summary(request: httpx.Request) -> httpx.Response:
        element_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        return httpx.Response(200, json=world.element_summary(element_id))

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{base}/bootstrap-static/").mock(
            side_effect=_json_response(world.bootstrap_static)
        )
        mock.get(f"{base}/fixtures/").mock(side_effect=_json_response(world.fixtures))
        mock.get(f"{base}/team/set-piece-notes/").mock(
            return_value=httpx.Response(200, json=_json("set_piece_notes.json"))
        )
        mock.get(url__regex=rf"{base}/element-summary/\d+/").mock(side_effect=summary)
        mock.get(url__regex=rf"{base}/event/\d+/live/").mock(
            side_effect=_json_response(world.event_live)
        )
        mock.get(url__regex=rf"{base}/entry/\d+/event/\d+/picks/").mock(side_effect=picks)
        mock.get(url__regex=rf"{base}/entry/\d+/transfers/").mock(
            return_value=httpx.Response(200, json=[])
        )
        mock.get(url__regex=rf"{base}/entry/\d+/history/").mock(
            side_effect=_json_response(world.history)
        )
        mock.get(url__regex=rf"{base}/entry/\d+/$").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": TEST_ENTRY_ID,
                    "name": "Test Entry",
                    "started_event": 1,
                    "current_event": None,
                    "last_deadline_bank": 5,
                    "last_deadline_value": 1000,
                    "last_deadline_total_transfers": 0,
                    "summary_overall_points": None,
                    "summary_overall_rank": None,
                },
            )
        )
        yield mock


def _configure(world: World, config_file: Path) -> None:
    """The recorded league's gate sizes (two fixtures more), and the declared squad the owner's
    GW1 picks are."""
    override = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    override["quality"]["expected_fixtures"] = 14
    # Two gameweeks of plan, not five: nothing here reads the plan, and its solves were most of
    # each run's decide time (ORC-09's test budget).
    override.setdefault("decision", {})["horizon"] = {"gameweeks": 2}
    override["entry"] = {"declared_squad": [p.model_dump() for p in world.squad]}
    config_file.write_text(yaml.safe_dump(override), encoding="utf-8")


def _published(data_dir: Path, name: str) -> Any:
    return json.loads((data_dir / "web" / "v1" / name).read_text(encoding="utf-8"))


def _evaluation_path(data_dir: Path) -> Path:
    return data_dir / "ledger" / "evaluation" / f"entry-{TEST_ENTRY_ID}" / f"gw{GW:02d}.json"


def _summary_requests(api: respx.MockRouter) -> int:
    return sum("/element-summary/" in str(call.request.url) for call in api.calls)


def test_the_fast_cadence_wants_the_per_player_rows_only_once_a_gameweek_is_checked() -> None:
    """LIVE-07: the one resource off the fast path that the check brings in, and only the check."""
    adapter = FplApiAdapter.__new__(FplApiAdapter)  # `wants` reads the declarations alone
    fast = IngestRequest(run_id="r", fast_path_only=True)
    assert not adapter.wants("element_summary", fast)
    assert not adapter.wants("element_summary", fast, in_play=True)
    assert adapter.wants("element_summary", fast, checked=True)
    for resource in ("event_live", "league_standings"):
        assert not adapter.wants(resource, fast, checked=True)
    assert adapter.wants("element_summary", IngestRequest(run_id="r"))


def _bonus(rows: pd.DataFrame, player_id: int) -> int:
    """The bonus silver holds for a player's GW1 row."""
    [row] = rows[(rows["gameweek"] == GW) & (rows["player_id"] == player_id)].itertuples()
    return as_int(row.bonus)


def _guard(capsys: pytest.CaptureFixture[str], data_dir: Path, *args: str) -> str:
    capsys.readouterr()
    argv = ["--data-dir", str(data_dir), "--now", CHECKED, "--decide", "pipeline", *args]
    assert schedule_main(argv) == 0
    return capsys.readouterr().out.strip()


def test_a_data_checked_gameweek_is_evaluated_by_the_run_its_change_started(
    tmp_path_factory: pytest.TempPathFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: dict[str, str],
    world: World,
    api: respx.MockRouter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A. Before the deadline: GW1 was Open and its advice of record was made.
    data_dir = _advised_then_finished(tmp_path_factory, tmp_path, monkeypatch, isolated_env, world)
    cli = ["--data-dir", str(data_dir)]
    assert (data_dir / "ledger" / "advice" / f"gw{GW:02d}.json").exists()
    assert not _evaluation_path(data_dir).exists()

    # B. Both matches played and FPL has marked the gameweek finished. A full ingest (the weekly
    # refresh of the per-player rows lands here), and the run it starts. Everything an evaluation
    # needs is in silver, and still nothing is evaluated: the gameweek is Playing until FPL has
    # checked it (ORC-01).
    assert main([*cli, "run", "--only", *RUN]) == EXIT_OK
    silver = data_dir / "silver"
    season = next(silver.glob("season=*")).name.removeprefix("season=")
    tables = SilverTables(
        read_table(silver, season, Table.GAMEWEEK), read_table(silver, season, Table.FIXTURE)
    )
    [first, *_] = season_states(tables, (), pd.Timestamp(FINISHED).to_pydatetime())
    assert (first.gameweek, first.phase, first.due) == (GW, Phase.PLAYING, Due.INGEST)
    rows = read_table(silver, season, Table.PLAYER_GAMEWEEK)
    assert (rows["gameweek"] == GW).sum() == 92, "the evidence is all in"
    assert _bonus(rows, world.corrected) == 0
    assert not _evaluation_path(data_dir).exists()
    assert _published(data_dir, "live.json")["status"] == "complete"
    assert not (data_dir / "web" / "v1" / "log.json").exists(), "no season log without a gameweek"

    # Hours on, still unchecked: a fast firing moves nothing and fetches no per-player rows.
    monkeypatch.setenv("FPL_DOF_AS_OF", "2026-08-24T14:00:00+00:00")
    swept = _summary_requests(api)
    assert main([*cli, "ingest", "--fast"]) == EXIT_OK
    assert _summary_requests(api) == swept
    changes = json.loads((data_dir / "runs" / "changes.json").read_text(encoding="utf-8"))
    assert changes["kinds"] == []

    # C. FPL checks the gameweek (and gives a defender a bonus point). The fast ingest sees the
    # flag flip and moves `results`, nothing else...
    world.stage = "checked"
    monkeypatch.setenv("FPL_DOF_AS_OF", CHECKED)
    assert main([*cli, "ingest", "--fast"]) == EXIT_OK
    changes = json.loads((data_dir / "runs" / "changes.json").read_text(encoding="utf-8"))
    assert changes["kinds"] == ["results"] and changes["gameweek"] == 2
    # ...the guard lets the run it starts go ahead...
    sent = ["--trigger", "change", "--kinds", "results", "--gameweek", "2"]
    assert _guard(capsys, data_dir, *sent) == "true"
    # ...and that run, which ingests nothing of its own, evaluates the gameweek.
    monkeypatch.setenv("FPL_DOF_TRIGGER", "change:results")
    capsys.readouterr()
    assert main([*cli, "run", "--only", *RUN]) == EXIT_OK
    [run_id] = re.findall(r"run (\S+) succeeded", capsys.readouterr().out)
    manifest = json.loads((data_dir / "runs" / run_id / "manifest.json").read_text("utf-8"))
    assert "ingest" not in manifest["requested_stages"]

    # The run the change started wrote the evaluation, on the final rows...
    rows = read_table(silver, season, Table.PLAYER_GAMEWEEK)
    assert _bonus(rows, world.corrected) == 1, "the fast ingest fetched the rows FPL checked"
    evaluation = json.loads(_evaluation_path(data_dir).read_text(encoding="utf-8"))
    assert (evaluation["gameweek"], evaluation["run_id"]) == (GW, run_id)
    assert evaluation["entry_id"] == TEST_ENTRY_ID
    assert evaluation["log"]["score"]["points"] == CHECKED_POINTS
    assert {"c3", "c3_e2", "engine"} <= set(evaluation["strategies"])
    # ...the season log holds the gameweek...
    log = _published(data_dir, "log.json")
    assert [row["gameweek"] for row in log["gameweeks"]] == [GW]
    assert log["summary"]["total_points"] == CHECKED_POINTS
    # ...and live.json reads final, the scorer agreeing with FPL's own figure.
    live = _published(data_dir, "live.json")
    assert (live["gameweek"], live["status"], live["provisional"]) == (GW, "final", False)
    [owner] = [team for team in live["teams"] if team["is_owner"]]
    assert owner["live"]["points"] == CHECKED_POINTS and owner["matches_game"] is True

    # Evaluated once: the gameweek is Evaluated now, and the next run's evaluation step, in the
    # week stage, does not judge it again.
    written = _evaluation_path(data_dir).read_bytes()
    assert main([*cli, "run", "--only", "week"]) == EXIT_OK
    assert _evaluation_path(data_dir).read_bytes() == written

    # Swept once: the next fast firing, the gameweek still final until GW2's deadline, neither
    # fetches a summary nor walks the cached ones.
    monkeypatch.setenv("FPL_DOF_AS_OF", "2026-08-25T13:00:00+00:00")
    swept = _summary_requests(api)
    capsys.readouterr()
    assert main([*cli, "ingest", "--fast"]) == EXIT_OK
    assert _summary_requests(api) == swept
    assert _ingested(capsys, data_dir)["fpl.element_summary"] == 0


def test_a_results_change_starts_a_run_with_no_gameweek_open(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The season's last gameweek has no Open successor; the run its data-check starts must still
    go ahead to evaluate it (`dispatch_decision`), where a price move would be refused."""
    frame = pd.DataFrame(
        [
            {
                "gameweek": gameweek,
                "name": f"Gameweek {gameweek}",
                "deadline_time": pd.Timestamp(deadline),
                "finished": True,
                "is_next": False,
                "data_checked": True,
            }
            for gameweek, deadline in ((37, "2027-05-15T10:00:00Z"), (38, "2027-05-23T13:30:00Z"))
        ]
    )
    write_table(tmp_path / "silver", SEASON, Table.GAMEWEEK, frame)
    argv = ["--data-dir", str(tmp_path), "--now", "2027-05-26T12:00:00Z", "--decide", "pipeline"]

    def decide(*args: str) -> str:
        capsys.readouterr()
        assert schedule_main([*argv, "--trigger", "change", *args]) == 0
        return capsys.readouterr().out.strip()

    assert decide("--kinds", "results") == "true"
    assert decide("--kinds", "prices") == "false"


#: GW2's deadline (28 August 17:30) has passed when FPL checks GW1: a Monday match, a Tuesday
#: deadline. The live gameweek is GW2 by then, in play and unchecked.
LATE_CHECK = "2026-08-28T19:00:00+00:00"


def _ingested(capsys: pytest.CaptureFixture[str], data_dir: Path) -> dict[str, Any]:
    """The ingest stage's metrics from the run whose output ``capsys`` holds."""
    [run_id] = re.findall(r"run (\S+) succeeded", capsys.readouterr().out)
    manifest = json.loads((data_dir / "runs" / run_id / "manifest.json").read_text("utf-8"))
    [stage] = [s for s in manifest["stages"] if s["name"] == "ingest"]
    metrics: dict[str, Any] = stage["metrics"]
    return metrics


def _advised_then_finished(
    tmp_path_factory: pytest.TempPathFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: dict[str, str],
    world: World,
) -> Path:
    """A and B of the module docstring: GW1 advised before its deadline, then a full ingest once
    FPL has marked it finished, not checked. The data root, a copy of the one every walk here
    starts from, built once a test run (ORC-09's test budget); the world and the clock at B."""
    monkeypatch.setenv("FPL_DOF_CONFIG_FILE", isolated_env["FPL_DOF_CONFIG_FILE"])
    monkeypatch.setenv("FPL_DOF_TEAM_ID", str(TEST_ENTRY_ID))
    _configure(world, Path(isolated_env["FPL_DOF_CONFIG_FILE"]))
    # The ledger closes by the real clock (ORC-03); stood at the moment the advice was given.
    pinned = pd.Timestamp(BEFORE_DEADLINE).to_pydatetime()
    advice, predictions = record_advice, record_predictions
    monkeypatch.setattr(
        week_stage, "record_advice", lambda *a, now, **k: advice(*a, now=pinned, **k)
    )
    monkeypatch.setattr(
        week_stage, "record_predictions", lambda *a, now, **k: predictions(*a, now=pinned, **k)
    )

    def build(data_dir: Path) -> None:
        cli = ["--data-dir", str(data_dir)]
        monkeypatch.setenv("FPL_DOF_AS_OF", BEFORE_DEADLINE)
        assert main([*cli, "run"]) == EXIT_OK
        world.stage = "finished"
        monkeypatch.setenv("FPL_DOF_AS_OF", FINISHED)
        assert main([*cli, "ingest", "--force-refresh"]) == EXIT_OK

    template = built_once(tmp_path_factory, "gw1-advised-then-finished", build)
    world.stage = "finished"
    monkeypatch.setenv("FPL_DOF_AS_OF", FINISHED)
    data_dir = tmp_path / "data"
    shutil.copytree(template, data_dir)
    return data_dir


def test_a_gameweek_checked_after_the_next_deadline_is_evaluated_on_its_final_rows(
    tmp_path_factory: pytest.TempPathFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: dict[str, str],
    world: World,
    api: respx.MockRouter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The sweep keys on the gameweek FPL checked, not on the live one. GW1 is checked after GW2's
    deadline, so the live gameweek is GW2, unchecked; the fast ingest that sees GW1's check still
    fetches the per-player rows that predate it, once, and the run its `results` change starts
    evaluates GW1 on the corrected figure rather than storing the pre-check one for good. A fast
    firing after that walks no summary at all."""
    data_dir = _advised_then_finished(tmp_path_factory, tmp_path, monkeypatch, isolated_env, world)
    cli = ["--data-dir", str(data_dir)]

    world.stage = "checked"
    monkeypatch.setenv("FPL_DOF_AS_OF", LATE_CHECK)
    swept = _summary_requests(api)
    assert main([*cli, "ingest", "--fast"]) == EXIT_OK
    changes = json.loads((data_dir / "runs" / "changes.json").read_text(encoding="utf-8"))
    assert changes["kinds"] == ["results"]
    assert _summary_requests(api) - swept == len(world.bootstrap["elements"]), "swept, once"

    monkeypatch.setenv("FPL_DOF_TRIGGER", "change:results")
    assert main([*cli, "run", "--only", *RUN]) == EXIT_OK
    silver = data_dir / "silver"
    season = next(silver.glob("season=*")).name.removeprefix("season=")
    rows = read_table(silver, season, Table.PLAYER_GAMEWEEK)
    assert _bonus(rows, world.corrected) == 1, "the rows FPL corrected at the check"
    evaluation = json.loads(_evaluation_path(data_dir).read_text(encoding="utf-8"))
    assert evaluation["gameweek"] == GW
    assert evaluation["log"]["score"]["points"] == CHECKED_POINTS

    # An hour on: no request, and no walk over the cached summaries either.
    monkeypatch.setenv("FPL_DOF_AS_OF", "2026-08-28T20:00:00+00:00")
    swept = _summary_requests(api)
    capsys.readouterr()
    assert main([*cli, "ingest", "--fast"]) == EXIT_OK
    assert _summary_requests(api) == swept
    assert _ingested(capsys, data_dir)["fpl.element_summary"] == 0


#: Thirty minutes before GW2's deadline (28 August 17:30): inside the 45-minute freeze (R-09).
IN_FREEZE = "2026-08-28T17:00:00+00:00"
#: The slow ingest's daily refresh the next morning, and the `schedule` run it dispatches.
DAILY_REFRESH = "2026-08-29T03:00:00+00:00"


def test_a_check_inside_the_freeze_is_evaluated_by_the_next_run_outside_it(
    tmp_path_factory: pytest.TempPathFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_env: dict[str, str],
    world: World,
    api: respx.MockRouter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FPL checks GW1 inside GW2's freeze. The `results` run its change dispatches is refused,
    the freeze binding every trigger, and no later fast firing moves `results` again: the change
    is spent. The gameweek is still Finished and unevaluated, so it is due EVALUATE in any run
    (ORC-05): the next one outside the freeze, at the latest the daily refresh's `schedule` run,
    evaluates it on the rows FPL checked."""
    data_dir = _advised_then_finished(tmp_path_factory, tmp_path, monkeypatch, isolated_env, world)
    cli = ["--data-dir", str(data_dir)]

    def guard(now: str, *args: str) -> str:
        capsys.readouterr()
        argv = ["--data-dir", str(data_dir), "--now", now, "--decide", "pipeline", *args]
        assert schedule_main(argv) == 0
        return capsys.readouterr().out.strip()

    world.stage = "checked"
    monkeypatch.setenv("FPL_DOF_AS_OF", IN_FREEZE)
    assert main([*cli, "ingest", "--fast"]) == EXIT_OK
    changes = json.loads((data_dir / "runs" / "changes.json").read_text(encoding="utf-8"))
    assert changes["kinds"] == ["results"]
    sent = ["--trigger", "change", "--kinds", "results", "--gameweek", str(changes["gameweek"])]
    assert guard(IN_FREEZE, *sent) == "false", "the freeze binds a results run too"

    monkeypatch.setenv("FPL_DOF_AS_OF", "2026-08-28T18:00:00+00:00")
    assert main([*cli, "ingest", "--fast"]) == EXIT_OK
    changes = json.loads((data_dir / "runs" / "changes.json").read_text(encoding="utf-8"))
    assert changes["kinds"] == [], "the check's change is spent"
    assert not _evaluation_path(data_dir).exists()

    monkeypatch.setenv("FPL_DOF_AS_OF", DAILY_REFRESH)
    assert main([*cli, "ingest"]) == EXIT_OK
    assert guard(DAILY_REFRESH, "--trigger", "schedule") == "true"
    monkeypatch.setenv("FPL_DOF_TRIGGER", "schedule")
    capsys.readouterr()
    assert main([*cli, "run", "--only", *RUN]) == EXIT_OK
    [run_id] = re.findall(r"run (\S+) succeeded", capsys.readouterr().out)
    evaluation = json.loads(_evaluation_path(data_dir).read_text(encoding="utf-8"))
    assert (evaluation["gameweek"], evaluation["run_id"]) == (GW, run_id)
    assert evaluation["log"]["score"]["points"] == CHECKED_POINTS


def test_a_fresh_bronze_whose_first_capture_shows_the_check_sweeps_once(
    tmp_path: Path, world: World, api: respx.MockRouter
) -> None:
    """With no bootstrap capture before it there is no telling when the check came, so the first
    capture counts as new and the fast ingest sweeps the summaries (`_newly_checked`): a sweep of
    cached ones is cheap, and a missed one is an evaluation stored on the rows before the check.
    The firing after it reads that capture, sees the check is not new, and fetches none."""
    world.stage = "checked"
    http = HttpConfig(
        rate_limit=RateLimitConfig(requests_per_second=1000.0),
        retry=RetryConfig(max_attempts=1, backoff_base_seconds=0.001),
    )
    players = len(world.bootstrap["elements"])

    def fast(at: str) -> IngestRequest:
        return IngestRequest(run_id="r", now=pd.Timestamp(at).to_pydatetime(), fast_path_only=True)

    bronze = BronzeStore(tmp_path / "bronze")
    with Fetcher(config=http, bronze=bronze, run_id="r", sleep=lambda _s: None) as fetcher:
        adapter = FplApiAdapter(fetcher)
        report = adapter.ingest(fast(CHECKED))
        assert report.resources["element_summary"] == players
        assert _summary_requests(api) == players, "swept, once"

        report = adapter.ingest(fast("2026-08-25T13:00:00+00:00"))
        assert len(list(bronze.resource_dir("fpl", "bootstrap_static").rglob("*.json.gz"))) == 2
        assert report.resources["element_summary"] == 0
        assert _summary_requests(api) == players
