"""Turning a stat line into points.

Pure functions over :class:`~fpl_dof.rules.models.GameRules`. No constant appears here; every
number comes from the rules object, which is itself seeded from the game's own published settings
(Invariant 2).

Every result is a breakdown rather than a total, because a number you cannot decompose is a number
you cannot argue with (DP-09, DP-10). The total is the sum of the parts, and that identity is
tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fpl_dof.rules.models import GameRules, Position


@dataclass(frozen=True, slots=True)
class StatLine:
    """One player's contribution in one match."""

    minutes: int = 0
    goals_scored: int = 0
    assists: int = 0
    clean_sheet: bool = False
    goals_conceded: int = 0
    saves: int = 0
    penalties_saved: int = 0
    penalties_missed: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    own_goals: int = 0
    defensive_actions: int = 0
    """Combined defensive actions, as counted for this position's DefCon threshold."""

    bonus: int = 0


@dataclass(frozen=True, slots=True)
class PointsBreakdown:
    """Points by component, plus the total. ``total`` is always ``sum(components.values())``."""

    total: int
    components: dict[str, int] = field(default_factory=dict)

    def __getitem__(self, component: str) -> int:
        return self.components.get(component, 0)


def defensive_contribution_points(stats: StatLine, position: Position, rules: GameRules) -> int:
    """The DefCon award: all-or-nothing at a per-position threshold, capped at one award."""
    award = rules.scoring.defensive_contribution[position]
    threshold = rules.scoring.defensive_contribution_threshold[position]
    if award == 0 or threshold <= 0:
        return 0
    return award if stats.defensive_actions >= threshold else 0


def points_for(stats: StatLine, position: Position, rules: GameRules) -> PointsBreakdown:
    """Score one player's match.

    A player who did not appear scores nothing at all — not even card or own-goal penalties, which
    they could not have incurred.
    """
    scoring = rules.scoring
    components: dict[str, int] = {}

    if stats.minutes <= 0:
        return PointsBreakdown(total=0, components={})

    components["appearance"] = scoring.appearance_points(stats.minutes)

    if stats.goals_scored:
        components["goals"] = stats.goals_scored * scoring.goals_scored[position]
    if stats.assists:
        components["assists"] = stats.assists * scoring.assists

    # A clean sheet requires a full appearance; a substitute who came on at 70 minutes into a 0-0
    # does not get one.
    if stats.clean_sheet and stats.minutes >= scoring.long_play_minutes:
        award = scoring.clean_sheets[position]
        if award:
            components["clean_sheet"] = award

    if stats.goals_conceded:
        per_point = scoring.goals_conceded[position]
        if per_point:
            units = stats.goals_conceded // scoring.goals_conceded_per_point
            if units:
                components["goals_conceded"] = units * per_point

    if stats.saves:
        units = stats.saves // scoring.saves_per_point
        if units:
            components["saves"] = units * scoring.saves

    if stats.penalties_saved:
        components["penalties_saved"] = stats.penalties_saved * scoring.penalties_saved
    if stats.penalties_missed:
        components["penalties_missed"] = stats.penalties_missed * scoring.penalties_missed
    if stats.yellow_cards:
        components["yellow_cards"] = stats.yellow_cards * scoring.yellow_cards
    if stats.red_cards:
        components["red_cards"] = stats.red_cards * scoring.red_cards
    if stats.own_goals:
        components["own_goals"] = stats.own_goals * scoring.own_goals

    defcon = defensive_contribution_points(stats, position, rules)
    if defcon:
        components["defensive_contribution"] = defcon

    if stats.bonus:
        components["bonus"] = stats.bonus * scoring.bonus

    return PointsBreakdown(total=sum(components.values()), components=components)
