"""Shared squad builders for the E1 tests.

A module rather than fixtures because these are called with arguments and composed; and a module
rather than one test file importing another, which gives the same file two module names and
confuses type checking.
"""

from __future__ import annotations

import pandas as pd

from fpl_dof.config.models import DeclaredPick
from fpl_dof.frames import as_float, as_int

#: The squad the rules require. Restated here so a helper that quietly builds fourteen players
#: fails loudly rather than producing tests that assert nothing.
COMPOSITION: tuple[tuple[str, int], ...] = (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3))

#: Six clubs, so a three-per-club limit is satisfiable across a full 2/5/5/3 squad.
CLUB_COUNT = 6

_POOL: tuple[tuple[str, int, float], ...] = (
    ("GKP", 6, 4.5),
    ("DEF", 12, 4.5),
    ("MID", 12, 5.0),
    ("FWD", 9, 5.5),
)


def players() -> pd.DataFrame:
    """A player pool that comfortably holds a legal squad, with budget headroom to spare."""
    rows = []
    player_id = 1
    for position, count, price in _POOL:
        for index in range(count):
            rows.append(
                {
                    "player_id": player_id,
                    "web_name": f"{position}{index}",
                    "position": position,
                    "team_id": (index % CLUB_COUNT) + 1,
                    "price": price,
                    "status": "a",
                    "chance_of_playing_next_round": None,
                    "selected_by_percent": 1.0,
                    "news": "",
                }
            )
            player_id += 1
    return pd.DataFrame(rows)


def legal_declaration(pool: pd.DataFrame) -> tuple[DeclaredPick, ...]:
    """A legal 15 drawn from ``pool``.

    The club counter is deliberately shared across positions: the limit applies to the whole squad,
    and a per-position counter builds a squad that looks fine and is not.
    """
    picks: list[DeclaredPick] = []
    per_club: dict[int, int] = {}
    for position, needed in COMPOSITION:
        remaining = needed
        for row in pool[pool["position"] == position].itertuples():
            if remaining == 0:
                break
            club = as_int(row.team_id)
            if per_club.get(club, 0) >= 3:
                continue
            picks.append(
                DeclaredPick(player_id=as_int(row.player_id), purchase_price=as_float(row.price))
            )
            per_club[club] = per_club.get(club, 0) + 1
            remaining -= 1
        assert remaining == 0, f"the pool cannot supply {needed} {position} within the club limit"
    return tuple(picks)


def same_position_swap(pool: pd.DataFrame, held: list[int]) -> tuple[int, int]:
    """A sell/buy pair that keeps composition and the club limit intact.

    Computed rather than written down: two hardcoded IDs make the test pass or fail on how the
    pool happens to be ordered, which is a property of the fixture and not of the code.
    """
    indexed = pool.set_index("player_id")
    clubs: dict[int, int] = {}
    for player_id in held:
        club = as_int(indexed.loc[player_id, "team_id"])
        clubs[club] = clubs.get(club, 0) + 1

    for out_id in held:
        position = str(indexed.loc[out_id, "position"])
        out_club = as_int(indexed.loc[out_id, "team_id"])
        for row in pool[pool["position"] == position].itertuples():
            candidate = as_int(row.player_id)
            if candidate in held:
                continue
            after = dict(clubs)
            after[out_club] -= 1
            after[as_int(row.team_id)] = after.get(as_int(row.team_id), 0) + 1
            if all(count <= 3 for count in after.values()):
                return out_id, candidate
    raise AssertionError("the pool offers no legal same-position swap")
