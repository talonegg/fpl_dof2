from __future__ import annotations

import datetime as dt
import gzip
from pathlib import Path

from fpl_dof.sources.bronze import META_SUFFIX, BronzeStore, Snapshot, safe_key


def _write(
    store: BronzeStore, payload: bytes, *, key: str = "all", now: dt.datetime | None = None
) -> Snapshot:
    return store.write(
        payload,
        source="demo",
        source_version="1",
        resource="things",
        key=key,
        url="https://example.invalid/things",
        http_status=200,
        run_id="run-1",
        now=now,
    )


def test_snapshot_round_trips_with_lineage(tmp_path: Path) -> None:
    store = BronzeStore(tmp_path)
    snapshot = _write(store, b'{"hello": "world"}')

    assert snapshot.path.exists()
    assert snapshot.read_bytes() == b'{"hello": "world"}'
    assert snapshot.meta.source == "demo"
    assert snapshot.meta.bytes == 18
    assert snapshot.meta.url.endswith("/things")
    assert snapshot.meta.run_id == "run-1"
    assert snapshot.path.with_name(snapshot.path.name + META_SUFFIX).exists()

    with gzip.open(snapshot.path, "rb") as handle:
        assert handle.read() == b'{"hello": "world"}'


def test_identical_payloads_produce_identical_bytes(tmp_path: Path) -> None:
    """mtime is pinned so a snapshot is content-addressable across runs (DP-11)."""
    store = BronzeStore(tmp_path)
    a = _write(store, b"same", now=dt.datetime(2026, 8, 10, 1, 0, tzinfo=dt.UTC))
    b = _write(store, b"same", now=dt.datetime(2026, 8, 11, 2, 0, tzinfo=dt.UTC))
    assert a.path.read_bytes() == b.path.read_bytes()
    assert a.meta.sha256 == b.meta.sha256


def test_latest_returns_the_most_recent_snapshot(tmp_path: Path) -> None:
    store = BronzeStore(tmp_path)
    _write(store, b"old", now=dt.datetime(2026, 8, 1, 0, 0, tzinfo=dt.UTC))
    _write(store, b"new", now=dt.datetime(2026, 8, 9, 0, 0, tzinfo=dt.UTC))
    latest = store.latest("demo", "things", "all")
    assert latest is not None
    assert latest.read_bytes() == b"new"


def test_latest_is_none_when_nothing_recorded(tmp_path: Path) -> None:
    store = BronzeStore(tmp_path)
    assert store.latest("demo", "things", "all") is None
    _write(store, b"x", key="other")
    assert store.latest("demo", "things", "all") is None


def test_torn_write_without_a_sidecar_is_skipped(tmp_path: Path) -> None:
    store = BronzeStore(tmp_path)
    good = _write(store, b"good", now=dt.datetime(2026, 8, 1, 0, 0, tzinfo=dt.UTC))
    torn = _write(store, b"torn", now=dt.datetime(2026, 8, 9, 0, 0, tzinfo=dt.UTC))
    torn.path.with_name(torn.path.name + META_SUFFIX).unlink()

    latest = store.latest("demo", "things", "all")
    assert latest is not None
    assert latest.path == good.path


def test_age_is_measured_against_fetch_time(tmp_path: Path) -> None:
    store = BronzeStore(tmp_path)
    snapshot = _write(store, b"x", now=dt.datetime(2026, 8, 10, 0, 0, tzinfo=dt.UTC))
    assert snapshot.age_seconds(dt.datetime(2026, 8, 10, 1, 0, tzinfo=dt.UTC)) == 3600


def test_keys_are_made_filename_safe() -> None:
    assert safe_key("123") == "123"
    assert safe_key("a/b c") == "a-b-c"
    assert safe_key("///") == "_"


def test_different_keys_do_not_collide(tmp_path: Path) -> None:
    store = BronzeStore(tmp_path)
    _write(store, b"one", key="1")
    _write(store, b"two", key="2")
    first = store.latest("demo", "things", "1")
    second = store.latest("demo", "things", "2")
    assert first is not None and second is not None
    assert first.read_bytes() == b"one"
    assert second.read_bytes() == b"two"
