"""The mini-league artefact — `league.json`. E6-S10, FR-32, DL-40.

Where being wrong here is invisible (DP-13), and therefore where the effort goes:

* **The gameweek filter.** ``entry_pick`` holds every gameweek the owner has played. Reading it
  unfiltered would merge a season of squads into one "fifteen" of three hundred players, and the
  overlap computed downstream would be a large, plausible, meaningless number. Nothing throws.
* **Starters come from the multiplier, not the slot.** An automatic substitution rewrites
  multipliers without moving anybody's slot, so reading the slot reports the eleven who were *named*
  rather than the eleven who actually played — right most weeks, wrong exactly when it matters.
* **Absent versus zero.** A rival outside the fetch budget must publish ``squad: null``, never an
  empty squad; an unreported ``event_total`` must be null, never 0. Both would render as measured
  facts nobody measured.
* **The owner anchor.** The whole comparison hangs off one row, and the owner can sit below the
  squad budget while their own picks were fetched in full. If that fill-in fails, every differential
  in the view silently disappears.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from fpl_dof.publish.contract import Contract, find_contracts_root
from fpl_dof.publish.league import build_league

OWNER = 200
RIVAL = 100


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract(root=find_contracts_root())


def _standings(entry_ids: tuple[int, ...] = (RIVAL, OWNER)) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "league_id": 4242,
                "league_name": "The Sunday League",
                "entry_id": entry_id,
                "entry_name": f"Team {entry_id}",
                "player_name": f"Manager {entry_id}",
                "rank": rank,
                "last_rank": rank + 1,
                "event_total": 50 + rank,
                "total": 300 - rank,
            }
            for rank, entry_id in enumerate(entry_ids, start=1)
        ]
    )


def _picks(
    entry_id: int, player_ids: list[int], gameweek: int, captain: int | None
) -> list[dict[str, Any]]:
    return [
        {
            "entry_id": entry_id,
            "gameweek": gameweek,
            "player_id": player_id,
            "slot": slot,
            # Slots 12-15 are the bench and score nothing.
            "multiplier": 0 if slot > 11 else 1,
            "is_captain": player_id == captain,
            "is_vice_captain": False,
        }
        for slot, player_id in enumerate(player_ids, start=1)
    ]


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "entry_id",
            "gameweek",
            "player_id",
            "slot",
            "multiplier",
            "is_captain",
            "is_vice_captain",
        ],
    )


def _fifteen(start: int) -> list[int]:
    return list(range(start, start + 15))


_UNSET = object()


def _build(
    *,
    standings: pd.DataFrame | None = None,
    league_picks: pd.DataFrame | object | None = _UNSET,
    entry_picks: pd.DataFrame | None = None,
    owner_entry_id: int | None = OWNER,
    gameweek: int | None = 3,
    squad_limit: int = 20,
    contract_version: int = 1,
) -> dict[str, Any]:
    if standings is None:
        standings = _standings()
    resolved_picks: pd.DataFrame | None
    if league_picks is _UNSET:
        resolved_picks = _frame(_picks(RIVAL, _fifteen(1), 3, 2) + _picks(OWNER, _fifteen(5), 3, 6))
    else:
        assert league_picks is None or isinstance(league_picks, pd.DataFrame)
        resolved_picks = league_picks
    return build_league(
        standings=standings,
        league_picks=resolved_picks,
        entry_picks=entry_picks,
        owner_entry_id=owner_entry_id,
        gameweek=gameweek,
        squad_limit=squad_limit,
        contract_version=contract_version,
    )


def test_a_populated_league_validates(contract: Contract) -> None:
    contract.validate("league", _build())


def test_the_owner_row_is_marked_and_is_unique(contract: Contract) -> None:
    payload = _build()
    owners = [entry for entry in payload["entries"] if entry["is_owner"]]

    assert len(owners) == 1
    assert owners[0]["entry_id"] == OWNER


def test_squads_are_restricted_to_the_published_gameweek(contract: Contract) -> None:
    """The bug this exists for: a season of picks merged into one three-hundred-player squad."""
    many_gameweeks = _frame(
        _picks(RIVAL, _fifteen(1), 1, 2)
        + _picks(RIVAL, _fifteen(40), 2, 41)
        + _picks(RIVAL, _fifteen(80), 3, 81)
    )
    payload = _build(league_picks=many_gameweeks)
    rival = next(e for e in payload["entries"] if e["entry_id"] == RIVAL)

    assert rival["squad"] is not None
    assert len(rival["squad"]["player_ids"]) == 15
    assert rival["squad"]["player_ids"] == _fifteen(80)
    contract.validate("league", payload)


def test_starters_come_from_the_multiplier_not_the_slot() -> None:
    """An automatic substitution rewrites multipliers and leaves every slot where it was."""
    rows = _picks(RIVAL, _fifteen(1), 3, 2)
    # The named starter in slot 3 did not play; the substitute in slot 13 came on for them.
    rows[2]["multiplier"] = 0
    rows[12]["multiplier"] = 1

    payload = _build(league_picks=_frame(rows + _picks(OWNER, _fifteen(5), 3, 6)))
    squad = next(e for e in payload["entries"] if e["entry_id"] == RIVAL)["squad"]

    assert squad is not None
    assert len(squad["starting_ids"]) == 11
    assert rows[2]["player_id"] not in squad["starting_ids"]
    assert rows[12]["player_id"] in squad["starting_ids"]


def test_a_rival_outside_the_budget_has_a_null_squad_not_an_empty_one(contract: Contract) -> None:
    payload = _build(league_picks=_frame(_picks(OWNER, _fifteen(5), 3, 6)))
    rival = next(e for e in payload["entries"] if e["entry_id"] == RIVAL)

    assert rival["squad"] is None
    assert payload["league"]["squads_published"] == 1
    contract.validate("league", payload)


def test_the_owner_squad_is_filled_from_their_own_picks_when_outside_the_budget(
    contract: Contract,
) -> None:
    """A mid-table owner is when a rival view is most wanted, and when this fill-in could fail."""
    payload = _build(
        league_picks=_frame(_picks(RIVAL, _fifteen(1), 3, 2)),
        entry_picks=_frame(_picks(OWNER, _fifteen(5), 3, 6)),
    )
    owner = next(e for e in payload["entries"] if e["is_owner"])

    assert owner["squad"] is not None
    assert owner["squad"]["player_ids"] == _fifteen(5)
    contract.validate("league", payload)


def test_no_scored_gameweek_publishes_the_table_and_no_squads(contract: Contract) -> None:
    payload = _build(gameweek=None, league_picks=None, entry_picks=None)

    assert payload["gameweek"] is None
    assert payload["league"]["squads_published"] == 0
    assert all(entry["squad"] is None for entry in payload["entries"])
    contract.validate("league", payload)


def test_an_unreported_event_total_is_null_rather_than_zero(contract: Contract) -> None:
    standings = _standings()
    standings.loc[standings["entry_id"] == RIVAL, "event_total"] = None
    payload = _build(standings=standings)
    rival = next(e for e in payload["entries"] if e["entry_id"] == RIVAL)

    assert rival["event_total"] is None
    contract.validate("league", payload)


def test_entries_are_published_in_rank_order(contract: Contract) -> None:
    payload = _build(standings=_standings((OWNER, RIVAL)))
    ranks = [entry["rank"] for entry in payload["entries"]]

    assert ranks == sorted(ranks)


def test_no_owner_configured_leaves_every_row_unmarked(contract: Contract) -> None:
    payload = _build(owner_entry_id=None)

    assert all(entry["is_owner"] is False for entry in payload["entries"])
    contract.validate("league", payload)
