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
from fpl_dof.week.evaluation import Evidence, build_evaluation
from fpl_dof.week.ledger import advice_path, read_advice, read_all_advice, record_advice

SQUAD = list(range(1, 16))


AS_OF = dt.datetime(2026, 8, 21, 12, 0, tzinfo=dt.UTC)


def _week_payload(gameweek: int, captain: int = 1) -> dict[str, object]:
    return {
        "run_id": f"run-gw{gameweek}",
        "skipped": False,
        "deadline": {"gameweek": gameweek, "deadline_utc": "2026-08-21T17:30:00Z"},
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
    path = record_advice(layout, _week_payload(5), as_of=AS_OF, now=AS_OF)
    assert path == advice_path(layout, 5)
    assert path is not None and path.name == "gw05.json"
    recorded = read_advice(layout, 5)
    assert recorded is not None
    assert recorded["run_id"] == "run-gw5"
    assert recorded["advised"]["captain"] == 1
    assert recorded["recommendation"]["transfers"] == 1


def test_a_skipped_week_records_nothing(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    assert record_advice(layout, {"run_id": "r", "skipped": True}, as_of=AS_OF, now=AS_OF) is None
    assert read_all_advice(layout) == {}


def test_rerunning_inside_a_gameweek_replaces_that_gameweek_only(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(5, captain=1), as_of=AS_OF, now=AS_OF)
    record_advice(layout, _week_payload(6, captain=3), as_of=AS_OF, now=AS_OF)
    record_advice(layout, _week_payload(6, captain=4), as_of=AS_OF, now=AS_OF)
    entries = read_all_advice(layout)
    assert sorted(entries) == [5, 6]
    assert entries[5]["advised"]["captain"] == 1
    assert entries[6]["advised"]["captain"] == 4


def _with_models(payload: dict[str, object], **models: dict[str, Any]) -> dict[str, object]:
    return payload | {"models": models}


def _success(captain: int, as_of: str) -> dict[str, Any]:
    return {
        "role": "challenger",
        "as_of": as_of,
        "trigger": "schedule",
        "advised": {"captain": captain},
    }


def _failure(reason: str, as_of: str) -> dict[str, Any]:
    return {"role": "challenger", "as_of": as_of, "trigger": "schedule", "no_advice": reason}


def test_a_later_failure_leaves_the_earlier_success_as_the_record(tmp_path: Path) -> None:
    """ORC-03, DL-94: replaced only by a newer success; a failure is noted beside it."""
    layout = DataLayout(root=tmp_path)
    later = AS_OF + dt.timedelta(hours=1)
    first = _with_models(_week_payload(5), c1=_success(7, "2026-08-21T12:00:00Z"))
    record_advice(layout, first, as_of=AS_OF, now=AS_OF)
    failed = _with_models(_week_payload(5), c1=_failure("no advice: boom", "2026-08-21T13:00:00Z"))
    record_advice(layout, failed, as_of=later, now=later)

    c1 = (read_advice(layout, 5) or {})["models"]["c1"]
    assert c1["advised"] == {"captain": 7} and c1["as_of"] == "2026-08-21T12:00:00Z"
    assert c1["last_failure"] == {"as_of": "2026-08-21T13:00:00Z", "reason": "no advice: boom"}

    latest = later + dt.timedelta(hours=1)
    again = _with_models(_week_payload(5), c1=_success(9, "2026-08-21T14:00:00Z"))
    record_advice(layout, again, as_of=latest, now=latest)
    c1 = (read_advice(layout, 5) or {})["models"]["c1"]
    assert c1["advised"] == {"captain": 9} and "last_failure" not in c1


def test_a_strategy_that_never_succeeded_records_no_advice(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    payload = _with_models(_week_payload(5), c1=_failure("no advice: boom", "2026-08-21T12:00:00Z"))
    record_advice(layout, payload, as_of=AS_OF, now=AS_OF)
    c1 = (read_advice(layout, 5) or {})["models"]["c1"]
    assert c1["no_advice"] == "no advice: boom" and "advised" not in c1


def test_failure_after_failure_keeps_since_the_first_and_a_success_ends_it(tmp_path: Path) -> None:
    """ORC-07: how long a strategy has waited is the first failure's ``as_of``, kept across runs."""
    layout = DataLayout(root=tmp_path)
    for hour in (12, 13, 14):
        moment = AS_OF.replace(hour=hour)
        failed = _failure("no advice: no odds", f"2026-08-21T{hour}:00:00Z")
        record_advice(layout, _with_models(_week_payload(5), c1=failed), as_of=moment, now=moment)
    c1 = (read_advice(layout, 5) or {})["models"]["c1"]
    assert c1["since"] == "2026-08-21T12:00:00Z" and c1["as_of"] == "2026-08-21T14:00:00Z"
    later = AS_OF.replace(hour=15)
    ok = _with_models(_week_payload(5), c1=_success(7, "2026-08-21T15:00:00Z"))
    record_advice(layout, ok, as_of=later, now=later)
    assert "since" not in (read_advice(layout, 5) or {})["models"]["c1"]


def test_a_write_mentioning_fewer_strategies_keeps_the_others(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    both = _with_models(_week_payload(5), c1=_success(7, "x"), c3=_success(1, "x"))
    record_advice(layout, both, as_of=AS_OF, now=AS_OF)
    record_advice(
        layout, _with_models(_week_payload(5), c3=_success(2, "x")), as_of=AS_OF, now=AS_OF
    )
    models = (read_advice(layout, 5) or {})["models"]
    assert models["c1"]["advised"] == {"captain": 7} and models["c3"]["advised"] == {"captain": 2}


def test_a_write_after_the_deadline_is_refused(tmp_path: Path) -> None:
    """ORC-03: the record closes at the deadline, whatever ``week`` is advising."""
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(5, captain=1), as_of=AS_OF, now=AS_OF)
    deadline = dt.datetime(2026, 8, 21, 17, 30, tzinfo=dt.UTC)
    for now in (deadline, deadline + dt.timedelta(seconds=1)):
        assert record_advice(layout, _week_payload(5, captain=4), as_of=AS_OF, now=now) is None
    assert (read_advice(layout, 5) or {})["advised"]["captain"] == 1
    undated = _week_payload(6)
    del undated["deadline"]
    assert record_advice(layout, undated, as_of=AS_OF, now=AS_OF) is None  # cannot show it open


def test_a_write_older_than_the_record_is_ignored(tmp_path: Path) -> None:
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(5, captain=1), as_of=AS_OF, now=AS_OF)
    earlier = AS_OF - dt.timedelta(hours=1)
    assert record_advice(layout, _week_payload(5, captain=4), as_of=earlier, now=AS_OF) is None
    assert (read_advice(layout, 5) or {})["advised"]["captain"] == 1


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


# --- the season log -----------------------------------------------------------------------


def _log(
    *,
    entry_id: int,
    season: str,
    picks: pd.DataFrame,
    entry_gameweeks: pd.DataFrame | None,
    chips: pd.DataFrame | None,
    advice: dict[int, dict[str, Any]],
    contract_version: int,
    rules: GameRules,
    player_gameweek: pd.DataFrame | None = None,
    player_pool: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """The season log as the pipeline builds it: each gameweek evaluated once (ORC-05), then
    logged from the evaluations."""
    evidence = Evidence(
        season=season,
        player_gameweek=player_gameweek,
        players=player_pool,
        picks=picks,
        entry_gameweeks=entry_gameweeks,
        chips=chips,
    )
    evaluations = {
        gw: build_evaluation(
            gw,
            evidence=evidence,
            advice=advice.get(gw),
            predictions={},
            rules=rules,
            entry_id=entry_id,
            as_of=AS_OF,
            run_id="r",
        )
        for gw in sorted({int(g) for g in picks["gameweek"]})
    }
    log = build_log(
        entry_id=entry_id, season=season, evaluations=evaluations, contract_version=contract_version
    )
    assert log is not None
    return log


def test_gameweeks_decided_without_the_tool_say_so(game_rules: GameRules) -> None:
    """GW1 to GW4 of 2026/27 have picks and points and no advice. Nothing is reconstructed."""
    log = _log(
        entry_id=7,
        season="2026/27",
        picks=pd.concat([_picks(1), _picks(2)], ignore_index=True),
        entry_gameweeks=_scores(1, 2),
        chips=None,
        advice={},
        contract_version=CONTRACT_VERSION,
        rules=game_rules,
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


def test_recorded_advice_is_reconciled_against_what_was_played(
    tmp_path: Path, game_rules: GameRules
) -> None:
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(5, captain=1), as_of=AS_OF, now=AS_OF)
    record_advice(layout, _week_payload(6, captain=1), as_of=AS_OF, now=AS_OF)
    log = _log(
        entry_id=7,
        season="2026/27",
        picks=pd.concat([_picks(5, captain=1), _picks(6, captain=3)], ignore_index=True),
        entry_gameweeks=_scores(5, 6),
        chips=pd.DataFrame([{"entry_id": 7, "name": "wildcard", "gameweek": 6}]),
        advice=read_all_advice(layout),
        contract_version=CONTRACT_VERSION,
        rules=game_rules,
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


def test_the_log_validates_against_its_contract(tmp_path: Path, game_rules: GameRules) -> None:
    layout = DataLayout(root=tmp_path)
    record_advice(layout, _week_payload(2), as_of=AS_OF, now=AS_OF)
    log = _log(
        entry_id=7,
        season="2026/27",
        picks=pd.concat([_picks(1), _picks(2, captain=5)], ignore_index=True),
        entry_gameweeks=_scores(1, 2),
        chips=None,
        advice=read_all_advice(layout),
        contract_version=CONTRACT_VERSION,
        rules=game_rules,
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
    record_advice(layout, payload, as_of=AS_OF, now=AS_OF)

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
                "price": 5.0,
                "total_points": 10 if pid in (1, 16) else 4,
            }
        )

    def build(gameweek_rows: list[dict[str, Any]]) -> dict[str, Any]:
        return _log(
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
    record_advice(layout, payload, as_of=AS_OF, now=AS_OF)
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
                "price": 5.0,
                "total_points": 4,
            }
            for gw in (1, 2)
            for p in range(1, 17)
        ]
    )
    return _log(
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


def test_the_optimum_is_solved_from_the_squad_held_at_the_deadline_not_the_record(
    tmp_path: Path, game_rules: GameRules
) -> None:
    """GW2's advice recorded no squad state: its optimum is solved from silver regardless (D-31).
    GW1 had no squad before it, so it has no optimum, and none is invented."""
    log = _hindsight_log(tmp_path, game_rules, None)
    gw1, gw2 = (gw["hindsight"] for gw in log["gameweeks"])
    assert "played" in {r["model_name"] for r in gw1["rankings"]}
    assert gw1["optimal"] is None and gw1["diagnostics"] == []
    assert gw1["optimal_unavailable_reason"] == "no squad was held before this gameweek"
    assert gw2["optimal"] is not None
    Contract(root=find_contracts_root()).validate("log", log)
