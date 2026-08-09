from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from fpl_dof.config.models import HttpConfig, RateLimitConfig, RetryConfig
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.errors import (
    OfflineWithoutSnapshotError,
    SourceNotFoundError,
    SourceRateLimitedError,
    SourceUnavailableError,
)
from fpl_dof.sources.fetch import Fetcher, RateLimiter, user_agent

URL = "https://example.invalid/thing"

FETCH_KWARGS = {
    "source": "demo",
    "source_version": "1",
    "resource": "things",
    "key": "all",
}


def _config(**overrides: Any) -> HttpConfig:
    base: dict[str, Any] = {
        "rate_limit": RateLimitConfig(requests_per_second=1000.0),
        "retry": RetryConfig(max_attempts=3, backoff_base_seconds=0.01, backoff_max_seconds=0.05),
        "default_cache_ttl_seconds": 3600,
    }
    base.update(overrides)
    return HttpConfig(**base)


def _fetcher(tmp_path: Path, config: HttpConfig | None = None) -> Fetcher:
    slept: list[float] = []
    fetcher = Fetcher(
        config=config or _config(),
        bronze=BronzeStore(tmp_path),
        run_id="run-1",
        sleep=slept.append,
        rng=random.Random(0),
    )
    fetcher.slept = slept  # type: ignore[attr-defined]
    return fetcher


def test_rate_limiter_waits_for_the_minimum_interval() -> None:
    slept: list[float] = []
    limiter = RateLimiter(2.0, sleep=slept.append)
    limiter.wait()
    limiter.wait()
    assert limiter.min_interval == 0.5
    assert slept and slept[0] <= 0.5


def test_user_agent_identifies_the_client_honestly() -> None:
    agent = user_agent(_config(user_agent_contact="https://example.invalid/me"))
    assert agent.startswith("fpl-dof/")
    assert "https://example.invalid/me" in agent


@respx.mock
def test_successful_fetch_snapshots_to_bronze(tmp_path: Path) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    with _fetcher(tmp_path) as fetcher:
        result = fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]

    assert route.called
    assert result.from_cache is False
    assert b'"ok"' in result.payload
    assert result.snapshot.path.exists()
    assert result.snapshot.meta.http_status == 200
    assert result.snapshot.meta.run_id == "run-1"


@respx.mock
def test_second_fetch_inside_the_ttl_makes_zero_network_calls(tmp_path: Path) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    with _fetcher(tmp_path) as fetcher:
        fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]
        assert fetcher.network_calls == 1
        second = fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]

    assert route.call_count == 1, "the cache window must eliminate the second call entirely"
    assert second.from_cache is True
    assert json.loads(second.payload) == {"ok": True}


@respx.mock
def test_force_refresh_ignores_the_cache(tmp_path: Path) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    with _fetcher(tmp_path) as fetcher:
        fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]
        fetcher.fetch(URL, force_refresh=True, **FETCH_KWARGS)  # type: ignore[arg-type]
    assert route.call_count == 2


@respx.mock
def test_expired_cache_is_refetched(tmp_path: Path) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    with _fetcher(tmp_path, _config(default_cache_ttl_seconds=60)) as fetcher:
        fetcher.fetch(URL, now=dt.datetime(2026, 8, 10, 0, 0, tzinfo=dt.UTC), **FETCH_KWARGS)  # type: ignore[arg-type]
        fetcher.fetch(URL, now=dt.datetime(2026, 8, 10, 1, 0, tzinfo=dt.UTC), **FETCH_KWARGS)  # type: ignore[arg-type]
    assert route.call_count == 2


@respx.mock
def test_offline_uses_a_stale_snapshot_rather_than_failing(tmp_path: Path) -> None:
    """DP-15: degrade, never break."""
    respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    with _fetcher(tmp_path, _config(default_cache_ttl_seconds=0)) as fetcher:
        fetcher.fetch(URL, now=dt.datetime(2026, 8, 1, tzinfo=dt.UTC), **FETCH_KWARGS)  # type: ignore[arg-type]
        calls_before = fetcher.network_calls
        stale = fetcher.fetch(
            URL,
            offline=True,
            now=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
            **FETCH_KWARGS,  # type: ignore[arg-type]
        )
        assert fetcher.network_calls == calls_before
    assert stale.from_cache is True


@respx.mock
def test_offline_without_a_snapshot_is_an_error(tmp_path: Path) -> None:
    with _fetcher(tmp_path) as fetcher, pytest.raises(OfflineWithoutSnapshotError) as exc:
        fetcher.fetch(URL, offline=True, **FETCH_KWARGS)  # type: ignore[arg-type]
    assert exc.value.source == "demo"
    assert exc.value.resource == "things"


@respx.mock
def test_404_is_not_retried(tmp_path: Path) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(404))
    with _fetcher(tmp_path) as fetcher, pytest.raises(SourceNotFoundError):
        fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]
    assert route.call_count == 1


@respx.mock
def test_transient_500_is_retried_then_succeeds(tmp_path: Path) -> None:
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    with _fetcher(tmp_path) as fetcher:
        result = fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]
        assert fetcher.slept, "a retry must back off before trying again"  # type: ignore[attr-defined]
    assert route.call_count == 2
    assert result.from_cache is False


@respx.mock
def test_persistent_500_exhausts_retries(tmp_path: Path) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    with _fetcher(tmp_path) as fetcher, pytest.raises(SourceUnavailableError):
        fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]
    assert route.call_count == 3


@respx.mock
def test_persistent_429_is_reported_as_rate_limiting(tmp_path: Path) -> None:
    respx.get(URL).mock(return_value=httpx.Response(429))
    with _fetcher(tmp_path) as fetcher, pytest.raises(SourceRateLimitedError):
        fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]


@respx.mock
def test_client_error_that_is_not_404_is_unavailable(tmp_path: Path) -> None:
    respx.get(URL).mock(return_value=httpx.Response(403))
    with _fetcher(tmp_path) as fetcher, pytest.raises(SourceUnavailableError):
        fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]


@respx.mock
def test_transport_error_is_retried(tmp_path: Path) -> None:
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("no route to host"))
    with _fetcher(tmp_path) as fetcher, pytest.raises(SourceUnavailableError):
        fetcher.fetch(URL, **FETCH_KWARGS)  # type: ignore[arg-type]
    assert route.call_count == 3


def test_backoff_grows_and_is_capped(tmp_path: Path) -> None:
    config = _config(
        retry=RetryConfig(
            max_attempts=6,
            backoff_base_seconds=1.0,
            backoff_max_seconds=4.0,
            jitter_fraction=0.0,
        )
    )
    with _fetcher(tmp_path, config) as fetcher:
        delays = [fetcher._backoff_seconds(n) for n in range(1, 6)]
    assert delays == [1.0, 2.0, 4.0, 4.0, 4.0]
