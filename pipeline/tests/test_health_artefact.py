"""The data health artefact — `health.json`. E7-S6, FR-33, NFR-07, DL-41.

Where being wrong here is invisible (DP-13), and therefore where the effort goes:

* **A missing gate report must not publish as a pass.** Nothing throws if it does. The page draws a
  green tick, the reader concludes the data was checked, and no check ran at all. This is the single
  most dangerous failure the artefact has, because the page exists to be trusted about exactly this.
* **A degraded source must never render as healthy**, and a source the run said nothing about must
  not render as healthy either. "No news" and "good news" are the same pixel if you let them be.
* **A gap must be null, not zero.** A run that never reached the optimiser has no solve time; a zero
  there reads as an instant solve on a chart, which is the friendliest possible way to hide a stage
  that did not run.
* **No source name appears in the publisher.** The tests use invented labels precisely so a module
  that had learned a real source's name would fail here rather than in a season's time
  (Invariant 1).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from fpl_dof.obs.manifest import RunManifest, StageRecord, StageStatus
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.health import (
    build_gates,
    build_health,
    build_metrics_history,
    build_run,
    build_sources,
    metrics_point,
    source_labels,
)

# Deliberately not the names of any source this project actually has. A publisher that branched on
# a real source would pass every test below while being a defect (DP-01).
SOURCE_A = "alpha-feed"
SOURCE_B = "beta-feed"

NOW = dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract(root=find_contracts_root())


def _stage(
    name: str,
    *,
    status: StageStatus = StageStatus.SUCCEEDED,
    metrics: dict[str, float | int | str] | None = None,
    error: str | None = None,
    offset_minutes: int = 0,
) -> StageRecord:
    started = NOW - dt.timedelta(minutes=30 - offset_minutes)
    return StageRecord(
        name=name,
        status=status,
        started_at=started,
        finished_at=started + dt.timedelta(seconds=12),
        duration_seconds=12.0,
        metrics=metrics or {},
        error=error,
    )


def _manifest(
    *,
    run_id: str = "20260816T113000Z-aaaabbbb",
    stages: list[StageRecord] | None = None,
    status: StageStatus | None = None,
    finished: bool = False,
) -> RunManifest:
    started = NOW - dt.timedelta(minutes=30)
    return RunManifest(
        run_id=run_id,
        started_at=started,
        finished_at=started + dt.timedelta(minutes=20) if finished else None,
        status=status,
        git_sha="0123456789abcdef",
        git_dirty=False,
        config_digest="deadbeef",
        requested_stages=["run"],
        stages=stages or [],
    )


def _healthy_manifest() -> RunManifest:
    return _manifest(
        stages=[
            _stage(
                "ingest",
                metrics={
                    f"{SOURCE_A}.players": 700,
                    f"{SOURCE_A}.network_calls": 3,
                    f"{SOURCE_A}.cache_hits": 1,
                    f"{DEGRADED}{SOURCE_B}": "HTTPError",
                    "sources": 2,
                },
            ),
            _stage("transform", metrics={"rows.player": 700, "rows.team": 20}, offset_minutes=1),
            _stage("quality", metrics={"gates.failed": 0, "passed": "True"}, offset_minutes=2),
            _stage("forecast", metrics={"r_squared_on_price": 0.49}, offset_minutes=3),
            _stage("optimise", metrics={"solve_seconds": 1.75}, offset_minutes=4),
        ]
    )


DEGRADED = "degraded."


def _gate_report(*, passed: bool = True) -> dict[str, Any]:
    return {
        "passed": passed,
        "counts": {"passed": 11, "failed": 0 if passed else 1, "skipped": 2},
        "blocking": [] if passed else ["player-volume"],
        "results": [
            {
                "gate": "player-volume",
                "class": "freshness_and_volume",
                "severity": "error",
                "outcome": "passed" if passed else "failed",
                "message": "700 players, within the expected band" if passed else "30 players",
                "requirement": "NFR-05",
                "observed": {"rows": 700},
            }
        ],
    }


# --- the gate report: the case that must never be softened ----------------------------------


def test_a_missing_gate_report_publishes_as_null_and_never_as_a_pass() -> None:
    """The whole point of the artefact. An absent report proves nothing (DP-13, Invariant 7)."""
    assert build_gates(None) is None


def test_a_failing_gate_keeps_its_reason_and_its_requirement() -> None:
    gates = build_gates(_gate_report(passed=False))
    assert gates is not None
    assert gates["passed"] is False
    assert gates["blocking"] == ["player-volume"]
    result = gates["results"][0]
    # DP-09: the flag travels with its derivation, and DP-14 with what it protects. A gate that
    # fails and cannot say why or what for is a gate that gets disabled the first time it fires.
    assert result["message"] == "30 players"
    assert result["requirement"] == "NFR-05"


def test_the_bulky_observation_payload_is_left_on_disk() -> None:
    """`observed` is free-form and the bulk of the report; `message` is the half written to read."""
    gates = build_gates(_gate_report())
    assert gates is not None
    assert "observed" not in gates["results"][0]


# --- sources --------------------------------------------------------------------------------


def test_a_degraded_source_is_flagged_with_the_stage_and_the_reason() -> None:
    sources = {
        entry["source"]: entry
        for entry in build_sources(manifest=_healthy_manifest(), observed={}, generated_at=NOW)
    }
    assert sources[SOURCE_B]["status"] == "degraded"
    assert sources[SOURCE_B]["detail"] == "HTTPError"
    assert sources[SOURCE_B]["degraded_at_stage"] == "ingest"
    assert sources[SOURCE_A]["status"] == "ok"


def test_a_source_the_run_said_nothing_about_is_unknown_rather_than_ok() -> None:
    """No news is not good news. A source with snapshots on disk that this run never touched has
    not been shown to be working, and showing it as working is how a silently stalled feed hides."""
    observed = {SOURCE_A: NOW - dt.timedelta(hours=9)}
    sources = build_sources(manifest=_manifest(), observed=observed, generated_at=NOW)
    assert [entry["status"] for entry in sources] == ["unknown"]
    assert sources[0]["detail"]


def test_freshness_is_measured_from_the_publication_and_not_from_a_clock() -> None:
    """A published age is the age at publication. An age the browser recomputes keeps growing while
    a cached page sits open, which makes stale data look like a stalled pipeline (DP-09)."""
    observed = {SOURCE_A: NOW - dt.timedelta(hours=2)}
    sources = build_sources(manifest=_healthy_manifest(), observed=observed, generated_at=NOW)
    entry = next(s for s in sources if s["source"] == SOURCE_A)
    assert entry["age_seconds"] == pytest.approx(7200)
    assert entry["observed_at"] == "2026-08-16T10:00:00Z"


def test_a_source_never_captured_reports_a_null_age_rather_than_zero() -> None:
    sources = build_sources(manifest=_healthy_manifest(), observed={}, generated_at=NOW)
    entry = next(s for s in sources if s["source"] == SOURCE_A)
    assert entry["observed_at"] is None
    assert entry["age_seconds"] is None


def test_cache_hits_and_network_calls_are_both_published() -> None:
    """A fully cached run is fast and legitimate, and is also why a source can be `ok` while its
    snapshots are older than the run. The two states must stay distinguishable."""
    sources = build_sources(manifest=_healthy_manifest(), observed={}, generated_at=NOW)
    entry = next(s for s in sources if s["source"] == SOURCE_A)
    assert entry["network_calls"] == 3
    assert entry["cache_hits"] == 1
    assert entry["resources"] == {"players": 700}


def test_source_labels_come_from_the_data_and_not_from_a_list_in_the_code() -> None:
    """Invariant 1 as a test: labels the publisher has never heard of must round-trip untouched."""
    manifest = _manifest(
        stages=[_stage("ingest", metrics={"wholly-invented.network_calls": 0, "sources": 1})]
    )
    assert source_labels(manifest, {"another-invention": NOW}) == [
        "another-invention",
        "wholly-invented",
    ]


def test_a_dotted_metric_that_is_not_a_source_is_not_mistaken_for_one() -> None:
    """`rows.player` and `resolved.x` are dotted too. Identifying a source by `.network_calls`
    rather than by "has a dot" is what keeps a table name out of the source list."""
    manifest = _manifest(
        stages=[_stage("transform", metrics={"rows.player": 700, f"resolved.{SOURCE_A}": 12})]
    )
    assert source_labels(manifest, {}) == []


# --- the run excerpt ------------------------------------------------------------------------


def test_the_publishing_run_reports_a_null_status_rather_than_claiming_success() -> None:
    """The run that writes this file has not finished. Claiming it succeeded is the one lie the
    page cannot afford, because it would be told on every single successful publication."""
    run = build_run(_healthy_manifest())
    assert run["status"] is None
    assert run["finished_at"] is None
    assert run["duration_seconds"] is None


def test_a_failed_stage_carries_its_error_into_the_excerpt() -> None:
    manifest = _manifest(
        stages=[_stage("ingest", status=StageStatus.FAILED, error="connection reset")]
    )
    stage = build_run(manifest)["stages"][0]
    assert stage["status"] == "failed"
    assert stage["error"] == "connection reset"


def test_a_dirty_working_tree_is_published_rather_than_left_implied() -> None:
    manifest = _healthy_manifest()
    manifest.git_dirty = True
    assert build_run(manifest)["git_dirty"] is True


# --- the rolling series ---------------------------------------------------------------------


def test_a_measurement_a_run_never_took_is_null_and_not_zero() -> None:
    """A zero solve time draws as an instant solve. A null draws as a gap, which is what it is."""
    point = metrics_point(_manifest(stages=[_stage("ingest")]))
    assert point["solve_seconds"] is None
    assert point["rows_total"] is None
    assert point["r_squared_on_price"] is None


def test_a_complete_run_carries_its_solve_time_volumes_and_diagnostic() -> None:
    point = metrics_point(_healthy_manifest())
    assert point["solve_seconds"] == pytest.approx(1.75)
    assert point["rows"] == {"player": 700, "team": 20}
    assert point["rows_total"] == 720
    assert point["r_squared_on_price"] == pytest.approx(0.49)
    assert point["gates_failed"] == 0


def test_the_series_is_oldest_first_and_trimmed_to_the_newest_runs() -> None:
    manifests = []
    for index in range(5):
        manifest = _manifest(run_id=f"run-{index}")
        manifest.started_at = NOW - dt.timedelta(hours=5 - index)
        manifests.append(manifest)

    history = build_metrics_history(manifests, limit=3)
    assert history is not None
    assert [point["run_id"] for point in history["runs"]] == ["run-2", "run-3", "run-4"]


def test_no_history_publishes_as_null_rather_than_an_empty_axis() -> None:
    assert build_metrics_history([], limit=30) is None
    assert build_metrics_history([_manifest()], limit=0) is None


def test_the_series_names_where_it_came_from() -> None:
    """The shape is the contract, the storage is not (DL-41). A reader has to be able to tell."""
    history = build_metrics_history([_healthy_manifest()], limit=30)
    assert history is not None
    assert history["derived_from"]


# --- the whole payload against the schema ---------------------------------------------------


def _payload(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "manifest": _healthy_manifest(),
        "gate_report": _gate_report(),
        "observed": {SOURCE_A: NOW - dt.timedelta(hours=1)},
        "recent": [_healthy_manifest()],
        "generated_at": NOW,
        "history_limit": 30,
        "contract_version": CONTRACT_VERSION,
    }
    kwargs.update(overrides)
    return build_health(**kwargs)


def test_a_populated_payload_matches_the_schema(contract: Contract) -> None:
    contract.validate("health", _payload())


def test_the_emptiest_survivable_payload_still_matches_the_schema(contract: Contract) -> None:
    """DP-15 at the contract level: no gate report, no snapshots, no history, no stages. The page
    must have a shape to render "nothing is known yet" from, rather than the publisher refusing."""
    payload = _payload(
        manifest=_manifest(), gate_report=None, observed={}, recent=[], history_limit=30
    )
    contract.validate("health", payload)
    assert payload["gates"] is None
    assert payload["metrics_history"] is None
    assert payload["sources"] == []


def test_a_blocked_run_matches_the_schema_and_says_which_gate_blocked(contract: Contract) -> None:
    payload = _payload(gate_report=_gate_report(passed=False))
    contract.validate("health", payload)
    assert payload["gates"]["passed"] is False
    assert payload["gates"]["blocking"] == ["player-volume"]


def test_every_timestamp_crosses_the_seam_as_utc(contract: Contract) -> None:
    payload = _payload()
    contract.validate("health", payload)
    assert payload["generated_at"].endswith("Z")
    assert payload["run"]["started_at"].endswith("Z")
    assert all(stage["started_at"].endswith("Z") for stage in payload["run"]["stages"])
