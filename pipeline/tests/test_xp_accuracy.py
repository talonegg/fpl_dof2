"""Per-player xP accuracy: the pure scorer, the CI and the record paths."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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


def test_paired_compares_every_strategy_with_the_champion() -> None:
    rows = []
    for gw in range(1, 11):
        for m, mae in (("C3", 1.0), ("C1", 0.9), ("engine", 1.1), ("A", 1.0)):
            rows.append(
                {"season": "s", "subset": "all", "gw": gw, "model": m, "mae": mae + 0.001 * gw}
            )
    out = paired(pd.DataFrame([*rows, {**rows[0], "model": "mystery"}]), draws=2000)
    assert all(set(r) == set(PAIRED_FIELDS) for r in out)
    # Registry order: published challengers by id.
    assert [(r["model"], r["comparator"]) for r in out] == [
        ("a", "c3"),
        ("c1", "c3"),
        ("engine", "c3"),
    ]
    assert out[1]["mean_delta"] == pytest.approx(-0.1)
