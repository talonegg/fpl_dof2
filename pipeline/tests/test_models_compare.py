"""The five-model comparison artefact: assembled from the harness record, never re-scored."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from fpl_dof.config.models import ModelsArtefactConfig, SourcesConfig
from fpl_dof.paths import DataLayout
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.models_compare import build_models
from fpl_dof.rules.models import GameRules
from fpl_dof.stages import publish
from fpl_dof.week.evaluation import Evidence, build_evaluation

#: The frozen harness's own model keys, as its records carry them.
HARNESS_KEYS = ("C3", "C1", "engine", "A", "A_odds")


def _pick(cap: int, xp: float, hit: int = 0) -> dict[str, Any]:
    return {
        "transfers": [{"out": 101, "out_name": "Out", "in": 111, "in_name": "In"}] if hit else [],
        "n_transfers": 2 if hit else 0,
        "hit_points": hit,
        "xi": list(range(100, 111)),
        "xi_names": [f"P{i}" for i in range(11)],
        "bench_order": [112, 113, 114],
        "bench_gk": 115,
        "bench_names": ["GK2", "B1", "B2", "B3"],
        "captain": cap,
        "captain_name": f"P{cap - 100}",
        "vice": 100,
        "vice_name": "P0",
        "xp_xi": xp,
    }


def _decision(gw: int) -> dict[str, Any]:
    keys = HARNESS_KEYS
    return {
        "gw": gw,
        "deadline": f"2026-10-{gw:02d}T09:00:00+00:00",
        "decided_at": f"2026-10-{gw:02d}T01:00:00+00:00",
        "code_commit": "79e080c",
        "code_to_element": {str(c): c - 99 for c in range(100, 116)},
        "models": {k: _pick(105, 50.0 + i, hit=-4 if k == "C1" else 0) for i, k in enumerate(keys)}
        | {"mystery": _pick(101, 1.0)},
    }


def _score(gw: int, model: str, points: float) -> dict[str, Any]:
    return {
        "gw": gw,
        "model": model,
        "points": points,
        "points_before_hits": points + 4 if model == "C1" else points,
        "hit_points": -4 if model == "C1" else 0,
        "n_autosubs": 1,
        "vice_used": "False",
        "armband_pts": 12,
    }


def _ok(*stale: str) -> dict[str, Any]:
    keys = HARNESS_KEYS
    return {
        "models": {
            k: {"available": k not in stale, "reason": "live odds missing" if k in stale else None}
            for k in keys
        }
    }


def _payload(statuses: dict[int, Any] | None = None) -> dict[str, Any]:
    payload = build_models(
        season="2026/27",
        decisions=[_decision(8), _decision(7)],
        scores=[_score(7, "C3", 60), _score(7, "C1", 52), _score(7, "A", 70), _score(9, "C3", 1)],
        frozen_tag="frozen-2026-10-13",
        contract_version=CONTRACT_VERSION,
        statuses={7: _ok(), 8: _ok()} if statuses is None else statuses,
    )
    assert payload is not None
    return payload


def test_none_without_decisions() -> None:
    assert (
        build_models(season="s", decisions=[], scores=[], frozen_tag=None, contract_version=1)
        is None
    )


def test_payload_matches_schema() -> None:
    Contract(root=find_contracts_root()).validate("models", _payload())


def test_all_five_models_in_display_order_champion_first() -> None:
    p = _payload()
    # Registry order: the champion, then published challengers by id.
    assert [m["id"] for m in p["models"]] == ["c3", "a", "a_odds", "c1", "engine"]
    assert [m["key"] for m in p["models"]] == ["C3", "A", "A_odds", "C1", "engine"]
    assert p["champion"] == "c3"
    assert p["models"][0]["role"] == "champion"
    assert {m["role"] for m in p["models"][1:]} == {"challenger"}


def test_advice_maps_codes_to_element_ids_and_keeps_hits() -> None:
    gw7 = _payload()["gameweeks"][0]
    assert gw7["gameweek"] == 7
    champ = gw7["advice"]["c3"]
    assert champ["starting"] == list(range(1, 12))
    assert champ["bench_order"] == [16, 13, 14, 15]  # GK first, then outfield order
    assert champ["captain"] == 6 and champ["vice_captain"] == 1
    assert gw7["advice"]["c1"]["hit_points"] == -4
    assert gw7["advice"]["c1"]["transfers"][0] == {
        "out": 2,
        "out_name": "Out",
        "in": 12,
        "in_name": "In",
    }
    assert "mystery" not in gw7["advice"]


def test_actuals_and_season_to_date() -> None:
    p = _payload()
    gw7, gw8 = p["gameweeks"]
    assert gw7["actual"]["c1"]["points"] == 52
    assert gw7["actual"]["c1"]["hit_points"] == -4
    assert gw8["actual"] is None  # not finished yet
    totals = {s["model"]: s for s in p["season_to_date"]}
    assert totals["a"]["total"] == 70 and totals["a"]["gameweeks_scored"] == 1
    assert totals["engine"]["gameweeks_scored"] == 0
    # A score for a gameweek with no recorded advice is unattributable and ignored.
    assert totals["c3"]["per_gameweek"] == [{"gameweek": 7, "points": 60, "cumulative": 60}]


def _ctx(source: Path | None, data: Path | None = None) -> Any:
    cfg = ModelsArtefactConfig(source_dir=str(source) if source else None)
    return SimpleNamespace(
        config=SimpleNamespace(
            publish=SimpleNamespace(models=cfg),
            runtime=SimpleNamespace(trigger="manual"),
            sources=SourcesConfig(),
        ),
        layout=DataLayout(root=data or (source or Path()) / "_data"),
        as_of=dt.datetime(2026, 10, 9, 7, tzinfo=dt.UTC),
    )


def test_stage_reads_harness_dir(tmp_path: Path) -> None:
    (tmp_path / "decisions").mkdir()
    (tmp_path / "decisions" / "GW7.json").write_text(json.dumps(_decision(7)))
    (tmp_path / "status").mkdir()
    (tmp_path / "status" / "GW7.json").write_text(json.dumps(_ok("A_odds")))
    (tmp_path / "scores.csv").write_text(
        "gw,model,points,points_before_hits,hit_points,n_autosubs,vice_used,armband_pts\n"
        "7,C3,61,61,0,0,True,0\n"
    )
    payload = publish._models(_ctx(tmp_path), "2026/27")
    assert payload is not None
    assert payload["gameweeks"][0]["actual"]["c3"]["vice_used"] is True
    assert (payload["as_of"], payload["trigger"]) == ("2026-10-09T07:00:00Z", "manual")
    assert payload["gameweeks"][0]["availability"]["a_odds"] == {
        "available": False,
        "reason": "live odds missing",
    }


def test_stale_model_is_unavailable_with_reason_and_no_partial_data() -> None:
    p = _payload({7: _ok("A"), 8: _ok("A_odds")})
    Contract(root=find_contracts_root()).validate("models", p)
    gw7, gw8 = p["gameweeks"]
    assert "a" not in gw7["advice"] and "a" not in (gw7["actual"] or {})
    assert gw7["availability"]["a"] == {"available": False, "reason": "live odds missing"}
    assert "a" in gw8["advice"] and "a_odds" not in gw8["advice"]
    totals = {s["model"]: s for s in p["season_to_date"]}
    assert totals["a"]["gameweeks_scored"] == 0  # GW7's A points are withheld with its advice
    info = {m["id"]: m for m in p["models"]}
    assert info["a_odds"]["available"] is False
    assert info["a_odds"]["unavailable_reason"] == "live odds missing"
    assert info["c3"]["available"] is True


def test_missing_check_fails_closed() -> None:
    p = _payload({8: _ok()})  # GW7 has no recorded input check
    gw7 = p["gameweeks"][0]
    assert gw7["advice"] == {} and gw7["actual"] is None
    assert gw7["availability"]["c3"]["reason"].startswith("no input-freshness check")


# --- the switch to the live ledger (MOD-06) ---------------------------------------------------


def _evaluated(gw: int, entry: dict[str, Any], rules: GameRules) -> dict[str, Any]:
    """The gameweek's evaluation (ORC-05): player i played 90 minutes and scored i points."""
    positions = ["GKP"] + ["DEF"] * 4 + ["MID"] * 4 + ["FWD"] * 2 + ["GKP"] + ["DEF"] * 3
    rows = pd.DataFrame(
        [
            {
                "season": "2026/27",
                "gameweek": gw,
                "player_id": i + 1,
                "position": p,
                "minutes": 90,
                "total_points": i + 1,
            }
            for i, p in enumerate(positions)
        ]
    )
    return build_evaluation(
        gw,
        evidence=Evidence(season="2026/27", player_gameweek=rows, players=None),
        advice=entry,
        predictions={},
        rules=rules,
        entry_id=None,
        as_of=dt.datetime(2026, 10, 30, tzinfo=dt.UTC),
        run_id="r",
    )


def _ledger_entry(gw: int, transfers: int, free: int) -> dict[str, Any]:
    def model(role: str, captain: int, moves: int) -> dict[str, Any]:
        move = {
            "out": {"player_id": 3, "web_name": "Out", "price": 5.0},
            "in": {"player_id": 16, "web_name": "In", "price": 5.0},
        }
        return {
            "role": role,
            "transfers": moves,
            "advised": {
                "gameweek": gw,
                "starting": list(range(1, 12)),
                "bench_order": [13, 14, 15],
                "reserve_goalkeeper": 12,
                "captain": captain,
                "vice_captain": 1,
                "expected_points": 50.0,
            },
            "recommendation": {
                "transfers": moves,
                "hit_points": -4 * max(0, moves - free),
                "moves": [move] * moves,
            },
        }

    return {
        "gameweek": gw,
        "recorded_at": f"2026-10-{gw:02d}T08:00:00Z",
        "squad_state": {"free_transfers": free},
        "models": {
            # Stamped as R1.3.0 records it (ORC-03); c1 is a pre-R1.3.0 entry with no stamp.
            "c3": model("champion", 11, 0)
            | {"as_of": f"2026-10-{gw:02d}T07:00:00Z", "trigger": "schedule"},
            "c1": model("challenger", 10, transfers),
            "a": {"role": "challenger", "no_advice": "no advice: odds missing"},
        },
    }


def test_the_switch_gameweek_follows_the_last_frozen_decision(game_rules: GameRules) -> None:
    p = build_models(
        season="2026/27",
        decisions=[_decision(7), _decision(8)],
        scores=[_score(8, "C3", 60)],
        frozen_tag="t",
        contract_version=CONTRACT_VERSION,
        statuses={7: _ok(), 8: _ok()},
        ledger={
            8: _ledger_entry(8, 0, 1),  # before the switch: the frozen record owns it
            9: _ledger_entry(9, 2, 2),
            10: _ledger_entry(10, 2, 1),
        },
        evaluations={9: _evaluated(9, _ledger_entry(9, 2, 2), game_rules)},
        names={3: "Out", 16: "In", 11: "Cap"},
    )
    assert p is not None
    Contract(root=find_contracts_root()).validate("models", p)
    assert p["switch_gameweek"] == 9
    assert [(g["gameweek"], g["record"]) for g in p["gameweeks"]] == [
        (7, "frozen"),
        (8, "frozen"),
        (9, "live"),
        (10, "live"),
    ]
    gw9, gw10 = p["gameweeks"][2:]
    assert gw9["advice"]["c3"]["captain_name"] == "Cap"
    assert (gw9["advice"]["c3"]["as_of"], gw9["advice"]["c3"]["trigger"]) == (
        "2026-10-09T07:00:00Z",
        "schedule",
    )
    assert "as_of" not in gw9["advice"]["c1"]
    assert gw9["advice"]["c1"]["transfers"][0]["in_name"] == "In"
    assert gw9["availability"]["a"] == {"available": False, "reason": "no advice: odds missing"}
    # Two moves with the two free transfers the owner really had cost nothing.
    assert gw9["actual"]["c1"]["hit_points"] == 0
    assert gw10["actual"] is None  # not finished
    totals = {s["model"]: s for s in p["season_to_date"]}
    assert totals["c3"]["per_gameweek"][-1]["gameweek"] == 9


def test_an_unscored_frozen_decision_gives_way_to_the_live_ledger(game_rules: GameRules) -> None:
    p = build_models(
        season="2026/27",
        decisions=[_decision(7), _decision(8)],
        scores=[_score(7, "C3", 60)],  # GW8 was decided but the harness never scored it
        frozen_tag="t",
        contract_version=CONTRACT_VERSION,
        statuses={7: _ok(), 8: _ok()},
        ledger={8: _ledger_entry(8, 0, 1)},
        evaluations={8: _evaluated(8, _ledger_entry(8, 0, 1), game_rules)},
    )
    assert p is not None and p["switch_gameweek"] == 8
    assert [(g["gameweek"], g["record"]) for g in p["gameweeks"]] == [(7, "frozen"), (8, "live")]
    assert p["gameweeks"][1]["actual"] is not None


def test_two_moves_on_one_free_transfer_cost_a_hit(game_rules: GameRules) -> None:
    p = build_models(
        season="2026/27",
        decisions=[],
        scores=[],
        frozen_tag=None,
        contract_version=CONTRACT_VERSION,
        ledger={5: _ledger_entry(5, 2, 1)},
        evaluations={5: _evaluated(5, _ledger_entry(5, 2, 1), game_rules)},
    )
    assert p is not None and p["switch_gameweek"] is None
    assert p["gameweeks"][0]["actual"]["c1"]["hit_points"] == 4
    assert p["gameweeks"][0]["record"] == "live"


@pytest.mark.parametrize("make", ["unset", "empty", "corrupt"])
def test_stage_returns_none_when_absent_or_bad(tmp_path: Path, make: str) -> None:
    if make == "corrupt":
        (tmp_path / "decisions").mkdir()
        (tmp_path / "decisions" / "GW7.json").write_text("{not json")
    assert publish._models(_ctx(None if make == "unset" else tmp_path), "2026/27") is None


def test_a_strategy_waiting_for_a_source_names_it_since_when_and_the_next_check() -> None:
    """ORC-07: the ledger's ``missing`` tables name the source; ``next_check`` is the Open
    gameweek's only, and a failure that is not a missing source names none."""
    waiting = {
        "role": "challenger",
        "as_of": "2026-10-10T08:00:00Z",
        "since": "2026-10-09T02:00:00Z",
        "no_advice": "no advice: MissingOddsError: no match odds knowable",
        "missing": ["team_match_expectation"],
    }
    broken = {"role": "challenger", "as_of": "2026-10-10T08:00:00Z", "no_advice": "boom"}
    ledger = {
        gw: {"gameweek": gw, "recorded_at": "x", "models": {"a_odds": waiting, "c1": broken}}
        for gw in (9, 10)
    }
    p = build_models(
        season="2026/27",
        decisions=[],
        scores=[],
        frozen_tag=None,
        contract_version=CONTRACT_VERSION,
        ledger=ledger,
        sources={"team_match_expectation": ["Match odds"], "fixture": []},
        open_gameweek=10,
        next_check="2026-10-10T09:07:00Z",
    )
    assert p is not None
    Contract(root=find_contracts_root()).validate("models", p)
    gw9, gw10 = (g["availability"] for g in p["gameweeks"])
    assert gw10["a_odds"] == {
        "available": False,
        "reason": waiting["no_advice"],
        "sources": ["Match odds"],
        "since": "2026-10-09T02:00:00Z",
        "next_check": "2026-10-10T09:07:00Z",
    }
    assert gw9["a_odds"]["next_check"] is None  # no longer Open: nothing is checked for it
    assert gw10["c1"] == {"available": False, "reason": "boom"}
