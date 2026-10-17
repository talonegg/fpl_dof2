"""The Sources catalogue: every source the pipeline depends on, with Scribe's labels (T-003).

This test file names real sources on purpose: it pins the catalogue (which lives in ``sources/``,
the one package allowed to name them) to the facts it describes, so a label cannot quietly drift
from the code, the frozen bundle or the dated backfill file it talks about.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from fpl_dof.config import load_config
from fpl_dof.obs.manifest import RunManifest, StageRecord, StageStatus
from fpl_dof.paths import find_repo_root
from fpl_dof.prospective.fdcouk import HISTORY
from fpl_dof.publish.contract import Contract, find_contracts_root
from fpl_dof.publish.health import build_sources
from fpl_dof.sources import SourceDescriptor, describe, known
from fpl_dof.sources.oddsapi.adapter import API_KEY_ENV
from fpl_dof.stages import publish as publish_stage

_ROOT = find_repo_root()
assert _ROOT is not None, "the catalogue tests read files from the repository checkout"
REPO: Path = _ROOT
NOW = dt.datetime(2026, 10, 17, 5, 0, tzinfo=dt.UTC)

#: labels.md (T-004), section 1, verbatim.
SCRIBE_LABELS: dict[str, tuple[str, str]] = {
    "fpl": ("live", "Official FPL data"),
    "oddsapi": ("live", "Match odds (The Odds API)"),
    "fplarchive": ("reference", "Past seasons archive (community FPL archive)"),
    "understat": ("live", "Expected goals (Understat)"),
    "fbref": ("live", "Advanced player stats (FBref)"),
    "fdcouk_fixtures": ("live", "Upcoming match odds (football-data.co.uk)"),
    "fdcouk_history": (
        "reference",
        "Past match odds, 2023/24–2025/26 (football-data.co.uk)",  # noqa: RUF001 - Scribe's label, verbatim
    ),
    "fdcouk_backfill_2627": ("reference", "Early-season odds, 2026/27 (football-data.co.uk)"),
    "fplcache": ("reference", "Archived FPL snapshots (fplcache)"),
}


def _catalogue(
    environ: dict[str, str] | None = None, *, config_file: str | None = None
) -> dict[str, SourceDescriptor]:
    env = {"FPL_DOF_DATA_DIR": "/tmp/unused"}
    if config_file:
        env["FPL_DOF_CONFIG_FILE"] = str(REPO / config_file)
    config, _ = load_config(environ=env, local_override=None)
    return {d.key: d for d in describe(config.sources, environ or {})}


def test_every_source_the_review_found_is_listed_with_scribes_label_and_kind() -> None:
    catalogue = _catalogue()
    assert set(catalogue) == set(SCRIBE_LABELS)
    for key, (kind, label) in SCRIBE_LABELS.items():
        assert (catalogue[key].kind, catalogue[key].label) == (kind, label), key
        assert catalogue[key].description, key


def test_every_registered_adapter_is_in_the_catalogue() -> None:
    """A source added later appears on the page without anyone editing a list."""
    assert set(known()) <= set(_catalogue())


def test_the_odds_api_is_not_set_up_without_a_key_and_is_with_one() -> None:
    assert _catalogue()["oddsapi"].enabled is True  # the shipped config switches it on
    assert _catalogue()["oddsapi"].not_configured == (
        "It's switched on, but no API key is set, so it has never collected any odds."
    )
    assert _catalogue({API_KEY_ENV: "present"})["oddsapi"].not_configured is None


def test_the_key_value_never_reaches_the_descriptor() -> None:
    secret = "do-not-publish-0123456789"
    assert secret not in repr(_catalogue({API_KEY_ENV: secret}))


def test_blocked_scrapers_are_switched_off_with_scribes_reason() -> None:
    catalogue = _catalogue()
    assert catalogue["understat"].enabled is False
    assert catalogue["understat"].disabled_reason == (
        "The site doesn't allow automated access, so this source isn't used."
    )
    assert catalogue["fbref"].enabled is False
    assert catalogue["fbref"].disabled_reason == (
        "The site blocks automated access, so this source isn't used."
    )


def test_the_archive_is_reference_data_whether_or_not_this_config_enables_it() -> None:
    """Off in the champion config, on in the decision/backtest config: reference either way."""
    assert _catalogue()["fplarchive"].enabled is False
    assert _catalogue(config_file="config/ci-backtest.yaml")["fplarchive"].enabled is True
    assert _catalogue()["fplarchive"].kind == "reference"


def test_the_history_label_names_exactly_the_hash_pinned_seasons() -> None:
    """Scribe asked if 2026/27 is pinned. It is not: ``SEASONS`` has it, ``HISTORY`` doesn't."""
    pinned = sorted(Path(rel).stem for rel in HISTORY)
    assert pinned == ["E0_2324", "E0_2425", "E0_2526"]
    manifest = json.loads((REPO / "prospective/bundle/manifest.json").read_text(encoding="utf-8"))
    hashes = manifest["models"]["A_odds"]["model_files_sha256"]
    assert set(HISTORY) <= set(hashes)
    assert _catalogue()["fdcouk_history"].as_of == manifest["frozen_at"][:10]


def test_the_backfill_row_describes_the_dated_file_written_once() -> None:
    path = REPO / "scripts/models_history/data/fdcouk/E0_2627_20261017.csv"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest.startswith("6731e95d")
    assert _catalogue()["fdcouk_backfill_2627"].as_of == "2026-10-17"


def test_the_fplcache_as_of_date_is_the_last_snapshot_in_the_frozen_bundle() -> None:
    bundle = REPO / "prospective/bundle/frozen-2026-10-13.tar.gz"
    with tarfile.open(bundle) as tar:
        member = tar.extractfile("frozen/backtest/fplcache/index.csv")
        assert member is not None
        rows = list(csv.DictReader(io.TextIOWrapper(member, encoding="utf-8")))
    last = max(rows, key=lambda row: row["snap_ts"])
    assert (last["season"], last["gw"]) == ("2025/26", "38")
    assert _catalogue()["fplcache"].as_of == last["snap_ts"][:10]


# --- the publish stage's reads ----------------------------------------------------------------


def _ctx(**fields: Any) -> Any:
    return cast(Any, SimpleNamespace(**fields))


def test_the_newest_decision_is_by_gameweek_number_not_by_file_name(tmp_path: Path) -> None:
    for gw in (7, 9, 10):
        (tmp_path / "decisions").mkdir(exist_ok=True)
        (tmp_path / "decisions" / f"GW{gw}.json").write_text(json.dumps({"gw": gw}))
    (tmp_path / "status").mkdir()
    (tmp_path / "status" / "GW10.json").write_text(json.dumps({"gw": 10, "models": {}}))
    ctx = _ctx(
        config=SimpleNamespace(
            publish=SimpleNamespace(models=SimpleNamespace(source_dir=str(tmp_path)))
        )
    )
    record = publish_stage._record_evidence(ctx)
    assert record is not None
    assert record.decision == {"gw": 10}
    assert record.status == {"gw": 10, "models": {}}


def test_no_record_directory_means_no_record_evidence(tmp_path: Path) -> None:
    unset = _ctx(
        config=SimpleNamespace(publish=SimpleNamespace(models=SimpleNamespace(source_dir=None)))
    )
    assert publish_stage._record_evidence(unset) is None
    empty = _ctx(
        config=SimpleNamespace(
            publish=SimpleNamespace(models=SimpleNamespace(source_dir=str(tmp_path)))
        )
    )
    assert publish_stage._record_evidence(empty) is None


def test_the_newest_snapshot_is_found_by_capture_stamp_not_by_mtime(tmp_path: Path) -> None:
    """T-001 F8: CI restores bronze with ``cp -r``, which scrambles modification times."""
    directory = tmp_path / "bronze" / "feed" / "resource" / "2026-10-17"
    directory.mkdir(parents=True)
    newer = directory / "key__20261017T041800Z.json.gz.meta.json"
    older = directory / "key__20261016T224044Z.json.gz.meta.json"
    newer.write_text(json.dumps({"fetched_at": "2026-10-17T04:18:00Z"}))
    older.write_text(json.dumps({"fetched_at": "2026-10-16T22:40:44Z"}))
    os.utime(newer, (1_000_000, 1_000_000))  # the newer capture has the older mtime
    ctx = _ctx(layout=SimpleNamespace(bronze=tmp_path / "bronze"))
    observed = publish_stage._source_observations(ctx)
    assert observed == {"feed": dt.datetime(2026, 10, 17, 4, 18, tzinfo=dt.UTC)}


# --- what the published run renders today ---------------------------------------------------------


def _published_manifest() -> RunManifest:
    started = NOW - dt.timedelta(minutes=10)
    return RunManifest(
        run_id="r",
        started_at=started,
        finished_at=None,
        status=None,
        git_sha=None,
        git_dirty=False,
        config_digest="d",
        requested_stages=["run"],
        stages=[
            StageRecord(
                name="transform",
                status=StageStatus.SUCCEEDED,
                started_at=started,
                finished_at=started,
                duration_seconds=1.0,
                metrics={"rows.player": 667},
            )
        ],
    )


@pytest.fixture(scope="module")
def published() -> list[dict[str, Any]]:
    from fpl_dof.publish.health import RecordEvidence

    decision = {
        "gw": 7,
        "odds": {
            "fixtures_in_gw": 10,
            "fixtures_with_odds": 10,
            "kept": 10,
            "fetched_at": "2026-10-16 22:18:13+00:00",
        },
    }
    status = {
        "gw": 7,
        "assessed_at": "2026-10-16T22:24:30+00:00",
        "models": {"A_odds": {"inputs": {"odds_history": None, "live_odds": None}}},
    }
    return build_sources(
        manifest=_published_manifest(),
        observed={"fpl": NOW - dt.timedelta(hours=1)},
        generated_at=NOW,
        catalogue=list(_catalogue().values()),
        record=RecordEvidence(decision=decision, status=status),
        stale_after_seconds=48 * 3600,
    )


def test_the_published_run_shows_every_source_in_its_real_state(
    published: list[dict[str, Any]],
) -> None:
    """The T-003 acceptance table, as the scheduled pipeline run (no ingest stage) publishes it."""
    states = {entry["source"]: (entry["kind"], entry["status"]) for entry in published}
    assert states == {
        "fpl": ("live", "ok"),
        "fdcouk_fixtures": ("live", "ok"),
        "oddsapi": ("live", "not_configured"),
        "understat": ("live", "disabled"),
        "fbref": ("live", "disabled"),
        "fplarchive": ("reference", "ok"),
        "fdcouk_history": ("reference", "ok"),
        "fdcouk_backfill_2627": ("reference", "ok"),
        "fplcache": ("reference", "ok"),
    }
    history = next(e for e in published if e["source"] == "fdcouk_history")
    assert history["check"] == "pass"


def test_the_published_rows_match_the_schema(published: list[dict[str, Any]]) -> None:
    contract = Contract(root=find_contracts_root())
    contract.validate(
        "health",
        {
            "contract_version": 1,
            "generated_at": "2026-10-17T05:00:00Z",
            "run": {"run_id": "r", "started_at": "2026-10-17T04:50:00Z", "stages": []},
            "sources": published,
            "gates": None,
        },
    )
