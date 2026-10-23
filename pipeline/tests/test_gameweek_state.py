"""ORC-01 — the gameweek state: derived from silver, the ledger and an instant, never stored.

Every transition is walked on one fixture season tail: GW36, GW37 with a postponed fixture, and
GW38, the season's last. A wrong state is invisible until a run advises a closed gameweek or never
evaluates a finished one (DP-13), so each boundary is checked on both sides.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Collection
from typing import Any

import pandas as pd
import pytest

from fpl_dof.config import Config
from fpl_dof.gameweek import (
    Due,
    Phase,
    SilverTables,
    gameweek_state,
    open_gameweek,
    season_states,
)
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import write_table
from fpl_dof.silver.tables import Table
from fpl_dof.stages import week
from fpl_dof.week.cadence import find_next_deadline_event
from fpl_dof.week.evaluation import SCORER_VERSION, evaluated, evaluation_path

DEADLINES = {36: "2027-05-08T10:00:00Z", 37: "2027-05-15T10:00:00Z", 38: "2027-05-23T13:30:00Z"}


def _at(raw: str) -> dt.datetime:
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _gameweeks(finished: dict[int, tuple[bool, bool]] | None = None) -> pd.DataFrame:
    """``finished`` maps a gameweek to FPL's (finished, data_checked); every other is neither."""
    flags = finished or {}
    return pd.DataFrame(
        [
            {
                "gameweek": gw,
                "name": f"Gameweek {gw}",
                "deadline_time": pd.Timestamp(deadline),
                "finished": flags.get(gw, (False, False))[0],
                "is_next": False,
                "data_checked": flags.get(gw, (False, False))[1],
            }
            for gw, deadline in DEADLINES.items()
        ]
    )


def _fixture(fixture_id: int, gameweek: int | None, kickoff: str | None) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "gameweek": gameweek,
        "kickoff_time": pd.Timestamp(kickoff) if kickoff else pd.NaT,
        "home_team_id": 1,
        "away_team_id": 2,
        "home_difficulty": 3,
        "away_difficulty": 3,
        "finished": False,
    }


#: GW37's first scheduled match (Friday) was postponed: FPL took it out of the gameweek. Its
#: original kick-off was before the deadline-day matches, so counting it would start Playing early.
FIXTURES = pd.DataFrame(
    [
        _fixture(1, 36, "2027-05-08T11:30:00Z"),
        _fixture(2, None, None),  # postponed out of GW37
        _fixture(3, 37, "2027-05-15T14:00:00Z"),
        _fixture(4, 37, "2027-05-16T15:00:00Z"),
        _fixture(5, 38, "2027-05-23T15:00:00Z"),
    ]
)
CHIPS = pd.DataFrame([{"entry_id": 1, "name": "freehit", "gameweek": 37}])


def _silver(finished: dict[int, tuple[bool, bool]] | None = None) -> SilverTables:
    return SilverTables(_gameweeks(finished), FIXTURES, CHIPS)


def _phase(
    gw: int, now: str, silver: SilverTables | None = None, ledger: Collection[int] = ()
) -> Phase:
    return gameweek_state(gw, silver or _silver(), ledger, _at(now)).phase


def test_a_gameweek_is_open_only_while_its_deadline_is_the_next() -> None:
    assert _phase(37, "2027-05-01T00:00:00Z") is Phase.UPCOMING  # GW36's deadline is next
    assert _phase(36, "2027-05-01T00:00:00Z") is Phase.OPEN
    assert _phase(37, "2027-05-08T10:00:01Z") is Phase.OPEN  # GW36's deadline has passed
    assert _phase(37, "2027-05-15T09:59:59Z") is Phase.OPEN


def test_the_deadline_records_the_gameweek() -> None:
    assert _phase(37, "2027-05-15T10:00:00Z") is Phase.RECORDED


def test_a_postponed_fixture_changes_when_the_gameweek_starts_playing_not_its_state() -> None:
    """The postponed match has left GW37, so the first kick-off is Saturday's 14:00."""
    assert _phase(37, "2027-05-15T13:59:59Z") is Phase.RECORDED
    assert _phase(37, "2027-05-15T14:00:00Z") is Phase.PLAYING
    # Had it stayed in the gameweek with an earlier kick-off, it would have started Playing then.
    kept = pd.DataFrame(
        [
            _fixture(2, 37, "2027-05-15T11:00:00Z"),
            *FIXTURES[FIXTURES["fixture_id"] != 2].to_dict("records"),
        ]
    )
    assert _phase(37, "2027-05-15T12:00:00Z", SilverTables(_gameweeks(), kept)) is Phase.PLAYING


def test_a_blank_gameweek_waits_on_fpl_rather_than_on_a_kick_off() -> None:
    """With no fixtures nothing kicks off: Recorded until FPL finishes and checks it."""
    blank = SilverTables(_gameweeks(), FIXTURES[FIXTURES["gameweek"] != 38])
    assert _phase(38, "2027-05-30T00:00:00Z", blank) is Phase.RECORDED
    checked = SilverTables(_gameweeks({38: (True, True)}), FIXTURES[FIXTURES["gameweek"] != 38])
    assert _phase(38, "2027-05-30T00:00:00Z", checked) is Phase.FINISHED


def test_finished_needs_both_of_fpls_flags() -> None:
    late = "2027-05-17T09:00:00Z"
    assert _phase(37, late, _silver({37: (True, False)})) is Phase.PLAYING
    assert _phase(37, late, _silver({37: (True, True)})) is Phase.FINISHED


def test_an_evaluation_for_the_current_scorer_makes_it_evaluated() -> None:
    late, silver = "2027-05-17T09:00:00Z", _silver({37: (True, True)})
    assert _phase(37, late, silver, ledger={37}) is Phase.EVALUATED
    # The ledger alone is not enough: an unfinished gameweek is not evaluated.
    assert _phase(37, late, _silver(), ledger={37}) is Phase.PLAYING


def test_each_phase_says_what_a_run_does() -> None:
    silver = _silver({36: (True, True), 37: (True, True)})
    states = season_states(silver, {36}, _at("2027-05-17T09:00:00Z"))
    assert [(s.gameweek, s.phase, s.due) for s in states] == [
        (36, Phase.EVALUATED, Due.NOTHING),
        (37, Phase.FINISHED, Due.EVALUATE),
        (38, Phase.OPEN, Due.ADVISE),
    ]
    playing = gameweek_state(37, _silver(), set(), _at("2027-05-15T15:00:00Z"))
    recorded = gameweek_state(37, _silver(), set(), _at("2027-05-15T11:00:00Z"))
    assert playing.due is Due.INGEST and recorded.due is Due.INGEST


def test_exactly_one_gameweek_is_open_until_the_last_deadline_and_none_after() -> None:
    silver = _silver({36: (True, True), 37: (True, True)})
    moment = _at("2027-05-01T00:00:00Z")
    while moment < _at("2027-06-01T00:00:00Z"):
        open_ = [s.gameweek for s in season_states(silver, set(), moment) if s.phase is Phase.OPEN]
        before_last = moment < _at(DEADLINES[38])
        assert len(open_) == (1 if before_last else 0), moment
        found = open_gameweek(silver, set(), moment)
        assert (found.gameweek if found else None) == (open_[0] if open_ else None)
        moment += dt.timedelta(hours=6)


def test_the_seasons_last_gameweek_finishes_and_is_evaluated_with_nothing_open() -> None:
    after = "2027-05-25T00:00:00Z"
    assert _phase(38, "2027-05-23T15:30:00Z") is Phase.PLAYING
    assert _phase(38, after, _silver({38: (True, True)})) is Phase.FINISHED
    assert _phase(38, after, _silver({38: (True, True)}), ledger={38}) is Phase.EVALUATED
    assert open_gameweek(_silver(), set(), _at(after)) is None


def test_the_chip_in_force_comes_from_entry_history() -> None:
    now = _at("2027-05-15T15:00:00Z")
    assert gameweek_state(37, _silver(), set(), now).chip == "freehit"
    assert gameweek_state(36, _silver(), set(), now).chip is None


def test_a_gameweek_table_without_the_checked_flag_is_never_finished() -> None:
    """A table written before ORC-01 has no ``data_checked``: fail closed, never evaluate."""
    old = SilverTables(_gameweeks({37: (True, True)}).drop(columns="data_checked"), FIXTURES)
    assert _phase(37, "2027-05-17T09:00:00Z", old) is Phase.PLAYING


def test_the_day_before_gate_reads_the_open_gameweek() -> None:
    events = [
        {"id": gw, "deadline_time": deadline, "finished": False}
        for gw, deadline in DEADLINES.items()
    ]
    assert find_next_deadline_event(events, _at("2027-05-09T00:00:00Z")) == (
        37,
        _at(DEADLINES[37]),
    )
    assert find_next_deadline_event(events, _at("2027-06-01T00:00:00Z")) is None


# --- the ledger's evaluations, and the week stage asking the state ----------------------------


def test_only_evaluations_for_the_current_scorer_version_count(layout: DataLayout) -> None:
    for gw, body in ((35, "not json"), (36, json.dumps({"scorer_version": "old"}))):
        evaluation_path(layout, gw).parent.mkdir(parents=True, exist_ok=True)
        evaluation_path(layout, gw).write_text(body, encoding="utf-8")
    evaluation_path(layout, 37).write_text(
        json.dumps({"scorer_version": SCORER_VERSION}), encoding="utf-8"
    )
    assert evaluated(layout) == frozenset({37})


def test_the_week_stage_evaluates_finished_gameweeks_and_advises_nothing_once_none_is_open(
    config: Config, layout: DataLayout, game_rules: GameRules, monkeypatch: pytest.MonkeyPatch
) -> None:
    season = config.rules.season
    write_table(layout.silver, season, Table.GAMEWEEK, _gameweeks({37: (True, True)}))
    write_table(layout.silver, season, Table.FIXTURE, FIXTURES)
    seen: list[int] = []
    monkeypatch.setattr(
        week, "read_rules", lambda *_: game_rules.model_copy(update={"season": season})
    )
    monkeypatch.setattr(week, "evaluate", lambda _ctx, _rules, due: seen.extend(due))

    result = week.run(
        StageContext(config=config, layout=layout, run_id="r", as_of=_at("2027-05-30T00:00:00Z"))
    )

    assert seen == [37]  # GW36 and GW38 are not finished; GW37 is, and is not yet evaluated
    assert result.metrics["status"] == "skipped" and not result.outputs
    assert "no gameweek is open" in str(result.metrics[week.SKIPPED_REASON_KEY])
