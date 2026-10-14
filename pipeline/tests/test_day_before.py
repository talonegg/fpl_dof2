"""Day-before refresh: the gate, the prospective veto, and the fail-closed contract check."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.week.day_before import (
    CRON_UTC_HOURS,
    SYDNEY,
    gate,
    nominal_fire_time,
    veto_plan,
)

REPO = Path(__file__).resolve().parents[2]
UTC = dt.UTC


def _script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        name, REPO / "pipeline" / "scripts" / f"{name}.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bs(*deadlines: str, finished: tuple[bool, ...] = ()) -> dict[str, Any]:
    return {
        "events": [
            {
                "id": i + 6,
                "deadline_time": d,
                "finished": (finished[i] if i < len(finished) else False),
            }
            for i, d in enumerate(deadlines)
        ]
    }


def at(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso)


# GW7: Sat 17 Oct 2026 10:00 UTC = 21:00 AEDT. GW8: Fri 23 Oct 17:30 UTC = Sat 24 Oct 04:30 AEDT.
GW7, GW8 = "2026-10-17T10:00:00Z", "2026-10-23T17:30:00Z"


def test_saturday_deadline_runs_friday_0700_aedt() -> None:
    now = at("2026-10-15T20:03:00+00:00")  # Fri 16 Oct 07:03 AEDT
    d = gate(now=now, bootstrap=bs("2026-10-10T10:00:00Z", GW7), cron_hour=20)
    assert d.run and d.gameweek == 7, d.reason
    assert "Sat 17 Oct 21:00 AEDT" in d.reason and "10:00 UTC" in d.reason


def test_the_other_cron_is_a_no_op_the_same_morning() -> None:
    now = at("2026-10-15T21:02:00+00:00")  # 08:02 AEDT: the AEST cron
    d = gate(now=now, bootstrap=bs(GW7), cron_hour=21)
    assert not d.run and "08:00 AEDT" in d.reason


def test_late_start_is_judged_by_its_nominal_time() -> None:
    now = at("2026-10-15T20:55:00+00:00")  # the 20:00 cron, started 55 min late
    assert nominal_fire_time(now, 20) == at("2026-10-15T20:00:00+00:00")
    assert gate(now=now, bootstrap=bs(GW7), cron_hour=20).run
    late_past_midnight = at("2026-10-16T00:10:00+00:00")
    assert nominal_fire_time(late_past_midnight, 21) == at("2026-10-15T21:00:00+00:00")


def test_early_saturday_deadline_runs_friday_too() -> None:
    """GW8 is Sat 04:30 AEDT; the day before in Sydney is Friday (not Thursday)."""
    d = gate(
        now=at("2026-10-22T20:00:00+00:00"),
        bootstrap=bs("2026-10-10T10:00:00Z", GW7, GW8),
        cron_hour=20,
    )
    assert d.run and d.gameweek == 8, d.reason


@pytest.mark.parametrize(
    ("now", "cron", "runs"),
    [
        # AEST -> AEDT starts Sun 4 Oct 2026 02:00. Deadline Sun 4 Oct 14:00 AEDT (03:00 UTC).
        ("2026-10-02T21:00:00+00:00", 21, True),  # Sat 3 Oct 07:00 AEST
        ("2026-10-02T20:00:00+00:00", 20, False),  # Sat 3 Oct 06:00 AEST
        # AEDT -> AEST ends Sun 4 Apr 2027 03:00. Deadline Mon 5 Apr 2027 19:00 AEST (09:00 UTC).
        ("2027-04-03T21:00:00+00:00", 21, True),  # Sun 4 Apr 07:00 AEST (just after the switch)
        ("2027-04-03T20:00:00+00:00", 20, False),  # Sun 4 Apr 06:00 AEST
    ],
)
def test_dst_boundaries_pick_exactly_one_cron(now: str, cron: int, runs: bool) -> None:
    deadlines = bs("2026-10-04T03:00:00Z", "2027-04-05T09:00:00Z")
    d = gate(now=at(now), bootstrap=deadlines, cron_hour=cron)
    assert d.run is runs, d.reason


def test_exactly_one_cron_is_0700_sydney_every_day_of_a_year() -> None:
    day = dt.date(2026, 7, 1)
    for _ in range(366):
        hits = [
            h
            for h in CRON_UTC_HOURS
            if dt.datetime(day.year, day.month, day.day, h, tzinfo=UTC).astimezone(SYDNEY).hour == 7
        ]
        assert len(hits) == 1, day
        day += dt.timedelta(days=1)


@pytest.mark.parametrize(
    ("now", "why"),
    [
        ("2026-10-14T20:00:00+00:00", "Thu: deadline is the day after tomorrow"),
        ("2026-10-16T20:00:00+00:00", "Sat: deadline is today"),
    ],
)
def test_deadline_not_tomorrow_skips(now: str, why: str) -> None:
    d = gate(now=at(now), bootstrap=bs(GW7), cron_hour=20)
    assert not d.run and "not tomorrow" in d.reason, why


def test_finished_and_past_events_are_ignored() -> None:
    d = gate(
        now=at("2026-10-15T20:00:00+00:00"),
        bootstrap=bs("2026-10-16T10:00:00Z", GW7, finished=(True,)),
        cron_hour=20,
    )
    assert d.run and d.gameweek == 7


@pytest.mark.parametrize(
    ("bootstrap", "error", "needle"),
    [
        (None, "URLError: <urlopen error [Errno -3]>", "could not read the FPL deadline"),
        (None, None, "could not read"),
        ({"events": []}, None, "no upcoming deadline"),
        ({"events": [{"id": 7, "deadline_time": "not a date"}]}, None, "malformed"),
    ],
)
def test_api_failure_or_bad_data_skips_with_a_reason(
    bootstrap: dict[str, Any] | None, error: str | None, needle: str
) -> None:
    d = gate(now=at("2026-10-15T20:00:00+00:00"), bootstrap=bootstrap, error=error, cron_hour=20)
    assert not d.run and needle in d.reason
    assert d.lines().startswith("run=false\n")


def test_manual_dispatch_skips_the_hour_check_only() -> None:
    assert gate(now=at("2026-10-16T03:00:00+00:00"), bootstrap=bs(GW7), cron_hour=None).run
    assert not gate(now=at("2026-10-14T03:00:00+00:00"), bootstrap=bs(GW7), cron_hour=None).run


def test_gate_script_writes_github_output_and_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _script("day_before_gate")
    monkeypatch.setattr(mod, "fetch", lambda: (None, "HTTPError: 503 Service Unavailable"))
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert mod.main(["--cron", "0 20 * * *"]) == 0
    assert out.read_text().startswith("run=false\n")
    assert "::warning title=Day-before refresh skipped::" in capsys.readouterr().out


# --- no early prospective decisions ----------------------------------------------------------


def test_every_passing_day_before_run_is_outside_the_14h_decision_window() -> None:
    """Whatever time tomorrow the deadline is, a 07:00 run is >= 17 h before it (> 14 h)."""
    window = dt.timedelta(hours=14)
    for minutes in range(0, 24 * 60, 15):
        today = dt.datetime(2026, 10, 15, 20, tzinfo=UTC)  # Fri 07:00 AEDT
        local_tomorrow = dt.datetime(2026, 10, 17, tzinfo=SYDNEY) + dt.timedelta(minutes=minutes)
        deadline = local_tomorrow.astimezone(UTC)
        d = gate(
            now=today,
            bootstrap={"events": [{"id": 7, "deadline_time": deadline.isoformat()}]},
            cron_hour=20,
        )
        assert d.run
        assert deadline - today > window


def test_veto_forces_decide_false_and_keeps_the_rest() -> None:
    plan = {"gw": 7, "decide": True, "decide_reason": "odds ready (10/10 fixtures)", "score": True}
    v = veto_plan(plan)
    assert v["decide"] is False and v["score"] is True and v["gw"] == 7
    assert v["decide_vetoed"] == "odds ready (10/10 fixtures)"
    assert "day-before" in v["decide_reason"]
    assert veto_plan({"decide": False})["decide"] is False


def test_veto_cli_rewrites_plan_json(tmp_path: Path) -> None:
    mod = _script("day_before_gate")
    plan = tmp_path / "ci" / "plan.json"
    plan.parent.mkdir()
    plan.write_text(json.dumps({"gw": 7, "decide": True, "score": False}))
    assert mod.main(["--veto-plan", str(plan)]) == 0
    assert json.loads(plan.read_text())["decide"] is False


def test_workflows_wire_the_veto_and_fail_closed_paths() -> None:
    wf = REPO / ".github" / "workflows"
    pipeline = (wf / "pipeline.yml").read_text()
    assert "--veto-plan" in pipeline
    assert "steps.plan.outputs.decide == 'true'" not in pipeline  # every decide step uses the veto
    deploy = (wf / "deploy.yml").read_text()
    assert "contract_fresh.py" in deploy and "if: env.DAY_BEFORE != 'true'" in deploy
    day = (wf / "day-before.yml").read_text()
    assert '"0 20 * * *"' in day and '"0 21 * * *"' in day and "group: day-before" in day


# --- fail-closed contract check --------------------------------------------------------------


def test_contract_fresh(tmp_path: Path) -> None:
    check = _script("contract_fresh").check
    now = at("2026-10-15T20:40:00+00:00")
    six = dt.timedelta(hours=6)
    root = tmp_path / "v1"
    root.mkdir()
    assert "empty" in (check(root, six, now) or "")
    (root / "week.json").write_text("{}")
    assert "unreadable" in (check(root, six, now) or "")
    (root / "meta.json").write_text(json.dumps({"generated_at": "2026-10-15T20:30:00Z"}))
    assert check(root, six, now) is None
    (root / "meta.json").write_text(json.dumps({"generated_at": "2026-10-14T01:00:00Z"}))
    assert "stale" in (check(root, six, now) or "")
