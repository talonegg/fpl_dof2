"""The checked-in 2026/27 GW1-6 replay artefact matches its CSV and the reported totals."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "models_history" / "build_replay_2627.py"
ARTEFACT = ROOT / "web" / "public" / "static" / "models_history_2627_replay.json"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_replay_2627", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_artefact_is_reproducible(tmp_path: Path) -> None:
    mod = _module()
    out = tmp_path / "r.json"
    assert mod.main(["x", str(mod.CSV), str(out)]) == 0
    assert json.loads(out.read_text()) == json.loads(ARTEFACT.read_text())


def test_replay_totals_and_labels() -> None:
    doc = json.loads(ARTEFACT.read_text())
    assert doc["kind"] == "replay"
    assert doc["as_of_gameweek"] == 6
    totals = {m: sum(g["models"][m]["points"] for g in doc["gameweeks"]) for m in doc["models"]}
    # RESULTS_2627_replay.md: C3 330, engine 318, C1 308, A 300, a_odds 300 (closing odds proxy).
    assert totals == {"champion": 330, "challenger": 308, "engine": 318, "a": 300, "a_odds": 300}
    assert "a_odds" in doc["models"]
    assert "closing odds proxy" in doc["caveat"]
