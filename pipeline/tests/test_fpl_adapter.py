"""Contract tests for the FPL adapter, against recorded real responses.

The fixtures in ``tests/fixtures/`` are trimmed copies of genuine API responses, not hand-written
approximations. That distinction is the whole point: a synthesised fixture asserts what we believe
the API returns, and will happily keep passing after the API changes shape.

``test_live_contract`` repeats the shape assertions against the live API. It is marked ``network``
and is the drift detector; the recorded tests are the regression net.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from fpl_dof.config.models import HttpConfig, RateLimitConfig, RetryConfig
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.errors import SourceContractError
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fpl.adapter import (
    REQUIRED_BOOTSTRAP_KEYS,
    REQUIRED_ELEMENT_KEYS,
    REQUIRED_HISTORY_PAST_KEYS,
    FplApiAdapter,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = FplApiAdapter.base_url


def load(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def recorded_api() -> Iterator[respx.MockRouter]:
    bootstrap = load("bootstrap_static")
    fixtures = load("fixtures")
    summaries = load("element_summary")
    assert isinstance(bootstrap, dict) and isinstance(summaries, dict)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/bootstrap-static/").mock(return_value=httpx.Response(200, json=bootstrap))
        mock.get(f"{BASE}/fixtures/").mock(return_value=httpx.Response(200, json=fixtures))
        for element_id, summary in summaries.items():
            mock.get(f"{BASE}/element-summary/{element_id}/").mock(
                return_value=httpx.Response(200, json=summary)
            )
        yield mock


@pytest.fixture
def adapter(tmp_path: Path) -> Iterator[FplApiAdapter]:
    config = HttpConfig(
        rate_limit=RateLimitConfig(requests_per_second=1000.0),
        retry=RetryConfig(max_attempts=2, backoff_base_seconds=0.001),
    )
    with Fetcher(
        config=config,
        bronze=BronzeStore(tmp_path / "bronze"),
        run_id="run-1",
        sleep=lambda _s: None,
    ) as fetcher:
        yield FplApiAdapter(fetcher)


REQUEST = IngestRequest(run_id="run-1")


def test_adapter_declares_its_resources() -> None:
    names = {resource.name for resource in FplApiAdapter.resources}
    assert names == {"bootstrap_static", "fixtures", "element_summary"}


def test_the_expensive_resource_is_marked_off_the_fast_path() -> None:
    """Architecture §9: ~570 requests must never run on the frequent cadence."""
    summary = next(r for r in FplApiAdapter.resources if r.name == "element_summary")
    assert summary.fast_path is False
    assert summary.cache_ttl_seconds is not None
    assert summary.cache_ttl_seconds >= 24 * 3600


def test_bootstrap_carries_everything_downstream_needs(
    recorded_api: respx.MockRouter, adapter: FplApiAdapter
) -> None:
    data = adapter.fetch_bootstrap(REQUEST)
    for key in REQUIRED_BOOTSTRAP_KEYS:
        assert key in data
    for key in REQUIRED_ELEMENT_KEYS:
        assert key in data["elements"][0]

    # Invariant 2 depends on these being present rather than hardcoded.
    assert data["game_settings"]["squad_squadsize"] == 15
    assert data["game_settings"]["squad_team_limit"] == 3
    assert data["game_settings"]["squad_total_spend"] == 1000
    assert "scoring" in data["game_config"]
    scoring = data["game_config"]["scoring"]
    assert set(scoring["goals_scored"]) == {"GKP", "DEF", "MID", "FWD"}
    assert "defensive_contribution" in scoring

    for element_type in data["element_types"]:
        assert element_type["squad_select"] > 0
        assert element_type["squad_min_play"] <= element_type["squad_max_play"]


def test_history_past_carries_defensive_contribution(
    recorded_api: respx.MockRouter, adapter: FplApiAdapter
) -> None:
    """E0-S3 route 1. If this ever fails, the archive fallback becomes necessary again."""
    data = adapter.fetch_bootstrap(REQUEST)
    outfield = [e for e in data["elements"] if e["element_type"] in (2, 3) and e["minutes"] > 1500]
    assert outfield, "fixture has no outfielder with enough minutes to check"

    seen_nonzero = False
    for element in outfield:
        summary = adapter.fetch_element_summary(int(element["id"]), REQUEST)
        for season in summary["history_past"]:
            for key in REQUIRED_HISTORY_PAST_KEYS:
                assert key in season, f"{key} missing from history_past"
            if season["season_name"] == "2025/26" and season["defensive_contribution"] > 0:
                seen_nonzero = True
    assert seen_nonzero, "no outfielder recorded any 2025/26 defensive contribution"


def test_fixtures_carry_per_side_difficulty(
    recorded_api: respx.MockRouter, adapter: FplApiAdapter
) -> None:
    """Preseason team strength_attack/defence are all zero, so difficulty must come from here."""
    fixtures = adapter.fetch_fixtures(REQUEST)
    assert fixtures
    for fixture in fixtures:
        assert fixture["team_h_difficulty"] >= 1
        assert fixture["team_a_difficulty"] >= 1
        assert {"event", "team_h", "team_a", "kickoff_time"} <= set(fixture)


def test_ingest_snapshots_everything_and_reuses_the_cache(
    recorded_api: respx.MockRouter, adapter: FplApiAdapter, tmp_path: Path
) -> None:
    report = adapter.ingest(REQUEST)
    assert report.source == "fpl"
    assert report.resources["bootstrap_static"] == 1
    assert report.resources["fixtures"] == 1
    assert report.resources["element_summary"] == 92
    assert report.network_calls == 94
    assert report.cache_hits == 0

    snapshots = list((tmp_path / "bronze").rglob("*.json.gz"))
    assert len(snapshots) == 94
    assert all(path.with_name(path.name + ".meta.json").exists() for path in snapshots)

    second = adapter.ingest(REQUEST)
    assert second.network_calls == 0, "a re-run inside the cache window must not touch the network"
    assert second.cache_hits == 94


def test_player_limit_is_honoured_and_warned_about(
    recorded_api: respx.MockRouter, adapter: FplApiAdapter
) -> None:
    report = adapter.ingest(IngestRequest(run_id="run-1", player_limit=3))
    assert report.resources["element_summary"] == 3
    assert any("player_limit" in warning for warning in report.warnings)


def test_a_removed_player_is_survivable(
    recorded_api: respx.MockRouter, adapter: FplApiAdapter
) -> None:
    """DP-15: a 404 on one player must not take down the run."""
    data = adapter.fetch_bootstrap(REQUEST)
    missing_id = int(data["elements"][0]["id"])
    recorded_api.get(f"{BASE}/element-summary/{missing_id}/").mock(return_value=httpx.Response(404))

    report = adapter.ingest(REQUEST)
    assert report.resources["element_summary"] == 91
    assert any(str(missing_id) in warning for warning in report.warnings)


@respx.mock
def test_a_changed_upstream_shape_is_a_contract_error(adapter: FplApiAdapter) -> None:
    respx.get(f"{BASE}/bootstrap-static/").mock(
        return_value=httpx.Response(200, json={"elements": [], "teams": []})
    )
    with pytest.raises(SourceContractError, match="missing required keys"):
        adapter.fetch_bootstrap(REQUEST)


@respx.mock
def test_empty_element_list_is_a_contract_error(adapter: FplApiAdapter) -> None:
    payload: dict[str, object] = {key: [] for key in REQUIRED_BOOTSTRAP_KEYS}
    payload["game_settings"] = {}
    respx.get(f"{BASE}/bootstrap-static/").mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(SourceContractError, match="no elements"):
        adapter.fetch_bootstrap(REQUEST)


@respx.mock
def test_non_json_body_is_a_contract_error(adapter: FplApiAdapter) -> None:
    respx.get(f"{BASE}/fixtures/").mock(return_value=httpx.Response(200, content=b"<html>"))
    with pytest.raises(SourceContractError, match="not valid JSON"):
        adapter.fetch_fixtures(REQUEST)


@respx.mock
def test_fixtures_object_instead_of_list_is_a_contract_error(adapter: FplApiAdapter) -> None:
    respx.get(f"{BASE}/fixtures/").mock(return_value=httpx.Response(200, json={"oops": 1}))
    with pytest.raises(SourceContractError, match="did not return a list"):
        adapter.fetch_fixtures(REQUEST)


@respx.mock
def test_element_summary_without_history_past_is_a_contract_error(adapter: FplApiAdapter) -> None:
    respx.get(f"{BASE}/element-summary/7/").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(SourceContractError, match="history_past"):
        adapter.fetch_element_summary(7, REQUEST)


@pytest.mark.network
def test_live_contract(adapter: FplApiAdapter) -> None:
    """Drift detector. Run explicitly: pytest -m network."""
    data = adapter.fetch_bootstrap(REQUEST)
    assert len(data["elements"]) > 400
    assert len(data["teams"]) == 20
    scoring = data["game_config"]["scoring"]
    assert set(scoring["goals_scored"]) == {"GKP", "DEF", "MID", "FWD"}
    assert set(scoring["defensive_contribution"]) == {"GKP", "DEF", "MID", "FWD"}

    fixtures = adapter.fetch_fixtures(REQUEST)
    assert len(fixtures) == 380

    element_id = int(data["elements"][0]["id"])
    summary = adapter.fetch_element_summary(element_id, REQUEST)
    if summary["history_past"]:
        for key in REQUIRED_HISTORY_PAST_KEYS:
            assert key in summary["history_past"][0]
