"""The checked-in 2025/26 model-history artefact and the pure assembly that builds it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.models_history import bootstrap_ci, build_models_history

ARTEFACT = (
    Path(__file__).resolve().parents[2] / "web" / "public" / "static" / "models_history_2526.json"
)


def _row(gw: int, points: float, hit: float = 0.0) -> dict[str, Any]:
    return {
        "gw": gw,
        "points": points,
        "points_before_hits": points - hit,
        "hit_points": hit,
        "n_transfers": 2 if hit else 1,
        "transfers": ["A → B"],
        "captain": "Haaland",
        "vice_captain": "Salah",
        "captain_points": 8.0,
        "vice_used": False,
        "n_autosubs": 0,
    }


def _build(**over: Any) -> dict[str, Any]:
    rows = {  # legacy keys, as the offline scripts write them: resolved through the registry
        "champion": [_row(1, 50), _row(2, 40), _row(3, 60)],
        "challenger": [_row(1, 60, -4), _row(2, 40), _row(3, 50)],
        "engine": [_row(1, 40), _row(2, 30), _row(3, 70), _row(4, 99)],
    }
    args: dict[str, Any] = {
        "season": "2025/26",
        "rows": rows,
        "unavailable": {"a": "no run"},
        "provenance": {"frozen_tag": "t"},
        "contract_version": CONTRACT_VERSION,
    } | over
    return build_models_history(**args)


def test_built_payload_matches_schema() -> None:
    Contract(root=find_contracts_root()).validate("models_history", _build())


def test_only_common_gameweeks_are_compared() -> None:
    p = _build()
    assert [g["gameweek"] for g in p["gameweeks"]] == [1, 2, 3]  # engine's GW4 has no pair


def test_ranks_cumulative_and_ties() -> None:
    p = _build()
    gw1, gw2, gw3 = (g["models"] for g in p["gameweeks"])
    assert (gw1["c1"]["rank"], gw1["c3"]["rank"], gw1["engine"]["rank"]) == (1, 2, 3)
    assert gw2["c3"]["rank"] == gw2["c1"]["rank"] == 1  # tie shares the better rank
    assert gw3["engine"]["cumulative"] == 140 and gw3["c3"]["cumulative"] == 150
    assert gw3["c3"]["cumulative_rank"] == 1 and gw3["c1"]["cumulative_rank"] == 1
    assert gw1["c1"]["hit_points"] == -4


def test_summary_and_deltas() -> None:
    s = {x["model"]: x for x in _build()["summary"]}
    assert s["c3"]["delta_vs_champion"] is None
    d = s["engine"]["delta_vs_champion"]
    assert d["total"] == -10 and d["mean"] == pytest.approx(-3.33, abs=0.01)
    assert d["gameweeks_better"] == 1 and d["gameweeks_worse"] == 2
    assert d["ci_low"] <= d["mean"] <= d["ci_high"]
    assert s["c1"]["gameweeks_won"] == 2  # GW1 outright + GW2 shared
    assert s["c1"]["hit_points"] == -4


def test_unavailable_models_are_marked_not_invented() -> None:
    p = _build()
    a = next(m for m in p["models"] if m["id"] == "a")
    assert a["available"] is False and a["unavailable_reason"] == "no run"
    assert all("a" not in g["models"] for g in p["gameweeks"])
    assert p["kind"] == "backtest" and "not real play" in p["caveat"]


def test_bootstrap_is_seeded_and_brackets_a_constant() -> None:
    assert bootstrap_ci([1.0, 2.0, 3.0, 4.0]) == bootstrap_ci([1.0, 2.0, 3.0, 4.0])
    assert bootstrap_ci([2.0] * 10) == (2.0, 2.0)
    assert bootstrap_ci([]) == (0.0, 0.0)


def test_checked_in_artefact_is_valid_and_consistent() -> None:
    payload = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    Contract(root=find_contracts_root()).validate("models_history", payload)
    assert payload["season"] == "2025/26" and payload["kind"] == "backtest"
    assert len(payload["gameweeks"]) == 38
    for s in payload["summary"]:
        pts = [g["models"][s["model"]]["points"] for g in payload["gameweeks"]]
        assert s["total"] == sum(pts)
        assert payload["gameweeks"][-1]["models"][s["model"]]["cumulative"] == s["total"]
    totals = {s["model"]: s["total"] for s in payload["summary"]}
    # Engine, C3 and C1 reproduce RESULTS_autosubs.md (L1, auto-subs, 2025/26 pts/GW x 38).
    assert totals["engine"] == 1804 and totals["champion"] == 1818 and totals["challenger"] == 1929
