"""Per-player xP accuracy: the pure scorer, the CI script score_xp.py and the record paths."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest

from fpl_dof.prospective.xp_accuracy import (
    PAIRED_FIELDS,
    SCORE_FIELDS,
    holm,
    paired,
    population,
    score_gw,
    signflip_p,
)

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name, REPO / "pipeline" / "scripts" / f"{name}.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _xp(vals: dict[int, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"player": list(vals), "position": ["MID"] * len(vals), "xp": list(vals.values())}
    )


def test_population_is_the_paired_intersection_and_counts_drops() -> None:
    xp = {"C3": _xp({1: 1.0, 2: 2.0, 3: 0.0}), "C1": _xp({1: 1.5, 2: 1.0})}
    act = pd.DataFrame({"player": [1, 2, 3], "actual": [2, 0, 0], "minutes": [90, 0, 0]})
    pop, dropped = population(xp, act)
    assert sorted(pop["player"]) == [1, 2]
    assert dropped == {"C3": 1, "C1": 0}


def test_score_gw_metrics_and_schema() -> None:
    xp = {"C3": _xp({1: 1.0, 2: 2.0}), "C1": _xp({1: 2.0, 2: 0.0})}
    act = pd.DataFrame(
        {"player": [1, 2], "actual": [2, 0], "minutes": [90, 0], "avail": [1.0, 0.5]}
    )
    rows = score_gw(season="2026/27", gw=7, xp=xp, actual=act, xp_sha256={"C3": "abc"})
    assert all(set(r) == set(SCORE_FIELDS) for r in rows)
    by = {(r["model"], r["subset"]): r for r in rows}
    c3 = by[("C3", "all")]
    assert c3["mae"] == pytest.approx(1.5) and c3["mse"] == pytest.approx(2.5)
    assert c3["rmse"] == pytest.approx(np.sqrt(2.5)) and c3["bias"] == pytest.approx(0.5)
    assert c3["zero_min_mean_xp"] == pytest.approx(2.0) and c3["xp_file_sha256"] == "abc"
    assert by[("C1", "all")]["mae"] == 0
    assert by[("C1", "avail_prior")]["n_rows"] == 1  # avail 0.5 < 0.75 drops player 2


def test_signflip_and_holm() -> None:
    assert signflip_p(np.full(20, -0.05), draws=2000) < 0.01
    assert holm([0.01, 0.04, float("nan")])[:2] == [0.02, 0.04]


def test_paired_primary_is_c1_vs_c3() -> None:
    rows = []
    for gw in range(1, 11):
        for m, mae in (("C3", 1.0), ("C1", 0.9), ("engine", 1.1), ("A", 1.0)):
            rows.append(
                {"season": "s", "subset": "all", "gw": gw, "model": m, "mae": mae + 0.001 * gw}
            )
    out = paired(pd.DataFrame(rows), draws=2000)
    assert all(set(r) == set(PAIRED_FIELDS) for r in out)
    prim = [r for r in out if r["family"] == "primary"]
    assert [(r["model"], r["comparator"]) for r in prim] == [("C1", "C3")]
    assert prim[0]["mean_delta"] == pytest.approx(-0.1)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _record(root: Path, gw: int, tamper: bool = False) -> None:
    gold = root / "data" / "gold" / "xp" / f"GW{gw}"
    gold.mkdir(parents=True)
    shas = {}
    for name, vals in (("C3", [1.0, 2.0]), ("C1", [2.0, 0.0])):
        d = pd.DataFrame({"player_id": [101, 102], "position": ["MID", "FWD"], "xp_next": vals})
        p = gold / f"xp_{name}.parquet"
        d.to_parquet(p)
        shas[name] = _sha(p.read_bytes())
    av = gold / "avail.parquet"
    pd.DataFrame({"player_id": [101, 102], "avail": [1.0, 1.0]}).to_parquet(av)
    shas["avail"] = "0" * 64 if tamper else _sha(av.read_bytes())
    doc = {
        "gw": gw,
        "xp_sha256": shas,
        "xp_gold_dir": f"data/gold/xp/GW{gw}",
        "code_to_element": {"101": 1, "102": 2},
    }
    (root / "decisions").mkdir(exist_ok=True)
    (root / "decisions" / f"GW{gw}.json").write_text(json.dumps(doc))


class _Feed:
    """The live reads ``score_xp.run`` makes, served from fixed data."""

    def state(self) -> dict[str, Any]:
        return {
            "events": [
                {"id": 7, "finished": True, "data_checked": True},
                {"id": 8, "finished": True, "data_checked": True},
            ]
        }

    def gameweek_live(self, gameweek: int) -> dict[str, Any]:
        return {"elements": [{"id": 1, "stats": {"total_points": 2, "minutes": 90}}]}


def test_score_xp_scores_once_and_refuses_a_tampered_file(tmp_path: Path) -> None:
    mod = _load("score_xp")
    _record(tmp_path, 7)
    _record(tmp_path, 8, tamper=True)
    now = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)
    assert mod.run(tmp_path, _Feed(), now) == 0
    s = pd.read_csv(tmp_path / "xp_scores.csv")
    assert list(s.columns) == list(SCORE_FIELDS)
    assert set(s["gw"]) == {7}  # GW8 avail hash mismatch -> not scored
    c1 = s[(s.model == "C1") & (s.subset == "all")].iloc[0]
    assert c1["mae"] == 0 and c1["n_rows"] == 2
    assert (tmp_path / "xp_scores_paired.csv").exists() and (
        tmp_path / "xp_calibration.csv"
    ).exists()
    assert mod.run(tmp_path, _Feed(), now) == 0
    assert len(pd.read_csv(tmp_path / "xp_scores.csv")) == len(s)  # idempotent


def test_record_keeps_gold_xp_and_rejects_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROSPECTIVE_ROOT", str(tmp_path))
    mod = _load("prospective_ci")
    assert mod._in_record("data/gold/xp/GW7/xp_C1.parquet")
    assert mod._in_record("xp_scores.csv")
    assert not mod._in_record("data/silver/x.parquet")
    assert not mod._in_record("../evil")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name in ("data/gold/xp/GW7/xp_C1.parquet", "data/silver/s.parquet"):
            info = tarfile.TarInfo(name)
            info.size = 1
            t.addfile(info, io.BytesIO(b"x"))
    tb = tmp_path / "r.tgz"
    tb.write_bytes(buf.getvalue())
    mod.unpack(tb)
    assert (tmp_path / "data/gold/xp/GW7/xp_C1.parquet").exists()
    assert not (tmp_path / "data/silver/s.parquet").exists()
