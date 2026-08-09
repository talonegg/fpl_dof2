from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

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


@pytest.fixture
def recorded_fpl_api() -> Iterator[respx.MockRouter]:
    """Serve the recorded API responses for the whole of a test.

    Shared so that end-to-end tests exercise the real adapter and the real transform rather than a
    stub — a stub source proves the wiring compiles, not that the pipeline works.
    """
    bootstrap = json.loads((FIXTURES / "bootstrap_static.json").read_text(encoding="utf-8"))
    fixtures = json.loads((FIXTURES / "fixtures.json").read_text(encoding="utf-8"))
    summaries = json.loads((FIXTURES / "element_summary.json").read_text(encoding="utf-8"))
    base = FplApiAdapter.base_url

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{base}/bootstrap-static/").mock(return_value=httpx.Response(200, json=bootstrap))
        mock.get(f"{base}/fixtures/").mock(return_value=httpx.Response(200, json=fixtures))
        for element_id, summary in summaries.items():
            mock.get(f"{base}/element-summary/{element_id}/").mock(
                return_value=httpx.Response(200, json=summary)
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


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """An environment that pins the data root inside tmp_path and nothing else."""
    return {"FPL_DOF_DATA_DIR": str(tmp_path / "data")}


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
