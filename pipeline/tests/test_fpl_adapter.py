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
    set_piece = load("set_piece_notes")
    assert isinstance(bootstrap, dict) and isinstance(summaries, dict)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/bootstrap-static/").mock(return_value=httpx.Response(200, json=bootstrap))
        mock.get(f"{BASE}/fixtures/").mock(return_value=httpx.Response(200, json=fixtures))
        mock.get(f"{BASE}/team/set-piece-notes/").mock(
            return_value=httpx.Response(200, json=set_piece)
        )
        for element_id, summary in summaries.items():
            mock.get(f"{BASE}/element-summary/{element_id}/").mock(
                return_value=httpx.Response(200, json=summary)
            )
        mock.get(url__regex=rf"{BASE}/event/\d+/live/").mock(
            return_value=httpx.Response(200, json={"elements": []})
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
    """E2-S1: every endpoint in the catalogue is either ingested or explicitly out of scope.

    Named exhaustively rather than counted, so adding a resource without deciding where it sits on
    the fast path is a test failure rather than a silent change of cadence.
    """
    names = {resource.name for resource in FplApiAdapter.resources}
    assert names == {
        "bootstrap_static",
        "fixtures",
        "element_summary",
        "event_live",
        "set_piece_notes",
        "league_standings",
        "entry",
        "entry_history",
        "entry_picks",
        "entry_transfers",
    }


def test_the_per_gameweek_sweeps_stay_off_the_fast_path() -> None:
    """``event/{gw}/live`` grows one request per finished gameweek and must not run 4-hourly."""
    live = next(r for r in FplApiAdapter.resources if r.name == "event_live")
    assert live.fast_path is False


def test_the_expensive_resource_is_marked_off_the_fast_path() -> None:
    """Architecture §9: ~570 requests must never run on the frequent cadence."""
    summary = next(r for r in FplApiAdapter.resources if r.name == "element_summary")
    assert summary.fast_path is False
    assert summary.cache_ttl_seconds is not None
    assert summary.cache_ttl_seconds >= 24 * 3600


#: What the four-hourly workflow asks for (E7-S1).
FAST_REQUEST = IngestRequest(run_id="run-1", fast_path_only=True)


def test_the_fast_cadence_skips_every_resource_declared_off_the_fast_path(
    recorded_api: respx.MockRouter, adapter: FplApiAdapter
) -> None:
    """E7-S1: the declarations above are honoured, not merely recorded.

    Asserted against the requests actually issued rather than against the report alone, because a
    report can say zero while the fetches happened and were discarded — which would cost the six
    minutes this cadence exists to avoid.
    """
    report = adapter.ingest(FAST_REQUEST)

    assert report.resources["bootstrap_static"] == 1
    assert report.resources["fixtures"] == 1
    assert report.resources["element_summary"] == 0
    assert report.resources["event_live"] == 0

    requested = [str(call.request.url) for call in recorded_api.calls]
    assert not [url for url in requested if "element-summary" in url]
    assert not [url for url in requested if "/live/" in url]


def test_the_full_cadence_still_fetches_the_expensive_sweep(
    recorded_api: respx.MockRouter, adapter: FplApiAdapter
) -> None:
    """The guard is opt-in: without ``--fast`` nothing about the daily ingest changes (D-10)."""
    report = adapter.ingest(REQUEST)
    assert report.resources["element_summary"] > 0
    assert [call for call in recorded_api.calls if "element-summary" in str(call.request.url)]


def test_wants_answers_from_the_resource_declaration_alone(adapter: FplApiAdapter) -> None:
    for resource in FplApiAdapter.resources:
        assert adapter.wants(resource.name, FAST_REQUEST) is resource.fast_path
        # Without the flag, every resource is wanted whatever it declared.
        assert adapter.wants(resource.name, REQUEST) is True


def test_the_official_source_has_a_fast_path_at_all(adapter: FplApiAdapter) -> None:
    """``has_fast_path`` is how the ingest stage skips a source without naming it (Invariant 1)."""
    assert adapter.has_fast_path() is True


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
    assert report.resources["set_piece_notes"] == 1
    # No gameweek has finished in the recorded preseason fixture, so nothing is fetched per
    # gameweek. Asking for a future gameweek would cache an empty payload as though it meant
    # something.
    assert report.resources["event_live"] == 0

    # Expressed as its parts rather than as a total: a bare number stops describing anything the
    # moment a resource is added, and the last thing wanted then is a magic constant to bump.
    expected_calls = sum(report.resources.values())
    assert report.network_calls == expected_calls
    assert report.cache_hits == 0

    snapshots = list((tmp_path / "bronze").rglob("*.json.gz"))
    assert len(snapshots) == expected_calls
    assert all(path.with_name(path.name + ".meta.json").exists() for path in snapshots)

    second = adapter.ingest(REQUEST)
    assert second.network_calls == 0, "a re-run inside the cache window must not touch the network"
    assert second.cache_hits == expected_calls


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
