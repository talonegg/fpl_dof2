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
from fpl_dof.gameweek import GameweekState, Phase
from fpl_dof.schedule_cli import EXIT_OK
from fpl_dof.schedule_cli import main as schedule_main
from fpl_dof.silver.store import write_table
from fpl_dof.silver.tables import Table
from fpl_dof.week.schedule import ScheduleDecision, fast_ingest_decision, pipeline_decision

SYDNEY = ZoneInfo("Australia/Sydney")
CONFIG = ScheduleConfig()


def _at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 8, 20, hour, minute, tzinfo=dt.UTC)


#: The instant the pipeline decisions are asked at; only minutes to the deadline matter to them.
NOW = _at(12)


def _state(now: dt.datetime, minutes: float | None) -> GameweekState | None:
    """Gameweek 3's state ``minutes`` before its deadline: Open ahead of it, Recorded from it."""
    if minutes is None:
        return None
    phase = Phase.OPEN if minutes > 0 else Phase.RECORDED
    return GameweekState(3, phase, now + dt.timedelta(minutes=minutes), None)


def _fast(*, hour: int, minutes: float | None, minute: int = 0) -> bool:
    now = _at(hour, minute)
    return fast_ingest_decision(now=now, state=_state(now, minutes), config=CONFIG).should_run


def _decide(minutes: float | None, config: ScheduleConfig = CONFIG) -> ScheduleDecision:
    return pipeline_decision(now=NOW, state=_state(NOW, minutes), config=config)


def _pipeline(minutes: float | None, config: ScheduleConfig = CONFIG) -> bool:
    return _decide(minutes, config).should_run


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
        decision = fast_ingest_decision(now=moment, state=None, config=CONFIG)
        assert decision.should_run is True


# --- pipeline ---------------------------------------------------------------------------------


def test_nothing_is_scheduled_inside_the_forty_five_minute_freeze() -> None:
    """R-09, swept minute by minute over the last six hours before a deadline.

    Written as a sweep rather than as a handful of cases on purpose: the failure mode this guards
    is an off-by-one or a sign error in the window arithmetic, and those hide precisely in the
    minutes nobody thought to write a case for.
    """
    for minutes in range(0, 6 * 60 + 1):
        decision = _decide(minutes)
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


#: pipeline.yml's deadline-relative cron, `7,23,41,53 * * * *`.
GUARD_MINUTES = (7, 23, 41, 53)


def test_the_odd_minute_cron_cannot_step_over_a_window() -> None:
    """Every deadline minute-of-hour: the `7,23,41,53` firings hit every window at least once.

    The offsets are fixed but the deadline's minute-of-hour is not. If the tolerance were no wider
    than the longest gap between firings, some deadlines would jump a window entirely.
    """
    nxt = GUARD_MINUTES[1:] + GUARD_MINUTES[:1]
    gaps = [(b - a) % 60 for a, b in zip(GUARD_MINUTES, nxt, strict=True)]
    assert max(gaps) == CONFIG.pipeline_cron_interval_minutes
    for deadline_minute in range(60):
        firings = [(deadline_minute - m) % 60 + 60 * h for h in range(12) for m in GUARD_MINUTES]
        fired = {
            offset
            for offset in CONFIG.pipeline_offsets_minutes
            for minutes in firings
            if offset <= minutes <= offset + CONFIG.pipeline_window_tolerance_minutes
        }
        assert fired == set(CONFIG.pipeline_offsets_minutes), (
            f"a deadline at :{deadline_minute:02d} misses window(s) "
            f"{set(CONFIG.pipeline_offsets_minutes) - fired}"
        )


def test_several_decision_chances_fall_inside_the_prospective_14h_window() -> None:
    tolerance = CONFIG.pipeline_window_tolerance_minutes
    inside = [o for o in CONFIG.pipeline_offsets_minutes if o + tolerance <= 14 * 60]
    assert len(inside) >= 4


def test_an_unknown_deadline_stands_the_deadline_trigger_down() -> None:
    """The nightly cron and manual dispatch are unaffected; only this trigger is conditional."""
    decision = _decide(None)
    assert decision.should_run is False
    assert "no open gameweek" in decision.reason


def test_a_gameweek_past_its_deadline_has_no_window_whatever_the_clock_says() -> None:
    """ORC-01: the window belongs to the Open gameweek; a Recorded one is due nothing but ingest,
    even at a moment that would match an offset if its deadline were still ahead."""
    recorded = GameweekState(3, Phase.RECORDED, NOW + dt.timedelta(minutes=50), None)
    assert pipeline_decision(now=NOW, state=recorded, config=CONFIG).should_run is False
    assert _pipeline(50) is True


def test_the_reason_names_the_window_so_a_skipped_run_is_never_a_mystery() -> None:
    assert "T-45m" in _decide(50).reason
    assert "freeze" in _decide(10).reason


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
    together. `pipeline_cron_interval_minutes` mirrors `7,23,41,53 * * * *` in pipeline.yml; the
    boundary
    hours mirror the four-hourly cadence ingest-fast.yml's hourly cron stands in for.
    """
    assert CONFIG.fast_ingest_boundary_hours == (0, 4, 8, 12, 16, 20)
    assert CONFIG.pipeline_offsets_minutes == (360, 180, 90, 45)
    assert CONFIG.pipeline_cron_interval_minutes == 18
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
    assert payload["gameweek_state"] == "open"
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


def test_the_guard_reads_gameweek_from_bronze_when_silver_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PIPE-14: Ingest-only jobs have no silver table yet, but can read gameweek from bronze."""
    from fpl_dof.sources.bronze import BronzeStore

    store = BronzeStore(tmp_path / "bronze")
    bootstrap = {
        "events": [
            {
                "id": 5,
                "name": "Gameweek 5",
                "deadline_time": "2026-09-19T10:00:00Z",
                "finished": False,
                "is_next": True,
            }
        ]
    }
    bs_bytes = json.dumps(bootstrap).encode("utf-8")
    store.write(
        bs_bytes,
        source="fpl",
        source_version="1.0",
        resource="bootstrap_static",
        key="all",
        url="https://dummy/api/bootstrap-static/",
        http_status=200,
    )

    payload = json.loads(_run(capsys, "--data-dir", str(tmp_path), "--now", "2026-09-19T07:00:00Z"))
    assert payload["gameweek"] == 5
    assert payload["hours_to_deadline"] == pytest.approx(3.0)
