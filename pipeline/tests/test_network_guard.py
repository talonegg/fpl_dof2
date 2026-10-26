"""The test harness itself: the network guard, and the shards CI runs side by side."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from conftest import in_shard


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


def test_the_shards_partition_the_suite() -> None:
    """ORC-09: CI's shards together run every test module exactly once, for any count it uses."""
    modules = [path.name for path in Path(__file__).parent.glob("test_*.py")]
    for count in (1, 2, 3):
        for module in modules:
            assert sum(in_shard(module, index, count) for index in range(count)) == 1
