from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from conftest import VirtualClock
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
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(2.0, sleep=sleep, clock=lambda: now[0])
    limiter.wait()  # first call never waits
    assert slept == []
    limiter.wait()  # back-to-back: waits the full interval
    assert limiter.min_interval == 0.5
    assert slept == [pytest.approx(0.5)]
    now[0] += 0.2  # 0.2 s of work: only the remainder is waited
    limiter.wait()
    assert slept[-1] == pytest.approx(0.3)
    now[0] += 1.0  # longer than the interval: no wait at all
    limiter.wait()
    assert len(slept) == 2


def test_the_suite_runs_on_a_virtual_clock(virtual_clock: VirtualClock) -> None:
    """The autouse fixture swaps the transport defaults: pacing advances virtual time only."""
    limiter = RateLimiter(2.0)
    start = virtual_clock.now
    for _ in range(5):
        limiter.wait()
    assert virtual_clock.now - start == pytest.approx(2.0)
    assert virtual_clock.slept == [pytest.approx(0.5)] * 4


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


@respx.mock
def test_conditional_request_sends_etag_and_handles_304(tmp_path: Path) -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            content=b"initial body",
            headers={"ETag": '"v1-hash"', "Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT"},
        )
    )
    with _fetcher(tmp_path) as fetcher:
        first = fetcher.fetch(URL, cache_ttl_seconds=10, **FETCH_KWARGS)  # type: ignore[arg-type]
        assert first.from_cache is False
        assert first.payload == b"initial body"
        assert first.snapshot.meta.etag == '"v1-hash"'

        # Re-mock with 304 conditional handler
        def conditional_handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("if-none-match") == '"v1-hash"'
            assert request.headers.get("if-modified-since") == "Wed, 21 Oct 2026 07:28:00 GMT"
            return httpx.Response(304, headers={"ETag": '"v1-hash"'})

        respx.get(URL).mock(side_effect=conditional_handler)

        # Expired TTL forces upstream check with conditional headers
        second = fetcher.fetch(URL, cache_ttl_seconds=0, **FETCH_KWARGS)  # type: ignore[arg-type]
        assert second.from_cache is True
        assert second.payload == b"initial body"
        assert fetcher.conditional_hits == 1
        assert fetcher.network_calls == 2


@respx.mock
def test_force_refresh_bypasses_conditional_headers(tmp_path: Path) -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(200, content=b"initial", headers={"ETag": '"v1-hash"'})
    )
    with _fetcher(tmp_path) as fetcher:
        fetcher.fetch(URL, cache_ttl_seconds=10, **FETCH_KWARGS)  # type: ignore[arg-type]

        def unconditional_handler(request: httpx.Request) -> httpx.Response:
            assert "if-none-match" not in request.headers
            assert "if-modified-since" not in request.headers
            return httpx.Response(200, content=b"refreshed")

        respx.get(URL).mock(side_effect=unconditional_handler)
        refreshed = fetcher.fetch(URL, force_refresh=True, **FETCH_KWARGS)  # type: ignore[arg-type]
        assert refreshed.from_cache is False
        assert refreshed.payload == b"refreshed"
        assert fetcher.conditional_hits == 0
