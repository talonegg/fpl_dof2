"""The shared transport every adapter fetches through.

Rate limiting, retry with jittered backoff, cache-by-bronze and snapshotting all live here, once.
An adapter that wanted its own HTTP handling would be a defect: the politeness budget (NFR-10) is
a property of the project, not of a source.
"""

from __future__ import annotations

import datetime as dt
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from fpl_dof import __version__
from fpl_dof.config.models import HttpConfig
from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.sources.bronze import BronzeStore, Snapshot
from fpl_dof.sources.errors import (
    OfflineWithoutSnapshotError,
    SourceNotFoundError,
    SourceRateLimitedError,
    SourceUnavailableError,
)

log = get_logger(__name__)


class RateLimiter:
    """Minimum-interval limiter. Deliberately serial and deliberately simple."""

    def __init__(self, requests_per_second: float, *, sleep: Callable[[float], None] | None = None):
        self.min_interval = 1.0 / requests_per_second
        self._sleep = sleep or time.sleep
        self._last: float | None = None
        self._monotonic = time.monotonic

    def wait(self) -> None:
        now = self._monotonic()
        if self._last is not None:
            remaining = self.min_interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._monotonic()


@dataclass(frozen=True, slots=True)
class Fetched:
    """The bytes, and how we came by them."""

    payload: bytes
    snapshot: Snapshot
    from_cache: bool

    @property
    def stale(self) -> bool:
        """True when this came from bronze in offline mode, past its TTL."""
        return self.from_cache and self.snapshot.meta.http_status == 0


def user_agent(config: HttpConfig) -> str:
    return config.user_agent_template.format(version=__version__, contact=config.user_agent_contact)


class Fetcher:
    """Fetch-or-reuse, with every snapshot landing in bronze."""

    def __init__(
        self,
        *,
        config: HttpConfig,
        bronze: BronzeStore,
        client: httpx.Client | None = None,
        run_id: str | None = None,
        sleep: Callable[[float], None] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self.bronze = bronze
        self.run_id = run_id
        self._sleep = sleep or time.sleep
        self._rng = rng or random.Random()
        self._limiter = RateLimiter(config.rate_limit.requests_per_second, sleep=self._sleep)
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=config.timeout_seconds,
            headers={"User-Agent": user_agent(config), "Accept-Encoding": "gzip"},
            follow_redirects=True,
        )
        self.network_calls = 0
        self.cache_hits = 0

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _backoff_seconds(self, attempt: int) -> float:
        retry = self.config.retry
        raw: float = retry.backoff_base_seconds * float(2 ** (attempt - 1))
        capped: float = min(raw, retry.backoff_max_seconds)
        jitter: float = capped * retry.jitter_fraction
        delay: float = capped + self._rng.uniform(-jitter, jitter)
        return delay if delay > 0.0 else 0.0

    def fetch(
        self,
        url: str,
        *,
        source: str,
        source_version: str,
        resource: str,
        key: str,
        cache_ttl_seconds: int | None = None,
        force_refresh: bool = False,
        offline: bool = False,
        params: Mapping[str, str] | None = None,
        now: dt.datetime | None = None,
    ) -> Fetched:
        moment = now or utcnow()
        ttl = (
            self.config.default_cache_ttl_seconds
            if cache_ttl_seconds is None
            else cache_ttl_seconds
        )
        cached = self.bronze.latest(source, resource, key)

        if cached is not None and not force_refresh and cached.age_seconds(moment) < ttl:
            self.cache_hits += 1
            log.debug("fetch.cache_hit", extra={"url": url, "resource": resource, "key": key})
            return Fetched(payload=cached.read_bytes(), snapshot=cached, from_cache=True)

        if offline:
            if cached is None:
                raise OfflineWithoutSnapshotError(
                    f"offline mode and no bronze snapshot for {source}/{resource}/{key}",
                    source=source,
                    resource=resource,
                    key=key,
                )
            self.cache_hits += 1
            log.warning(
                "fetch.offline_stale",
                extra={"resource": resource, "key": key, "age_seconds": cached.age_seconds(moment)},
            )
            return Fetched(payload=cached.read_bytes(), snapshot=cached, from_cache=True)

        response = self._request_with_retries(
            url, source=source, resource=resource, key=key, params=params
        )
        snapshot = self.bronze.write(
            response.content,
            source=source,
            source_version=source_version,
            resource=resource,
            key=key,
            url=str(response.request.url),
            http_status=response.status_code,
            run_id=self.run_id,
            content_encoding=response.headers.get("content-encoding"),
        )
        return Fetched(payload=response.content, snapshot=snapshot, from_cache=False)

    def _request_with_retries(
        self,
        url: str,
        *,
        source: str,
        resource: str,
        key: str,
        params: Mapping[str, str] | None,
    ) -> httpx.Response:
        retry = self.config.retry
        last_error: str = "no attempt was made"

        for attempt in range(1, retry.max_attempts + 1):
            self._limiter.wait()
            self.network_calls += 1
            try:
                response = self.client.get(url, params=dict(params) if params else None)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 404:
                    raise SourceNotFoundError(
                        f"{url} returned 404",
                        source=source,
                        resource=resource,
                        key=key,
                    )
                if response.status_code not in retry.retry_on_status:
                    if response.status_code >= 400:
                        raise SourceUnavailableError(
                            f"{url} returned {response.status_code}",
                            source=source,
                            resource=resource,
                            key=key,
                        )
                    return response
                last_error = f"HTTP {response.status_code}"

            if attempt < retry.max_attempts:
                delay = self._backoff_seconds(attempt)
                log.warning(
                    "fetch.retry",
                    extra={
                        "url": url,
                        "attempt": attempt,
                        "of": retry.max_attempts,
                        "error": last_error,
                        "sleep_seconds": round(delay, 3),
                    },
                )
                self._sleep(delay)

        message = f"{url} failed after {retry.max_attempts} attempts: {last_error}"
        if last_error == "HTTP 429":
            raise SourceRateLimitedError(message, source=source, resource=resource, key=key)
        raise SourceUnavailableError(message, source=source, resource=resource, key=key)
