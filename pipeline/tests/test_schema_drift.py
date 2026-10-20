"""PIPE-08: Ingestion Schema Drift Canary & Early Detection Gate tests.

Verifies:
1. Missing or renamed root keys in bootstrap_static halt ingest immediately before
   launching per-player sweeps.
2. Missing required keys in fixtures halt ingest immediately before launching per-player sweeps.
3. Structural drift errors produce a diagnostic diff of expected vs received keys in
   the pipeline log and run manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from fpl_dof.config import Config
from fpl_dof.config.models import HttpConfig
from fpl_dof.obs.manifest import ManifestWriter
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext, StageFailedError, get_stage, run_stages
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.errors import SourceContractError
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fpl.adapter import FplApiAdapter


@pytest.fixture
def base_bootstrap() -> dict[str, object]:
    return {
        "elements": [
            {
                "id": 1,
                "element_type": 1,
                "team": 1,
                "now_cost": 50,
                "web_name": "Player 1",
                "status": "a",
            }
        ],
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "element_types": [{"id": 1, "singular_name_short": "GKP"}],
        "events": [
            {
                "id": 1,
                "name": "Gameweek 1",
                "deadline_time": "2026-08-21T17:30:00Z",
                "finished": False,
            }
        ],
        "game_settings": {
            "squad_squadsize": 15,
            "squad_squadplay": 11,
            "squad_total_spend": 1000,
            "squad_team_limit": 3,
        },
    }


@pytest.fixture
def base_fixtures() -> list[dict[str, object]]:
    return [
        {
            "id": 1,
            "event": 1,
            "team_h": 1,
            "team_a": 2,
            "team_h_difficulty": 2,
            "team_a_difficulty": 3,
            "finished": False,
        }
    ]


def test_missing_root_key_in_bootstrap_halts_before_per_player_sweep(
    tmp_path: Path, base_bootstrap: dict[str, object]
) -> None:
    # Rename 'elements' to 'players'
    drifted = dict(base_bootstrap)
    drifted["players"] = drifted.pop("elements")

    element_summary_called = False

    def on_element_summary(_request: httpx.Request) -> httpx.Response:
        nonlocal element_summary_called
        element_summary_called = True
        return httpx.Response(200, json={"history_past": []})

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{FplApiAdapter.base_url}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=drifted)
        )
        mock.get(url__regex=rf"{FplApiAdapter.base_url}/element-summary/\d+/").mock(
            side_effect=on_element_summary
        )

        fetcher = Fetcher(config=HttpConfig(), bronze=BronzeStore(tmp_path / "bronze"))
        adapter = FplApiAdapter(fetcher)
        request = IngestRequest(run_id="test-run")

        with pytest.raises(SourceContractError) as exc_info:
            adapter.ingest(request)

        assert "elements" in exc_info.value.diff.get("missing", [])
        assert not element_summary_called


def test_missing_fixture_key_halts_before_per_player_sweep(
    tmp_path: Path, base_bootstrap: dict[str, object], base_fixtures: list[dict[str, object]]
) -> None:
    drifted_fixtures = [
        {
            "id": 1,
            "event": 1,
            # Missing team_h and team_a
            "finished": False,
        }
    ]

    element_summary_called = False

    def on_element_summary(_request: httpx.Request) -> httpx.Response:
        nonlocal element_summary_called
        element_summary_called = True
        return httpx.Response(200, json={"history_past": []})

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{FplApiAdapter.base_url}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=base_bootstrap)
        )
        mock.get(f"{FplApiAdapter.base_url}/fixtures/").mock(
            return_value=httpx.Response(200, json=drifted_fixtures)
        )
        mock.get(url__regex=rf"{FplApiAdapter.base_url}/element-summary/\d+/").mock(
            side_effect=on_element_summary
        )

        fetcher = Fetcher(config=HttpConfig(), bronze=BronzeStore(tmp_path / "bronze"))
        adapter = FplApiAdapter(fetcher)
        request = IngestRequest(run_id="test-run")

        with pytest.raises(SourceContractError) as exc_info:
            adapter.ingest(request)

        assert "team_h" in exc_info.value.diff.get("missing", [])
        assert not element_summary_called


def test_schema_drift_records_diagnostic_diff_in_manifest(
    tmp_path: Path, base_bootstrap: dict[str, object]
) -> None:
    drifted = dict(base_bootstrap)
    del drifted["teams"]

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{FplApiAdapter.base_url}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=drifted)
        )

        layout = DataLayout(root=tmp_path / "data")
        layout.ensure()
        config = Config()
        ctx = StageContext(config=config, layout=layout, run_id="drift-test")
        writer = ManifestWriter(
            run_id="drift-test",
            config_digest="test-digest",
            runs_dir=layout.runs,
            data_root=layout.root,
        )

        with pytest.raises(StageFailedError):
            run_stages([get_stage("ingest")], ctx, writer)

        manifest = writer.manifest
        ingest_rec = manifest.stage("ingest")
        assert ingest_rec is not None
        assert ingest_rec.status == "failed"
        assert "schema_drift" in ingest_rec.metrics
        diff = json.loads(str(ingest_rec.metrics["schema_drift"]))
        assert "teams" in diff.get("missing", [])
