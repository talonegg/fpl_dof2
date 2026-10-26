"""The gameweek in play, published: ``live.json`` (LIVE-04, DL-99, FR-26, FR-32).

The latest gameweek past its deadline, once it has kicked off: its status, the matchdays done and
to come, each fixture's state, and for the owner and each mini-league rival their provisional
points, hit, chip, live total, rank by live total and their fifteen as the scorer has them. Every
figure comes from :func:`fpl_dof.live.score_team`, and so from the one realised scorer (ORC-04);
this module arranges and ranks, and never scores.

**Provisional, and says so.** Until FPL data-checks the gameweek, and the scores published are the
capture taken after the check, the figures can move, and ``provisional`` is true. ``log.json``
and the evaluation are the record (ORC-05): nothing reads this artefact back, and nothing here
writes to the ledger (DP-14).

**Absent, not empty.** Preseason, and from a deadline until that gameweek's first kick-off, this
builder is not called and no ``live.json`` is written; the publish stage removes a stale one, as
for ``league.json`` (DP-15).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.gameweek import TeamStatus, matchdays
from fpl_dof.live import (
    GameFigures,
    LiveTables,
    LiveTeam,
    fixture_progress,
    gameweek_status,
    score_team,
)
from fpl_dof.optimise.chips import chip_label
from fpl_dof.rules.models import GameRules


def build_live(
    *,
    tables: LiveTables,
    gameweek: int,
    rules: GameRules,
    as_of: dt.datetime,
    matchday_zone: str,
    settle: dt.timedelta,
    owner_entry_id: int | None,
    owner_name: str | None,
    standings: pd.DataFrame | None,
    contract_version: int,
) -> dict[str, Any]:
    """The whole ``live.json`` payload. Pure: no I/O, no clock, no config loading (DP-03)."""
    status = gameweek_status(tables, gameweek)
    fixtures = _fixtures(tables.fixtures, gameweek, as_of, matchday_zone)
    days = [
        {
            "date": day.day.isoformat(),
            "fixtures": day.fixtures,
            "fixtures_confirmed": day.finished,
            "last_kickoff": _iso(day.last_kickoff),
            "done": day.done,
            "bonus_pending": day.bonus_pending,
        }
        for day in matchdays(tables.fixtures, as_of, zone=matchday_zone, settle=settle)
        if day.gameweek == gameweek
    ]

    teams = [
        _team(score_team(tables, gameweek, entry_id, rules), names, entry_id == owner_entry_id)
        for entry_id, names in _entries(standings, owner_entry_id, owner_name).items()
    ]
    _rank(teams)

    return {
        "contract_version": contract_version,
        "gameweek": gameweek,
        "status": status.value,
        "provisional": status is not TeamStatus.FINAL,
        "as_of": _iso(as_of),
        "observed_at": _observed_at(tables.player_live, gameweek),
        "matchdays": days,
        "fixtures": fixtures,
        "teams": sorted(teams, key=_order),
    }


def _entries(
    standings: pd.DataFrame | None, owner_entry_id: int | None, owner_name: str | None
) -> dict[int, dict[str, str | None]]:
    """Every team to publish, by entry id: the owner, then the league's table in rank order.

    The whole table, not only the teams whose picks were read: a rival past ``league_rival_limit``
    is published without a live figure, and says why, rather than vanishing (LIVE-05).
    """
    entries: dict[int, dict[str, str | None]] = {}
    if owner_entry_id is not None:
        entries[owner_entry_id] = {"entry_name": owner_name or "", "player_name": None}
    if standings is not None and not standings.empty:
        for row in standings.sort_values(["rank", "entry_id"]).to_dict(orient="records"):
            entries[as_int(row["entry_id"])] = {
                "entry_name": str(row["entry_name"]),
                "player_name": str(row["player_name"]),
            }
    return entries


def _team(team: LiveTeam, names: dict[str, str | None], is_owner: bool) -> dict[str, Any]:
    game = team.game
    score = team.score
    live: dict[str, Any] | None = None
    if score is not None and team.status is not None:
        chip = game.chip if game is not None else None
        live = {
            "points": score.gameweek_points,
            "points_before_hits": score.scored.points_before_hits,
            "hit_cost": score.scored.hit_points,
            "chip": chip,
            "chip_label": None if chip is None else chip_label(chip),
            "last_total": score.live_total - score.gameweek_points,
            "live_total": score.live_total,
            "status": team.status.value,
            "captain_id": score.scored.captain_id,
            "vice_used": score.scored.vice_used,
            "autosubs_in": list(score.scored.autosubs_in),
            "autosubs_out": list(score.scored.autosubs_out),
            "players": [
                {
                    "player_id": p.player_id,
                    "slot": p.slot,
                    "minutes": p.minutes,
                    "points": p.points,
                    "bonus": p.bonus,
                    "bonus_confirmed": p.bonus_confirmed,
                    "complete": p.complete,
                    "multiplier": p.multiplier,
                    "is_captain": p.is_captain,
                    "is_vice_captain": p.is_vice_captain,
                }
                for p in team.players
            ],
        }
    return {
        "entry_id": team.entry_id,
        "entry_name": names["entry_name"],
        "player_name": names["player_name"],
        "is_owner": is_owner,
        "rank": None,
        "live": live,
        "reason": team.reason,
        "game": None if game is None else _game(game),
        "matches_game": team.matches_game,
    }


def _game(game: GameFigures) -> dict[str, Any]:
    """FPL's own figures for a team, published beside the scorer's so a mismatch can be shown."""
    return {"points": game.points, "hit_cost": game.hit, "total": game.total, "final": game.final}


def _rank(teams: list[dict[str, Any]]) -> None:
    """Rank the teams with a live figure by live total, best first; equal totals share a rank.
    A team without one is unranked here: it has no live total to stand on (LIVE-05 ranks it by
    FPL's own figures)."""
    ranked = sorted(
        (t for t in teams if t["live"] is not None), key=lambda t: -t["live"]["live_total"]
    )
    previous: int | None = None
    rank = 0
    for position, team in enumerate(ranked, start=1):
        total = team["live"]["live_total"]
        if total != previous:
            rank, previous = position, total
        team["rank"] = rank


def _order(team: dict[str, Any]) -> tuple[int, int, int]:
    rank = team["rank"]
    return (0 if rank is not None else 1, rank or 0, team["entry_id"])


def _fixtures(
    fixtures: pd.DataFrame | None, gameweek: int, as_of: dt.datetime, zone: str
) -> list[dict[str, Any]]:
    """The gameweek's fixtures in kick-off order, each with its state and its matchday."""
    if fixtures is None or fixtures.empty:
        return []
    progress = fixture_progress(fixtures, gameweek)
    rows = fixtures[fixtures["gameweek"] == gameweek].sort_values(["kickoff_time", "fixture_id"])
    moment = pd.Timestamp(as_of)
    moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
    published = []
    for row in rows.to_dict(orient="records"):
        fixture_id = as_int(row["fixture_id"])
        kickoff = row["kickoff_time"]
        kicked = kickoff is not None and not pd.isna(kickoff)
        stamp = pd.Timestamp(kickoff).tz_convert("UTC") if kicked else None
        state = progress[fixture_id]
        started = row.get("started")
        if started is None or pd.isna(started):
            # A fixture table from before LIVE-01 has no started flag: the clock stands in for it.
            started = stamp is not None and stamp <= moment
        published.append(
            {
                "fixture_id": fixture_id,
                "kickoff_time": None if stamp is None else _iso(stamp.to_pydatetime()),
                "matchday": None if stamp is None else stamp.tz_convert(zone).date().isoformat(),
                "home_team_id": as_int(row["home_team_id"]),
                "away_team_id": as_int(row["away_team_id"]),
                "state": "bonus_confirmed"
                if state.bonus_confirmed
                else "full_time"
                if state.finished
                else "playing"
                if bool(started)
                else "to_come",
            }
        )
    return published


def _observed_at(player_live: pd.DataFrame | None, gameweek: int) -> str | None:
    """When the scores were captured: the newest live row's ``observed_at``."""
    if player_live is None or player_live.empty:
        return None
    rows = player_live[player_live["gameweek"] == gameweek]
    if rows.empty:
        return None
    return _iso(pd.Timestamp(rows["observed_at"].max()).to_pydatetime())


def _iso(moment: dt.datetime) -> str:
    stamp = pd.Timestamp(moment)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.to_pydatetime().isoformat().replace("+00:00", "Z")


__all__ = ["build_live"]
