from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml

from fpl_dof.config import Config, load_config
from fpl_dof.config.models import RulesConfig
from fpl_dof.paths import DataLayout
from fpl_dof.rules.build import build_game_rules
from fpl_dof.rules.models import ApiRules, GameRules
from fpl_dof.sources.fpl.adapter import FplApiAdapter


@pytest.fixture(autouse=True)
def no_accidental_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """Fail loudly rather than quietly reaching the internet.

    Without this, a test that exercises the whole pipeline happily performs a real ~570-request
    sweep of the FPL API: slow, impolite, and non-deterministic. respx intercepts above this layer,
    so mocked requests are unaffected — only genuinely unmocked ones are stopped.

    Tests that mean to use the network carry ``@pytest.mark.network``.
    """
    if request.node.get_closest_marker("network"):
        yield
        return

    def blocked(self: socket.socket, address: Any) -> None:
        raise RuntimeError(
            f"unmocked network connection to {address!r} — mock it with respx, or mark the test "
            "@pytest.mark.network if it is meant to hit the live API"
        )

    # The socket layer, deliberately. respx patches httpx *and* httpcore, so a guard installed at
    # either of those layers fights with it; a mocked request never reaches a socket, so this
    # catches exactly the calls that would have gone out for real and nothing else.
    original = socket.socket.connect
    socket.socket.connect = blocked  # type: ignore[assignment,method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original  # type: ignore[method-assign]


FIXTURES = Path(__file__).parent / "fixtures"


#: A made-up entry. The entry endpoints return a real manager's name and region, and this
#: repository is public (Invariant 10) — recording a third party's details as a test fixture is not
#: something to do casually, and nothing about these tests needs a real one.
TEST_ENTRY_ID = 9_999_999


@pytest.fixture
def recorded_fpl_api() -> Iterator[respx.MockRouter]:
    """Serve the recorded API responses for the whole of a test.

    Shared so that end-to-end tests exercise the real adapter and the real transform rather than a
    stub — a stub source proves the wiring compiles, not that the pipeline works.

    Endpoints that are empty in preseason are mocked as empty rather than left unrouted: an
    unrouted request reaches the socket guard and fails as "unmocked network call", which hides
    what is actually being tested.
    """
    bootstrap = json.loads((FIXTURES / "bootstrap_static.json").read_text(encoding="utf-8"))
    fixtures = json.loads((FIXTURES / "fixtures.json").read_text(encoding="utf-8"))
    summaries = json.loads((FIXTURES / "element_summary.json").read_text(encoding="utf-8"))
    set_piece = json.loads((FIXTURES / "set_piece_notes.json").read_text(encoding="utf-8"))
    base = FplApiAdapter.base_url

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{base}/bootstrap-static/").mock(return_value=httpx.Response(200, json=bootstrap))
        mock.get(f"{base}/fixtures/").mock(return_value=httpx.Response(200, json=fixtures))
        mock.get(f"{base}/team/set-piece-notes/").mock(
            return_value=httpx.Response(200, json=set_piece)
        )
        for element_id, summary in summaries.items():
            mock.get(f"{base}/element-summary/{element_id}/").mock(
                return_value=httpx.Response(200, json=summary)
            )
        mock.get(url__regex=rf"{base}/event/\d+/live/").mock(
            return_value=httpx.Response(200, json={"elements": []})
        )
        mock.get(url__regex=rf"{base}/entry/\d+/event/\d+/picks/").mock(
            return_value=httpx.Response(404, json={"detail": "Not found."})
        )
        mock.get(url__regex=rf"{base}/entry/\d+/transfers/").mock(
            return_value=httpx.Response(200, json=[])
        )
        mock.get(url__regex=rf"{base}/entry/\d+/history/").mock(
            return_value=httpx.Response(200, json={"current": [], "past": [], "chips": []})
        )
        mock.get(url__regex=rf"{base}/entry/\d+/$").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": TEST_ENTRY_ID,
                    "name": "Test Entry",
                    "started_event": 1,
                    "current_event": None,
                    "last_deadline_bank": None,
                    "last_deadline_value": None,
                    "last_deadline_total_transfers": 0,
                    "summary_overall_points": None,
                    "summary_overall_rank": None,
                },
            )
        )
        yield mock


@pytest.fixture(scope="session")
def api_rules() -> ApiRules:
    """The real published 2026/27 rules, read from the recorded bootstrap fixture.

    Tests assert against what the game actually says, not against a hand-written imitation of it.
    """
    bootstrap = json.loads(
        (Path(__file__).parent / "fixtures" / "bootstrap_static.json").read_text(encoding="utf-8")
    )
    adapter = FplApiAdapter.__new__(FplApiAdapter)  # no fetcher needed for pure extraction
    return adapter.extract_rules(bootstrap)


@pytest.fixture(scope="session")
def game_rules(api_rules: ApiRules) -> GameRules:
    return build_game_rules(api_rules, RulesConfig())


#: The recorded fixtures are a deliberately trimmed league: 8 clubs, 92 players, 12 fixtures. That
#: keeps the test suite fast, and it means the production quality thresholds — which exist to catch
#: a partial outage of the *real* API — would reject it, correctly.
#:
#: Overriding them here rather than lowering the real ones is the point: a threshold loose enough
#: for a 92-player fixture is a threshold that would not notice the FPL API returning 92 players.
FIXTURE_QUALITY = {
    "quality": {
        "minimum_players": 50,
        "expected_teams": 8,
        "expected_fixtures": 12,
    }
}


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """Data root inside tmp_path, plus gate thresholds sized for the recorded fixture."""
    override = tmp_path / "test-config.yaml"
    override.write_text(yaml.safe_dump(FIXTURE_QUALITY), encoding="utf-8")
    return {
        "FPL_DOF_DATA_DIR": str(tmp_path / "data"),
        "FPL_DOF_CONFIG_FILE": str(override),
    }


@pytest.fixture
def config(isolated_env: dict[str, str]) -> Config:
    loaded, _digest = load_config(environ=isolated_env, local_override=None)
    return loaded


@pytest.fixture
def layout(config: Config) -> Iterator[DataLayout]:
    built = DataLayout(root=config.runtime.data_dir)
    built.ensure()
    yield built


def pytest_collection_modifyitems(config: pytest.Config, items: list[Any]) -> None:
    """Keep network-marked tests out of the default run without needing -m on every invocation."""
    if config.getoption("--network"):
        return
    skip = pytest.mark.skip(reason="hits the live FPL API; run with --network")
    for item in items:
        if item.get_closest_marker("network"):
            item.add_marker(skip)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--network",
        action="store_true",
        default=False,
        help="Run tests that hit the live FPL API.",
    )
