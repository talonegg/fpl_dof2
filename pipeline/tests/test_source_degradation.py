"""Fault injection: killing any non-official source degrades the model, never the pipeline.

E5-S5's named acceptance criterion, and DP-15's whole point. The assertion is deliberately not
"nothing crashed" — it is that the run **completes and the forecast still produces expected points**
for a full squad's worth of players, using whatever remains. A pipeline that survives by publishing
nothing has not degraded, it has failed quietly.

Each source is killed three ways, because they fail in all three: an exception on fetch, an
exception on conformance, and a source that returns nothing at all without complaining. The last is
the nastiest, because it looks like success.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from conftest import FIXTURE_QUALITY
from fpl_dof.cli import EXIT_OK, main
from fpl_dof.sources.base import Conformed, IngestReport, IngestRequest
from fpl_dof.sources.fbref.adapter import FbrefAdapter
from fpl_dof.sources.oddsapi.adapter import OddsApiAdapter
from fpl_dof.sources.understat.adapter import UnderstatAdapter
from fpl_dof.stages.forecast import XP_FILENAME

pytestmark = pytest.mark.usefixtures("recorded_fpl_api")

#: Every source this epic added. Each one must be individually survivable.
EXTERNAL = (UnderstatAdapter, FbrefAdapter, OddsApiAdapter)

SEASON_SLUG = "2026-27"


@pytest.fixture
def enabled_externals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Turn every external source on, so that killing one is actually killing something."""
    override = tmp_path / "degradation-config.yaml"
    override.write_text(
        yaml.safe_dump(
            {
                **FIXTURE_QUALITY,
                "sources": {"overrides": {adapter.name: {"enabled": True} for adapter in EXTERNAL}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FPL_DOF_CONFIG_FILE", str(override))
    return override


def _explode(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("the source fell over, as scraped sources do")


def _silently_empty_report(self: Any, request: IngestRequest) -> IngestReport:
    return IngestReport(source=self.name)


def _silently_empty_conform(self: Any, request: IngestRequest) -> Conformed:
    return Conformed(tables={})


def run_pipeline(data_dir: Path) -> dict[str, Any]:
    assert main(["--data-dir", str(data_dir), "run"]) == EXIT_OK
    manifests = sorted((data_dir / "runs").glob("*/manifest.json"))
    loaded: dict[str, Any] = json.loads(manifests[-1].read_text(encoding="utf-8"))
    return loaded


def assert_the_model_still_ran(data_dir: Path) -> None:
    """Not "it did not crash" — the forecast produced usable expected points."""
    forecast = pd.read_parquet(data_dir / "gold" / f"season={SEASON_SLUG}" / XP_FILENAME)
    assert len(forecast) >= 15, "the forecast produced fewer players than a squad needs"
    assert forecast["xp_next"].notna().all()
    assert float(forecast["xp_next"].max()) > 0.0
    # Invariant 6: a mean with no spread is not a forecast.
    assert forecast["xp_next_sd"].notna().all()
    squad = json.loads(
        (data_dir / "gold" / f"season={SEASON_SLUG}" / "squad.json").read_text(encoding="utf-8")
    )
    assert len(squad["players"]) == 15
    assert squad["captain_id"]


@pytest.mark.parametrize("adapter", EXTERNAL, ids=[a.name for a in EXTERNAL])
def test_a_source_that_raises_while_fetching_does_not_stop_the_run(
    adapter: type[Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled_externals: Path,
) -> None:
    monkeypatch.setattr(adapter, "ingest", _explode)
    monkeypatch.setattr(adapter, "conform", _explode)
    data_dir = tmp_path / "data"

    manifest = run_pipeline(data_dir)

    assert manifest["status"] == "succeeded"
    assert all(stage["status"] == "succeeded" for stage in manifest["stages"])
    degraded = {
        key: value
        for stage in manifest["stages"]
        for key, value in (stage.get("metrics") or {}).items()
        if key.startswith("degraded.")
    }
    # Visible, not silent. A degradation nobody can see is worse than a failure (DP-15).
    assert f"degraded.{adapter.name}" in degraded
    assert_the_model_still_ran(data_dir)


@pytest.mark.parametrize("adapter", EXTERNAL, ids=[a.name for a in EXTERNAL])
def test_a_source_that_returns_nothing_at_all_does_not_stop_the_run(
    adapter: type[Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled_externals: Path,
) -> None:
    """The quiet failure: no error, no data. The pipeline must simply have less to work with."""
    monkeypatch.setattr(adapter, "ingest", _silently_empty_report)
    monkeypatch.setattr(adapter, "conform", _silently_empty_conform)
    data_dir = tmp_path / "data"

    manifest = run_pipeline(data_dir)

    assert manifest["status"] == "succeeded"
    assert_the_model_still_ran(data_dir)


def test_losing_every_external_source_at_once_still_produces_a_squad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled_externals: Path
) -> None:
    """The bad night: the scrapers break and the odds allowance is gone, an hour before a
    deadline."""
    for adapter in EXTERNAL:
        monkeypatch.setattr(adapter, "ingest", _explode)
        monkeypatch.setattr(adapter, "conform", _explode)
    data_dir = tmp_path / "data"

    manifest = run_pipeline(data_dir)

    assert manifest["status"] == "succeeded"
    assert_the_model_still_ran(data_dir)


def test_the_official_source_is_the_only_one_that_may_stop_a_run() -> None:
    """The other half of the rule. Degrading on *every* source would hide a total outage."""
    from fpl_dof.sources import known

    essential = {name for name, adapter in known().items() if adapter.essential}
    assert len(essential) == 1, f"exactly one source may be essential, found {sorted(essential)}"
    for adapter in EXTERNAL:
        assert adapter.essential is False
