"""The change manifest (ORC-02, DL-94 item 4): each kind that starts a run, on fixture bronze, and
nothing else."""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from conftest import FIXTURES
from fpl_dof.cli import EXIT_OK, main
from fpl_dof.config import load_config
from fpl_dof.sources import BronzeStore, Fetcher, SourceAdapter, before_ingest, changed_kinds
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
        return changed_kinds(bronze, adapters, before, WINDOW)


LATER = T0 + dt.timedelta(hours=1)


def _bootstrap(edit: Callable[[dict[str, Any]], None]) -> Callable[[BronzeStore], None]:
    def ingest(bronze: BronzeStore) -> None:
        payload = copy.deepcopy(_json("bootstrap_static.json"))
        edit(payload["elements"][0])
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
