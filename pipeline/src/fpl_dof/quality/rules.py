"""The gates themselves.

Each declares its class, its severity, and **the requirement it protects**. Thresholds live in
configuration, not here (DP-06): a gate that hardcodes "at least 400 players" is a gate that fails
the day the Premier League changes squad rules, and the fix would be a code change under deadline
pressure.

Severity is assigned by asking one question: *if this fires, is the resulting squad wrong, or just
worth a look?* Only the first kind blocks.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from fpl_dof.config.models import QualityConfig
from fpl_dof.live import LiveTables, score_team
from fpl_dof.quality.gates import GateSeverity
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.tables import Table

CheckResult = tuple[bool, str, dict[str, object]]


class GateClass(StrEnum):
    SCHEMA = "schema"
    RANGE = "range"
    REFERENTIAL = "referential"
    FRESHNESS_AND_VOLUME = "freshness_and_volume"


@dataclass(frozen=True, slots=True)
class Gate:
    name: str
    gate_class: GateClass
    severity: GateSeverity
    table: str
    requirement: str
    """The requirement ID this protects. Not decoration — DP-14, and it is what makes a gate
    arguable rather than merely obstructive."""

    summary: str
    check: Callable[[pd.DataFrame, Mapping[str, object]], CheckResult]


def _config(context: Mapping[str, object]) -> QualityConfig:
    found = context.get("quality")
    return found if isinstance(found, QualityConfig) else QualityConfig()


# --- volume ------------------------------------------------------------------------------------


def _enough_players(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    """The gate that catches the failure nobody anticipates.

    A source outage that returns 30 players instead of 700 produces a silver layer that passes
    every schema, range and referential check, and a squad built from it looks entirely reasonable.
    Volume is the only check that sees it.
    """
    minimum = _config(context).minimum_players
    count = len(frame)
    return (
        count >= minimum,
        f"{count} players, at least {minimum} expected",
        {"count": count, "minimum": minimum},
    )


def _volume_has_not_collapsed(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    """Row count against the previous run.

    An absolute floor cannot catch a table that halves while staying above it. A relative check
    can, and it is the difference between noticing a partial outage and shipping one.
    """
    previous = context.get("previous_row_counts")
    if not isinstance(previous, Mapping):
        return True, "no previous run to compare against", {}
    before = previous.get(Table.PLAYER.value)
    if not isinstance(before, int) or before <= 0:
        return True, "no previous player count recorded", {}

    ratio = len(frame) / before
    floor = _config(context).minimum_volume_ratio
    return (
        ratio >= floor,
        f"player count is {ratio:.0%} of the previous run ({len(frame)} vs {before}), "
        f"floor is {floor:.0%}",
        {"ratio": round(ratio, 4), "current": len(frame), "previous": before},
    )


def _teams_are_a_full_league(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    expected = _config(context).expected_teams
    count = len(frame)
    return (
        count == expected,
        f"{count} teams, exactly {expected} expected",
        {"count": count, "expected": expected},
    )


def _fixtures_are_a_full_season(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    expected = _config(context).expected_fixtures
    count = len(frame)
    return (
        count == expected,
        f"{count} fixtures, exactly {expected} expected",
        {"count": count, "expected": expected},
    )


# --- freshness ---------------------------------------------------------------------------------


def _snapshot_is_fresh(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    """How old the newest snapshot behind this run is.

    Deliberately a warning rather than an error. A stale snapshot still produces an *honest*
    recommendation — one that says what was true yesterday — and blocking on it would take the
    tool offline in precisely the situation where the API is down and a decision is still due
    (DP-15). What must never happen is presenting it as fresh.
    """
    age = context.get("snapshot_age_seconds")
    if not isinstance(age, int | float):
        return True, "no snapshot age recorded", {}
    limit = _config(context).maximum_snapshot_age_hours * 3600
    hours = age / 3600
    return (
        age <= limit,
        f"newest snapshot is {hours:.1f}h old, limit is {limit / 3600:.0f}h",
        {"age_hours": round(hours, 2), "limit_hours": limit / 3600},
    )


def _player_gameweeks_reach_the_latest_finished(
    frame: pd.DataFrame, context: Mapping[str, object]
) -> CheckResult:
    """Players whose club played the latest finished gameweek but who have no row for it.

    A stale per-player cache produces a table that passes every other gate: the rows it has are
    right, it just stops a gameweek early, and the forecast trains without the latest result. The
    weekly per-player cache TTL did exactly that to GW7 in October 2026. Warn, not block: last
    week's evidence still gives an honest forecast (DP-15), but it must not pass for current.
    """
    tables = context.get("tables")
    tbl_dict: Mapping[str, pd.DataFrame] = tables if isinstance(tables, Mapping) else {}
    gameweeks = tbl_dict.get(Table.GAMEWEEK.value)
    fixtures = tbl_dict.get(Table.FIXTURE.value)
    if gameweeks is None or fixtures is None:
        return True, "no gameweek or fixture table to check against", {}
    finished = gameweeks.loc[gameweeks["finished"].astype(bool), "gameweek"]
    if finished.empty:
        return True, "no gameweek has finished yet", {}
    latest = int(finished.max())
    lagging, expected, clubs = lagging_players(
        frame[frame["season"] == context.get("season")], fixtures, latest
    )
    if not expected:
        return (
            not clubs,
            f"no player_gameweek rows this season, though GW{latest} has finished",
            {"latest_finished": latest},
        )
    share = lagging / expected
    limit = _config(context).maximum_lagging_player_share
    return (
        share <= limit,
        f"{lagging} of {expected} players have no GW{latest} row ({share:.0%}), "
        f"limit is {limit:.0%}",
        {"latest_finished": latest, "lagging": lagging, "players": expected},
    )


def lagging_players(
    season_rows: pd.DataFrame, fixtures: pd.DataFrame, gameweek: int
) -> tuple[int, int, set[int]]:
    """``(lagging, expected, clubs)``: of the ``expected`` players whose club played a finished
    fixture in ``gameweek``, how many have no row for it yet. One season's rows only. The
    evaluation step asks the same of a gameweek before it judges it once (ORC-05)."""
    played = fixtures[(fixtures["gameweek"] == gameweek) & fixtures["finished"].astype(bool)]
    clubs = set(played["home_team_id"]) | set(played["away_team_id"])
    last = season_rows.groupby("player_id").agg(
        gameweek=("gameweek", "max"), team_id=("team_id", "first")
    )
    expected = last[last["team_id"].isin(clubs)]
    return int((expected["gameweek"] < gameweek).sum()), len(expected), clubs


def _deadlines_are_in_the_future(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    """At least one gameweek is still ahead. A season that has entirely ended is a real state,
    but so is a gameweek table cached from last season, and they look identical."""
    now = context.get("now")
    if not isinstance(now, dt.datetime):
        return False, "no as-of time in the gate context", {}
    moment = pd.Timestamp(now)
    ahead = int((frame["deadline_time"] > moment).sum())
    return (
        ahead > 0 or bool(frame["finished"].all()),
        f"{ahead} deadline(s) still ahead",
        {"ahead": ahead},
    )


# --- range -------------------------------------------------------------------------------------


def _prices_are_plausible(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    """Catches the tenths-versus-millions mistake, which is the single most likely unit bug here.

    A price of 145.0 parses, validates and produces a squad nobody can afford. A price of 0.45
    produces a squad of fifteen superstars. Both are silent.
    """
    config = _config(context)
    low = frame["price"].min()
    high = frame["price"].max()
    ok = bool(config.minimum_price <= low and high <= config.maximum_price)
    return (
        ok,
        f"prices span £{low:.1f}m-£{high:.1f}m, expected within "
        f"£{config.minimum_price:.1f}m-£{config.maximum_price:.1f}m",
        {"min": float(low), "max": float(high)},
    )


def _ownership_is_a_percentage(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    high = float(frame["selected_by_percent"].max())
    low = float(frame["selected_by_percent"].min())
    return (
        low >= 0.0 and high <= 100.0,
        f"ownership spans {low:.1f}%-{high:.1f}%",
        {"min": low, "max": high},
    )


def _difficulty_is_on_the_published_scale(
    frame: pd.DataFrame, context: Mapping[str, object]
) -> CheckResult:
    values = pd.concat([frame["home_difficulty"], frame["away_difficulty"]])
    low, high = int(values.min()), int(values.max())
    return (
        low >= 1 and high <= 5,
        f"fixture difficulty spans {low}-{high}, expected 1-5",
        {"min": low, "max": high},
    )


def _temporal_monotonicity_and_containment(
    frame: pd.DataFrame, context: Mapping[str, object]
) -> CheckResult:
    """Prove temporal containment and monotonicity across silver tables (Invariant 5).

    1. Price history timestamps must be monotonic per player and not in the future.
    2. This season's metric rows are observed no later than their ``as_of_gameweek`` deadline, and
       its ``player_gameweek`` rows kick off after their own gameweek's deadline (DL-83).
    """
    tables = context.get("tables")
    tbl_dict: Mapping[str, pd.DataFrame] = tables if isinstance(tables, Mapping) else {}

    # Extract gameweek deadlines
    deadlines: dict[int, pd.Timestamp] = {}
    gw_table = tbl_dict.get(Table.GAMEWEEK.value, frame)
    if (
        isinstance(gw_table, pd.DataFrame)
        and "gameweek" in gw_table.columns
        and "deadline_time" in gw_table.columns
    ):
        known = gw_table.dropna(subset=["gameweek", "deadline_time"])
        deadlines = dict(
            zip(
                known["gameweek"].astype(int),
                pd.to_datetime(known["deadline_time"], utc=True),
                strict=True,
            )
        )

    # 1. Price history check
    price_hist = tbl_dict.get(Table.PRICE_HISTORY.value)
    if price_hist is None and "observed_at" in frame.columns and "player_id" in frame.columns:
        price_hist = frame

    now_val = context.get("now")
    now_ts = pd.to_datetime(now_val, utc=True) if isinstance(now_val, str | dt.datetime) else None

    if price_hist is not None and not price_hist.empty:
        obs = pd.to_datetime(price_hist["observed_at"], utc=True)
        if now_ts is not None:
            future = price_hist[obs > now_ts]
            if not future.empty:
                bad = future.iloc[0]
                pid = bad.get("player_id", bad.get("player_code", "unknown"))
                ts_str = str(bad["observed_at"])
                return (
                    False,
                    f"price_history contains future-dated observation at {ts_str} "
                    f"(after {now_ts}) for player {pid}",
                    {
                        "violating_entity": f"player_id={pid}",
                        "timestamp": ts_str,
                        "deadline": str(now_ts),
                    },
                )

        key = "player_id" if "player_id" in price_hist.columns else "player_code"
        if key in price_hist.columns:
            for pid, group in price_hist.groupby(key, sort=False):
                diffs = pd.to_datetime(group["observed_at"], utc=True).diff()
                non_pos = group[diffs <= pd.Timedelta(0)]
                if not non_pos.empty:
                    bad = non_pos.iloc[0]
                    ts_str = str(bad["observed_at"])
                    entity = f"{key}={pid!s}"
                    return (
                        False,
                        f"price_history is not strictly monotonic for {entity} at {ts_str}",
                        {
                            "violating_entity": entity,
                            "timestamp": ts_str,
                            "deadline": "strictly_increasing",
                        },
                    )

    # 2. Containment, on the columns the strict schemas hold (DL-83). Only this season's rows:
    # its deadlines are the only ones silver knows.
    season = context.get("season")
    deadline = pd.Series(deadlines, dtype="datetime64[ns, UTC]")
    for t_name in (Table.PLAYER_METRIC.value, Table.PLAYER_ADVANCED.value):
        metric = tbl_dict.get(t_name)
        if metric is None or metric.empty:
            continue
        rows = metric[(metric["season"] == season) & metric["as_of_gameweek"].notna()]
        due = rows["as_of_gameweek"].astype(int).map(deadline)
        late = rows[pd.to_datetime(rows["observed_at"], utc=True) > due]
        if not late.empty:
            bad = late.iloc[0]
            gw = int(bad["as_of_gameweek"])
            return _leak(t_name, bad, "observed_at", f"after the GW{gw} deadline", deadline[gw])

    played = tbl_dict.get(Table.PLAYER_GAMEWEEK.value)
    if played is not None and not played.empty:
        rows = played[(played["season"] == season) & played["kickoff_time"].notna()]
        own = rows["gameweek"].astype(int).map(deadline)
        early = rows[pd.to_datetime(rows["kickoff_time"], utc=True) <= own]
        if not early.empty:
            # Kicked off before its own deadline: the outcome was already a feature when it was
            # being predicted.
            bad = early.iloc[0]
            gw = int(bad["gameweek"])
            return _leak(
                Table.PLAYER_GAMEWEEK.value,
                bad,
                "kickoff_time",
                f"before the GW{gw} deadline",
                deadline[gw],
            )

    return True, "timestamps respect gameweek deadlines and price history is monotonic", {}


def _leak(
    table: str, row: pd.Series, column: str, when: str, deadline: pd.Timestamp
) -> CheckResult:
    key = "player_code" if pd.notna(row.get("player_code")) else "source_player_id"
    entity = f"{key}={row.get(key)}"
    return (
        False,
        f"{table} has {column} {row[column]} {when} {deadline} for {entity}",
        {"violating_entity": entity, "timestamp": str(row[column]), "deadline": str(deadline)},
    )


# --- referential -------------------------------------------------------------------------------


def _players_belong_to_known_teams(
    frame: pd.DataFrame, context: Mapping[str, object]
) -> CheckResult:
    teams = context.get("team_ids")
    if not isinstance(teams, frozenset | set):
        return True, "no team table to check against", {}
    orphans = sorted(set(frame["team_id"]) - set(teams))
    return (
        not orphans,
        f"{len(orphans)} player team_id(s) point at no team: {orphans[:5]}",
        {"orphans": orphans[:20]},
    )


def _fixtures_reference_known_teams(
    frame: pd.DataFrame, context: Mapping[str, object]
) -> CheckResult:
    teams = context.get("team_ids")
    if not isinstance(teams, frozenset | set):
        return True, "no team table to check against", {}
    referenced = set(frame["home_team_id"]) | set(frame["away_team_id"])
    orphans = sorted(referenced - set(teams))
    return (
        not orphans,
        f"{len(orphans)} fixture team reference(s) point at no team: {orphans[:5]}",
        {"orphans": orphans[:20]},
    )


def _history_belongs_to_known_players(
    frame: pd.DataFrame, context: Mapping[str, object]
) -> CheckResult:
    players = context.get("player_ids")
    if not isinstance(players, frozenset | set):
        return True, "no player table to check against", {}
    orphans = sorted(set(frame["player_id"]) - set(players))
    return (
        not orphans,
        f"{len(orphans)} history row(s) reference an unknown player: {orphans[:5]}",
        {"orphans": orphans[:20]},
    )


def _crosswalk_is_mostly_matched(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    """How many of each source's players resolution failed to identify (FR-07).

    The gate that stands between this project and R-10. A matcher that quietly stops working does
    not raise: it produces a crosswalk with fewer rows in it, every one of which is still perfectly
    valid, and a forecast that has simply lost a source's signal for half the league. Only the rate
    sees that.

    Per source rather than overall, because one broken source averaged against three working ones
    is exactly the failure an aggregate hides.

    **The current season only.** A backfilled season is matched against *this* season's player
    list, so everyone who has since left the league is unmatched in it — correctly, and in numbers
    that would swamp the rate this gate exists to watch. Judging a matcher by how many of last
    year's departed players it failed to find in this year's squad list is judging it on the one
    thing it cannot do.
    """
    limit = _config(context).maximum_unmatched_player_rate
    season = context.get("season")
    current = frame[frame["season"] == season] if season is not None else frame
    if current.empty:
        current = frame
    worst_source, worst_rate, counts = "", 0.0, {}
    for source, group in current.groupby("source"):
        unmatched = int((group["match_method"] == "unmatched").sum())
        rate = unmatched / len(group) if len(group) else 0.0
        counts[str(source)] = {"unmatched": unmatched, "total": len(group)}
        if rate > worst_rate:
            worst_source, worst_rate = str(source), rate
    return (
        worst_rate <= limit,
        f"worst unmatched rate is {worst_rate:.1%}"
        + (f" for {worst_source}" if worst_source else "")
        + f", limit is {limit:.0%}",
        {"rate": round(worst_rate, 4), "limit": limit, "by_source": counts},
    )


def _crosswalk_identities_are_one_to_one(
    frame: pd.DataFrame, context: Mapping[str, object]
) -> CheckResult:
    """No canonical player is claimed twice by one source.

    Resolution already fails hard on this, and the gate exists anyway: a guardrail that has only
    ever been enforced at the point of writing stops being enforced the moment somebody writes the
    table another way. This one checks the artefact rather than the process.
    """
    matched = frame[frame["player_id"].notna()]
    duplicated = matched.duplicated(subset=["season", "source", "player_id"], keep=False)
    offenders = (
        matched.loc[duplicated, ["source", "player_id"]].astype(str).agg("/".join, axis=1).tolist()
    )
    return (
        not offenders,
        f"{len(offenders)} crosswalk row(s) map two source players onto one footballer: "
        f"{offenders[:5]}",
        {"offenders": offenders[:20]},
    )


def _crosswalk_is_for_this_season(
    frame: pd.DataFrame, context: Mapping[str, object]
) -> CheckResult:
    """Every crosswalk row belongs to a season this run actually asked for.

    Resolution is re-run from scratch each season because transfers invalidate club-based matching
    (Design §3.2). A row carried over from last season is last season's answer wearing this
    season's clothes — *unless* last season was explicitly backfilled, in which case its identities
    are the point rather than the residue, and the prior-season features depend on them existing.
    """
    expected = context.get("season")
    if not isinstance(expected, str):
        return True, "no season in context to check against", {}
    requested = context.get("backfill_seasons")
    backfilled = requested if isinstance(requested, tuple | list) else ()
    allowed = {expected} | {str(value) for value in backfilled}
    stale = sorted({str(value) for value in frame["season"].unique()} - allowed)
    return (
        not stale,
        f"crosswalk carries {len(stale)} season(s) nobody asked for: {stale[:3]}",
        {"stale_seasons": stale[:10], "expected": sorted(allowed)},
    )


# --- schema ------------------------------------------------------------------------------------


def _every_player_has_a_position(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    missing = int(frame["position"].isna().sum())
    return missing == 0, f"{missing} player(s) have no position", {"missing": missing}


def _prices_are_never_null(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    missing = int(frame["price"].isna().sum())
    return missing == 0, f"{missing} player(s) have no price", {"missing": missing}


# --- the scorer against FPL (LIVE-03) -------------------------------------------------------


def _scorer_matches_game(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    """The one realised scorer's gameweek points for each fetched team against FPL's own.

    Checked once the live gameweek is finished and FPL's figures and the scores are both from the
    data-checked capture: before that FPL's figures are the deadline's (the picks are fetched once
    after it), and a comparison would only measure the clock. Both sides net of the gameweek's hit.

    **A warning, not a block** (R1.4.3 §5 Q3): a scorer that disagrees with FPL publishes and says
    so, here, on `/health` and against the team in `live.json`; the evaluation waits for
    data-checked regardless (ORC-05). No tolerance: the scorer's claim is that it is the game's
    rules (ORC-04), and a point either way is a rule written wrong, which is what DP-13 means by
    a wrong answer that looks right.
    """
    tables = context.get("tables")
    tbl_dict: Mapping[str, pd.DataFrame] = tables if isinstance(tables, Mapping) else {}
    rules = context.get("rules")
    gameweeks = tbl_dict.get(Table.GAMEWEEK.value)
    if not isinstance(rules, GameRules) or gameweeks is None:
        return True, "no rules or gameweek table to score with", {}
    if frame.empty:
        return True, "no team's figures were read for a gameweek in play", {}
    gameweek = int(frame["gameweek"].iloc[0])
    live = LiveTables(
        gameweeks=gameweeks,
        fixtures=tbl_dict.get(Table.FIXTURE.value),
        players=tbl_dict.get(Table.PLAYER.value),
        player_live=tbl_dict.get(Table.PLAYER_LIVE.value),
        entry_live=frame,
        entry_picks=tbl_dict.get(Table.ENTRY_PICK.value),
        league_picks=tbl_dict.get(Table.LEAGUE_PICK.value),
        entry_gameweeks=tbl_dict.get(Table.ENTRY_GAMEWEEK.value),
        league_gameweeks=tbl_dict.get(Table.LEAGUE_GAMEWEEK.value),
    )
    teams = [score_team(live, gameweek, int(e), rules) for e in sorted(set(frame["entry_id"]))]
    compared = [team for team in teams if team.matches_game is not None]
    if not compared:
        return (
            True,
            f"GW{gameweek} is not finished with FPL's final figures yet: nothing to compare",
            {"gameweek": gameweek},
        )
    differ = {
        team.entry_id: {"scorer": team.points, "game": team.game.net}
        for team in compared
        if not team.matches_game and team.points is not None and team.game is not None
    }
    unscored = sorted(team.entry_id for team in teams if team.points is None)
    detail = "; ".join(
        f"entry {entry}: scorer {d['scorer']}, FPL {d['game']}" for entry, d in differ.items()
    )
    return (
        not differ,
        f"GW{gameweek}: the scorer equals FPL for {len(compared) - len(differ)} of "
        f"{len(compared)} teams" + (f"; differs for {detail}" if differ else ""),
        {
            "gameweek": gameweek,
            "compared": len(compared),
            "mismatched": {str(entry): d for entry, d in differ.items()},
            "unscored": unscored,
        },
    )


GATES: tuple[Gate, ...] = (
    Gate(
        name="player_volume",
        gate_class=GateClass.FRESHNESS_AND_VOLUME,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER.value,
        requirement="FR-08",
        summary="The player table holds a full league's worth of players",
        check=_enough_players,
    ),
    Gate(
        name="player_volume_stability",
        gate_class=GateClass.FRESHNESS_AND_VOLUME,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER.value,
        requirement="FR-08",
        summary="The player count has not collapsed against the previous run",
        check=_volume_has_not_collapsed,
    ),
    Gate(
        name="team_count",
        gate_class=GateClass.FRESHNESS_AND_VOLUME,
        severity=GateSeverity.ERROR,
        table=Table.TEAM.value,
        requirement="FR-08",
        summary="Exactly one league's worth of clubs",
        check=_teams_are_a_full_league,
    ),
    Gate(
        name="fixture_count",
        gate_class=GateClass.FRESHNESS_AND_VOLUME,
        severity=GateSeverity.WARN,
        table=Table.FIXTURE.value,
        requirement="FR-08",
        summary="A full season of fixtures",
        check=_fixtures_are_a_full_season,
    ),
    Gate(
        name="snapshot_freshness",
        gate_class=GateClass.FRESHNESS_AND_VOLUME,
        severity=GateSeverity.WARN,
        table=Table.PLAYER.value,
        requirement="NFR-07",
        summary="The snapshots behind this run are recent",
        check=_snapshot_is_fresh,
    ),
    Gate(
        name="player_gameweek_current",
        gate_class=GateClass.FRESHNESS_AND_VOLUME,
        severity=GateSeverity.WARN,
        table=Table.PLAYER_GAMEWEEK.value,
        requirement="FR-08",
        summary="Per-gameweek player rows reach the latest finished gameweek",
        check=_player_gameweeks_reach_the_latest_finished,
    ),
    Gate(
        name="deadlines_ahead",
        gate_class=GateClass.FRESHNESS_AND_VOLUME,
        severity=GateSeverity.WARN,
        table=Table.GAMEWEEK.value,
        requirement="FR-26",
        summary="At least one deadline is still in the future",
        check=_deadlines_are_in_the_future,
    ),
    Gate(
        name="price_range",
        gate_class=GateClass.RANGE,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER.value,
        requirement="FR-08",
        summary="Prices are in millions and inside plausible bounds",
        check=_prices_are_plausible,
    ),
    Gate(
        name="ownership_range",
        gate_class=GateClass.RANGE,
        severity=GateSeverity.WARN,
        table=Table.PLAYER.value,
        requirement="FR-09",
        summary="Ownership is a percentage",
        check=_ownership_is_a_percentage,
    ),
    Gate(
        name="fixture_difficulty_range",
        gate_class=GateClass.RANGE,
        severity=GateSeverity.ERROR,
        table=Table.FIXTURE.value,
        requirement="FR-11",
        summary="Fixture difficulty is on the published 1-5 scale",
        check=_difficulty_is_on_the_published_scale,
    ),
    Gate(
        name="temporal_monotonicity_and_containment",
        gate_class=GateClass.RANGE,
        severity=GateSeverity.ERROR,
        table=Table.GAMEWEEK.value,
        requirement="NFR-06",
        summary="Timestamps strictly respect gameweek deadlines and price history is monotonic",
        check=_temporal_monotonicity_and_containment,
    ),
    Gate(
        name="player_team_reference",
        gate_class=GateClass.REFERENTIAL,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER.value,
        requirement="FR-08",
        summary="Every player belongs to a club that exists",
        check=_players_belong_to_known_teams,
    ),
    Gate(
        name="fixture_team_reference",
        gate_class=GateClass.REFERENTIAL,
        severity=GateSeverity.ERROR,
        table=Table.FIXTURE.value,
        requirement="FR-08",
        summary="Every fixture is between clubs that exist",
        check=_fixtures_reference_known_teams,
    ),
    Gate(
        name="history_player_reference",
        gate_class=GateClass.REFERENTIAL,
        severity=GateSeverity.WARN,
        table=Table.PLAYER_SEASON_HISTORY.value,
        requirement="FR-06",
        summary="History rows reference players that exist",
        check=_history_belongs_to_known_players,
    ),
    Gate(
        name="crosswalk_unmatched_rate",
        gate_class=GateClass.REFERENTIAL,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER_CROSSWALK.value,
        requirement="FR-07",
        summary="Each source's players are mostly resolved to canonical ones",
        check=_crosswalk_is_mostly_matched,
    ),
    Gate(
        name="crosswalk_identity_uniqueness",
        gate_class=GateClass.REFERENTIAL,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER_CROSSWALK.value,
        requirement="FR-07",
        summary="No source maps two of its players onto one canonical player",
        check=_crosswalk_identities_are_one_to_one,
    ),
    Gate(
        name="crosswalk_season",
        gate_class=GateClass.REFERENTIAL,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER_CROSSWALK.value,
        requirement="FR-07",
        summary="The crosswalk was resolved for the season being run",
        check=_crosswalk_is_for_this_season,
    ),
    Gate(
        name="player_position_present",
        gate_class=GateClass.SCHEMA,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER.value,
        requirement="FR-08",
        summary="Every player has a position",
        check=_every_player_has_a_position,
    ),
    Gate(
        name="player_price_present",
        gate_class=GateClass.SCHEMA,
        severity=GateSeverity.ERROR,
        table=Table.PLAYER.value,
        requirement="FR-08",
        summary="Every player has a price",
        check=_prices_are_never_null,
    ),
    Gate(
        name="scorer_matches_game",
        gate_class=GateClass.REFERENTIAL,
        severity=GateSeverity.WARN,
        table=Table.ENTRY_LIVE.value,
        requirement="FR-32",
        summary="On a finished gameweek the scorer's points equal FPL's for every fetched team",
        check=_scorer_matches_game,
    ),
)


__all__ = ["GATES", "CheckResult", "Gate", "GateClass"]
