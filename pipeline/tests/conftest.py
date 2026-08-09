from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.config import Config, load_config
from fpl_dof.paths import DataLayout


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
