"""DL-69: the advice ledger, and the season log built from it.

What is being pinned is *provenance*: advice comes only from what was recorded before the deadline,
a gameweek with none says so rather than inventing any, and the played and scored halves come from
the game's own tables rather than from anything the pipeline computed. Being wrong here would be
invisible — a season log that looked complete and flattered the tool (DP-13).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fpl_dof.paths import DataLayout
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.season_log import build_log
from fpl_dof.week.ledger import advice_path, read_advice, read_all_advice, record_advice

SQUAD = list(range(1, 16))


def _week_payload(gameweek: int, captain: int = 1) -> dict[str, object]:
    return {
        "run_id": f"run-gw{gameweek}",
        "skipped": False,
        "recommendation": {
            "transfers": 1,
            "hit_points": 0,
            "moves": [{"out": {"player_id": 99}, "in": {"player_id": 15}}],
        },
        "squad_state": {"bank": 0.5},
        "advised": {
            "gameweek": gameweek,
            "squad": SQUAD,
            "starting": SQUAD[:11],
            "bench_order": SQUAD[11:],
            "captain": captain,
            "vice_captain": 2,
            "expected_points": 52.4,
        },
    }


def _picks(gameweek: int, captain: int = 1, squad: list[int] | None = None) -> pd.DataFrame:
    members = squad or SQUAD
    return pd.DataFrame(
        [
            {
                "entry_id": 7,
                "gameweek": gameweek,
                "player_id": pid,
                "slot": index + 1,
                "multiplier": (2 if pid == captain else 1) if index < 11 else 0,
                "is_captain": pid == captain,
                "is_vice_captain": pid == 2,
                "purchase_price": None,
                "selling_price": None,
            }
            for index, pid in enumerate(members)
        ]
    )


def _scores(*gameweeks: int) -> pd.DataFrame:
    total = 0
    rows = []
    for gameweek in gameweeks:
        total += 50 + gameweek
        rows.append(
            {
                "entry_id": 7,
                "gameweek": gameweek,
                "points": 50 + gameweek,
                "total_points": total,
                "rank": 1000,
                "overall_rank": 2000,
                "bank": 0.5,
                "squad_value": 100.0,
                "transfers": 1,
                "transfers_cost": 0,
                "points_on_bench": 3,
            }
        )
    return pd.DataFrame(rows)


# --- the ledger ------------------------------------------------------------------------------


def test_advice_is_recorded_under_its_gameweek(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    path = record_advice(layout, _week_payload(5))
    assert path == advice_path(layout, 5)
    assert path is not None and path.name == "gw05.json"
    recorded = read_advice(layout, 5)
    assert recorded is not None
    assert recorded["run_id"] == "run-gw5"
    assert recorded["advised"]["captain"] == 1
    assert recorded["recommendation"]["transfers"] == 1


def test_a_skipped_week_records_nothing(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    assert record_advice(layout, {"run_id": "r", "skipped": True}) is None
    assert read_all_advice(layout) == {}


def test_rerunning_inside_a_gameweek_replaces_that_gameweek_only(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(5, captain=1))
    record_advice(layout, _week_payload(6, captain=3))
    record_advice(layout, _week_payload(6, captain=4))
    entries = read_all_advice(layout)
    assert sorted(entries) == [5, 6]
    assert entries[5]["advised"]["captain"] == 1
    assert entries[6]["advised"]["captain"] == 4


def test_a_corrupt_entry_is_reported_as_absent_not_raised(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    path = advice_path(layout, 3)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert read_advice(layout, 3) is None
    assert read_all_advice(layout) == {}


def test_an_entry_filed_under_the_wrong_gameweek_is_refused(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    path = advice_path(layout, 3)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"gameweek": 4, "advised": {}}), encoding="utf-8")
    assert read_advice(layout, 3) is None


# --- the season log --------------------------------------------------------------------------


def test_gameweeks_decided_without_the_tool_say_so() -> None:
    """GW1 to GW4 of 2026/27 have picks and points and no advice. Nothing is reconstructed."""
    log = build_log(
        entry_id=7,
        season="2026/27",
        picks=pd.concat([_picks(1), _picks(2)], ignore_index=True),
        entry_gameweeks=_scores(1, 2),
        chips=None,
        advice={},
        contract_version=CONTRACT_VERSION,
    )
    assert [row["gameweek"] for row in log["gameweeks"]] == [1, 2]
    for row in log["gameweeks"]:
        assert row["advised"] is None
        assert row["reconciliation"] is None
        assert row["score"] is not None
        assert row["played"]["captain"] == 1
        assert len(row["played"]["starting"]) == 11
        assert len(row["played"]["bench_order"]) == 4
    assert log["summary"] == {
        "gameweeks_played": 2,
        "gameweeks_advised": 0,
        "advice_followed": 0,
        "advice_overridden": 0,
        "total_points": 103,
    }


def test_recorded_advice_is_reconciled_against_what_was_played(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(5, captain=1))
    record_advice(layout, _week_payload(6, captain=1))
    log = build_log(
        entry_id=7,
        season="2026/27",
        picks=pd.concat([_picks(5, captain=1), _picks(6, captain=3)], ignore_index=True),
        entry_gameweeks=_scores(5, 6),
        chips=pd.DataFrame([{"entry_id": 7, "name": "wildcard", "gameweek": 6}]),
        advice=read_all_advice(layout),
        contract_version=CONTRACT_VERSION,
    )
    followed, overridden = log["gameweeks"]
    assert followed["advised"]["run_id"] == "run-gw5"
    assert followed["advised"]["moves"] == [{"out": 99, "in": 15}]
    assert followed["reconciliation"] == {"followed": True, "divergences": []}
    assert followed["chip"] is None

    assert overridden["chip"] == "wildcard"
    assert overridden["reconciliation"]["followed"] is False
    kinds = {d["kind"]: d["status"] for d in overridden["reconciliation"]["divergences"]}
    assert kinds == {"captain": "unexplained"}
    assert log["summary"]["advice_followed"] == 1
    assert log["summary"]["advice_overridden"] == 1


def test_a_gameweek_the_game_has_not_scored_yet_has_a_null_score() -> None:
    log = build_log(
        entry_id=7,
        season="2026/27",
        picks=_picks(3),
        entry_gameweeks=None,
        chips=None,
        advice={},
        contract_version=CONTRACT_VERSION,
    )
    assert log["gameweeks"][0]["score"] is None
    assert log["summary"]["total_points"] == 0


def test_the_log_validates_against_its_contract(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(2))
    log = build_log(
        entry_id=7,
        season="2026/27",
        picks=pd.concat([_picks(1), _picks(2, captain=5)], ignore_index=True),
        entry_gameweeks=_scores(1, 2),
        chips=None,
        advice=read_all_advice(layout),
        contract_version=CONTRACT_VERSION,
    )
    Contract(root=find_contracts_root()).validate("log", log)
