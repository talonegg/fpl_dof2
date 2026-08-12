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
from fpl_dof.quality.gates import GateSeverity
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


def _deadlines_are_in_the_future(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    """At least one gameweek is still ahead. A season that has entirely ended is a real state,
    but so is a gameweek table cached from last season, and they look identical."""
    now = context.get("now")
    moment = pd.Timestamp(now if isinstance(now, dt.datetime) else dt.datetime.now(dt.UTC))
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
    """
    limit = _config(context).maximum_unmatched_player_rate
    worst_source, worst_rate, counts = "", 0.0, {}
    for source, group in frame.groupby("source"):
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
    """Every crosswalk row belongs to the season being run.

    Resolution is re-run from scratch each season because transfers invalidate club-based matching
    (Design §3.2). A row carried over from last season is last season's answer wearing this
    season's clothes.
    """
    expected = context.get("season")
    if not isinstance(expected, str):
        return True, "no season in context to check against", {}
    stale = sorted({str(value) for value in frame["season"].unique()} - {expected})
    return (
        not stale,
        f"crosswalk carries {len(stale)} season(s) other than {expected}: {stale[:3]}",
        {"stale_seasons": stale[:10], "expected": expected},
    )


# --- schema ------------------------------------------------------------------------------------


def _every_player_has_a_position(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    missing = int(frame["position"].isna().sum())
    return missing == 0, f"{missing} player(s) have no position", {"missing": missing}


def _prices_are_never_null(frame: pd.DataFrame, context: Mapping[str, object]) -> CheckResult:
    missing = int(frame["price"].isna().sum())
    return missing == 0, f"{missing} player(s) have no price", {"missing": missing}


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
)


__all__ = ["GATES", "CheckResult", "Gate", "GateClass"]
