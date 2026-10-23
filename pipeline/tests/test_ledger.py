"""DL-69: the advice ledger, and the season log built from it.

What is being pinned is *provenance*: advice comes only from what was recorded before the deadline,
a gameweek with none says so rather than inventing any, and the played and scored halves come from
the game's own tables rather than from anything the pipeline computed. Being wrong here would be
invisible — a season log that looked complete and flattered the tool (DP-13).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pandas as pd

from fpl_dof.paths import DataLayout
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.season_log import build_log
from fpl_dof.rules.models import GameRules
from fpl_dof.week.ledger import advice_path, read_advice, read_all_advice, record_advice

SQUAD = list(range(1, 16))


AS_OF = dt.datetime(2026, 8, 21, 12, 0, tzinfo=dt.UTC)


def _week_payload(gameweek: int, captain: int = 1) -> dict[str, object]:
    return {
        "run_id": f"run-gw{gameweek}",
        "skipped": False,
        "recommendation": {
            "transfers": 1,
            "hit_points": 0,
            "moves": [{"out": {"player_id": 99}, "in": {"player_id": 15}}],
        },
        "squad_state": {"bank": 0.5, "free_transfers": 1},
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
    path = record_advice(layout, _week_payload(5), as_of=AS_OF)
    assert path == advice_path(layout, 5)
    assert path is not None and path.name == "gw05.json"
    recorded = read_advice(layout, 5)
    assert recorded is not None
    assert recorded["run_id"] == "run-gw5"
    assert recorded["advised"]["captain"] == 1
    assert recorded["recommendation"]["transfers"] == 1


def test_a_skipped_week_records_nothing(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    assert record_advice(layout, {"run_id": "r", "skipped": True}, as_of=AS_OF) is None
    assert read_all_advice(layout) == {}


def test_rerunning_inside_a_gameweek_replaces_that_gameweek_only(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(5, captain=1), as_of=AS_OF)
    record_advice(layout, _week_payload(6, captain=3), as_of=AS_OF)
    record_advice(layout, _week_payload(6, captain=4), as_of=AS_OF)
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
    record_advice(layout, _week_payload(5, captain=1), as_of=AS_OF)
    record_advice(layout, _week_payload(6, captain=1), as_of=AS_OF)
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
    record_advice(layout, _week_payload(2), as_of=AS_OF)
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


def test_hindsight_is_populated_and_validates_against_contract(
    tmp_path: Path, game_rules: GameRules
) -> None:
    layout = DataLayout(root=tmp_path)
    payload = _week_payload(2, captain=1)
    payload["models"] = {
        "c1": {
            "advised": {
                "starting": [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
                "bench_order": [15, 7, 12],
                "reserve_goalkeeper": 2,
                "captain": 13,
                "vice_captain": 1,
                "expected_points": 45.0,
            },
            "transfers": 0,
        }
    }
    record_advice(layout, payload, as_of=AS_OF)

    positions = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3 + ["MID"]  # 16 players
    pool_rows = []
    gw_perf_rows = []
    for pid in range(1, 17):
        pos = positions[pid - 1]
        pool_rows.append(
            {
                "player_id": pid,
                "web_name": f"P{pid}",
                "position": pos,
                "team_id": (pid % 5) + 1,
                "price": 5.0,
                "now_cost": 5.0,
                "start_cost": 5.0,
            }
        )
        gw_perf_rows.append(
            {
                "season": "2026/27",
                "gameweek": 2,
                "player_id": pid,
                "web_name": f"P{pid}",
                "position": pos,
                "minutes": 90,
                "total_points": 10 if pid in (1, 16) else 4,
            }
        )

    def build(gameweek_rows: list[dict[str, Any]]) -> dict[str, Any]:
        return build_log(
            entry_id=7,
            season="2026/27",
            picks=pd.concat([_picks(1), _picks(2, captain=1)], ignore_index=True),
            entry_gameweeks=_scores(1, 2),
            chips=None,
            advice=read_all_advice(layout),
            contract_version=CONTRACT_VERSION,
            player_gameweek=pd.DataFrame(gameweek_rows),
            player_pool=pd.DataFrame(pool_rows),
            rules=game_rules,
        )

    log = build(gw_perf_rows)
    # A backfilled season reuses ids and gameweek numbers with other points: nothing may change.
    prior = [{**row, "season": "2025/26", "total_points": 0} for row in gw_perf_rows]
    assert build(prior + gw_perf_rows) == log

    gw2 = log["gameweeks"][1]
    assert gw2["hindsight"] is not None
    assert "rankings" in gw2["hindsight"]
    assert "optimal" in gw2["hindsight"]
    assert "diagnostics" in gw2["hindsight"]
    assert len(gw2["hindsight"]["rankings"]) >= 2  # played, the champion, c1
    ranked = {r["model_name"] for r in gw2["hindsight"]["rankings"]}
    assert "c3" in ranked and "xp_v1" not in ranked  # the champion is keyed by registry id (MOD-03)
    Contract(root=find_contracts_root()).validate("log", log)


def _hindsight_log(tmp_path: Path, game_rules: GameRules, state: dict[str, float] | None) -> Any:
    layout = DataLayout(root=tmp_path)
    payload = _week_payload(2, captain=1)
    if state is None:
        del payload["squad_state"]
    else:
        payload["squad_state"] = state
    record_advice(layout, payload, as_of=AS_OF)
    positions = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3 + ["MID"]
    pool = pd.DataFrame(
        [
            {
                "player_id": p,
                "web_name": f"P{p}",
                "position": positions[p - 1],
                "team_id": (p % 5) + 1,
                "price": 5.0,
                "now_cost": 5.0,
                "start_cost": 5.0,
            }
            for p in range(1, 17)
        ]
    )
    perf = pd.DataFrame(
        [
            {
                "season": "2026/27",
                "gameweek": gw,
                "player_id": p,
                "web_name": f"P{p}",
                "position": positions[p - 1],
                "minutes": 90,
                "total_points": 4,
            }
            for gw in (1, 2)
            for p in range(1, 17)
        ]
    )
    return build_log(
        entry_id=7,
        season="2026/27",
        picks=pd.concat([_picks(1), _picks(2, captain=1)], ignore_index=True),
        entry_gameweeks=_scores(1, 2),
        chips=None,
        advice=read_all_advice(layout),
        contract_version=CONTRACT_VERSION,
        player_gameweek=perf,
        player_pool=pool,
        rules=game_rules,
    )


def test_gameweek_without_recorded_state_keeps_rankings_and_has_no_invented_optimal(
    tmp_path: Path, game_rules: GameRules
) -> None:
    log = _hindsight_log(tmp_path, game_rules, None)
    for gw in log["gameweeks"]:  # GW1 has no ledger entry; GW2's entry lacks squad_state
        h = gw["hindsight"]
        assert h is not None
        assert "played" in {r["model_name"] for r in h["rankings"]}
        assert h["optimal"] is None and h["diagnostics"] == []
        assert h["optimal_unavailable_reason"]
    Contract(root=find_contracts_root()).validate("log", log)


def test_real_zero_bank_and_free_transfers_are_kept_as_zeros(
    tmp_path: Path, game_rules: GameRules
) -> None:
    log = _hindsight_log(tmp_path, game_rules, {"bank": 0.0, "free_transfers": 0})
    assert log["gameweeks"][1]["hindsight"]["optimal"] is not None
    assert log["gameweeks"][0]["hindsight"]["optimal"] is None
