"""The matchday rule and the gameweeks in play (LIVE-02, R1.4.3 §1): pure, source-free, on
silver's fixture and gameweek shapes. A fixture's ``finished`` is FPL's bonus-confirmed flag, not
full time. The change manifest's end-to-end cases are in test_change_manifest.py."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from pydantic import ValidationError

from fpl_dof.config.models import ScheduleConfig
from fpl_dof.gameweek import gameweeks_in_play, matchdays, matchdays_done_since

CONFIG = ScheduleConfig()
SETTLE = dt.timedelta(hours=CONFIG.matchday_settle_hours)


def _fixtures(*rows: tuple[int | None, str | None, bool]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gameweek": [row[0] for row in rows],
            "kickoff_time": pd.to_datetime(pd.Series([row[1] for row in rows]), utc=True),
            "finished": [row[2] for row in rows],
        }
    )


def _at(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)


def test_a_matchday_is_the_kick_off_date_in_uk_time_not_in_utc() -> None:
    """§5 Q1: the game's clock. In British Summer Time a 23:30 UTC kick-off is past midnight in the
    UK, so it is the next day's; a zone set elsewhere would group it otherwise."""
    fixtures = _fixtures(
        (3, "2026-08-22T14:00:00Z", False),
        (3, "2026-08-22T23:30:00Z", False),  # 00:30 on Sunday 23 August, UK time
        (3, "2026-08-23T15:30:00Z", False),
    )
    london = matchdays(fixtures, _at("2026-08-22T12:00"), zone=CONFIG.matchday_zone, settle=SETTLE)
    assert [(m.day.isoformat(), m.fixtures) for m in london] == [
        ("2026-08-22", 1),
        ("2026-08-23", 2),
    ]
    utc = matchdays(fixtures, _at("2026-08-22T12:00"), zone="UTC", settle=SETTLE)
    assert [(m.day.isoformat(), m.fixtures) for m in utc] == [("2026-08-22", 2), ("2026-08-23", 1)]


def test_done_when_every_bonus_is_confirmed_or_the_cap_has_passed_and_only_then_pending() -> None:
    saturday = _fixtures((9, "2026-10-31T15:00:00Z", True), (9, "2026-10-31T17:30:00Z", False))
    last = _at("2026-10-31T17:30")

    def one(fixtures: pd.DataFrame, at: dt.datetime) -> tuple[bool, bool]:
        [matchday] = matchdays(fixtures, at, zone=CONFIG.matchday_zone, settle=SETTLE)
        return matchday.done, matchday.bonus_pending

    assert one(saturday, last + SETTLE - dt.timedelta(minutes=1)) == (False, False)
    assert one(saturday, last + SETTLE) == (True, True)  # the cap: done, bonus pending
    confirmed = _fixtures((9, "2026-10-31T15:00:00Z", True), (9, "2026-10-31T17:30:00Z", True))
    assert one(confirmed, last + dt.timedelta(hours=2)) == (True, False)


def test_a_postponed_fixture_belongs_to_no_matchday() -> None:
    fixtures = _fixtures(
        (9, "2026-10-31T15:00:00Z", True),
        (None, "2026-10-31T15:00:00Z", False),  # out of the gameweek
        (9, None, False),  # kick-off to be confirmed
    )
    [matchday] = matchdays(fixtures, _at("2026-10-31T18:00"), zone="Europe/London", settle=SETTLE)
    assert matchday.done and matchday.fixtures == 1 and not matchday.bonus_pending
    assert (
        matchdays(
            _fixtures((None, None, False)), _at("2026-10-31T18:00"), zone="UTC", settle=SETTLE
        )
        == []
    )
    assert matchdays(None, _at("2026-10-31T18:00"), zone="UTC", settle=SETTLE) == []


def test_a_matchday_moves_once_whichever_capture_first_sees_it_done() -> None:
    before = _fixtures((9, "2026-10-31T15:00:00Z", False))
    after = _fixtures((9, "2026-10-31T15:00:00Z", True))
    early, late = _at("2026-10-31T17:00"), _at("2026-10-31T18:00")
    zone = CONFIG.matchday_zone
    [moved] = matchdays_done_since(before, early, after, late, zone=zone, settle=SETTLE)
    assert (moved.gameweek, moved.day.isoformat()) == (9, "2026-10-31")
    hour_on = late + dt.timedelta(hours=1)
    assert matchdays_done_since(after, late, after, hour_on, zone=zone, settle=SETTLE) == []
    # No earlier capture holds it open.
    assert matchdays_done_since(None, early, after, late, zone=zone, settle=SETTLE)


def _gameweeks(*rows: tuple[int, str, bool, bool]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gameweek": [row[0] for row in rows],
            "deadline_time": pd.to_datetime([row[1] for row in rows], utc=True),
            "finished": [row[2] for row in rows],
            "data_checked": [row[3] for row in rows],
        }
    )


def test_a_gameweek_is_in_play_from_its_deadline_until_data_checked() -> None:
    season = _gameweeks(
        (8, "2026-10-24T10:00:00Z", True, True),
        (9, "2026-10-30T18:30:00Z", False, False),
        (10, "2026-11-06T18:30:00Z", False, False),
    )
    assert gameweeks_in_play(season, _at("2026-10-30T18:00")) == ()  # before the deadline
    assert gameweeks_in_play(season, _at("2026-10-30T18:30")) == (9,)
    finished = _gameweeks(
        (8, "2026-10-24T10:00:00Z", True, True),
        (9, "2026-10-30T18:30:00Z", True, False),  # finished, not yet data-checked
        (10, "2026-11-06T18:30:00Z", False, False),
    )
    assert gameweeks_in_play(finished, _at("2026-11-03T12:00")) == (9,)
    checked = finished.assign(data_checked=[True, True, False])
    assert gameweeks_in_play(checked, _at("2026-11-03T12:00")) == ()
    # A midweek deadline passing before the gameweek before it is checked: both are in play.
    assert gameweeks_in_play(finished, _at("2026-11-06T19:00")) == (9, 10)
    assert gameweeks_in_play(season.iloc[0:0], _at("2026-11-06T19:00")) == ()


def test_the_matchday_zone_must_be_a_real_zone() -> None:
    assert CONFIG.matchday_zone == "Europe/London" and CONFIG.matchday_settle_hours == 3.0
    with pytest.raises(ValidationError, match="IANA"):
        ScheduleConfig(matchday_zone="Europe/Atlantis")
    with pytest.raises(ValidationError):
        ScheduleConfig(matchday_settle_hours=0)
