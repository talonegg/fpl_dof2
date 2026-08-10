"""E1-S4 deadlines and alerts, and E1-S5 reconciliation.

The deadline tests exist because of a specific, dated hazard: **the UK and Australian clock changes
do not coincide**. The UK leaves BST in late October; Australia enters AEDT in early October. For
the weeks in between, the offset is +11 instead of the +10 that holds for most of the season, and
any code that assumes a constant gap is wrong exactly then and correct either side of it — the
hardest kind of bug to notice and the most expensive to hit, because it lands on a real deadline.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from fpl_dof.config.models import AlertsConfig
from fpl_dof.rules.models import GameRules
from fpl_dof.squad.state import Provenance, SquadState
from fpl_dof.week.alerts import AlertSeverity, collect_alerts
from fpl_dof.week.deadline import (
    UK_ZONE,
    NoDeadlineError,
    describe_deadline,
    next_deadline,
    to_contract,
)
from fpl_dof.week.reconcile import DivergenceStatus, reconcile

SYDNEY = "Australia/Sydney"


def _gameweeks(*deadlines: tuple[int, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "gameweek": gameweek,
                "name": f"Gameweek {gameweek}",
                "deadline_time": pd.Timestamp(when),
                "finished": False,
                "is_next": False,
            }
            for gameweek, when in deadlines
        ]
    )


def test_the_next_deadline_is_the_next_one_by_time(game_rules: GameRules) -> None:
    """Chosen by clock, not by FPL's ``is_next`` flag, which updates when the API does."""
    frame = _gameweeks(
        (1, "2026-08-21T17:30:00Z"), (2, "2026-08-28T17:30:00Z"), (3, "2026-09-12T10:00:00Z")
    )
    view = next_deadline(
        frame,
        now=dt.datetime(2026, 8, 25, tzinfo=dt.UTC),
        local_zone=SYDNEY,
        decide_by_hours=12,
    )
    assert view.gameweek == 2


def test_a_finished_season_says_so_rather_than_returning_nothing() -> None:
    frame = _gameweeks((1, "2026-08-21T17:30:00Z"))
    with pytest.raises(NoDeadlineError, match="season is over"):
        next_deadline(
            frame,
            now=dt.datetime(2027, 6, 1, tzinfo=dt.UTC),
            local_zone=SYDNEY,
            decide_by_hours=12,
        )


def test_gw1_renders_as_saturday_morning_locally() -> None:
    """The finding in INPUTS-REQUIRED §7: an 18:30 BST Friday deadline is 03:30 Saturday AEST."""
    frame = _gameweeks((1, "2026-08-21T17:30:00Z"))
    view = next_deadline(
        frame,
        now=dt.datetime(2026, 8, 10, tzinfo=dt.UTC),
        local_zone=SYDNEY,
        decide_by_hours=12,
    )

    assert view.uk.strftime("%a %H:%M") == "Fri 18:30"
    assert view.local.strftime("%a %H:%M") == "Sat 03:30"
    assert view.offset_hours == 9.0


def test_the_offset_is_not_a_constant_across_the_season() -> None:
    """The clock-change window. August is UK+9; November is UK+11.

    A single hardcoded offset is right for most of the season and wrong for the weeks that matter
    most, which is why the offset is computed per deadline rather than once.
    """
    august = _gameweeks((1, "2026-08-21T17:30:00Z"))
    november = _gameweeks((13, "2026-11-28T11:00:00Z"))
    now = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)

    early = next_deadline(august, now=now, local_zone=SYDNEY, decide_by_hours=12)
    late = next_deadline(november, now=now, local_zone=SYDNEY, decide_by_hours=12)

    assert early.offset_hours == 9.0
    assert late.offset_hours == 11.0
    assert early.offset_hours != late.offset_hours


def test_decide_by_is_earlier_than_the_deadline_and_is_reported() -> None:
    frame = _gameweeks((1, "2026-08-21T17:30:00Z"))
    view = next_deadline(
        frame,
        now=dt.datetime(2026, 8, 10, tzinfo=dt.UTC),
        local_zone=SYDNEY,
        decide_by_hours=12,
    )

    assert view.decide_by_utc < view.deadline_utc
    assert view.decide_by_utc == view.deadline_utc - dt.timedelta(hours=12)
    text = "\n".join(describe_deadline(view))
    assert "decide by" in text
    assert "UK" in text and "AE" in text


def test_the_contract_carries_utc_and_lets_the_browser_render_zones() -> None:
    """DL-11: store and compute in UTC; render locally at the edge, including in the browser."""
    frame = _gameweeks((1, "2026-08-21T17:30:00Z"))
    view = next_deadline(
        frame,
        now=dt.datetime(2026, 8, 10, tzinfo=dt.UTC),
        local_zone=SYDNEY,
        decide_by_hours=12,
    )
    payload = to_contract(view)

    assert str(payload["deadline_utc"]).endswith("Z")
    assert str(payload["decide_by_utc"]).endswith("Z")
    assert payload["local_zone"] == SYDNEY
    assert payload["uk_zone"] == UK_ZONE


# --- alerts -----------------------------------------------------------------------------------


def _state(player_ids: list[int], chips_used: tuple[str, ...] = ()) -> SquadState:
    from fpl_dof.rules.models import Position
    from fpl_dof.squad.state import HeldPlayer

    return SquadState(
        entry_id=1,
        gameweek=5,
        players=tuple(
            HeldPlayer(
                player_id=pid,
                position=Position.MID,
                team_id=1,
                current_price=5.0,
                purchase_price=5.0,
                web_name=f"P{pid}",
            )
            for pid in player_ids
        ),
        bank=0.0,
        free_transfers=1,
        chips_used=chips_used,
        provenance=Provenance.DECLARED,
    )


def _player_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_an_injured_owned_player_is_urgent(game_rules: GameRules) -> None:
    players = _player_frame(
        [
            {
                "player_id": 1,
                "web_name": "Hurt",
                "status": "i",
                "news": "Knee injury",
                "chance_of_playing_next_round": 0,
                "selected_by_percent": 10.0,
            }
        ]
    )
    alerts = collect_alerts(
        state=_state([1]),
        players=players,
        rules=game_rules,
        config=AlertsConfig(),
        current_gameweek=5,
    )
    availability = [a for a in alerts if a.category == "availability"]
    assert availability and availability[0].severity is AlertSeverity.URGENT
    assert "Knee injury" in availability[0].message


def test_an_unowned_injured_player_raises_nothing(game_rules: GameRules) -> None:
    """Attention is the scarce resource; 500 injured players I do not own is noise."""
    players = _player_frame(
        [
            {
                "player_id": 99,
                "web_name": "Other",
                "status": "i",
                "news": "Out",
                "chance_of_playing_next_round": 0,
                "selected_by_percent": 10.0,
            }
        ]
    )
    alerts = collect_alerts(
        state=_state([1]),
        players=players,
        rules=game_rules,
        config=AlertsConfig(),
        current_gameweek=5,
    )
    assert [a for a in alerts if a.category == "availability"] == []


def _chips() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "chip_id": 1,
                "name": "wildcard",
                "chip_type": "transfer",
                "start_event": 2,
                "stop_event": 19,
            },
            {
                "chip_id": 2,
                "name": "bboost",
                "chip_type": "team",
                "start_event": 1,
                "stop_event": 19,
            },
            {
                "chip_id": 3,
                "name": "wildcard",
                "chip_type": "transfer",
                "start_event": 20,
                "stop_event": 38,
            },
        ]
    )


@pytest.mark.parametrize(
    ("gameweek", "expected"),
    [(5, AlertSeverity.INFO), (12, AlertSeverity.WARNING), (17, AlertSeverity.URGENT)],
)
def test_chip_expiry_escalates_as_the_deadline_approaches(
    gameweek: int, expected: AlertSeverity, game_rules: GameRules
) -> None:
    """E2-S7: it must be impossible to reach the expiry without having been told, repeatedly."""
    alerts = collect_alerts(
        state=_state([1]),
        players=_player_frame(
            [
                {
                    "player_id": 1,
                    "web_name": "P1",
                    "status": "a",
                    "news": "",
                    "chance_of_playing_next_round": None,
                    "selected_by_percent": 1.0,
                }
            ]
        ),
        rules=game_rules,
        config=AlertsConfig(),
        current_gameweek=gameweek,
        chips=_chips(),
    )
    chip_alerts = [a for a in alerts if a.category == "chips"]
    assert chip_alerts
    first_set = next(a for a in chip_alerts if a.detail and a.detail["expires_gameweek"] == 19)
    assert first_set.severity is expected


def test_the_chip_expiry_gameweek_is_read_not_written_down(game_rules: GameRules) -> None:
    """Invariant 2. "Set one expires at GW19" is true this season and is not a constant."""
    chips = _chips()
    chips.loc[chips["stop_event"] == 19, "stop_event"] = 17

    alerts = collect_alerts(
        state=_state([1]),
        players=_player_frame(
            [
                {
                    "player_id": 1,
                    "web_name": "P1",
                    "status": "a",
                    "news": "",
                    "chance_of_playing_next_round": None,
                    "selected_by_percent": 1.0,
                }
            ]
        ),
        rules=game_rules,
        config=AlertsConfig(),
        current_gameweek=10,
        chips=chips,
    )
    expiries = {a.detail["expires_gameweek"] for a in alerts if a.category == "chips" and a.detail}
    assert 17 in expiries
    assert 19 not in expiries


def test_a_chip_already_played_stops_being_chased(game_rules: GameRules) -> None:
    alerts = collect_alerts(
        state=_state([1], chips_used=("wildcard", "bboost")),
        players=_player_frame(
            [
                {
                    "player_id": 1,
                    "web_name": "P1",
                    "status": "a",
                    "news": "",
                    "chance_of_playing_next_round": None,
                    "selected_by_percent": 1.0,
                }
            ]
        ),
        rules=game_rules,
        config=AlertsConfig(),
        current_gameweek=10,
        chips=_chips(),
    )
    first_set = [
        a
        for a in alerts
        if a.category == "chips" and a.detail and a.detail["expires_gameweek"] == 19
    ]
    assert first_set == []


# --- reconciliation ---------------------------------------------------------------------------


def _picks(player_ids: list[int], captain: int, vice: int, gameweek: int = 2) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entry_id": 1,
                "gameweek": gameweek,
                "player_id": pid,
                "slot": index + 1,
                "multiplier": 1 if index < 11 else 0,
                "is_captain": pid == captain,
                "is_vice_captain": pid == vice,
                "purchase_price": None,
                "selling_price": None,
            }
            for index, pid in enumerate(player_ids)
        ]
    )


def test_advice_followed_exactly_produces_no_divergence() -> None:
    squad = list(range(1, 16))
    advised = {
        "gameweek": 2,
        "squad": squad,
        "starting": squad[:11],
        "captain": 1,
        "vice_captain": 2,
    }
    result = reconcile(
        gameweek=2, entry_id=1, advised=advised, picks=_picks(squad, captain=1, vice=2)
    )
    assert result.followed
    assert result.divergences == ()


def test_an_unexplained_difference_is_surfaced_not_absorbed() -> None:
    """Usually a submission error. Worth catching in GW3 rather than discovering in May."""
    squad = list(range(1, 16))
    played = [*squad[:14], 99]
    advised = {
        "gameweek": 2,
        "squad": squad,
        "starting": squad[:11],
        "captain": 1,
        "vice_captain": 2,
    }
    result = reconcile(
        gameweek=2, entry_id=1, advised=advised, picks=_picks(played, captain=1, vice=2)
    )

    assert not result.followed
    assert result.unexplained
    assert all(d.status is DivergenceStatus.UNEXPLAINED for d in result.unexplained)


def test_a_difference_with_a_recorded_reason_is_an_override() -> None:
    """ASM-6: the human overrules, correctly. That is evidence, not error — if it is recorded."""
    squad = list(range(1, 16))
    played = [*squad[:14], 99]
    advised = {
        "gameweek": 2,
        "squad": squad,
        "starting": squad[:11],
        "captain": 1,
        "vice_captain": 2,
    }
    result = reconcile(
        gameweek=2,
        entry_id=1,
        advised=advised,
        picks=_picks(played, captain=1, vice=2),
        overrides={"15": "press conference ruled him out", "99": "the replacement I chose"},
    )

    assert not result.followed
    assert result.unexplained == ()
    assert all(d.status is DivergenceStatus.OVERRIDE for d in result.divergences)


def test_a_different_captain_is_its_own_divergence() -> None:
    squad = list(range(1, 16))
    advised = {
        "gameweek": 2,
        "squad": squad,
        "starting": squad[:11],
        "captain": 1,
        "vice_captain": 2,
    }
    result = reconcile(
        gameweek=2, entry_id=1, advised=advised, picks=_picks(squad, captain=3, vice=2)
    )

    captain = [d for d in result.divergences if d.kind.value == "captain"]
    assert len(captain) == 1
    assert result.played_captain == 3
    assert result.advised_captain == 1


def test_reconciling_against_the_wrong_gameweek_is_refused() -> None:
    """Reconciling GW2 advice against GW3 picks would blame this week for next week's transfers."""
    squad = list(range(1, 16))
    advised = {"gameweek": 2, "squad": squad, "starting": squad[:11], "captain": 1}
    with pytest.raises(ValueError, match="no picks recorded"):
        reconcile(
            gameweek=2,
            entry_id=1,
            advised=advised,
            picks=_picks(squad, captain=1, vice=2, gameweek=3),
        )
