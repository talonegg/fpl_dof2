"""The gameweek in play, scored: each fetched team's provisional points (LIVE-03, LIVE-04, DL-99).

One reading of the live tables for the two places that need it: the publish stage's ``live.json``
and the quality gate that checks the scorer against FPL once the gameweek is finished. Both reach
the scorer through here, and the scorer is :func:`fpl_dof.rules.realised.live_score` itself, or
for a team with no total to stand on the :func:`~fpl_dof.rules.realised.score_lineup` it wraps
(ORC-04): nothing in this module adds, multiplies or substitutes. What it does is read a team's
picks, its fixtures, its total after the gameweek before and FPL's own figures for it out of
silver, and say plainly when one of them is missing, so that team alone goes without a live figure
(NFR-15).

Pure (DP-03): frames and an instant in, an answer out. Source-free (Invariant 1): it reads the
conformed silver shapes and nothing else.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.gameweek import (
    FixtureProgress,
    Phase,
    SilverTables,
    TeamStatus,
    gameweek_state,
    team_status,
)
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.realised import Lineup, LiveScore, live_score, performances, score_lineup


@dataclass(frozen=True, slots=True)
class LiveTables:
    """The silver tables a gameweek in play is read from. Only the gameweek table is required;
    every other absence costs the figures that needed it, said, and nothing more (DP-15)."""

    gameweeks: pd.DataFrame
    fixtures: pd.DataFrame | None = None
    players: pd.DataFrame | None = None
    player_live: pd.DataFrame | None = None
    entry_live: pd.DataFrame | None = None
    entry_picks: pd.DataFrame | None = None
    league_picks: pd.DataFrame | None = None
    entry_gameweeks: pd.DataFrame | None = None
    """The owner's season log (``entry_gameweek``): his total after the gameweek before."""
    league_gameweeks: pd.DataFrame | None = None
    """Each rival's per-gameweek history (``league_gameweek``, ORC-14): theirs."""


def live_gameweek(gameweeks: pd.DataFrame, now: dt.datetime) -> int | None:
    """The latest gameweek whose deadline is at or before ``now``: the gameweek in play until FPL
    data-checks it, then final until the next deadline (LIVE-01). ``None`` preseason."""
    if gameweeks.empty:
        return None
    moment = pd.Timestamp(now)
    moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
    past = gameweeks[pd.to_datetime(gameweeks["deadline_time"], utc=True) <= moment]
    if past.empty:
        return None
    return as_int(past.sort_values("deadline_time").iloc[-1]["gameweek"])


def has_kicked_off(tables: LiveTables, gameweek: int, now: dt.datetime) -> bool:
    """Whether ``gameweek`` is past its first kick-off at ``now``: Playing or later (ORC-01).

    Asked of the gameweek state, the one definition of Playing, so ``live.json`` appears when the
    run banner and the schedule say the gameweek started, and not by a reading of its own.
    """
    state = gameweek_state(gameweek, SilverTables(tables.gameweeks, tables.fixtures), (), now)
    return state.phase in {Phase.PLAYING, Phase.FINISHED, Phase.EVALUATED}


@dataclass(frozen=True, slots=True)
class GameFigures:
    """FPL's own figures for one team in the live gameweek, from its picks (``entry_live``)."""

    points: int
    """The gameweek's points before hits, as FPL showed them when the picks were captured."""
    hit: int
    total: int
    """The season total including this gameweek, net of every hit."""
    chip: str | None
    final: bool
    """Captured once FPL had data-checked the gameweek. Before that the figures are the
    deadline's capture (the picks are fetched once after the deadline, LIVE-01), so they are no
    measure of the gameweek's points and nothing is checked against them."""

    @property
    def net(self) -> int:
        """The gameweek's points net of its hit: what :attr:`LiveScore.gameweek_points` claims."""
        return self.points - self.hit


@dataclass(frozen=True, slots=True)
class LivePlayer:
    """One of a team's fifteen in the gameweek in play, as far as his gameweek has got."""

    player_id: int
    slot: int
    minutes: int
    points: int
    bonus: int
    """FPL's bonus so far: confirmed or not, never estimated from BPS (R1.4.3 §5 Q2)."""
    bonus_confirmed: bool
    """Every fixture he has has its bonus confirmed (or he has none)."""
    complete: bool
    """Every fixture he has is at full time (or he has none): his minutes can no longer grow."""
    multiplier: int
    """As the scorer applied it: 0 off the field, 1 on it, the armband's on whoever wears it."""
    is_captain: bool
    is_vice_captain: bool


@dataclass(frozen=True, slots=True)
class LiveTeam:
    """One team's gameweek in play. ``score`` is ``None`` when something it needs is missing, and
    ``reason`` then says what."""

    entry_id: int
    game: GameFigures | None
    score: LiveScore | None
    status: TeamStatus | None
    players: tuple[LivePlayer, ...]
    reason: str | None
    comparable: bool
    """The gameweek is finished and FPL's figures and the scores are both final: the one moment
    the scorer can be checked against FPL (LIVE-03, R1.4.3 §5 Q3)."""
    points: int | None = None
    """The scorer's gameweek points net of the hit, whenever the team could be scored: also for a
    team without a live total (no total after the gameweek before), so the check still has it."""

    @property
    def matches_game(self) -> bool | None:
        """Whether the scorer's gameweek points equal FPL's, net of the hit on both sides; ``None``
        until they can be compared."""
        if not self.comparable or self.points is None or self.game is None:
            return None
        return self.points == self.game.net


def score_team(tables: LiveTables, gameweek: int, entry_id: int, rules: GameRules) -> LiveTeam:
    """One team's gameweek ``gameweek``, scored by the one scorer from silver.

    Its picks are the owner's ``entry_pick`` or a rival's ``league_pick`` for the gameweek, its
    chip and hit are FPL's own for it (``entry_live``), its players' gameweeks are
    ``player_live``, and its live total stands on its total after the gameweek before, from the
    game's per-gameweek history (:func:`last_total`). Any of those missing leaves this team
    without a live figure, and no other.
    """
    game = _game_figures(tables.entry_live, gameweek, entry_id)
    picks = _picks(tables, gameweek, entry_id)
    live = _rows(tables.player_live, gameweek)

    def degraded(reason: str) -> LiveTeam:
        return LiveTeam(entry_id, game, None, None, (), reason, False)

    if picks is None:
        return degraded("no picks were read for this team")
    if game is None:
        # The chip and the hit are FPL's to report: guessing either would score a bench boost as
        # an ordinary week, plausibly and wrongly (DP-13).
        return degraded("FPL's own figures for this team were not read, so its chip is unknown")
    if live is None:
        return degraded("no live scores for the gameweek were read")
    positions = _positions(tables.players)
    ids = [as_int(p) for p in picks["player_id"]]
    unknown = [pid for pid in ids if pid not in positions]
    if unknown:
        return degraded(f"players {unknown} have no position the rules know")

    lineup = _lineup(picks, positions, game, rules)
    if lineup is None:
        return degraded("its picks name no captain or no vice-captain")

    mine = live[live["player_id"].isin(ids)]
    perfs = performances(
        mine.assign(
            total_points=mine["points"],
            position=mine["player_id"].map(lambda pid: positions[as_int(pid)].value),
        ),
        positions={pid: positions[pid] for pid in ids},
    )
    comparable = _finished(tables.gameweeks, gameweek) and game.final and _scores_final(live)
    before = last_total(tables, gameweek, entry_id)
    if before is None:
        # The gameweek's points are still the scorer's to check; only the total has nothing to
        # stand on, and a guessed one would rank the team plausibly and wrongly (DP-13).
        return LiveTeam(
            entry_id,
            game,
            None,
            None,
            (),
            f"its season total after gameweek {gameweek - 1} was not read",
            comparable,
            score_lineup(lineup, perfs, rules).net_points,
        )
    score = live_score(lineup, perfs, rules, last_total=before)
    # Final only on the figures FPL checked: the gameweek data-checked, and both the scores and
    # this team's own figures from captures taken after the check. A refetch that failed leaves
    # the team complete, provisional, rather than "final" over the figures before (DP-13).
    final = _checked(tables.gameweeks, gameweek) and _scores_final(live) and game.final
    status = team_status(_progress(mine).values(), data_checked=final)

    armband = rules.chips.armband(lineup.chip)
    fielded = set(score.scored.fielded)
    players = []
    for pick in picks.itertuples():
        pid = as_int(pick.player_id)
        rows = mine[mine["player_id"] == pid]
        multiplier = (armband if pid == score.scored.captain_id else 1) if pid in fielded else 0
        players.append(
            LivePlayer(
                player_id=pid,
                slot=as_int(pick.slot),
                minutes=perfs[pid].minutes,
                points=perfs[pid].points,
                bonus=as_int(rows["bonus"].sum()) if not rows.empty else 0,
                bonus_confirmed=bool(rows["bonus_confirmed"].astype(bool).all()),
                complete=perfs[pid].complete,
                multiplier=multiplier,
                is_captain=bool(pick.is_captain),
                is_vice_captain=bool(pick.is_vice_captain),
            )
        )
    return LiveTeam(
        entry_id, game, score, status, tuple(players), None, comparable, score.gameweek_points
    )


def last_total(tables: LiveTables, gameweek: int, entry_id: int) -> int | None:
    """The team's season total after the gameweek before ``gameweek``: 0 before GW1, else the
    game's own figure from its per-gameweek history, the owner's season log first and then the
    league's; ``None`` when neither has the row. The owner first because he is in his league too,
    and his own history is fetched on every fast firing where the league's is the daily ingest's:
    where the two disagree, his is the later word.

    Not FPL's total in the picks capture less the gameweek's points: whether that total already
    counts this gameweek's points, or its hit, depends on the moment the capture was taken, and
    the picks are captured once, just after the deadline (LIVE-01). The history row is the total
    after a gameweek finished, every hit to then taken; :func:`live_score` adds this gameweek's
    points, its hit taken once, from the gameweek (LIVE-03).
    """
    previous = gameweek - 1
    if previous < 1:
        return 0
    for frame in (tables.entry_gameweeks, tables.league_gameweeks):
        rows = _rows(frame, previous)
        if rows is None or "total_points" not in rows.columns:
            # A league history written before LIVE-03 carries no totals: unknown, so this team
            # degrades alone rather than failing the read (DP-15).
            continue
        totals = rows.loc[rows["entry_id"] == entry_id, "total_points"].dropna()
        if not totals.empty:
            return as_int(totals.iloc[0])
    return None


def gameweek_status(tables: LiveTables, gameweek: int) -> TeamStatus:
    """How far the whole gameweek has got, on the same rule as a team's, over every fixture it
    has: in play, bonus pending, complete, or final once data-checked and the live scores
    published with it are the capture taken after the check. Until then a checked gameweek is
    complete, and provisional: the scores beside it are not the ones FPL checked."""
    final = _checked(tables.gameweeks, gameweek) and _scores_final(
        _rows(tables.player_live, gameweek)
    )
    return team_status(fixture_progress(tables.fixtures, gameweek).values(), data_checked=final)


def fixture_progress(fixtures: pd.DataFrame | None, gameweek: int) -> dict[int, FixtureProgress]:
    """Each of the gameweek's fixtures, by id, as far as it has got (FPL's flags). A postponed
    fixture has left the gameweek, so it is not here."""
    if fixtures is None or fixtures.empty:
        return {}
    rows = fixtures[fixtures["gameweek"] == gameweek]
    return {
        as_int(row["fixture_id"]): FixtureProgress(
            finished=_flag(row, "finished_provisional") or bool(row["finished"]),
            bonus_confirmed=bool(row["finished"]),
        )
        for row in rows.to_dict(orient="records")
    }


def _flag(row: Mapping[Hashable, Any], column: str) -> bool:
    """An optional fixture flag: absent or unknown is false, not a guess (LIVE-01)."""
    value = row.get(column)
    return value is not None and not pd.isna(value) and bool(value)


def _rows(frame: pd.DataFrame | None, gameweek: int) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    rows = frame[frame["gameweek"] == gameweek]
    return None if rows.empty else rows


def _scores_final(rows: pd.DataFrame | None) -> bool:
    """The live scores are from a capture taken once FPL had data-checked the gameweek."""
    return rows is not None and not rows["provisional"].astype(bool).any()


def _game_figures(
    entry_live: pd.DataFrame | None, gameweek: int, entry_id: int
) -> GameFigures | None:
    rows = _rows(entry_live, gameweek)
    if rows is None:
        return None
    mine = rows[rows["entry_id"] == entry_id]
    if mine.empty:
        return None
    row = mine.iloc[0]
    chip = row["chip"]
    return GameFigures(
        points=as_int(row["points"]),
        hit=as_int(row["transfers_cost"]),
        total=as_int(row["total_points"]),
        chip=None if chip is None or pd.isna(chip) else str(chip),
        final=not bool(row["provisional"]),
    )


def _picks(tables: LiveTables, gameweek: int, entry_id: int) -> pd.DataFrame | None:
    """The team's picks for the gameweek: the owner's own table first, then the league's."""
    for frame in (tables.entry_picks, tables.league_picks):
        rows = _rows(frame, gameweek)
        if rows is not None:
            mine = rows[rows["entry_id"] == entry_id]
            if not mine.empty:
                return mine.sort_values("slot")
    return None


def _positions(players: pd.DataFrame | None) -> dict[int, Position]:
    if players is None or players.empty:
        return {}
    known = {p.value for p in Position}
    return {
        as_int(row.player_id): Position(str(row.position))
        for row in players.itertuples()
        if str(row.position) in known
    }


def _lineup(
    picks: pd.DataFrame, positions: Mapping[int, Position], game: GameFigures, rules: GameRules
) -> Lineup | None:
    """The team as submitted: the starters by slot, the reserve goalkeeper and the outfield bench
    in order, both armbands, and FPL's own chip and hit for the gameweek."""
    starting_size = rules.squad.starting_size
    starting = tuple(
        as_int(p.player_id) for p in picks.itertuples() if as_int(p.slot) <= starting_size
    )
    bench = [as_int(p.player_id) for p in picks.itertuples() if as_int(p.slot) > starting_size]
    bench_gkp = next((pid for pid in bench if positions[pid] is Position.GKP), None)
    captain = next((as_int(p.player_id) for p in picks.itertuples() if bool(p.is_captain)), None)
    vice = next((as_int(p.player_id) for p in picks.itertuples() if bool(p.is_vice_captain)), None)
    if captain is None or vice is None:
        return None
    return Lineup(
        starting=starting,
        bench_order=tuple(pid for pid in bench if pid != bench_gkp),
        bench_gkp=bench_gkp,
        captain=captain,
        vice_captain=vice,
        chip=game.chip,
        hit_points=game.hit,
    )


def _progress(rows: pd.DataFrame) -> dict[int, FixtureProgress]:
    """The fixtures a team's players have, by id, from the live rows' own flags."""
    progress: dict[int, FixtureProgress] = {}
    for row in rows.to_dict(orient="records"):
        progress[as_int(row["fixture_id"])] = FixtureProgress(
            finished=bool(row["finished"]), bonus_confirmed=bool(row["bonus_confirmed"])
        )
    return progress


def _gameweek_row(gameweeks: pd.DataFrame, gameweek: int) -> Mapping[Hashable, Any] | None:
    rows = gameweeks[gameweeks["gameweek"] == gameweek]
    return None if rows.empty else rows.iloc[0].to_dict()


def _finished(gameweeks: pd.DataFrame, gameweek: int) -> bool:
    row = _gameweek_row(gameweeks, gameweek)
    return row is not None and _flag(row, "finished")


def _checked(gameweeks: pd.DataFrame, gameweek: int) -> bool:
    row = _gameweek_row(gameweeks, gameweek)
    return row is not None and _flag(row, "finished") and _flag(row, "data_checked")


__all__ = [
    "GameFigures",
    "LivePlayer",
    "LiveTables",
    "LiveTeam",
    "fixture_progress",
    "gameweek_status",
    "has_kicked_off",
    "last_total",
    "live_gameweek",
    "score_team",
]
