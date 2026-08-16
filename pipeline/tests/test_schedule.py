"""E7-S1/E7-S2 scheduling: which cron firings are allowed to do work.

These tests carry more weight than their size suggests. The behaviour they pin cannot be observed
locally — a cron fires or does not fire on GitHub's infrastructure at a moment nobody is watching,
against a deadline that only exists once a week — so a mistake here is invisible until it costs a
gameweek (DP-13). Two properties matter most:

* **R-09.** Nothing that produces a recommendation may run inside 45 minutes of a deadline. The
  test below sweeps every minute of the final six hours and asserts it, rather than checking the
  two or three cases a reader would think of.
* **UTC everywhere.** The guard must reach the same decision whatever zone the clock is expressed
  in, because the UK/AEST offset moves twice a season and not on the same dates (CON-11).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pydantic import ValidationError

from fpl_dof.config.models import ScheduleConfig
from fpl_dof.schedule_cli import EXIT_OK
from fpl_dof.schedule_cli import main as schedule_main
from fpl_dof.silver.store import write_table
from fpl_dof.silver.tables import Table
from fpl_dof.week.schedule import fast_ingest_decision, pipeline_decision

SYDNEY = ZoneInfo("Australia/Sydney")
CONFIG = ScheduleConfig()


def _at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 8, 20, hour, minute, tzinfo=dt.UTC)


def _fast(*, hour: int, minutes: float | None, minute: int = 0) -> bool:
    return fast_ingest_decision(
        now=_at(hour, minute),
        minutes_to_deadline=minutes,
        gameweek=3,
        config=CONFIG,
    ).should_run


def _pipeline(minutes: float | None, config: ScheduleConfig = CONFIG) -> bool:
    return pipeline_decision(minutes_to_deadline=minutes, gameweek=3, config=config).should_run


# --- fast ingest ------------------------------------------------------------------------------


@pytest.mark.parametrize("hour", [0, 4, 8, 12, 16, 20])
def test_the_four_hourly_boundary_hours_run_with_no_deadline_in_sight(hour: int) -> None:
    assert _fast(hour=hour, minutes=None) is True


@pytest.mark.parametrize("hour", [1, 2, 3, 5, 7, 11, 13, 17, 19, 21, 22, 23])
def test_every_other_hour_stands_down_with_no_deadline_in_sight(hour: int) -> None:
    """The workflow fires hourly and mostly does nothing. That is the whole trick."""
    assert _fast(hour=hour, minutes=None) is False


@pytest.mark.parametrize("hour", range(24))
def test_every_hour_runs_inside_the_pre_deadline_window(hour: int) -> None:
    assert _fast(hour=hour, minutes=23 * 60) is True


def test_the_window_boundary_is_inclusive_and_the_hour_outside_it_is_not() -> None:
    inside = CONFIG.fast_ingest_deadline_window_hours * 60
    assert _fast(hour=1, minutes=inside) is True
    assert _fast(hour=1, minutes=inside + 1) is False
    # ...unless the fixed cadence would have run anyway.
    assert _fast(hour=0, minutes=inside + 1) is True


def test_an_unknown_deadline_falls_back_to_the_fixed_cadence_rather_than_to_hourly() -> None:
    """Unknown is not evidence a deadline is imminent.

    The opposite reading — "we cannot tell, so fetch every hour" — turns a silver outage into a
    permanent 24x cadence, which is the kind of failure that is only noticed by its bill.
    """
    assert _fast(hour=3, minutes=None) is False
    assert _fast(hour=4, minutes=None) is True


def test_a_passed_deadline_does_not_count_as_being_inside_the_window() -> None:
    assert _fast(hour=3, minutes=-10) is False


def test_the_decision_is_the_same_instant_however_the_clock_is_expressed() -> None:
    """CON-11: the guard reasons in UTC, not in whatever zone it was handed."""
    utc = _at(4, 30)
    sydney = utc.astimezone(SYDNEY)
    assert sydney.hour != utc.hour  # the test would be vacuous otherwise
    for moment in (utc, sydney):
        decision = fast_ingest_decision(
            now=moment, minutes_to_deadline=None, gameweek=3, config=CONFIG
        )
        assert decision.should_run is True


# --- pipeline ---------------------------------------------------------------------------------


def test_nothing_is_scheduled_inside_the_forty_five_minute_freeze() -> None:
    """R-09, swept minute by minute over the last six hours before a deadline.

    Written as a sweep rather than as a handful of cases on purpose: the failure mode this guards
    is an off-by-one or a sign error in the window arithmetic, and those hide precisely in the
    minutes nobody thought to write a case for.
    """
    for minutes in range(0, 6 * 60 + 1):
        decision = pipeline_decision(minutes_to_deadline=minutes, gameweek=3, config=CONFIG)
        if decision.should_run:
            assert minutes >= CONFIG.deadline_freeze_minutes, (
                f"pipeline would run at T-{minutes}m, inside the "
                f"{CONFIG.deadline_freeze_minutes:g}m freeze"
            )


def test_the_t_minus_45_window_opens_early_and_closes_exactly_on_the_offset() -> None:
    """The tolerance points backwards in time only. T-45m is the *latest* it can fire."""
    tolerance = CONFIG.pipeline_window_tolerance_minutes
    assert _pipeline(45) is True
    assert _pipeline(45 + tolerance) is True
    assert _pipeline(45 + tolerance + 1) is False
    assert _pipeline(44.9) is False


def test_the_t_minus_3h_window_behaves_the_same_way() -> None:
    tolerance = CONFIG.pipeline_window_tolerance_minutes
    assert _pipeline(180) is True
    assert _pipeline(180 + tolerance) is True
    assert _pipeline(180 + tolerance + 1) is False
    assert _pipeline(179) is False


def test_a_quarter_hourly_cron_cannot_step_over_a_window() -> None:
    """Every 15-minute firing pattern hits both windows at least once.

    The offsets are fixed but the deadline's minute-of-hour is not, so the set of
    ``minutes_to_deadline`` values a :15 cron produces is offset by an arbitrary phase. If the
    tolerance were no wider than the interval, some phases would jump the window entirely and the
    pre-deadline run would silently never happen for those gameweeks.
    """
    interval = CONFIG.pipeline_cron_interval_minutes
    for phase in range(interval):
        fired = {
            offset
            for offset in CONFIG.pipeline_offsets_minutes
            for minutes in range(phase, 12 * 60, interval)
            if offset <= minutes <= offset + CONFIG.pipeline_window_tolerance_minutes
        }
        assert fired == set(CONFIG.pipeline_offsets_minutes), (
            f"a deadline at phase {phase} misses window(s) "
            f"{set(CONFIG.pipeline_offsets_minutes) - fired}"
        )


def test_an_unknown_deadline_stands_the_deadline_trigger_down() -> None:
    """The nightly cron and manual dispatch are unaffected; only this trigger is conditional."""
    decision = pipeline_decision(minutes_to_deadline=None, gameweek=None, config=CONFIG)
    assert decision.should_run is False
    assert "no deadline" in decision.reason


def test_the_reason_names_the_window_so_a_skipped_run_is_never_a_mystery() -> None:
    assert "T-45m" in pipeline_decision(minutes_to_deadline=50, gameweek=3, config=CONFIG).reason
    assert "freeze" in pipeline_decision(minutes_to_deadline=10, gameweek=3, config=CONFIG).reason


def test_days_out_from_a_deadline_the_pipeline_leaves_it_to_the_nightly_run() -> None:
    assert _pipeline(5 * 24 * 60) is False


# --- configuration guards ---------------------------------------------------------------------


def test_a_tolerance_no_wider_than_the_cron_interval_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must exceed"):
        ScheduleConfig(pipeline_window_tolerance_minutes=15, pipeline_cron_interval_minutes=15)


def test_an_offset_inside_the_freeze_is_rejected() -> None:
    """Configuration cannot be used to walk R-09 back quietly."""
    with pytest.raises(ValidationError, match="freeze"):
        ScheduleConfig(pipeline_offsets_minutes=(180, 30))


def test_the_offsets_cannot_be_emptied() -> None:
    with pytest.raises(ValidationError, match="at least one offset"):
        ScheduleConfig(pipeline_offsets_minutes=())


def test_the_shipped_defaults_are_the_ones_the_workflows_assume() -> None:
    """A change to any of these needs the matching change in `.github/workflows/`.

    The cron expressions cannot import Python, so this is the only place the two can be held
    together. `pipeline_cron_interval_minutes` mirrors `*/15 * * * *` in pipeline.yml; the boundary
    hours mirror the four-hourly cadence ingest-fast.yml's hourly cron stands in for.
    """
    assert CONFIG.fast_ingest_boundary_hours == (0, 4, 8, 12, 16, 20)
    assert CONFIG.pipeline_offsets_minutes == (180, 45)
    assert CONFIG.pipeline_cron_interval_minutes == 15
    assert CONFIG.deadline_freeze_minutes == 45.0


# --- the guard command ------------------------------------------------------------------------

SEASON = "2026/27"
DEADLINE = "2026-08-21T17:30:00Z"


def _write_gameweeks(data_dir: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "gameweek": 1,
                "name": "Gameweek 1",
                "deadline_time": pd.Timestamp(DEADLINE),
                "finished": False,
                "is_next": True,
            }
        ]
    )
    write_table(data_dir / "silver", SEASON, Table.GAMEWEEK, frame)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    assert schedule_main(list(argv)) == EXIT_OK
    return capsys.readouterr().out.strip()


def test_the_guard_reports_the_time_to_the_next_deadline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_gameweeks(tmp_path)
    payload = json.loads(_run(capsys, "--data-dir", str(tmp_path), "--now", "2026-08-21T14:30:00Z"))
    assert payload["gameweek"] == 1
    assert payload["hours_to_deadline"] == pytest.approx(3.0)
    assert payload["pipeline"]["should_run"] is True


def test_the_guard_decides_for_one_workflow_in_a_form_a_yaml_if_can_compare(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--decide`` prints exactly ``true`` or ``false`` and nothing else."""
    _write_gameweeks(tmp_path)
    # T-3h exactly: in the T-180m window.
    inside = ["--now", "2026-08-21T14:30:00Z", "--decide", "pipeline"]
    # T-5h30m: in no window at all.
    outside = ["--now", "2026-08-21T12:00:00Z", "--decide", "pipeline"]
    assert _run(capsys, "--data-dir", str(tmp_path), *inside) == "true"
    assert _run(capsys, "--data-dir", str(tmp_path), *outside) == "false"


def test_the_guard_never_fails_when_the_data_tier_is_not_there_yet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The very first run of a fresh clone has no silver at all.

    A guard that raised here would fail every workflow before ingestion had ever happened —
    the one moment the automation most needs to be able to bootstrap itself (DP-15).
    """
    payload = json.loads(_run(capsys, "--data-dir", str(tmp_path), "--now", "2026-08-21T14:30:00Z"))
    assert payload["hours_to_deadline"] is None
    assert "not been ingested" in payload["deadline_unknown_reason"]
    assert payload["pipeline"]["should_run"] is False
    # ...and the fast ingest keeps its fixed cadence rather than stopping.
    assert payload["fast_ingest"]["should_run"] is False
    assert (
        json.loads(_run(capsys, "--data-dir", str(tmp_path), "--now", "2026-08-21T16:00:00Z"))[
            "fast_ingest"
        ]["should_run"]
        is True
    )


def test_the_guard_survives_a_silver_tier_that_is_present_but_unreadable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Half-written parquet is a real outcome of a cancelled run, not a hypothetical."""
    _write_gameweeks(tmp_path)
    path = tmp_path / "silver" / "season=2026-27" / "gameweek.parquet"
    path.write_bytes(b"this is not parquet")
    payload = json.loads(_run(capsys, "--data-dir", str(tmp_path), "--now", "2026-08-21T14:30:00Z"))
    assert payload["hours_to_deadline"] is None
    assert "could not be read" in payload["deadline_unknown_reason"]


def test_the_guard_stands_down_once_the_season_is_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_gameweeks(tmp_path)
    payload = json.loads(_run(capsys, "--data-dir", str(tmp_path), "--now", "2027-06-01T00:00:00Z"))
    assert payload["hours_to_deadline"] is None
    assert payload["pipeline"]["should_run"] is False


def test_the_guard_reads_a_naive_clock_as_utc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CON-11: an instant without an offset is UTC here, never the runner's local zone."""
    _write_gameweeks(tmp_path)
    naive = json.loads(_run(capsys, "--data-dir", str(tmp_path), "--now", "2026-08-21T14:30:00"))
    aware = json.loads(_run(capsys, "--data-dir", str(tmp_path), "--now", "2026-08-21T14:30:00Z"))
    assert naive["hours_to_deadline"] == aware["hours_to_deadline"]
