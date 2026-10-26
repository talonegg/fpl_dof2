"""The change manifest (ORC-02, DL-94 item 4): each kind that starts a run, on fixture bronze, and
nothing else; and the `results` kind over a simulated gameweek in play (LIVE-02)."""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
import respx

from conftest import FIXTURES
from fpl_dof.cli import EXIT_OK, main
from fpl_dof.config import load_config
from fpl_dof.config.models import ScheduleConfig
from fpl_dof.gameweek import matchdays
from fpl_dof.sources import (
    BronzeStore,
    ChangeContext,
    Fetcher,
    SourceAdapter,
    before_ingest,
    changed_kinds,
)
from fpl_dof.sources.fdcouk.adapter import FdcoukAdapter
from fpl_dof.sources.fpl.adapter import FplApiAdapter

T0 = dt.datetime(2026, 8, 15, 12, 0, tzinfo=dt.UTC)
#: GW1 is Open: its deadline, then GW2's.
WINDOW = (
    dt.datetime(2026, 8, 21, 17, 30, tzinfo=dt.UTC),
    dt.datetime(2026, 8, 28, 17, 30, tzinfo=dt.UTC),
)
ODDS_HEAD = "Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A\n"
GW1_MATCH = "E0,22/08/2026,15:00,Arsenal,Chelsea,2.10,3.40,3.60\n"
GW2_MATCH = "E0,29/08/2026,15:00,Everton,Fulham,2.50,3.20,2.90\n"


def _json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _bronze(tmp_path: Path, odds: str = ODDS_HEAD) -> tuple[BronzeStore, dict[str, Any]]:
    """Bronze as a restored `data` branch leaves it: one capture of each watched resource."""
    bronze = BronzeStore(tmp_path / "bronze")
    payloads = {
        ("fpl", "bootstrap_static", "all"): json.dumps(_json("bootstrap_static.json")).encode(),
        ("fpl", "fixtures", "all"): json.dumps(_json("fixtures.json")).encode(),
        ("fdcouk", "fixtures", "upcoming"): odds.encode("latin-1"),
    }
    for (source, resource, key), payload in payloads.items():
        _write(bronze, source, resource, key, payload, T0)
    return bronze, {"bootstrap": _json("bootstrap_static.json"), "fixtures": _json("fixtures.json")}


def _write(
    bronze: BronzeStore, source: str, resource: str, key: str, payload: bytes, at: dt.datetime
) -> None:
    bronze.write(
        payload,
        source=source,
        source_version="1",
        resource=resource,
        key=key,
        url="u",
        http_status=200,
        now=at,
    )


def _kinds(bronze: BronzeStore, ingest: Callable[[BronzeStore], None]) -> list[str]:
    config, _ = load_config(environ={}, local_override=None)
    with Fetcher(config=config.http, bronze=bronze) as fetcher:
        adapters: list[SourceAdapter] = [FplApiAdapter(fetcher), FdcoukAdapter(fetcher)]
        before = before_ingest(bronze, adapters)
        ingest(bronze)
        return changed_kinds(bronze, adapters, before, ChangeContext.of(WINDOW, config.schedule))


LATER = T0 + dt.timedelta(hours=1)


def _bootstrap(
    edit: Callable[[dict[str, Any]], None], part: str = "elements"
) -> Callable[[BronzeStore], None]:
    def ingest(bronze: BronzeStore) -> None:
        payload = copy.deepcopy(_json("bootstrap_static.json"))
        edit(payload[part][0])
        _write(bronze, "fpl", "bootstrap_static", "all", json.dumps(payload).encode(), LATER)

    return ingest


def _fixtures(edit: Callable[[dict[str, Any]], None]) -> Callable[[BronzeStore], None]:
    def ingest(bronze: BronzeStore) -> None:
        payload = copy.deepcopy(_json("fixtures.json"))
        edit(payload[0])
        _write(bronze, "fpl", "fixtures", "all", json.dumps(payload).encode(), LATER)

    return ingest


def _odds(text: str) -> Callable[[BronzeStore], None]:
    return lambda bronze: _write(
        bronze, "fdcouk", "fixtures", "upcoming", text.encode("latin-1"), LATER
    )


@pytest.mark.parametrize(
    ("ingest", "kinds"),
    [
        (_bootstrap(lambda e: e.update(now_cost=e["now_cost"] + 1)), ["prices"]),
        (_bootstrap(lambda e: e.update(status="i")), ["status"]),
        (_bootstrap(lambda e: e.update(news="Hamstring - 75% chance of playing")), ["status"]),
        (
            _bootstrap(lambda e: e.update(selected_by_percent="99.9")),
            [],
        ),  # ownership starts nothing
        (_fixtures(lambda f: f.update(kickoff_time="2026-08-22T11:30:00Z")), ["fixtures"]),
        (_fixtures(lambda f: f.update(event=None)), ["fixtures"]),  # postponed out of its gameweek
        (_fixtures(lambda f: f.update(team_h_difficulty=5)), []),
        (_odds(ODDS_HEAD + GW1_MATCH), ["odds"]),  # the first odds for the Open gameweek
        (_odds(ODDS_HEAD + GW2_MATCH), []),  # a later gameweek's odds are not the Open one's
        # LIVE-02: a match's bonus confirmed is its matchday done; a start or a goal is nothing.
        (_fixtures(lambda f: f.update(finished=True)), ["results"]),
        (_fixtures(lambda f: f.update(started=True, minutes=30, team_h_score=1)), []),
        (_fixtures(lambda f: f.update(finished_provisional=True, minutes=90)), []),
        (_bootstrap(lambda e: e.update(finished=True), "events"), ["results"]),
        (_bootstrap(lambda e: e.update(data_checked=True), "events"), ["results"]),
        (_bootstrap(lambda e: e.update(most_captained=7), "events"), []),
    ],
    ids=[
        "price",
        "status",
        "news",
        "ownership",
        "kickoff",
        "gameweek",
        "difficulty",
        "odds",
        "later-odds",
        "bonus",
        "goal",
        "full-time",
        "gameweek-finished",
        "data-checked",
        "gameweek-other",
    ],
)
def test_each_kind_produces_its_entry_and_nothing_else(
    tmp_path: Path, ingest: Callable[[BronzeStore], None], kinds: list[str]
) -> None:
    bronze, _ = _bronze(tmp_path)
    assert _kinds(bronze, ingest) == kinds


def test_a_price_moving_on_a_match_already_priced_is_not_a_first(tmp_path: Path) -> None:
    bronze, _ = _bronze(tmp_path, ODDS_HEAD + GW1_MATCH)
    assert _kinds(bronze, _odds(ODDS_HEAD + GW1_MATCH.replace("2.10", "1.95"))) == []


def test_no_change_and_an_identical_recapture_move_nothing(tmp_path: Path) -> None:
    bronze, payloads = _bronze(tmp_path)
    assert _kinds(bronze, lambda b: None) == []
    same = json.dumps(payloads["bootstrap"]).encode()
    assert _kinds(bronze, lambda b: _write(b, "fpl", "bootstrap_static", "all", same, LATER)) == []


def test_two_kinds_at_once_are_both_named_in_order(tmp_path: Path) -> None:
    bronze, _ = _bronze(tmp_path)

    def both(b: BronzeStore) -> None:
        _bootstrap(lambda e: e.update(status="d", now_cost=e["now_cost"] - 1))(b)
        _odds(ODDS_HEAD + GW1_MATCH)(b)

    assert _kinds(bronze, both) == ["prices", "status", "odds"]


def test_the_ingest_stage_writes_the_manifest_the_workflows_dispatch_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_fpl_api: respx.MockRouter
) -> None:
    data_dir = tmp_path / "data"
    changes = data_dir / "runs" / "changes.json"
    assert main(["--data-dir", str(data_dir), "ingest", "--fast"]) == EXIT_OK
    first = json.loads(changes.read_text(encoding="utf-8"))
    assert first["kinds"] == [] and first["gameweek"] == 1  # nothing earlier to compare with

    moved = _json("bootstrap_static.json")
    moved["elements"][0]["now_cost"] += 1
    recorded_fpl_api.get(f"{FplApiAdapter.base_url}/bootstrap-static/").mock(
        return_value=httpx.Response(200, json=moved)
    )
    monkeypatch.setenv("FPL_DOF_AS_OF", "2026-08-15T14:00:00+00:00")  # past the bootstrap's TTL
    assert main(["--data-dir", str(data_dir), "ingest", "--fast"]) == EXIT_OK
    second = json.loads(changes.read_text(encoding="utf-8"))
    assert second["kinds"] == ["prices"] and second["gameweek"] == 1


# --- results: matchdays and completion (LIVE-02) ----------------------------------------------
#
# A simulated gameweek in play, fetched by the fast ingest's hourly firings. Each match starts,
# scores and reaches full time (none of which moves anything) and has its bonus confirmed, FPL's
# fixture `finished`, a while after. Dates are after the clocks go back, so UK time is UTC here; the
# zone itself is tested on the pure rule in test_matchdays.py.

SCHEDULE = ScheduleConfig()
BONUS_AFTER = dt.timedelta(hours=2, minutes=40)  # a match, then FPL confirming its bonus
FIRING_MINUTE = SCHEDULE.fast_ingest_cron_minute


def _utc(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)


def _match(
    fixture_id: int,
    kickoff: str | None,
    *,
    bonus: dt.timedelta | None = BONUS_AFTER,
    event: int | None = 9,
) -> dict[str, Any]:
    """One fixture: its kick-off (UTC) and how long after it FPL confirms its bonus, ``None`` for a
    match whose bonus never comes."""
    return {
        "id": fixture_id,
        "event": event,
        "kickoff_time": kickoff,
        "team_h": fixture_id,
        "team_a": fixture_id + 10,
        "team_h_difficulty": 3,
        "team_a_difficulty": 3,
        "bonus_after": bonus,
    }


def _as_fetched(matches: list[dict[str, Any]], at: dt.datetime) -> bytes:
    """The fixtures endpoint as a firing at ``at`` reads it: started, scoring, at full time, then
    finished once the bonus is in."""
    payload = []
    for match in matches:
        fixture = {k: v for k, v in match.items() if k != "bonus_after"}
        kickoff = None if match["kickoff_time"] is None else _utc(match["kickoff_time"][:-1])
        played = (
            0 if kickoff is None else max(0, min(90, int((at - kickoff).total_seconds() // 60)))
        )
        bonus = match["bonus_after"]
        fixture |= {
            "started": played > 0,
            "minutes": played,
            "team_h_score": None if played == 0 else played // 30,
            "team_a_score": None if played == 0 else played // 45,
            "finished_provisional": played >= 90,
            "finished": kickoff is not None and bonus is not None and at >= kickoff + bonus,
        }
        payload.append(fixture)
    return json.dumps(payload).encode()


def _bootstrap_for(finished: bool, data_checked: bool) -> bytes:
    payload = copy.deepcopy(_json("bootstrap_static.json"))
    payload["events"] = [
        {
            "id": 9,
            "name": "Gameweek 9",
            "deadline_time": "2026-10-30T18:30:00Z",
            "finished": finished,
            "is_next": False,
            "data_checked": data_checked,
        }
    ]
    return json.dumps(payload).encode()


def _hourly(start: str, end: str) -> list[dt.datetime]:
    """The fast ingest's firings from ``start`` to ``end`` (UTC), hourly at its cron minute."""
    first, last = _utc(start), _utc(end)
    moment = first.replace(minute=FIRING_MINUTE)
    firings = []
    while moment <= last:
        firings.append(moment)
        moment += dt.timedelta(hours=1)
    return firings


def _moves(
    tmp_path: Path,
    matches: list[dict[str, Any]],
    firings: list[dt.datetime],
    *,
    flags: Callable[[dt.datetime], tuple[bool, bool]] | None = None,
) -> dict[dt.datetime, list[str]]:
    """Each firing's change manifest, ingest after ingest on one bronze, as CI's `data` branch
    carries it from firing to firing. ``flags`` is the gameweek's finished and data-checked at a
    firing; without it, only the fixtures are fetched."""
    bronze = BronzeStore(tmp_path / "bronze")
    context = ChangeContext.of(None, SCHEDULE)  # no gameweek Open: results needs none
    config, _ = load_config(environ={}, local_override=None)
    manifests: dict[dt.datetime, list[str]] = {}
    with Fetcher(config=config.http, bronze=bronze) as fetcher:
        adapters: list[SourceAdapter] = [FplApiAdapter(fetcher)]
        for at in firings:
            before = before_ingest(bronze, adapters)
            _write(bronze, "fpl", "fixtures", "all", _as_fetched(matches, at), at)
            if flags is not None:
                _write(bronze, "fpl", "bootstrap_static", "all", _bootstrap_for(*flags(at)), at)
            manifests[at] = changed_kinds(bronze, adapters, before, context)
    return manifests


def _results(manifests: dict[dt.datetime, list[str]]) -> list[dt.datetime]:
    """The firings whose manifest moved ``results``; every other firing must have moved nothing."""
    for kinds in manifests.values():
        assert kinds in ([], ["results"]), kinds
    return [at for at, kinds in manifests.items() if kinds]


#: Saturday 31 October 2026: three kick-off times, five matches.
SATURDAY = [
    _match(1, "2026-10-31T12:30:00Z"),
    _match(2, "2026-10-31T15:00:00Z"),
    _match(3, "2026-10-31T15:00:00Z"),
    _match(4, "2026-10-31T15:00:00Z"),
    _match(5, "2026-10-31T17:30:00Z"),
]


def test_a_saturday_of_three_kick_off_times_moves_results_once_after_the_last_bonus(
    tmp_path: Path,
) -> None:
    """Twelve hours of firings through kick-offs, goals and full times move nothing; the first
    firing after the 17:30 match's bonus is confirmed (20:10) moves `results`, and only that one."""
    moves = _results(_moves(tmp_path, SATURDAY, _hourly("2026-10-31T11:00", "2026-11-01T02:00")))
    assert moves == [_utc(f"2026-10-31T21:{FIRING_MINUTE:02d}")]


#: Gameweek 9, Friday to Monday: one matchday a day.
FRIDAY_TO_MONDAY = [
    _match(1, "2026-10-30T20:00:00Z"),
    _match(2, "2026-10-31T12:30:00Z"),
    _match(3, "2026-10-31T15:00:00Z"),
    _match(4, "2026-10-31T17:30:00Z"),
    _match(5, "2026-11-01T14:00:00Z"),
    _match(6, "2026-11-01T16:30:00Z"),
    _match(7, "2026-11-02T20:00:00Z"),
]
FINISHED_AT = _utc("2026-11-03T09:30")
DATA_CHECKED_AT = _utc("2026-11-03T13:30")


def _gameweek_flags(at: dt.datetime) -> tuple[bool, bool]:
    return at >= FINISHED_AT, at >= DATA_CHECKED_AT


def test_a_friday_to_monday_gameweek_moves_results_four_times_then_finished_then_checked(
    tmp_path: Path,
) -> None:
    manifests = _moves(
        tmp_path,
        FRIDAY_TO_MONDAY,
        _hourly("2026-10-30T18:00", "2026-11-03T20:00"),
        flags=_gameweek_flags,
    )
    minute = f"{FIRING_MINUTE:02d}"
    assert _results(manifests) == [
        _utc(f"2026-10-30T23:{minute}"),  # Friday's match, its bonus at 22:40
        _utc(f"2026-10-31T21:{minute}"),  # Saturday's last, at 20:10
        _utc(f"2026-11-01T20:{minute}"),  # Sunday's last, at 19:10
        _utc(f"2026-11-02T23:{minute}"),  # Monday's, at 22:40
        _utc(f"2026-11-03T10:{minute}"),  # the gameweek marked finished
        _utc(f"2026-11-03T14:{minute}"),  # ...and data-checked (LIVE-07's run)
    ]


def test_dropped_firings_move_each_matchday_at_the_next_firing_and_never_twice(
    tmp_path: Path,
) -> None:
    """D-35: GitHub drops firings. Saturday evening's are lost, so the first firing after them
    sees Saturday done and moves it, and Sunday moves on its own later; nothing moves twice."""
    firings = [
        at
        for at in _hourly("2026-10-30T18:00", "2026-11-02T02:00")
        if not _utc("2026-10-31T19:00") <= at <= _utc("2026-11-01T09:30")
    ]
    minute = f"{FIRING_MINUTE:02d}"
    assert _results(_moves(tmp_path, FRIDAY_TO_MONDAY, firings)) == [
        _utc(f"2026-10-30T23:{minute}"),
        _utc(f"2026-11-01T10:{minute}"),  # Saturday, seen at the first firing back
        _utc(f"2026-11-01T20:{minute}"),
    ]


@pytest.mark.parametrize(
    "postponed",
    [
        _match(6, None, event=None, bonus=None),  # postponed: no kick-off, out of the gameweek
        _match(6, "2026-10-31T15:00:00Z", event=None, bonus=None),  # moved out, kick-off kept
        _match(6, None, bonus=None),  # in the gameweek, its kick-off to be confirmed
    ],
    ids=["no-kickoff-no-gameweek", "out-of-the-gameweek", "no-kickoff"],
)
def test_a_postponed_fixture_leaves_its_matchday_done_without_it(
    tmp_path: Path, postponed: dict[str, Any]
) -> None:
    moves = _results(
        _moves(tmp_path, [*SATURDAY, postponed], _hourly("2026-10-31T11:00", "2026-11-01T02:00"))
    )
    assert moves == [_utc(f"2026-10-31T21:{FIRING_MINUTE:02d}")]


def test_a_fixture_postponed_after_the_rest_have_finished_moves_results_as_it_leaves(
    tmp_path: Path,
) -> None:
    """The matchday was held open by a match that was never played; the capture in which FPL takes
    it out of the gameweek is the one that sees the matchday done."""
    bronze = BronzeStore(tmp_path / "bronze")
    config, _ = load_config(environ={}, local_override=None)
    stuck = _match(6, "2026-10-31T19:45:00Z", bonus=None)
    earlier, later = _utc("2026-10-31T21:07"), _utc("2026-10-31T22:07")
    _write(bronze, "fpl", "fixtures", "all", _as_fetched([*SATURDAY, stuck], earlier), earlier)
    with Fetcher(config=config.http, bronze=bronze) as fetcher:
        adapters: list[SourceAdapter] = [FplApiAdapter(fetcher)]
        before = before_ingest(bronze, adapters)
        out = {**stuck, "event": None, "kickoff_time": None}
        _write(bronze, "fpl", "fixtures", "all", _as_fetched([*SATURDAY, out], later), later)
        kinds = changed_kinds(bronze, adapters, before, ChangeContext.of(None, SCHEDULE))
    assert kinds == ["fixtures", "results"]


def test_a_fixture_stuck_short_of_bonus_moves_results_once_at_the_settle_cap_bonus_pending(
    tmp_path: Path,
) -> None:
    """The 17:30 match's bonus never comes. The settle cap, three hours after the last kick-off
    (20:30), moves `results` at the first firing past it, once, from captures whose bytes no longer
    change; the run that firing starts reads the matchday as bonus pending."""
    stuck = [*SATURDAY[:-1], _match(5, "2026-10-31T17:30:00Z", bonus=None)]
    firings = _hourly("2026-10-31T11:00", "2026-11-01T06:00")
    moves = _results(_moves(tmp_path, stuck, firings))
    cap = _utc("2026-10-31T17:30") + dt.timedelta(hours=SCHEDULE.matchday_settle_hours)
    assert moves == [_utc(f"2026-10-31T21:{FIRING_MINUTE:02d}")]
    assert moves[0] - cap < dt.timedelta(hours=1)
    assert _as_fetched(stuck, firings[-2]) == _as_fetched(stuck, firings[-1])  # same bytes

    [saturday] = matchdays(
        _silver_fixtures(_as_fetched(stuck, moves[0])),
        moves[0],
        zone=SCHEDULE.matchday_zone,
        settle=dt.timedelta(hours=SCHEDULE.matchday_settle_hours),
    )
    assert saturday.done and saturday.bonus_pending
    assert (saturday.fixtures, saturday.finished) == (5, 4)


def test_a_bonus_confirmed_after_the_cap_moves_nothing_more(tmp_path: Path) -> None:
    """The cap has already published the matchday; the late bonus waits for the next `results`
    change (the next matchday, or finished and data-checked) to be read."""
    late = [*SATURDAY[:-1], _match(5, "2026-10-31T17:30:00Z", bonus=dt.timedelta(hours=6))]
    moves = _results(_moves(tmp_path, late, _hourly("2026-10-31T11:00", "2026-11-01T06:00")))
    assert moves == [_utc(f"2026-10-31T21:{FIRING_MINUTE:02d}")]


def _silver_fixtures(payload: bytes) -> pd.DataFrame:
    """The fixtures in silver's shape, as the run conforms them."""
    rows = json.loads(payload)
    return pd.DataFrame(
        {
            "gameweek": [row["event"] for row in rows],
            "kickoff_time": pd.to_datetime([row["kickoff_time"] for row in rows], utc=True),
            "finished": [row["finished"] for row in rows],
        }
    )
