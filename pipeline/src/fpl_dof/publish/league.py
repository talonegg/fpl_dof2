"""The mini-league payload. E6-S10, FR-32.

Two silver tables become one artefact: ``league_standing`` is the table, ``league_pick`` is as many
of those managers' squads as the configured budget allowed. The owner's own squad comes from
``entry_pick`` when the owner is in the league but outside the squad budget, so the one row the
whole comparison hangs off is never missing merely because the owner is mid-table.

**What this module deliberately does not do is compute the comparison.** Overlap, differentials and
captain divergence are derived in the app from the squads published here. They are set arithmetic
over data the artefact already carries, so precomputing them would put a second, unarguable copy of
the answer in the payload next to its own inputs (DP-10) — and every derived figure would then have
to be re-derived anyway the moment the reader wanted it against the starting XI instead of the
fifteen.

**Absent, not empty.** When no league is configured this builder is never called and no
``league.json`` is written; the publish stage removes a stale one. That is a stronger statement than
an empty table, which a view cannot distinguish from a league nobody has joined (DP-15).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from fpl_dof.frames import as_int


def build_league(
    *,
    standings: pd.DataFrame,
    league_picks: pd.DataFrame | None,
    entry_picks: pd.DataFrame | None,
    owner_entry_id: int | None,
    gameweek: int | None,
    squad_limit: int,
    contract_version: int,
) -> dict[str, Any]:
    """The whole ``league.json`` payload. Pure: no I/O, no clock, no config loading (DP-03)."""
    squads = _squads(league_picks, gameweek)

    # The owner may sit below the squad budget and so have no `league_pick` row, while their own
    # picks were fetched in full regardless. Filling from `entry_pick` is what keeps the comparison
    # anchor present for a mid-table owner — the case where a rival view is most wanted.
    if owner_entry_id is not None and owner_entry_id not in squads:
        owner_squad = _squads(entry_picks, gameweek).get(owner_entry_id)
        if owner_squad is not None:
            squads[owner_entry_id] = owner_squad

    entries = []
    for row in _ordered(standings):
        entry_id = as_int(row["entry_id"])
        entries.append(
            {
                "entry_id": entry_id,
                "entry_name": str(row["entry_name"]),
                "player_name": str(row["player_name"]),
                "rank": as_int(row["rank"]),
                "last_rank": _optional_int(row.get("last_rank")),
                "event_total": _optional_int(row.get("event_total")),
                "total": as_int(row["total"]),
                "is_owner": entry_id == owner_entry_id,
                "squad": squads.get(entry_id),
            }
        )

    return {
        "contract_version": contract_version,
        "league": {
            "id": _league_id(standings),
            "name": _league_name(standings),
            "entries_published": len(entries),
            "squads_published": sum(1 for entry in entries if entry["squad"] is not None),
            "squad_limit": squad_limit,
        },
        "gameweek": gameweek,
        "entries": entries,
    }


def _ordered(standings: pd.DataFrame) -> list[dict[str, Any]]:
    if standings.empty:
        return []
    ordered = standings.sort_values(["rank", "entry_id"])
    return [{str(k): v for k, v in row.items()} for row in ordered.to_dict(orient="records")]


def _league_id(standings: pd.DataFrame) -> int:
    return as_int(standings["league_id"].iloc[0]) if not standings.empty else 0


def _league_name(standings: pd.DataFrame) -> str:
    return str(standings["league_name"].iloc[0]) if not standings.empty else ""


def _optional_int(value: Any) -> int | None:
    """None and NaN both mean 'not reported', which is not the same claim as zero (DL-18)."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    return as_int(value)


def _squads(picks: pd.DataFrame | None, gameweek: int | None) -> dict[int, dict[str, Any]]:
    """One squad per entry, for the published gameweek only.

    The gameweek filter is not decoration. ``entry_pick`` holds every gameweek the owner has
    played, so an unfiltered read would merge a season of squads into one 300-player "fifteen" and
    the overlap it produced downstream would look entirely plausible (DP-13).
    """
    if picks is None or picks.empty or gameweek is None:
        return {}

    current = picks[picks["gameweek"] == gameweek]
    if current.empty:
        return {}

    squads: dict[int, dict[str, Any]] = {}
    for entry_id, group in current.groupby("entry_id"):
        ordered = group.sort_values("slot")
        rows = [{str(k): v for k, v in row.items()} for row in ordered.to_dict(orient="records")]
        squads[as_int(entry_id)] = {
            "player_ids": sorted(as_int(row["player_id"]) for row in rows),
            # A starter is one the game is counting, which is `multiplier > 0` — not `slot <= 11`.
            # Automatic substitutions rewrite the multipliers of a played gameweek without moving
            # anybody's slot, so reading the slot would report the eleven who were named rather
            # than the eleven who actually scored.
            "starting_ids": [as_int(row["player_id"]) for row in rows if as_int(row["multiplier"])],
            "captain_id": _flagged(rows, "is_captain"),
            "vice_captain_id": _flagged(rows, "is_vice_captain"),
        }
    return squads


def _flagged(rows: list[dict[str, Any]], column: str) -> int | None:
    for row in rows:
        if bool(row.get(column)):
            return as_int(row["player_id"])
    return None


__all__ = ["build_league"]
