"""Day-before refresh: the gate, the prospective veto, and the fail-closed contract check."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.week.ci_runs import active_or_succeeded, start_of_utc_day, succeeded_since
from fpl_dof.week.day_before import CRON, SYDNEY, gate, marker

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


def _cron_times(day: dt.date) -> list[dt.datetime]:
    """Every firing of CRON (`7,27,47 19-22 * * *`) on a UTC date."""
    minutes, hours = (part for part in CRON.split()[:2])
    lo, hi = (int(x) for x in hours.split("-"))
    return [
        dt.datetime(day.year, day.month, day.day, h, int(m), tzinfo=UTC)
        for h in range(lo, hi + 1)
        for m in minutes.split(",")
    ]


def test_cron_is_off_the_hour_and_half_hour_and_brackets_0700_sydney_all_year() -> None:
    day = dt.date(2026, 7, 1)
    for _ in range(366):
        times = _cron_times(day)
        assert all(t.minute not in (0, 30) for t in times)
        local = [t.astimezone(SYDNEY) for t in times]
        assert min(local).hour < 7 and max(local).hour >= 8, day  # firings before and after 07:00
        day += dt.timedelta(days=1)


def test_saturday_deadline_runs_on_the_first_firing_from_0700_friday() -> None:
    boot = bs("2026-10-10T10:00:00Z", GW7)  # GW7: Sat 17 Oct 21:00 AEDT
    decisions = [(t, gate(now=t, bootstrap=boot)) for t in _cron_times(dt.date(2026, 10, 15))]
    first = next(t for t, d in decisions if d.run)
    assert first == at("2026-10-15T20:07:00+00:00")  # Fri 16 Oct 07:07 AEDT
    early = [d for t, d in decisions if t < first]
    assert early and all("before 07:00" in d.reason for d in early)
    d = dict(decisions)[first]
    assert d.gameweek == 7 and "Sat 17 Oct 21:00 AEDT" in d.reason and "10:00 UTC" in d.reason


def test_later_firings_are_no_ops_once_this_gameweek_ran() -> None:
    now = at("2026-10-15T20:27:00+00:00")
    boot = bs("2026-10-10T10:00:00Z", GW7)
    for status, conclusion in (("queued", None), ("in_progress", None), ("completed", "success")):
        prior = [
            {
                "databaseId": 41,
                "displayTitle": f"Ingest (slow) {marker(7)}",
                "status": status,
                "conclusion": conclusion,
            }
        ]
        d = gate(now=now, bootstrap=boot, prior_runs=prior)
        assert not d.run and d.reason.startswith("no-op") and "41" in d.reason


def test_a_failed_earlier_run_or_another_gameweeks_run_does_not_block() -> None:
    now = at("2026-10-15T20:27:00+00:00")
    prior = [
        {
            "databaseId": 40,
            "displayTitle": f"Ingest (slow) {marker(7)}",
            "status": "completed",
            "conclusion": "failure",
        },
        {
            "databaseId": 39,
            "displayTitle": f"Ingest (slow) {marker(6)}",
            "status": "completed",
            "conclusion": "success",
        },
        {
            "databaseId": 38,
            "displayTitle": "Ingest (slow)",
            "status": "completed",
            "conclusion": "success",
        },
    ]
    assert gate(now=now, bootstrap=bs("2026-10-10T10:00:00Z", GW7), prior_runs=prior).run


def test_unreadable_run_list_skips_and_the_next_firing_retries() -> None:
    d = gate(
        now=at("2026-10-15T20:07:00+00:00"),
        bootstrap=bs("2026-10-10T10:00:00Z", GW7),
        prior_runs=None,
        runs_error="CalledProcessError: gh exited 1",
    )
    assert not d.run and "next firing retries" in d.reason


def test_early_saturday_deadline_runs_friday_too() -> None:
    """GW8 is Sat 04:30 AEDT; the day before in Sydney is Friday (not Thursday)."""
    d = gate(now=at("2026-10-22T20:07:00+00:00"), bootstrap=bs("2026-10-10T10:00:00Z", GW7, GW8))
    assert d.run and d.gameweek == 8, d.reason


@pytest.mark.parametrize(
    ("now", "runs"),
    [
        # AEST -> AEDT starts Sun 4 Oct 2026 02:00. Deadline Sun 4 Oct 14:00 AEDT (03:00 UTC).
        ("2026-10-02T21:07:00+00:00", True),  # Sat 3 Oct 07:07 AEST
        ("2026-10-02T20:47:00+00:00", False),  # Sat 3 Oct 06:47 AEST
        # AEDT -> AEST ends Sun 4 Apr 2027 03:00. Deadline Mon 5 Apr 2027 19:00 AEST (09:00 UTC).
        ("2027-04-03T21:07:00+00:00", True),  # Sun 4 Apr 07:07 AEST (just after the switch)
        ("2027-04-03T20:47:00+00:00", False),  # Sun 4 Apr 06:47 AEST
        ("2026-10-02T20:07:00+00:00", False),  # Sat 3 Oct 06:07 AEST (an AEDT-07:07 cron time)
    ],
)
def test_dst_boundaries(now: str, runs: bool) -> None:
    deadlines = bs("2026-10-04T03:00:00Z", "2027-04-05T09:00:00Z")
    d = gate(now=at(now), bootstrap=deadlines)
    assert d.run is runs, d.reason


@pytest.mark.parametrize(
    ("now", "why"),
    [
        ("2026-10-14T20:07:00+00:00", "Thu: deadline is the day after tomorrow"),
        ("2026-10-16T20:07:00+00:00", "Sat: deadline is today"),
    ],
)
def test_deadline_not_tomorrow_skips(now: str, why: str) -> None:
    d = gate(now=at(now), bootstrap=bs("2026-10-10T10:00:00Z", GW7))
    assert not d.run and "not tomorrow" in d.reason, why


def test_finished_and_past_events_are_ignored() -> None:
    d = gate(
        now=at("2026-10-15T20:07:00+00:00"),
        bootstrap=bs("2026-10-16T10:00:00Z", GW7, finished=(True,)),
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
    d = gate(now=at("2026-10-15T20:07:00+00:00"), bootstrap=bootstrap, error=error)
    assert not d.run and needle in d.reason
    assert d.lines().startswith("run=false\n")


def test_manual_dispatch_skips_the_hour_check_only() -> None:
    assert gate(
        now=at("2026-10-15T15:00:00+00:00"), bootstrap=bs("2026-10-10T10:00:00Z", GW7), manual=True
    ).run
    assert not gate(
        now=at("2026-10-15T15:00:00+00:00"), bootstrap=bs("2026-10-10T10:00:00Z", GW7)
    ).run
    assert not gate(
        now=at("2026-10-14T03:00:00+00:00"), bootstrap=bs("2026-10-10T10:00:00Z", GW7), manual=True
    ).run


def test_gate_script_writes_github_output_and_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _script("day_before_gate")
    monkeypatch.setattr(mod, "fetch", lambda: (None, "HTTPError: 503 Service Unavailable"))
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert mod.main([]) == 0
    assert out.read_text().startswith("run=false\n")
    assert "::warning title=Day-before refresh skipped::" in capsys.readouterr().out


# --- fallback firings: "already done today" -------------------------------------------------


def _run(i: int, created: str, conclusion: str | None, title: str = "x") -> dict[str, Any]:
    status = "completed" if conclusion else "in_progress"
    return {
        "databaseId": i,
        "createdAt": created,
        "conclusion": conclusion,
        "status": status,
        "displayTitle": title,
    }


def test_succeeded_since_today_only_counts_todays_successes_and_not_itself() -> None:
    now = at("2026-10-15T05:41:00+00:00")
    since = start_of_utc_day(now)
    runs = [
        _run(9, "2026-10-15T05:41:00Z", None),  # this run
        _run(8, "2026-10-15T02:30:00Z", "failure"),
        _run(7, "2026-10-14T02:31:00Z", "success"),  # yesterday
    ]
    assert succeeded_since(runs, since, exclude_id=9) is None
    runs.insert(1, _run(10, "2026-10-15T09:30:00Z", "success"))
    assert succeeded_since(runs, since, exclude_id=9)["databaseId"] == 10  # type: ignore[index]


def test_active_or_succeeded_matches_title() -> None:
    runs = [_run(1, "2026-10-15T20:07:00Z", None, title="Ingest (slow) [day-before GW7]")]
    assert active_or_succeeded(runs, title_contains="[day-before GW7]") is not None
    assert active_or_succeeded(runs, title_contains="[day-before GW8]") is None


def test_today_done_requires_the_named_job(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _script("ci_runs")
    runs = [_run(5, "2026-10-15T01:20:00Z", "success"), _run(4, "2026-10-15T01:07:00Z", "success")]
    monkeypatch.setattr(mod, "list_runs", lambda wf: runs)
    monkeypatch.setattr(mod, "job_succeeded", lambda rid, job: rid == 4)  # 5 was guard-only
    now = at("2026-10-15T03:53:00+00:00")
    assert mod.today_done("pipeline.yml", "run", now, self_id=None) is True
    monkeypatch.setattr(mod, "job_succeeded", lambda rid, job: False)
    assert mod.today_done("pipeline.yml", "run", now, self_id=None) is False


def test_ci_runs_script_says_not_done_when_github_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _script("ci_runs")

    def boom(wf: str) -> list[dict[str, Any]]:
        raise OSError("gh not found")

    monkeypatch.setattr(mod, "list_runs", boom)
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert mod.main(["today-done", "--workflow", "ingest-slow.yml"]) == 0
    assert out.read_text() == "done=false\n"


# --- no early prospective decisions ----------------------------------------------------------


def test_every_passing_day_before_run_is_outside_the_14h_decision_window() -> None:
    """Whatever time tomorrow the deadline is, any passing firing is > 14 h before it."""
    window = dt.timedelta(hours=14)
    for day in (dt.date(2026, 10, 15), dt.date(2026, 7, 9)):  # AEDT and AEST
        for fire in _cron_times(day):
            local_tomorrow = dt.datetime.combine(
                fire.astimezone(SYDNEY).date() + dt.timedelta(days=1), dt.time(), SYDNEY
            )
            for minutes in range(0, 24 * 60, 15):
                deadline = (local_tomorrow + dt.timedelta(minutes=minutes)).astimezone(UTC)
                boot = {"events": [{"id": 7, "deadline_time": deadline.isoformat()}]}
                if gate(now=fire, bootstrap=boot).run:
                    assert deadline - fire > window


def test_workflows_wire_the_fail_closed_paths_and_the_frozen_harness_is_gone() -> None:
    wf = REPO / ".github" / "workflows"
    pipeline = (wf / "pipeline.yml").read_text()
    # MOD-06: the frozen harness is retired; the run job only reads its last record.
    for retired in ("frozen-2026-10-13", "prospective_ci", "--veto-plan", "fpl_prospective"):
        assert retired not in pipeline
    assert "needs: [guard]" in pipeline and "prospective:\n" not in pipeline
    deploy = (wf / "deploy.yml").read_text()
    assert "contract_fresh.py" in deploy and "if: env.DAY_BEFORE != 'true'" in deploy
    day = (wf / "day-before.yml").read_text()
    assert f'"{CRON}"' in day and "group: day-before" in day


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
