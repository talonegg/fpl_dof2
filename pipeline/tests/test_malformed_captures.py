"""A malformed capture never reaches history (ORC-10, DL-94 item 3).

A capture that is whole but breaks its source's contract used to stay the latest in bronze: it
failed the run, and a backtest or replay at a later ``as_of`` read it again. Now ingest checks each
new capture with the parser conformance uses, quarantines one that fails with its reason, and every
reader takes the last valid capture at or before its ``as_of``. The gates still judge the capture
actually used, so falling back never hides that the data is old (Invariant 7).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml

from conftest import FIXTURE_QUALITY, FIXTURES
from fpl_dof.cli import EXIT_OK, main
from fpl_dof.config import load_config
from fpl_dof.quality.rules import _snapshot_is_fresh
from fpl_dof.sources import BronzeStore, Fetcher, IngestRequest, SourceContractError
from fpl_dof.sources.fpl.adapter import FplApiAdapter
from fpl_dof.stages.quality import _newest_snapshot_age

BASE = FplApiAdapter.base_url
T0 = dt.datetime(2026, 8, 15, 12, 0, tzinfo=dt.UTC)


def _bootstrap() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (FIXTURES / "bootstrap_static.json").read_text(encoding="utf-8")
    )
    return loaded


def _malformed() -> dict[str, Any]:
    """One row short of whole: the last player has lost a required key. All or nothing (DL-94)."""
    broken = copy.deepcopy(_bootstrap())
    del broken["elements"][-1]["status"]
    return broken


def _ingest_bootstrap(bronze: BronzeStore, payload: dict[str, Any], now: dt.datetime) -> Any:
    config, _ = load_config(environ={}, local_override=None)
    with respx.mock() as mock, Fetcher(config=config.http, bronze=bronze) as fetcher:
        mock.get(f"{BASE}/bootstrap-static/").mock(return_value=httpx.Response(200, json=payload))
        data = FplApiAdapter(fetcher).fetch_bootstrap(IngestRequest(run_id="r", now=now))
    return data, fetcher


def test_a_malformed_capture_after_a_valid_one_is_quarantined_and_the_valid_one_used(
    tmp_path: Path,
) -> None:
    bronze = BronzeStore(tmp_path / "bronze")
    _ingest_bootstrap(bronze, _bootstrap(), T0)

    later = T0 + dt.timedelta(hours=2)
    data, fetcher = _ingest_bootstrap(bronze, _malformed(), later)

    assert data == _bootstrap(), "ingest went on with the last valid capture"
    [aside] = fetcher.quarantined
    assert aside.is_relative_to(bronze.quarantine_root)
    record = json.loads(aside.with_name(aside.name + ".meta.json").read_text(encoding="utf-8"))
    assert "status" in record["quarantine_reason"]
    assert bronze.quarantined() == {"fpl": 1}
    assert bronze.latest("fpl", "bootstrap_static", "all").meta.fetched_at == T0  # type: ignore[union-attr]


def test_a_malformed_first_capture_still_fails_when_there_is_nothing_valid_to_fall_back_on(
    tmp_path: Path,
) -> None:
    bronze = BronzeStore(tmp_path / "bronze")
    with pytest.raises(SourceContractError, match="status"):
        _ingest_bootstrap(bronze, _malformed(), T0)
    assert bronze.latest("fpl", "bootstrap_static", "all") is None
    assert bronze.quarantined() == {"fpl": 1}


def test_a_backtest_at_a_later_as_of_reads_the_valid_capture(tmp_path: Path) -> None:
    bronze = BronzeStore(tmp_path / "bronze")
    _ingest_bootstrap(bronze, _bootstrap(), T0)
    _ingest_bootstrap(bronze, _malformed(), T0 + dt.timedelta(hours=2))

    # Offline, as transform and the backtest read bronze, at an as_of after the malformed capture.
    config, _ = load_config(environ={}, local_override=None)
    with Fetcher(config=config.http, bronze=bronze) as fetcher:
        replayed = FplApiAdapter(fetcher).fetch_bootstrap(
            IngestRequest(run_id="r", offline=True, now=T0 + dt.timedelta(days=3))
        )
    assert replayed == _bootstrap()
    assert fetcher.network_calls == 0


def test_a_fallback_older_than_the_freshness_limit_still_fails_that_gate(tmp_path: Path) -> None:
    config, _ = load_config(environ={}, local_override=None)
    limit = dt.timedelta(hours=config.quality.maximum_snapshot_age_hours)
    bronze = BronzeStore(tmp_path / "bronze")
    _ingest_bootstrap(bronze, _bootstrap(), T0)
    now = T0 + limit + dt.timedelta(hours=1)
    _ingest_bootstrap(bronze, _malformed(), now)  # fresh, but quarantined

    ctx: Any = type("Ctx", (), {"layout": type("L", (), {"bronze": bronze.root}), "as_of": now})
    age = _newest_snapshot_age(ctx)
    assert age == pytest.approx((limit + dt.timedelta(hours=1)).total_seconds())
    passed, message, _ = _snapshot_is_fresh(
        None,  # type: ignore[arg-type]
        {"quality": config.quality, "snapshot_age_seconds": age},
    )
    assert not passed, message


# --- the one-off sweep of history kept before ingest checked captures ---------------------------


def _kept(bronze: BronzeStore, payload: dict[str, Any], now: dt.datetime) -> None:
    """A capture written straight to bronze, as history was before ORC-10."""
    bronze.write(
        json.dumps(payload).encode(),
        source="fpl",
        source_version="1",
        resource="bootstrap_static",
        key="all",
        url=f"{BASE}/bootstrap-static/",
        http_status=200,
        now=now,
        retain=True,
    )


def _verify(data_dir: Path, *flags: str) -> int:
    return main(["--data-dir", str(data_dir), "bronze", "verify", "--contract", *flags])


def test_the_sweep_finds_nothing_on_a_clean_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _kept(BronzeStore(tmp_path / "data" / "bronze"), _bootstrap(), T0)
    assert _verify(tmp_path / "data", "--quarantine") == EXIT_OK
    out = capsys.readouterr().out
    assert "1 passed, 0 failed, 0 issue(s)" in out
    assert "silver rebuild" not in out


def test_the_sweep_reports_and_quarantines_a_malformed_capture_in_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bronze = BronzeStore(tmp_path / "data" / "bronze")
    _kept(bronze, _bootstrap(), T0)
    _kept(bronze, _malformed(), T0 + dt.timedelta(hours=1))

    assert _verify(tmp_path / "data") != EXIT_OK, "reported, not moved, without --quarantine"
    assert "[contract]" in capsys.readouterr().out
    assert bronze.quarantined() == {}

    assert _verify(tmp_path / "data", "--quarantine") == EXIT_OK
    out = capsys.readouterr().out
    assert "1 passed, 1 failed" in out
    assert "fpl-dof silver rebuild" in out
    assert bronze.quarantined() == {"fpl": 1}
    assert bronze.latest("fpl", "bootstrap_static", "all").meta.fetched_at == T0  # type: ignore[union-attr]


# --- end to end: the run completes, and says so in health.json ----------------------------------


def test_a_run_after_a_malformed_capture_completes_on_the_valid_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_fpl_api: respx.MockRouter
) -> None:
    override = tmp_path / "config.yaml"
    override.write_text(yaml.safe_dump(FIXTURE_QUALITY), encoding="utf-8")
    monkeypatch.setenv("FPL_DOF_CONFIG_FILE", str(override))
    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "run"]) == EXIT_OK

    # Past the bootstrap's TTL, so the next run fetches it again, and gets a malformed one.
    monkeypatch.setenv("FPL_DOF_AS_OF", "2026-08-15T14:00:00+00:00")
    recorded_fpl_api.get(f"{BASE}/bootstrap-static/").mock(
        return_value=httpx.Response(200, json=_malformed())
    )
    assert main(["--data-dir", str(data_dir), "run"]) == EXIT_OK

    bronze = BronzeStore(data_dir / "bronze")
    assert bronze.quarantined() == {"fpl": 1}
    used = bronze.latest("fpl", "bootstrap_static", "all")
    assert used is not None and used.meta.fetched_at == T0
    health = json.loads(next((data_dir / "web").rglob("health.json")).read_text(encoding="utf-8"))
    [fpl] = [entry for entry in health["sources"] if entry["source"] == "fpl"]
    assert fpl["quarantined"] == 1
