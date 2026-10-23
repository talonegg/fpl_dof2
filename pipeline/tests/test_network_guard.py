"""The test suite's network guard stops real connections and lets local process plumbing through."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest


def test_an_internet_connection_is_refused() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s, pytest.raises(RuntimeError):
        s.connect(("192.0.2.1", 80))


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no Unix sockets on this platform")
def test_a_local_unix_socket_is_not_the_network(tmp_path: Path) -> None:
    path = str(tmp_path / "s")
    unix = socket.AF_UNIX  # type: ignore[attr-defined,unused-ignore]  # absent on Windows
    with socket.socket(unix) as server, socket.socket(unix) as client:
        server.bind(path)
        server.listen(1)
        client.connect(path)
