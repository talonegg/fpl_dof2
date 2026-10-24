"""Underlying expected points: the game's rules applied to what a player produced (ORC-12, DL-95).

A gameweek's realised points carry the finishing: a 0.1 xG chance that went in, a 0.8 that did not.
Underlying xP scores the chances instead, so a model's miss splits into **forecast error** (its xP
against the underlying) and **luck** (the points scored against the underlying). Per component:

- **Appearance**: the minutes played, by the rules' minutes threshold. Minutes are taken as they
  happened, so a starter who did not play is the forecast's miss, not luck.
- **Goals** and **assists**: FPL's own expected goals and expected assists for the match, times the
  points for a goal at his position and for an assist.
- **Clean sheet**: P(no goal) under a Poisson with FPL's expected goals conceded while he was on the
  pitch, ``exp(-xGC)``, times the clean-sheet award, only at or above the full-appearance minutes.
- **Goals conceded**: the expected number of whole scoring units, ``E[floor(N / per_point)]`` for
  ``N ~ Poisson(xGC)``, times the per-unit deduction.
- **Saves, penalties saved and missed, cards, own goals, Defensive Contribution and bonus** have no
  expected input in the data, so they are **the actual**, scored by :func:`points_for`. Bonus
  therefore keeps some finishing luck (a goal raises BPS); leaving it out would bias every player's
  underlying below his points instead.

A match whose expected figure is not recorded falls back to the actual for that component, so a
missing measure reads as no luck rather than as no chance.

Pure (DP-03). Every number comes from :class:`~fpl_dof.rules.models.GameRules` (Invariant 2).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.realised import Lineup, ScoredLineup
from fpl_dof.rules.scoring import StatLine, points_for


def underlying_points(gameweek_rows: pd.DataFrame, rules: GameRules) -> dict[int, float]:
    """Each player's underlying points for one gameweek's ``player_gameweek`` rows, by player id;
    a double gameweek's fixtures are summed."""
    scoring = rules.scoring
    totals: dict[int, float] = {}
    for r in gameweek_rows.itertuples():
        pid = as_int(r.player_id)
        position = Position(str(r.position))
        minutes = _count(r, "minutes")
        xg, xa, xgc = (_known(r, c) for c in _EXPECTED)
        actual = StatLine(
            minutes=minutes,
            goals_scored=0 if xg is not None else _count(r, "goals_scored"),
            assists=0 if xa is not None else _count(r, "assists"),
            clean_sheet=xgc is None and _count(r, "clean_sheets") > 0,
            goals_conceded=0 if xgc is not None else _count(r, "goals_conceded"),
            saves=_count(r, "saves"),
            penalties_saved=_count(r, "penalties_saved"),
            penalties_missed=_count(r, "penalties_missed"),
            yellow_cards=_count(r, "yellow_cards"),
            red_cards=_count(r, "red_cards"),
            own_goals=_count(r, "own_goals"),
            defensive_actions=_count(r, "defensive_contribution"),
            bonus=_count(r, "bonus"),
        )
        points = float(points_for(actual, position, rules).total)
        if minutes > 0:
            points += (xg or 0.0) * scoring.goals_scored[position] + (xa or 0.0) * scoring.assists
            if xgc is not None:
                if minutes >= scoring.long_play_minutes:
                    points += math.exp(-xgc) * scoring.clean_sheets[position]
                units = _expected_units(xgc, scoring.goals_conceded_per_point)
                points += units * scoring.goals_conceded[position]
        totals[pid] = totals.get(pid, 0.0) + points
    return totals


def underlying_team_points(
    lineup: Lineup, scored: ScoredLineup, underlying: Mapping[int, float], rules: GameRules
) -> float:
    """A scored lineup's points before hits with each player's underlying points in place of his
    realised ones: the same final XI (all fifteen under a bench chip) and the same armband."""
    fielded = list(scored.final_starting)
    if lineup.chip in rules.chips.bench_scores_with:
        fielded += [
            *([lineup.bench_gkp] if lineup.bench_gkp is not None else []),
            *lineup.bench_order,
        ]
    extra = rules.chips.armband(lineup.chip) - 1
    return (
        sum(underlying.get(p, 0.0) for p in fielded)
        + underlying.get(scored.captain_id, 0.0) * extra
    )


_EXPECTED = ("expected_goals", "expected_assists", "expected_goals_conceded")


def _known(row: Any, column: str) -> float | None:
    value = getattr(row, column, None)
    return None if value is None or pd.isna(value) else float(value)


def _count(row: Any, column: str) -> int:
    value = _known(row, column)
    return 0 if value is None else int(value)


def _expected_units(mean: float, per: int) -> float:
    """``E[floor(N / per)]`` for ``N ~ Poisson(mean)``: the expected whole scoring units."""
    total, pmf = 0.0, math.exp(-mean)
    # Twelve standard deviations past the mean leaves a tail below double precision.
    for k in range(int(mean + 12 * math.sqrt(mean)) + 13):
        total += pmf * (k // per)
        pmf *= mean / (k + 1)
    return total
