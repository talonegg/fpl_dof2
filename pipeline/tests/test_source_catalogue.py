"""The Sources catalogue: every source the pipeline depends on, with Scribe's labels (T-003).

This test file names real sources on purpose: it pins the catalogue (which lives in ``sources/``,
the one package allowed to name them) to the facts it describes, so a label cannot quietly drift
from the code, the frozen bundle or the dated backfill file it talks about.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from fpl_dof.config import load_config
from fpl_dof.obs.manifest import RunManifest, StageRecord, StageStatus
from fpl_dof.paths import find_repo_root
from fpl_dof.publish.contract import Contract, find_contracts_root
from fpl_dof.publish.health import build_sources
from fpl_dof.sources import SourceDescriptor, describe, known
from fpl_dof.sources.oddsapi.adapter import API_KEY_ENV, OddsApiAdapter
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
    "fdcouk": ("live", "Match odds in the pipeline run (football-data.co.uk)"),
}


def _catalogue(
    environ: dict[str, str] | None = None, *, config_file: str | None = None
) -> dict[str, SourceDescriptor]:
    env = {"FPL_DOF_DATA_DIR": "/tmp/unused"}
    override = Path(REPO / config_file) if config_file else Path(os.devnull)
    config, _ = load_config(environ=env, local_override=override)
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


def test_the_odds_api_is_switched_off_by_default() -> None:
    """PIPE-09, DL-79: The Odds API is off by default like the scrapers."""
    odds = _catalogue()["oddsapi"]
    assert odds.enabled is False
    assert odds.disabled_reason == (
        "Switched off by configuration; match odds come from football-data.co.uk."
    )
    # If switched on, it needs a key:
    assert OddsApiAdapter.configuration_problem({}) == (
        "It's switched on, but no API key is set, so it has never collected any odds."
    )
    assert OddsApiAdapter.configuration_problem({API_KEY_ENV: "present"}) is None


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
    """On in the shipped config (DL-87) and in the backtest config: reference either way."""
    assert _catalogue()["fplarchive"].enabled is True
    assert _catalogue()["fdcouk"].enabled is True
    assert _catalogue(config_file="config/ci-backtest.yaml")["fplarchive"].enabled is True
    assert _catalogue()["fplarchive"].kind == "reference"


# --- the publish stage's reads ----------------------------------------------------------------


def _ctx(**fields: Any) -> Any:
    return cast(Any, SimpleNamespace(**fields))


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
    return build_sources(
        manifest=_published_manifest(),
        observed={"fpl": NOW - dt.timedelta(hours=1)},
        generated_at=NOW,
        catalogue=list(_catalogue().values()),
        stale_after_seconds=48 * 3600,
    )


def test_the_published_run_shows_every_source_in_its_real_state(
    published: list[dict[str, Any]],
) -> None:
    """The T-003 acceptance table, as the scheduled pipeline run (no ingest stage) publishes it."""
    states = {entry["source"]: (entry["kind"], entry["status"]) for entry in published}
    assert states == {
        "fpl": ("live", "ok"),
        "fdcouk": ("live", "unknown"),  # enabled (DL-87), not observed in this fixture
        "oddsapi": ("live", "disabled"),
        "understat": ("live", "disabled"),
        "fbref": ("live", "disabled"),
        "fplarchive": ("reference", "ok"),
    }


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
