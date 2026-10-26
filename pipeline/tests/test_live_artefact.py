"""LIVE-04 and LIVE-03's check: ``live.json``, the gameweek in play, and the scorer against FPL.

Where being wrong here is invisible (DP-13), and so where the tests go:

* **The live total.** It is the game's total after the gameweek before, from each team's
  per-gameweek history, plus the gameweek's points. FPL's total in the picks capture counts this
  gameweek's points and hit or not depending on when it was taken; standing on it, or taking the
  hit twice, is a plausible number one hit or one gameweek out.
* **Final.** Only on the figures FPL checked: a checked gameweek still read from the captures
  before the check stays complete, and provisional.
* **One scorer.** Every figure comes from ``live_score``; the published multipliers must add up
  to what it scored, so a view never shows a second arithmetic.
* **Degrade one team.** A rival with no picks is published without a live figure, says why, and
  costs nobody else theirs (NFR-15).
* **The check.** On a finished gameweek the scorer equals FPL for the owner and every rival; a
  seeded mismatch trips the warning gate, names the team, and does not block (§5 Q3).

The gameweek is GW5: four fixtures, three of whose clubs the teams' players have. Saturday's
fixture 1 (clubs 1 v 2) is finished with bonus confirmed, fixture 2 (3 v 4) at full time awaiting
bonus, fixture 4 (7 v 8) playing; Sunday's fixture 3 (5 v 6) is to come. The owner is entry 9; the
league's rivals are 100 (a triple captain and a hit) and 101 (no picks read).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from conftest import FIXTURES
from fpl_dof.cli import EXIT_OK, main
from fpl_dof.config.models import Config
from fpl_dof.frames import as_int
from fpl_dof.gameweek import SilverTables, open_gameweek
from fpl_dof.live import LiveTables, has_kicked_off, last_total, live_gameweek, score_team
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.publish.contract import ARTEFACTS, Contract, find_contracts_root
from fpl_dof.publish.live import build_live
from fpl_dof.quality.gates import GateOutcome, GateSeverity, run_gates
from fpl_dof.quality.rules import GATES
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import read_table, table_path, write_table
from fpl_dof.silver.tables import Table, validate
from fpl_dof.stages import publish as publish_stage
from fpl_dof.stages import week as week_stage
from fpl_dof.week.ledger import record_advice, record_predictions
from squads import legal_declaration

GW = 5
OWNER, RIVAL, NO_PICKS = 9, 100, 101
DEADLINE = pd.Timestamp("2026-09-19T10:00:00Z")
KICKOFFS = {
    1: "2026-09-19T11:30:00Z",  # Saturday 12:30 UK
    2: "2026-09-19T14:00:00Z",
    4: "2026-09-19T16:30:00Z",
    3: "2026-09-20T13:00:00Z",  # Sunday
}
CLUBS = {1: (1, 2), 2: (3, 4), 3: (5, 6), 4: (7, 8)}
SATURDAY_EVENING = pd.Timestamp("2026-09-19T18:00:00Z").to_pydatetime()
MONDAY = pd.Timestamp("2026-09-21T12:00:00Z").to_pydatetime()

#: player -> (position, fixture, minutes, points, bonus) on Saturday evening.
PLAYING: dict[int, tuple[str, int, int, int, int]] = {
    1: ("GKP", 1, 90, 6, 1),
    2: ("DEF", 1, 90, 6, 0),
    3: ("DEF", 2, 90, 2, 0),
    4: ("DEF", 2, 90, 1, 0),
    5: ("DEF", 3, 0, 0, 0),
    6: ("MID", 1, 90, 5, 0),
    7: ("MID", 2, 60, 3, 0),
    8: ("MID", 3, 0, 0, 0),
    9: ("MID", 1, 90, 2, 0),
    10: ("FWD", 3, 0, 0, 0),  # the owner's captain, yet to play
    11: ("FWD", 1, 0, 0, 0),  # did not play: substituted
    12: ("GKP", 2, 0, 0, 0),
    13: ("DEF", 1, 90, 2, 0),  # first on the bench: comes on for 11
    14: ("MID", 3, 0, 0, 0),
    15: ("FWD", 2, 90, 9, 0),
}
#: Sunday's fixture played: the captain scores 8.
SUNDAY = {5: (90, 1, 0), 8: (90, 2, 0), 10: (90, 8, 1), 14: (0, 0, 0)}


def _gameweeks(*, finished: bool = False, checked: bool = False) -> pd.DataFrame:
    rows = []
    for gw in (4, 5, 6):
        deadline = DEADLINE + pd.Timedelta(days=7 * (gw - GW))
        rows.append(
            {
                "gameweek": gw,
                "name": f"Gameweek {gw}",
                "deadline_time": deadline,
                "finished": gw < GW or (gw == GW and finished),
                "is_next": gw == GW + 1,
                "data_checked": gw < GW or (gw == GW and checked),
            }
        )
    return validate(Table.GAMEWEEK, pd.DataFrame(rows))


def _fixtures(*, sunday: bool = False) -> pd.DataFrame:
    """Saturday as described; with ``sunday`` every fixture is finished with bonus confirmed."""
    states = {1: (True, True, True), 2: (True, True, False), 4: (True, False, False)}
    states[3] = (True, True, True) if sunday else (False, False, False)
    if sunday:
        states.update({2: (True, True, True), 4: (True, True, True)})
    rows = [
        {
            "fixture_id": fixture,
            "gameweek": GW,
            "kickoff_time": pd.Timestamp(KICKOFFS[fixture]),
            "home_team_id": CLUBS[fixture][0],
            "away_team_id": CLUBS[fixture][1],
            "home_difficulty": 3,
            "away_difficulty": 3,
            "started": states[fixture][0],
            "finished_provisional": states[fixture][1],
            "finished": states[fixture][2],
        }
        for fixture in (1, 2, 3, 4)
    ]
    return validate(Table.FIXTURE, pd.DataFrame(rows))


def _players() -> pd.DataFrame:
    return pd.DataFrame([{"player_id": pid, "position": spec[0]} for pid, spec in PLAYING.items()])


def _player_live(
    fixtures: pd.DataFrame, *, sunday: bool = False, final: bool = False
) -> pd.DataFrame:
    flags = {
        as_int(r.fixture_id): (bool(r.finished_provisional), bool(r.finished))
        for r in fixtures.itertuples()
    }
    rows = []
    for pid, (_, fixture, minutes, points, bonus) in PLAYING.items():
        if sunday and pid in SUNDAY:
            minutes, points, bonus = SUNDAY[pid]
        rows.append(
            {
                "gameweek": GW,
                "observed_at": SATURDAY_EVENING if not sunday else MONDAY,
                "provisional": not final,
                "fixture_id": fixture,
                "player_id": pid,
                "minutes": minutes,
                "points": points,
                "bonus": bonus,
                "bps": None,
                "finished": flags[fixture][0],
                "bonus_confirmed": flags[fixture][1],
            }
        )
    return validate(Table.PLAYER_LIVE, pd.DataFrame(rows))


def _picks(entry_id: int, *, captain: int, vice: int) -> list[dict[str, Any]]:
    return [
        {
            "entry_id": entry_id,
            "gameweek": GW,
            "player_id": pid,
            "slot": pid,
            "multiplier": 0 if pid > 11 else (2 if pid == captain else 1),
            "is_captain": pid == captain,
            "is_vice_captain": pid == vice,
        }
        for pid in PLAYING
    ]


def _entry_picks() -> pd.DataFrame:
    rows = [
        {**pick, "purchase_price": 5.0, "selling_price": 5.0}
        for pick in _picks(OWNER, captain=10, vice=6)
    ]
    return validate(Table.ENTRY_PICK, pd.DataFrame(rows))


def _league_picks() -> pd.DataFrame:
    return validate(Table.LEAGUE_PICK, pd.DataFrame(_picks(RIVAL, captain=6, vice=10)))


def _entry_live(
    *, owner: tuple[int, int, int], rival: tuple[int, int, int], final: bool
) -> pd.DataFrame:
    """Each team's FPL figures as (points before the hit, hit, season total)."""
    rows = [
        {
            "gameweek": GW,
            "observed_at": MONDAY if final else DEADLINE + pd.Timedelta(minutes=30),
            "provisional": not final,
            "entry_id": entry_id,
            "points": points,
            "transfers_cost": hit,
            "total_points": total,
            "chip": chip,
        }
        for entry_id, (points, hit, total), chip in (
            (OWNER, owner, None),
            (RIVAL, rival, "3xc"),
        )
    ]
    return validate(Table.ENTRY_LIVE, pd.DataFrame(rows))


#: The deadline's capture: no points yet; the rival's hit is already off his total. Both teams had
#: 300 after GW4.
AT_DEADLINE: dict[str, Any] = {"owner": (0, 0, 300), "rival": (0, 4, 296), "final": False}
#: Each team's season total after GW4, from the game's per-gameweek history: the owner's season
#: log, and the rival's history (ORC-14). What the live total stands on.
AFTER_GW4 = 300


def _entry_gameweeks(total: int = AFTER_GW4) -> pd.DataFrame:
    """The owner's season log: GW3 and GW4, the total after GW4 ``total``."""
    return validate(
        Table.ENTRY_GAMEWEEK,
        pd.DataFrame(
            [
                {
                    "entry_id": OWNER,
                    "gameweek": gameweek,
                    "points": 50,
                    "total_points": total - 50 * (4 - gameweek),
                    "rank": None,
                    "overall_rank": None,
                    "bank": 0.0,
                    "squad_value": 100.0,
                    "transfers": 0,
                    "transfers_cost": 0,
                    "points_on_bench": 0,
                }
                for gameweek in (3, 4)
            ]
        ),
    )


def _league_gameweeks(total: int = AFTER_GW4) -> pd.DataFrame:
    """The rival's history: his GW4 row, the total after it ``total``."""
    row = {"entry_id": RIVAL, "gameweek": 4, "transfers": 0, "transfers_cost": 0, "chip": None}
    return validate(Table.LEAGUE_GAMEWEEK, pd.DataFrame([{**row, "total_points": total}]))


def _standings() -> pd.DataFrame:
    return validate(
        Table.LEAGUE_STANDING,
        pd.DataFrame(
            [
                {
                    "league_id": 42,
                    "league_name": "The Sunday League",
                    "entry_id": entry_id,
                    "entry_name": f"Team {entry_id}",
                    "player_name": f"Manager {entry_id}",
                    "rank": rank,
                    "last_rank": rank,
                    "event_total": 0,
                    "total": 300,
                }
                for rank, entry_id in enumerate((RIVAL, OWNER, NO_PICKS), start=1)
            ]
        ),
    )


def _tables(
    *,
    sunday: bool = False,
    finished: bool = False,
    checked: bool = False,
    entry_live: dict[str, Any] | None = None,
) -> LiveTables:
    fixtures = _fixtures(sunday=sunday)
    return LiveTables(
        gameweeks=_gameweeks(finished=finished, checked=checked),
        fixtures=fixtures,
        players=_players(),
        player_live=_player_live(fixtures, sunday=sunday, final=checked),
        entry_live=_entry_live(**(entry_live or AT_DEADLINE)),
        entry_picks=_entry_picks(),
        league_picks=_league_picks(),
        entry_gameweeks=_entry_gameweeks(),
        league_gameweeks=_league_gameweeks(),
    )


#: What FPL scored once the gameweek was checked, worked out by hand from the tables above: the
#: owner's XI with 13 on for 11 is 38, and the captain's 8 doubled makes 46; the rival's triple
#: captain is player 6's 5, so 38 + 10 = 48, less his 4-point hit.
CHECKED: dict[str, Any] = {"owner": (46, 0, 346), "rival": (48, 4, 344), "final": True}


def _final(entry_live: dict[str, Any] = CHECKED) -> LiveTables:
    return _tables(sunday=True, finished=True, checked=True, entry_live=entry_live)


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract(root=find_contracts_root())


def _build(tables: LiveTables, rules: GameRules, as_of: dt.datetime) -> dict[str, Any]:
    return build_live(
        tables=tables,
        gameweek=GW,
        rules=rules,
        as_of=as_of,
        matchday_zone="Europe/London",
        settle=dt.timedelta(hours=3),
        owner_entry_id=OWNER,
        owner_name="Owner FC",
        standings=_standings(),
        contract_version=1,
    )


def _team(payload: dict[str, Any], entry_id: int) -> dict[str, Any]:
    return next(t for t in payload["teams"] if t["entry_id"] == entry_id)


# --- a Playing gameweek --------------------------------------------------------------------------


def test_a_playing_gameweek_validates_and_scores_each_team_from_the_one_scorer(
    contract: Contract, game_rules: GameRules
) -> None:
    payload = _build(_tables(), game_rules, SATURDAY_EVENING)
    contract.validate("live", payload)

    assert (payload["gameweek"], payload["status"], payload["provisional"]) == (5, "in_play", True)
    owner = _team(payload, OWNER)["live"]
    # 11 did not play and 13 comes on; the captain is yet to play and keeps the armband.
    assert owner["autosubs_out"] == [11] and owner["autosubs_in"] == [13]
    assert owner["captain_id"] == 10 and not owner["vice_used"]
    assert owner["points"] == 27 and owner["status"] == "in_play"
    # The live total takes the gameweek once: 300 after GW4, plus 27.
    assert (owner["last_total"], owner["live_total"]) == (300, 327)

    rival = _team(payload, RIVAL)["live"]
    assert (rival["chip"], rival["chip_label"]) == ("3xc", "Triple Captain")
    # 27 with player 6's 5 tripled is 37; the 4-point hit is taken once, from the gameweek.
    assert (rival["points_before_hits"], rival["hit_cost"], rival["points"]) == (37, 4, 33)
    assert (rival["last_total"], rival["live_total"]) == (300, 333)


def test_the_published_multipliers_add_up_to_what_the_scorer_scored(
    game_rules: GameRules,
) -> None:
    """A view multiplying the published points never needs a second scorer (ORC-04)."""
    for tables, as_of in ((_tables(), SATURDAY_EVENING), (_final(), MONDAY)):
        payload = _build(tables, game_rules, as_of)
        for entry_id in (OWNER, RIVAL):
            live = _team(payload, entry_id)["live"]
            total = sum(p["points"] * p["multiplier"] for p in live["players"])
            assert total == live["points_before_hits"], entry_id
            by_id = {p["player_id"]: p for p in live["players"]}
            assert by_id[11]["multiplier"] == 0 and by_id[13]["multiplier"] == 1
            armband = game_rules.chips.armband("3xc" if entry_id == RIVAL else None)
            assert by_id[live["captain_id"]]["multiplier"] == armband


def test_each_player_says_how_far_his_gameweek_has_got_and_bonus_is_never_estimated(
    game_rules: GameRules,
) -> None:
    players = {
        p["player_id"]: p
        for p in _team(_build(_tables(), game_rules, SATURDAY_EVENING), OWNER)["live"]["players"]
    }
    assert (players[1]["minutes"], players[1]["points"], players[1]["bonus"]) == (90, 6, 1)
    assert players[1]["bonus_confirmed"] and players[1]["complete"]
    # Fixture 2 is at full time with its bonus unconfirmed: final minutes, no bonus invented.
    assert players[3]["complete"] and not players[3]["bonus_confirmed"] and players[3]["bonus"] == 0
    # Sunday's players are yet to play: not complete, and so not substituted.
    assert not players[10]["complete"] and players[10]["multiplier"] == 2
    assert [p["slot"] for p in players.values()] == list(range(1, 16))


def test_rank_is_by_live_total_and_a_rival_without_picks_degrades_alone(
    game_rules: GameRules,
) -> None:
    payload = _build(_tables(), game_rules, SATURDAY_EVENING)
    assert [(t["entry_id"], t["rank"]) for t in payload["teams"]] == [
        (RIVAL, 1),
        (OWNER, 2),
        (NO_PICKS, None),
    ]
    missing = _team(payload, NO_PICKS)
    assert missing["live"] is None and missing["game"] is None
    assert "no picks" in str(missing["reason"])
    assert _team(payload, OWNER)["is_owner"] and not missing["is_owner"]
    assert _team(payload, OWNER)["player_name"] == f"Manager {OWNER}"  # the league's own name


def test_equal_live_totals_share_a_rank(game_rules: GameRules) -> None:
    # The rival's 37 less a 10-point hit, on 300 after GW4, is level with the owner's 327.
    level = {"owner": (0, 0, 300), "rival": (0, 10, 290), "final": False}
    payload = _build(_tables(entry_live=level), game_rules, SATURDAY_EVENING)
    assert _team(payload, RIVAL)["live"]["live_total"] == 300 + 27
    assert _team(payload, RIVAL)["rank"] == _team(payload, OWNER)["rank"] == 1


def _without(tables: LiveTables, **frames: pd.DataFrame | None) -> LiveTables:
    return LiveTables(
        **{**{f: getattr(tables, f) for f in LiveTables.__dataclass_fields__}, **frames}
    )


def test_the_live_total_stands_on_each_teams_history_and_takes_the_hit_once(
    game_rules: GameRules,
) -> None:
    """The owner's from his season log, the rival's from his history; a different total after GW4
    moves each live total by exactly that, and the rival's 4-point hit comes off once."""
    tables = _without(
        _tables(), entry_gameweeks=_entry_gameweeks(310), league_gameweeks=_league_gameweeks(280)
    )
    payload = _build(tables, game_rules, SATURDAY_EVENING)
    owner, rival = _team(payload, OWNER)["live"], _team(payload, RIVAL)["live"]
    assert (owner["last_total"], owner["live_total"]) == (310, 310 + 27)
    assert (rival["last_total"], rival["points"], rival["live_total"]) == (280, 33, 280 + 33)


def test_the_owners_own_history_wins_over_the_leagues_when_they_disagree(
    game_rules: GameRules,
) -> None:
    """The owner is in his league, so the league's history holds a row for him too. His own
    season log is fetched on every fast firing, the league's only by the daily ingest, so where
    the two disagree (FPL corrected his total since the league's was captured) his own is the one
    his live total stands on."""
    league = pd.concat(
        [_league_gameweeks(), _league_gameweeks(290).assign(entry_id=OWNER)], ignore_index=True
    )
    tables = _without(_tables(), entry_gameweeks=_entry_gameweeks(310), league_gameweeks=league)
    assert last_total(tables, GW, OWNER) == 310
    assert last_total(_without(tables, entry_gameweeks=None), GW, OWNER) == 290
    payload = _build(tables, game_rules, SATURDAY_EVENING)
    owner = _team(payload, OWNER)["live"]
    assert (owner["last_total"], owner["live_total"]) == (310, 310 + 27)


def test_a_league_history_written_before_the_totals_still_reads_and_its_teams_degrade_alone(
    config: Config, layout: DataLayout, game_rules: GameRules, contract: Contract
) -> None:
    """A ``league_gameweek`` file from before LIVE-03 has no ``total_points``, and is not rewritten
    while the league is unreadable. It still reads, the totals unknown: each rival in it goes
    without a live figure and says why, the owner's stands, and no silver rebuild is needed."""
    season = config.rules.season
    path = table_path(layout.silver, season, Table.LEAGUE_GAMEWEEK)
    path.parent.mkdir(parents=True, exist_ok=True)
    _league_gameweeks().drop(columns="total_points").to_parquet(path, index=False)

    old = read_table(layout.silver, season, Table.LEAGUE_GAMEWEEK)
    assert "total_points" not in old.columns
    tables = _without(_tables(), league_gameweeks=old)
    assert last_total(tables, GW, RIVAL) is None
    payload = _build(tables, game_rules, SATURDAY_EVENING)
    contract.validate("live", payload)
    rival = _team(payload, RIVAL)
    assert rival["live"] is None and "total after gameweek 4" in str(rival["reason"])
    assert _team(payload, OWNER)["live"]["live_total"] == 327


def test_a_team_without_a_total_after_the_gameweek_before_degrades_alone(
    contract: Contract, game_rules: GameRules
) -> None:
    """No row in its history for GW4: no live figure, a reason, and nobody else's lost. Its
    gameweek points are still the scorer's to check against FPL once the gameweek is final."""
    for tables, as_of in ((_tables(), SATURDAY_EVENING), (_final(), MONDAY)):
        payload = _build(_without(tables, league_gameweeks=None), game_rules, as_of)
        contract.validate("live", payload)
        rival = _team(payload, RIVAL)
        assert rival["live"] is None and rival["rank"] is None
        assert "total after gameweek 4" in str(rival["reason"])
        assert _team(payload, OWNER)["live"] is not None and _team(payload, OWNER)["rank"] == 1
    assert rival["matches_game"] is True
    _, result = _scorer_gate(_without(_final(), league_gameweeks=None), game_rules)
    assert result.outcome is GateOutcome.PASSED and result.observed["compared"] == 2


def test_before_gw1_the_last_total_is_nought(game_rules: GameRules) -> None:
    """GW1 has no gameweek before it: every team stands on 0, with no history row to read."""
    tables = _tables()
    first = {
        name: frame.assign(gameweek=frame["gameweek"] - (GW - 1))
        for name in ("gameweeks", "fixtures", "player_live", "entry_live", "entry_picks")
        if (frame := getattr(tables, name)) is not None
    }
    first["gameweeks"] = first["gameweeks"][first["gameweeks"]["gameweek"] >= 1]
    shifted = _without(tables, **first, entry_gameweeks=None, league_gameweeks=None)
    assert last_total(shifted, 1, OWNER) == 0
    team = score_team(shifted, 1, OWNER, game_rules)
    assert team.score is not None and team.score.live_total == team.score.gameweek_points == 27


def test_a_team_whose_game_figures_were_not_read_has_no_live_figure(
    game_rules: GameRules,
) -> None:
    """Its chip is FPL's to report; guessing none would score a triple captain as a single."""
    tables = _tables()
    tables = LiveTables(
        **{
            **{f: getattr(tables, f) for f in LiveTables.__dataclass_fields__},
            "entry_live": tables.entry_live[tables.entry_live["entry_id"] == OWNER],  # type: ignore[index]
        }
    )
    rival = _team(_build(tables, game_rules, SATURDAY_EVENING), RIVAL)
    assert rival["live"] is None and "chip is unknown" in str(rival["reason"])


def test_the_fixtures_and_matchdays_say_what_is_done_and_what_is_to_come(
    game_rules: GameRules,
) -> None:
    payload = _build(_tables(), game_rules, SATURDAY_EVENING)
    states = {f["fixture_id"]: f["state"] for f in payload["fixtures"]}
    assert states == {1: "bonus_confirmed", 2: "full_time", 4: "playing", 3: "to_come"}
    assert [f["fixture_id"] for f in payload["fixtures"]] == [1, 2, 4, 3]  # kick-off order
    days = {d["date"]: d for d in payload["matchdays"]}
    assert set(days) == {"2026-09-19", "2026-09-20"}
    assert (days["2026-09-19"]["fixtures"], days["2026-09-19"]["fixtures_confirmed"]) == (3, 1)
    assert not days["2026-09-19"]["done"] and not days["2026-09-20"]["done"]
    # Past the settle cap after Saturday's last kick-off, it is done with a bonus pending.
    later = _build(_tables(), game_rules, pd.Timestamp("2026-09-19T20:00:00Z").to_pydatetime())
    saturday = next(d for d in later["matchdays"] if d["date"] == "2026-09-19")
    assert saturday["done"] and saturday["bonus_pending"]


# --- complete and final --------------------------------------------------------------------------


def test_a_complete_gameweek_validates_and_is_still_provisional(
    contract: Contract, game_rules: GameRules
) -> None:
    payload = _build(_tables(sunday=True, finished=True), game_rules, MONDAY)
    contract.validate("live", payload)
    assert (payload["status"], payload["provisional"]) == ("complete", True)
    owner = _team(payload, OWNER)
    assert owner["live"]["status"] == "complete" and owner["live"]["points"] == 46
    # FPL's figures are still the deadline's: nothing is compared against them yet.
    assert owner["game"]["final"] is False and owner["matches_game"] is None


def test_a_final_gameweek_validates_and_the_scorer_equals_fpl_for_every_team(
    contract: Contract, game_rules: GameRules
) -> None:
    payload = _build(_final(), game_rules, MONDAY)
    contract.validate("live", payload)
    assert (payload["status"], payload["provisional"]) == ("final", False)
    for entry_id, (points, hit, total) in ((OWNER, CHECKED["owner"]), (RIVAL, CHECKED["rival"])):
        team = _team(payload, entry_id)
        assert team["matches_game"] is True, entry_id
        assert team["live"]["points"] == points - hit
        assert team["live"]["live_total"] == total, "the live total is FPL's own total, final"
        assert team["live"]["status"] == "final"


def test_a_checked_gameweek_read_from_pre_check_captures_is_not_final(
    contract: Contract, game_rules: GameRules
) -> None:
    """Silver says data-checked, but the refetch of the live scores and the picks after the check
    failed (the ingest warns and carries on): the figures are the pre-check captures, so neither
    the gameweek nor any team may read ``final``. It stays complete, and provisional."""
    fixtures = _fixtures(sunday=True)
    tables = LiveTables(
        gameweeks=_gameweeks(finished=True, checked=True),
        fixtures=fixtures,
        players=_players(),
        player_live=_player_live(fixtures, sunday=True, final=False),
        entry_live=_entry_live(**AT_DEADLINE),
        entry_picks=_entry_picks(),
        league_picks=_league_picks(),
        entry_gameweeks=_entry_gameweeks(),
        league_gameweeks=_league_gameweeks(),
    )
    payload = _build(tables, game_rules, MONDAY)
    contract.validate("live", payload)
    assert (payload["status"], payload["provisional"]) == ("complete", True)
    for entry_id in (OWNER, RIVAL):
        team = _team(payload, entry_id)
        assert team["live"]["status"] == "complete", entry_id
        assert team["game"]["final"] is False and team["matches_game"] is None


def test_a_team_whose_picks_were_not_refetched_after_the_check_is_not_final(
    contract: Contract, game_rules: GameRules
) -> None:
    """The scores are the post-check capture, so the gameweek is final; the rival's picks refetch
    failed, so his FPL figures are the deadline's and his team stays complete, alone."""
    tables = _final()
    assert tables.entry_live is not None
    entry_live = tables.entry_live.copy()
    rival = entry_live["entry_id"] == RIVAL
    entry_live.loc[rival, ["points", "total_points", "provisional"]] = [0, 296, True]
    tables = LiveTables(
        **{
            **{f: getattr(tables, f) for f in LiveTables.__dataclass_fields__},
            "entry_live": validate(Table.ENTRY_LIVE, entry_live),
        }
    )
    payload = _build(tables, game_rules, MONDAY)
    contract.validate("live", payload)
    assert (payload["status"], payload["provisional"]) == ("final", False)
    assert _team(payload, OWNER)["live"]["status"] == "final"
    assert _team(payload, RIVAL)["live"]["status"] == "complete"
    assert _team(payload, RIVAL)["matches_game"] is None


# --- the scorer check gate (LIVE-03) ------------------------------------------------------------


def _gate_tables(tables: LiveTables) -> dict[str, pd.DataFrame]:
    frames = {
        Table.GAMEWEEK: tables.gameweeks,
        Table.FIXTURE: tables.fixtures,
        Table.PLAYER: tables.players,
        Table.PLAYER_LIVE: tables.player_live,
        Table.ENTRY_LIVE: tables.entry_live,
        Table.ENTRY_PICK: tables.entry_picks,
        Table.LEAGUE_PICK: tables.league_picks,
        Table.ENTRY_GAMEWEEK: tables.entry_gameweeks,
        Table.LEAGUE_GAMEWEEK: tables.league_gameweeks,
    }
    return {t.value: f for t, f in frames.items() if f is not None}


def _scorer_gate(tables: LiveTables, rules: GameRules) -> Any:
    frames = _gate_tables(tables)
    gate = next(g for g in GATES if g.name == "scorer_matches_game")
    report = run_gates([gate], frames, {"tables": frames, "rules": rules})
    return report, report.results[0]


def test_the_scorer_gate_passes_when_the_scorer_equals_fpl_for_every_team(
    game_rules: GameRules,
) -> None:
    _, result = _scorer_gate(_final(), game_rules)
    assert result.outcome is GateOutcome.PASSED
    assert result.observed["compared"] == 2 and not result.observed["mismatched"]


def test_a_seeded_mismatch_trips_the_warning_gate_names_the_team_and_publishes(
    contract: Contract, game_rules: GameRules
) -> None:
    seeded = {**CHECKED, "rival": (49, 4, 345)}  # FPL says one point more than the scorer
    report, result = _scorer_gate(_final(seeded), game_rules)
    assert result.outcome is GateOutcome.FAILED
    assert result.severity is GateSeverity.WARN and report.passed, "a warning, not a block"
    assert f"entry {RIVAL}: scorer 44, FPL 45" in result.message
    assert str(OWNER) not in result.observed["mismatched"]

    payload = _build(_final(seeded), game_rules, MONDAY)
    contract.validate("live", payload)
    assert _team(payload, RIVAL)["matches_game"] is False
    assert _team(payload, OWNER)["matches_game"] is True


def test_the_scorer_gate_compares_nothing_before_fpls_figures_are_final(
    game_rules: GameRules,
) -> None:
    """FPL's figures before data-checked are the deadline's: comparing them measures the clock."""
    for tables in (_tables(), _tables(sunday=True, finished=True)):
        _, result = _scorer_gate(tables, game_rules)
        assert result.outcome is GateOutcome.PASSED
        assert "nothing to compare" in result.message


def test_the_scorer_gate_is_skipped_with_no_gameweek_in_play(game_rules: GameRules) -> None:
    frames = _gate_tables(_final())
    del frames[Table.ENTRY_LIVE.value]
    gate = next(g for g in GATES if g.name == "scorer_matches_game")
    result = run_gates([gate], frames, {"tables": frames, "rules": game_rules}).results[0]
    assert result.outcome is GateOutcome.SKIPPED


def test_the_team_reader_degrades_one_team_for_an_unknown_player(game_rules: GameRules) -> None:
    tables = _tables()
    tables = LiveTables(
        **{
            **{f: getattr(tables, f) for f in LiveTables.__dataclass_fields__},
            "players": _players()[lambda p: p["player_id"] != 15],
        }
    )
    team = score_team(tables, GW, OWNER, game_rules)
    assert team.score is None and "[15]" in str(team.reason)


# --- absent, not empty ---------------------------------------------------------------------------


def test_the_live_gameweek_is_the_latest_past_its_deadline_once_it_has_kicked_off() -> None:
    tables = _tables()
    preseason = (DEADLINE - pd.Timedelta(days=30)).to_pydatetime()
    assert live_gameweek(tables.gameweeks, preseason) is None
    assert live_gameweek(tables.gameweeks, (DEADLINE - pd.Timedelta(days=1)).to_pydatetime()) == 4
    between = (DEADLINE + pd.Timedelta(minutes=30)).to_pydatetime()  # past it, not kicked off
    assert live_gameweek(tables.gameweeks, between) == GW
    assert not has_kicked_off(tables, GW, between)
    assert has_kicked_off(tables, GW, SATURDAY_EVENING)
    assert has_kicked_off(_final(), GW, MONDAY)


def test_the_registry_publishes_live_as_optional_and_warmed() -> None:
    """The smoke check reads `required` and the offline warm-up reads `warm`, from the registry
    the types carry (WEB-04): neither names an artefact itself."""
    assert ARTEFACTS["live"].schema == "live.schema.json"
    assert not ARTEFACTS["live"].required and ARTEFACTS["live"].warm
    types = (find_contracts_root().parent / "web" / "src" / "contract" / "types.ts").read_text(
        encoding="utf-8"
    )
    assert (
        '"live": {\n    "path": "live.json",\n    "required": false,\n    "warm": true\n  }'
        in types
    )


# --- the publish stage: absent preseason, and the ledger on a matchday run ----------------------


def _silver(layout: DataLayout, season: str, *, last_gameweek: int) -> pd.DataFrame:
    """The Saturday tables in silver, the season ending at ``last_gameweek``."""
    tables = _tables()
    gameweeks = tables.gameweeks[tables.gameweeks["gameweek"] <= last_gameweek]
    players = pd.DataFrame(
        {
            "player_id": pid,
            "code": 1000 + pid,
            "web_name": f"P{pid}",
            "full_name": f"Player {pid}",
            "position": spec[0],
            "team_id": CLUBS[spec[1]][0],
            "price": 5.0,
            "status": "a",
            "chance_of_playing_next_round": None,
            "selected_by_percent": 1.0,
            "news": "",
        }
        for pid, spec in PLAYING.items()
    )
    for table, frame in (
        (Table.GAMEWEEK, gameweeks),
        (Table.FIXTURE, tables.fixtures),
        (Table.PLAYER, players),
        (Table.PLAYER_LIVE, tables.player_live),
        (Table.ENTRY_LIVE, tables.entry_live),
        (Table.ENTRY_PICK, tables.entry_picks),
        (Table.ENTRY_GAMEWEEK, tables.entry_gameweeks),
    ):
        assert frame is not None
        write_table(layout.silver, season, table, frame)
    return gameweeks


def test_the_stage_writes_live_on_the_seasons_last_weekend_with_no_gameweek_open(
    config: Config, layout: DataLayout, game_rules: GameRules, contract: Contract
) -> None:
    """GW5 the season's last: every deadline has passed, so `week` skips (LIVE-02), and the
    gameweek in play is still published, the owner scored from silver."""
    season = config.rules.season
    gameweeks = _silver(layout, season, last_gameweek=GW)
    owned = config.model_copy(update={"entry": config.entry.model_copy(update={"team_id": OWNER})})
    ctx = StageContext(config=owned, layout=layout, run_id="r", as_of=SATURDAY_EVENING)
    assert open_gameweek(SilverTables(gameweeks), (), SATURDAY_EVENING) is None

    payload = publish_stage._live(ctx, season, gameweeks, game_rules)
    assert payload is not None
    contract.validate("live", payload)
    assert payload["gameweek"] == GW
    assert [t["entry_id"] for t in payload["teams"]] == [OWNER]
    assert payload["teams"][0]["live"]["live_total"] == 327


def test_the_last_total_is_the_games_total_after_the_previous_gameweek_whatever_the_picks_say(
    config: Config, layout: DataLayout, game_rules: GameRules, contract: Contract
) -> None:
    """The live total stands on the owner's season log, the total after GW4, and not on the
    picks capture's own ``total_points``: whether FPL's total in that capture already counts this
    gameweek's points, or its hit, depends on the moment it was taken, which nothing here knows.
    This capture counts 20 points of the gameweek and not its 4-point hit; taking the gameweek
    back out of it would stand the live total on 304. The hit is still taken once."""
    season = config.rules.season
    gameweeks = _silver(layout, season, last_gameweek=6)
    mid_gameweek = _entry_live(owner=(20, 4, 320), rival=(0, 4, 296), final=False)
    write_table(layout.silver, season, Table.ENTRY_LIVE, mid_gameweek)
    owned = config.model_copy(update={"entry": config.entry.model_copy(update={"team_id": OWNER})})
    ctx = StageContext(config=owned, layout=layout, run_id="r", as_of=SATURDAY_EVENING)

    payload = publish_stage._live(ctx, season, gameweeks, game_rules)
    assert payload is not None
    contract.validate("live", payload)
    owner = payload["teams"][0]["live"]
    # 27 before the hit, 23 after it; on 300 after GW4.
    assert (owner["points"], owner["hit_cost"]) == (23, 4)
    assert (owner["last_total"], owner["live_total"]) == (300, 323)


def test_the_stage_publishes_nothing_before_the_live_gameweek_kicks_off(
    config: Config, layout: DataLayout, game_rules: GameRules
) -> None:
    season = config.rules.season
    gameweeks = _silver(layout, season, last_gameweek=6)
    for as_of in (
        DEADLINE - pd.Timedelta(days=30),  # preseason: no deadline has passed
        DEADLINE + pd.Timedelta(minutes=30),  # GW5's deadline passed, its first match to come
    ):
        ctx = StageContext(config=config, layout=layout, run_id="r", as_of=as_of.to_pydatetime())
        assert publish_stage._live(ctx, season, gameweeks, game_rules) is None


@pytest.mark.usefixtures("recorded_fpl_api")
def test_preseason_no_live_json_is_written_and_a_stale_one_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env: dict[str, str]
) -> None:
    monkeypatch.setenv("FPL_DOF_CONFIG_FILE", isolated_env["FPL_DOF_CONFIG_FILE"])
    data_dir = tmp_path / "data"
    stale = data_dir / "web" / "v1" / "live.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    assert main(["--data-dir", str(data_dir), "run"]) == EXIT_OK
    assert not stale.exists()


_RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]+")


def _masked(value: Any) -> Any:
    """A ledger document with its run ids masked: the one field two runs on one input differ in."""
    if isinstance(value, dict):
        return {k: "<run>" if k == "run_id" else _masked(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_masked(v) for v in value]
    return "<run>" if isinstance(value, str) and _RUN_ID.fullmatch(value) else value


def _declare_a_squad(config_file: Path) -> None:
    """A declared fifteen from the recorded players, so the week stage advises GW2 (DL-20)."""
    bootstrap = json.loads((FIXTURES / "bootstrap_static.json").read_text(encoding="utf-8"))
    positions = {t["id"]: t["singular_name_short"] for t in bootstrap["element_types"]}
    pool = pd.DataFrame(
        {
            "player_id": e["id"],
            "position": positions[e["element_type"]],
            "team_id": e["team"],
            "price": e["now_cost"] / 10,
        }
        for e in sorted(bootstrap["elements"], key=lambda e: e["now_cost"])
    )
    override = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    override["entry"] = {"declared_squad": [p.model_dump() for p in legal_declaration(pool)]}
    config_file.write_text(yaml.safe_dump(override), encoding="utf-8")


def _ledger(data_dir: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted((data_dir / "ledger").rglob("*")):
        if path.is_file():
            name = str(path.relative_to(data_dir / "ledger"))
            files[name] = (
                _masked(json.loads(path.read_text("utf-8")))
                if path.suffix == ".json"
                else path.read_bytes()
            )
    return files


@pytest.mark.usefixtures("recorded_fpl_api")
def test_a_matchday_run_changes_no_ledger_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env: dict[str, str]
) -> None:
    """GW1 is Playing (its first match kicked off on the Friday). Two runs on the same inputs, then
    a third after a matchday's results reach silver: the results move `live.json`, and the ledger
    after the third run is the ledger after the second, file for file, up to the run id the Open
    gameweek's advice of record is re-stamped with (DP-14, ORC-05). Nothing live reaches it."""
    monkeypatch.setenv("FPL_DOF_CONFIG_FILE", isolated_env["FPL_DOF_CONFIG_FILE"])
    monkeypatch.setenv("FPL_DOF_AS_OF", "2026-08-22T12:00:00+00:00")
    _declare_a_squad(Path(isolated_env["FPL_DOF_CONFIG_FILE"]))
    # The ledger closes by the real clock (ORC-03); stood at the pinned moment, so each run writes
    # the Open gameweek's advice of record as it would that Saturday.
    pinned = pd.Timestamp("2026-08-22T12:00:00Z").to_pydatetime()
    advice, predictions = record_advice, record_predictions
    monkeypatch.setattr(
        week_stage, "record_advice", lambda *a, now, **k: advice(*a, now=pinned, **k)
    )
    monkeypatch.setattr(
        week_stage, "record_predictions", lambda *a, now, **k: predictions(*a, now=pinned, **k)
    )
    data_dir = tmp_path / "data"
    stages = ["quality", "forecast", "optimise", "week", "publish"]
    assert main(["--data-dir", str(data_dir), "run"]) == EXIT_OK
    assert main(["--data-dir", str(data_dir), "run", "--only", *stages]) == EXIT_OK
    live_path = data_dir / "web" / "v1" / "live.json"
    before_live = json.loads(live_path.read_text("utf-8"))
    assert before_live["gameweek"] == 1
    ledger = _ledger(data_dir)
    assert any(name.startswith("advice") for name in ledger), "the runs recorded GW2's advice"
    assert any(name.startswith("predictions") for name in ledger)

    # Friday's match ends with its bonus confirmed and its players' points in.
    silver = data_dir / "silver"
    season = next(silver.glob("season=*")).name.removeprefix("season=")
    fixtures = read_table(silver, season, Table.FIXTURE)
    first = fixtures["fixture_id"] == 1
    fixtures.loc[first, ["started", "finished_provisional", "finished"]] = True
    write_table(silver, season, Table.FIXTURE, fixtures)
    live = read_table(silver, season, Table.PLAYER_LIVE)
    played = live["fixture_id"] == 1
    live.loc[played, ["finished", "bonus_confirmed"]] = True
    live.loc[played, ["minutes", "points"]] = [90, 3]
    write_table(silver, season, Table.PLAYER_LIVE, live)

    assert main(["--data-dir", str(data_dir), "run", "--only", *stages]) == EXIT_OK
    after_live = json.loads(live_path.read_text("utf-8"))
    assert after_live != before_live, "the matchday reached live.json"
    assert next(f for f in after_live["fixtures"] if f["fixture_id"] == 1)["state"] == (
        "bonus_confirmed"
    )
    assert _ledger(data_dir) == ledger
    assert not any("gw01" in name for name in ledger), "nothing records the gameweek in play"
