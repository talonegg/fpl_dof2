"""CI support for the frozen prospective models: bundle integrity, odds-history ingest,
fail-closed freshness, the record's round trip, and the config hook."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import tarfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from fpl_dof.config.loader import load_config
from fpl_dof.prospective import freshness as fr
from fpl_dof.prospective.bundle import (
    BundleReport,
    bundled_model_configs,
    canon,
    manifest_body_ok,
    sha256_bytes,
    verify_bundle,
)
from fpl_dof.prospective.fdcouk import HISTORY, fetch_history

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "prospective" / "bundle" / "frozen-2026-10-13.tar.gz"
MANIFEST = REPO / "prospective" / "bundle" / "manifest.json"
FROZEN_MODELS = ("engine", "C3", "C1", "A", "A_odds")


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return dict(json.loads(MANIFEST.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def extracted(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("bundle")
    with tarfile.open(BUNDLE, "r:gz") as tar:
        tar.extractall(root, filter="data")
    return root


# --- the frozen bundle -----------------------------------------------------------------------


def test_manifest_is_unedited(manifest: dict[str, Any]) -> None:
    assert manifest_body_ok(manifest)
    assert manifest["frozen_tag"] == "frozen-2026-10-13"
    assert manifest["code_commit"].startswith("79e080c")
    assert set(manifest["models"]) == set(FROZEN_MODELS)


def test_frozen_config_hashes_match_the_manifest(manifest: dict[str, Any], extracted: Path) -> None:
    """The acceptance check: every model's config, as bundled, hashes to the frozen value."""
    bundled = bundled_model_configs(extracted / "harness")
    for name in FROZEN_MODELS:
        want = manifest["models"][name]["config_sha256"]
        assert sha256_bytes(canon(manifest["models"][name]["config"])) == want, name
        assert sha256_bytes(canon(bundled[name])) == want, name


def test_bundle_matches_manifest_except_the_fetched_odds_history(
    manifest: dict[str, Any], extracted: Path
) -> None:
    report = verify_bundle(extracted / "frozen", extracted / "harness", manifest)
    assert report.shared_ok, (report.common_mismatches, report.harness_mismatches)
    for name in ("engine", "C3", "C1", "A"):
        assert report.model_ok(name), report.model_problems[name]
    # The raw football-data.co.uk CSVs are deliberately not redistributed in the bundle.
    assert not report.model_ok("A_odds")
    assert all("E0_" in p for p in report.model_problems["A_odds"])


def test_tampering_is_caught_per_file(manifest: dict[str, Any], tmp_path: Path) -> None:
    with tarfile.open(BUNDLE, "r:gz") as tar:
        tar.extractall(tmp_path, filter="data")
    target = tmp_path / "frozen" / "backtest" / "comp_model.py"
    target.write_text(target.read_text() + "\n# edited\n")
    report = verify_bundle(tmp_path / "frozen", tmp_path / "harness", manifest)
    assert report.shared_ok  # comp_model.py is a model file, not a common one
    assert report.model_ok("C1") and not report.model_ok("A")
    assert "comp_model.py" in (report.reason("A") or "")
    (tmp_path / "harness" / "decide.py").write_text("print('changed')\n")
    report = verify_bundle(tmp_path / "frozen", tmp_path / "harness", manifest)
    assert not report.shared_ok and not report.model_ok("engine")
    assert "harness" in (report.reason("engine") or "")


def test_edited_manifest_fails_everything(manifest: dict[str, Any], extracted: Path) -> None:
    edited = json.loads(json.dumps(manifest))
    edited["models"]["C3"]["config"]["captain_rule"] = "engine"
    report = verify_bundle(extracted / "frozen", extracted / "harness", edited)
    assert not report.manifest_ok and report.reason("C3") == "frozen manifest was edited"


# --- odds history ingest -----------------------------------------------------------------------


def _expected(payloads: dict[str, bytes]) -> dict[str, str]:
    return {rel: hashlib.sha256(b).hexdigest() for rel, b in payloads.items()}


def test_fetch_history_places_verified_files_and_caches(tmp_path: Path) -> None:
    payloads = {rel: f"csv for {rel}".encode() for rel in HISTORY}
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        return payloads[next(r for r, u in HISTORY.items() if u == url)]

    out = fetch_history(tmp_path, _expected(payloads), get)
    assert out == dict.fromkeys(HISTORY)
    assert len(calls) == 3
    assert (tmp_path / "backtest/fdcouk/E0_2526.csv").read_bytes() == payloads[
        "backtest/fdcouk/E0_2526.csv"
    ]
    assert fetch_history(tmp_path, _expected(payloads), get) == dict.fromkeys(HISTORY)
    assert len(calls) == 3  # cached: correct bytes on disk are not re-downloaded


def test_fetch_history_rejects_changed_or_unreachable_upstream(tmp_path: Path) -> None:
    payloads = dict.fromkeys(HISTORY, b"frozen")
    rels = list(HISTORY)

    def get(url: str) -> bytes:
        if url == HISTORY[rels[0]]:
            return b"publisher edited this file"
        if url == HISTORY[rels[1]]:
            raise TimeoutError
        return b"frozen"

    out = fetch_history(tmp_path, _expected(payloads), get)
    assert out[rels[0]] == "upstream file differs from the frozen copy"
    assert out[rels[1]] == "download failed (TimeoutError)"
    assert out[rels[2]] is None
    assert not (tmp_path / rels[0]).exists()  # a mismatching file is never written


def test_history_urls_are_the_publishers() -> None:
    assert all(u.startswith("https://www.football-data.co.uk/mmz4281/") for u in HISTORY.values())


# --- freshness (fail closed) ---------------------------------------------------------------------

DEADLINE = dt.datetime(2026, 10, 17, 10, 0, tzinfo=dt.UTC)


def _decision(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "gw": 7,
        "deadline": DEADLINE.isoformat(),
        "decided_at": (DEADLINE - dt.timedelta(hours=12)).isoformat(),
        "real_squad_start": {"players": [{"code": 1}]},
        "odds": {"fixtures_in_gw": 10, "fixtures_with_odds": 10, "kept": 9},
        "models": {m: {} for m in FROZEN_MODELS}
        | {"A_odds": {"info": {"odds_rows_used": 18, "odds_fallback_rows": 2}}},
    }
    doc.update(over)
    return doc


def _silver(**over: Any) -> fr.SilverStats:
    base: dict[str, Any] = {
        "refresh_ok": True,
        "refreshed_at": DEADLINE - dt.timedelta(hours=13),
        "current_season_max_gw": 6,
        "rows_by_season": {"2023/24": 29725, "2024/25": 27283, "2025/26": 29747, "2026/27": 3883},
        "xg_coverage_last_gw": 1.0,
    }
    base.update(over)
    return fr.SilverStats(**base)


GOOD_BUNDLE = BundleReport(manifest_ok=True, model_problems={m: [] for m in FROZEN_MODELS})
GOOD_ODDS = dict.fromkeys(HISTORY)


def _assess(**over: Any) -> dict[str, dict[str, Any]]:
    args: dict[str, Any] = {
        "bundle": GOOD_BUNDLE,
        "silver": _silver(),
        "last_finished": 6,
        "odds_history": GOOD_ODDS,
    }
    decision = over.pop("decision", _decision())
    args.update(over)
    return fr.assess(decision, **args)


def _unavailable(result: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {m: r["reason"] for m, r in result.items() if not r["available"]}


def test_all_fresh_means_all_available() -> None:
    assert _unavailable(_assess()) == {}


def test_live_odds_only_affect_a_odds() -> None:
    low = _decision(odds={"fixtures_in_gw": 10, "fixtures_with_odds": 5, "kept": 5})
    assert _unavailable(_assess(decision=low)) == {"A_odds": "live odds for only 5/10 fixtures"}
    none = _decision(odds={"fixtures_in_gw": 10, "fixtures_with_odds": 0, "kept": 0})
    assert _unavailable(_assess(decision=none))["A_odds"] == "no live odds for this gameweek"
    fallback = _decision()
    fallback["models"]["A_odds"] = {"info": {"odds_rows_used": 10, "odds_fallback_rows": 10}}
    assert "fell back" in _unavailable(_assess(decision=fallback))["A_odds"]


def test_odds_history_mismatch_only_affects_a_odds() -> None:
    bad = dict(GOOD_ODDS) | {
        "backtest/fdcouk/E0_2425.csv": "upstream file differs from the frozen copy"
    }
    assert list(_unavailable(_assess(odds_history=bad))) == ["A_odds"]
    assert list(_unavailable(_assess(odds_history={}))) == ["A_odds"]


def test_missing_xg_affects_c1_a_and_a_odds_not_the_engine_family() -> None:
    out = _unavailable(_assess(silver=_silver(xg_coverage_last_gw=0.4)))
    assert set(out) == {"C1", "A", "A_odds"}
    assert out["A"] == "xG/xA missing for GW6 (40%)"


@pytest.mark.parametrize(
    ("silver", "needle"),
    [
        (None, "missing"),
        ({"current_season_max_gw": 5}, "ends at GW5"),
        ({"refresh_ok": False, "refreshed_at": DEADLINE - dt.timedelta(hours=40)}, "24 h"),
        ({"rows_by_season": {"2023/24": 29725, "2024/25": 100, "2025/26": 29747}}, "2024/25"),
    ],
)
def test_stale_or_incomplete_history_makes_every_model_unavailable(
    silver: dict[str, Any] | None, needle: str
) -> None:
    out = _unavailable(_assess(silver=None if silver is None else _silver(**silver)))
    assert set(out) == set(FROZEN_MODELS)
    assert all(needle in r for r in out.values())


def test_silver_not_refreshed_this_run_but_recent_is_fresh() -> None:
    s = _silver(refresh_ok=False, refreshed_at=DEADLINE - dt.timedelta(hours=20))
    assert _unavailable(_assess(silver=s)) == {}


@pytest.mark.parametrize(
    ("decided", "needle"),
    [
        (DEADLINE + dt.timedelta(minutes=1), "after the deadline"),
        (DEADLINE - dt.timedelta(hours=37), "36 h"),
    ],
)
def test_decision_timing_bounds_availability_age(decided: dt.datetime, needle: str) -> None:
    out = _unavailable(_assess(decision=_decision(decided_at=decided.isoformat())))
    assert set(out) == set(FROZEN_MODELS) and needle in out["engine"]


def test_bundle_and_squad_failures() -> None:
    bad = BundleReport(
        manifest_ok=True,
        model_problems={"C1": ["C1: frozen input changed: x"]}
        | {m: [] for m in ("engine", "C3", "A", "A_odds")},
    )
    assert _unavailable(_assess(bundle=bad)) == {"C1": "C1: frozen input changed: x"}
    nosquad = _decision(real_squad_start={})
    assert set(_unavailable(_assess(decision=nosquad))) == set(FROZEN_MODELS)
    partial = _decision()
    del partial["models"]["engine"]
    assert _unavailable(_assess(decision=partial)) == {
        "engine": "no decision recorded for this model"
    }


def test_silver_stats_from_a_frame() -> None:
    frame = pd.DataFrame(
        {
            "season": ["2025/26"] * 2 + ["2026/27"] * 3,
            "gameweek": [38, 38, 6, 6, 5],
            "minutes": [90, 0, 90, 45, 90],
            "expected_goals": [0.1, None, 0.2, None, 0.3],
        }
    )
    s = fr.silver_stats(
        frame, season="2026/27", last_finished=6, refresh_ok=True, refreshed_at=None
    )
    assert s.current_season_max_gw == 6 and s.xg_coverage_last_gw == 0.5
    assert s.rows_by_season == {"2025/26": 2, "2026/27": 3}


# --- the record and the config hook --------------------------------------------------------------


def _ci_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "prospective_ci", REPO / "pipeline" / "scripts" / "prospective_ci.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pack_is_deterministic_and_unpack_restores_only_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ci = _ci_module()
    root = tmp_path / "root"
    (root / "decisions").mkdir(parents=True)
    (root / "decisions" / "GW7.json").write_text('{"gw": 7}')
    (root / "status").mkdir()
    (root / "status" / "GW7.json").write_text('{"gw": 7, "models": {}}')
    (root / "scores.csv").write_text("gw,model\n")
    (root / "data" / "bronze" / "fdcouk").mkdir(parents=True)
    (root / "data" / "bronze" / "fdcouk" / "GW7_fixtures.csv").write_text("Div,Date,HomeTeam\n")
    (root / "raw").mkdir()
    (root / "raw" / "big.json").write_text("{}")
    monkeypatch.setattr(ci, "ROOT", root)
    a, b = tmp_path / "a.tar.gz", tmp_path / "b.tar.gz"
    ci.pack(a)
    (root / "decisions" / "GW7.json").touch()
    ci.pack(b)
    assert a.read_bytes() == b.read_bytes()
    with tarfile.open(a) as tar:
        assert sorted(tar.getnames()) == [
            "data/bronze/fdcouk/GW7_fixtures.csv",
            "decisions/GW7.json",
            "scores.csv",
            "status/GW7.json",
        ]
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    monkeypatch.setattr(ci, "ROOT", fresh)
    ci.unpack(a)
    assert (fresh / "status" / "GW7.json").exists() and not (fresh / "raw").exists()
    assert (fresh / "data" / "bronze" / "fdcouk" / "GW7_fixtures.csv").exists()


def test_models_source_dir_can_be_set_from_the_environment() -> None:
    cfg, _ = load_config(environ={"FPL_DOF_MODELS_SOURCE_DIR": "/workspace/fpl_prospective"})
    assert cfg.publish.models.source_dir == "/workspace/fpl_prospective"


# --- provisional preview -------------------------------------------------------------------------

#: A stand-in for the frozen decide.py that misbehaves on purpose: in --dry-run it writes the
#: preview where the real one does, and also tries to write a decision, state and the kept xP
#: copy, all relative to FPL_PROSPECTIVE_ROOT / _DATA (how the real harness resolves them).
FAKE_DECIDE = """
import json, os, sys
from pathlib import Path
root = Path(os.environ["FPL_PROSPECTIVE_ROOT"])
assert "--dry-run" in sys.argv
gw = int(sys.argv[sys.argv.index("--gw") + 1])
(root / "decisions" / f"GW{gw}.json").write_text("{}")
(root / "state" / "C3.json").write_text('{"tampered": true}')
gold = Path(os.environ["FPL_PROSPECTIVE_DATA"]) / "gold" / "xp" / f"GW{gw}"
gold.mkdir(parents=True, exist_ok=True)
(gold / "xp_C3.parquet").write_bytes(b"x")
work = root / "cache" / f"dryrun_GW{gw}"
work.mkdir(parents=True, exist_ok=True)
(work / "decision_preview.json").write_text(json.dumps({"gw": gw, "models": {}}))
"""


def _harness_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    for d in ("decisions", "state", "status", "ci", "data/gold/xp/GW6", "data/bronze/fdcouk"):
        (root / d).mkdir(parents=True)
    (root / "decisions" / "GW6.json").write_text('{"gw": 6}')
    (root / "state" / "C3.json").write_text('{"next_gw": 7}')
    (root / "status" / "GW6.json").write_text('{"gw": 6, "models": {}}')
    (root / "data" / "gold" / "xp" / "GW6" / "xp_C3.parquet").write_bytes(b"frozen")
    (root / "scores.csv").write_text("gw,model\n")
    (root / "decide.py").write_text(FAKE_DECIDE)
    (root / "ci" / "plan.json").write_text('{"gw": 7, "last_finished": 6}')
    (root / "ci" / "bundle.json").write_text('{"shared_ok": true}')
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.relative_to(root).as_posix().startswith(("preview/", "ci/"))
    }


def test_preview_never_touches_decisions_state_gold_or_the_ledger_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ci = _ci_module()
    root = _harness_root(tmp_path)
    monkeypatch.setattr(ci, "ROOT", root)
    monkeypatch.setattr(ci, "PREP", root / "ci")
    monkeypatch.setattr(ci, "PREVIEW", root / "preview")
    monkeypatch.setattr(ci, "HARNESS_PY", "/nonexistent")  # falls back to this interpreter
    before = _snapshot(root)
    ci.pack(tmp_path / "before.tgz")
    assert ci.main(["preview"]) == 0
    # Byte-identical, and no new files, anywhere outside preview/ (decisions, state, data/gold/xp).
    assert _snapshot(root) == before
    ci.pack(tmp_path / "after.tgz")
    assert (tmp_path / "before.tgz").read_bytes() == (tmp_path / "after.tgz").read_bytes()
    doc = json.loads((root / "preview" / "GW7.json").read_text())
    assert doc["gw"] == 7 and doc["provisional"] is True and "preview_status" in doc
    assert not ci._in_record("preview/GW7.json")  # never packed, never restored


def test_preview_skips_a_decided_gameweek_or_an_unverified_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ci = _ci_module()
    root = _harness_root(tmp_path)
    monkeypatch.setattr(ci, "ROOT", root)
    monkeypatch.setattr(ci, "PREP", root / "ci")
    monkeypatch.setattr(ci, "PREVIEW", root / "preview")
    assert ci.preview(6) == 0 and not (root / "preview").exists()
    (root / "ci" / "bundle.json").write_text('{"shared_ok": false}')
    assert ci.preview(7) == 0 and not (root / "preview").exists()


def test_plan_creates_the_dirs_decide_writes_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """decide.py writes state/<model>.json without creating state/ (run 38974140926)."""
    ci = _ci_module()
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(ci, "ROOT", root)
    monkeypatch.setattr(ci, "_bootstrap", lambda: (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError, match="stop"):
        ci.plan()
    assert (root / "state").is_dir() and (root / "decisions").is_dir()
    assert "state" in ci.RECORD  # and the state then survives on the ledger


def _rebuild_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "rebuild_gw_state", REPO / "pipeline" / "scripts" / "rebuild_gw_state.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gw_record(root: Path) -> None:
    gold = root / "data" / "gold" / "xp" / "GW7"
    gold.mkdir(parents=True)
    (gold / "xp_engine.parquet").write_bytes(b"xp")
    real = {"players": [1, 2], "bank": 5, "free_transfers": 1, "source": "picks GW6"}
    pick = {"transfers": [], "captain_name": "X", "vice_name": "Y", "hit_points": 0}
    doc = {
        "gw": 7,
        "real_squad_start": real,
        "xp_gold_dir": "data/gold/xp/GW7",
        "xp_sha256": {"engine": hashlib.sha256(b"xp").hexdigest()},
        "models": {"engine": pick},
    }
    (root / "decisions").mkdir()
    (root / "decisions" / "GW7.json").write_text(json.dumps(doc))


def test_rebuild_state_replays_from_the_seed_and_checks_the_pick(tmp_path: Path) -> None:
    rb = _rebuild_module()
    _gw_record(tmp_path)
    seen: list[dict[str, Any]] = []

    def pdecide(pf: Any, st: dict[str, Any], gw: int, *_: Any) -> Any:
        seen.append(st)
        ns = {**st, "next_gw": gw + 1}
        return {"transfers": [], "captain_name": "X", "vice_name": "Y", "hit_points": 0}, ns

    out = rb.rebuild(tmp_path, 7, pdecide, {"engine": {"config": {}}}, None, None, Path.read_bytes)
    assert seen[0]["players"] == [1, 2] and seen[0]["next_gw"] == 7 and seen[0]["log"] == []
    assert out["engine"]["next_gw"] == 8


def test_rebuild_state_refuses_on_a_different_pick_or_hash(tmp_path: Path) -> None:
    rb = _rebuild_module()
    _gw_record(tmp_path)

    def other(pf: Any, st: dict[str, Any], gw: int, *_: Any) -> Any:
        return {"transfers": [], "captain_name": "Z", "vice_name": "Y", "hit_points": 0}, st

    with pytest.raises(SystemExit, match="captain_name"):
        rb.rebuild(tmp_path, 7, other, {"engine": {"config": {}}}, None, None, Path.read_bytes)
    (tmp_path / "data/gold/xp/GW7/xp_engine.parquet").write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="sha256"):
        rb.rebuild(tmp_path, 7, other, {"engine": {"config": {}}}, None, None, Path.read_bytes)
