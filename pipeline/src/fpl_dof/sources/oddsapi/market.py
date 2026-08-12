"""Turning prices into goal expectations. Pure arithmetic, no I/O (DP-03).

A bookmaker's price is not a probability: it carries the margin the book is built on, and the
implied probabilities of a three-way market sum to something like 1.05. Removing that margin is
*de-vigging*, and it has to happen before the numbers mean anything.

**Why proportional de-vigging.** The implied probabilities are scaled to sum to one. It is the
simplest defensible method and, more importantly, the one whose bias is known and stated: it
slightly over-corrects favourites, because the margin in practice sits more heavily on longshots.
The alternatives — Shin, power, logarithmic — fit the margin's shape better and are much harder to
argue with when a recommendation is questioned (DP-10). If the bias ever proves material, this is
one function with one test to replace.

**Why an independent-Poisson fit.** Goals per team are close to Poisson, and independence is a
known simplification — real matches have a small positive correlation and a draw excess. What it
buys is that a match-result market and a totals market can be reconciled into exactly two numbers,
expected goals for each side, which is the shape the rest of the pipeline already speaks. The fit is
a deterministic grid search rather than an optimiser, so the same inputs always produce the same
answer and the residual is reported rather than hidden.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

#: Goals per team the fit will consider, and the resolution it works at. Four is comfortably beyond
#: any Premier League match expectation; the two-stage step keeps the search exact enough to be
#: reproducible without being slow.
MAX_GOALS_EXPECTED = 4.0
COARSE_STEP = 0.1
FINE_STEP = 0.01

#: Goals summed over both sides that the Poisson tail is evaluated to. Beyond this the terms are
#: smaller than the precision anything downstream carries.
_MAX_GOALS = 12


class MarketError(ValueError):
    """Prices that cannot mean what a market means."""


@dataclass(frozen=True, slots=True)
class GoalExpectation:
    """The market's view of one match, in the canonical shape."""

    expected_goals_home: float
    expected_goals_away: float
    home_win_probability: float
    draw_probability: float
    away_win_probability: float
    clean_sheet_probability_home: float
    clean_sheet_probability_away: float
    residual: float
    """How badly the fitted Poisson pair reproduces the de-vigged market. Carried, not discarded:
    a large residual means the market is saying something this model cannot represent, and a number
    that cannot state its own uncertainty should not be trusted (DP-09)."""

    @property
    def total_goals(self) -> float:
        return self.expected_goals_home + self.expected_goals_away


def devig(prices: Mapping[str, float]) -> dict[str, float]:
    """Decimal odds to probabilities summing to one."""
    if not prices:
        raise MarketError("no prices to de-vig")
    implied = {}
    for outcome, price in prices.items():
        if price <= 1.0:
            raise MarketError(f"decimal odds for {outcome!r} must exceed 1.0, got {price}")
        implied[outcome] = 1.0 / price
    total = sum(implied.values())
    if total <= 0:
        raise MarketError("implied probabilities summed to zero")
    return {outcome: value / total for outcome, value in implied.items()}


@lru_cache(maxsize=4096)
def _pmf(lam: float) -> tuple[float, ...]:
    """Poisson probabilities for 0..``_MAX_GOALS`` goals. Cached: the fit revisits few values many
    times, and recomputing an exponential inside the inner loop dominates everything else."""
    scale = math.exp(-lam)
    values = []
    term = 1.0
    for count in range(_MAX_GOALS + 1):
        if count:
            term *= lam / count
        values.append(scale * term)
    return tuple(values)


def _markets(home: float, away: float, line: float) -> tuple[float, float, float, float]:
    """Home win, draw, away win and over-the-line, from one pass over the scoreline grid."""
    home_pmf, away_pmf = _pmf(home), _pmf(away)
    home_win = draw = away_win = over = 0.0
    for home_goals, home_probability in enumerate(home_pmf):
        for away_goals, away_probability in enumerate(away_pmf):
            probability = home_probability * away_probability
            if home_goals > away_goals:
                home_win += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away_win += probability
            if home_goals + away_goals > line:
                over += probability
    return home_win, draw, away_win, over


def outcome_probabilities(home: float, away: float) -> tuple[float, float, float]:
    """Home win, draw and away win under independent Poisson scorelines."""
    home_win, draw, away_win, _ = _markets(home, away, 2.5)
    return home_win, draw, away_win


def over_probability(home: float, away: float, line: float) -> float:
    """Probability the match finishes with more than ``line`` goals in total."""
    return _markets(home, away, line)[3]


def _error(
    home: float,
    away: float,
    result: Mapping[str, float] | None,
    over: float | None,
    line: float,
) -> float:
    home_win, draw, away_win, modelled_over = _markets(home, away, line)
    total = 0.0
    if result is not None:
        for value, key in zip((home_win, draw, away_win), ("home", "draw", "away"), strict=True):
            total += (value - result[key]) ** 2
    if over is not None:
        # Weighted equally with the three result terms taken together, so a match with both markets
        # is not dominated by whichever one happens to have more of them.
        total += 3.0 * (modelled_over - over) ** 2
    return total


def fit_goal_expectations(
    *,
    result: Mapping[str, float] | None = None,
    over: float | None = None,
    line: float = 2.5,
) -> GoalExpectation:
    """Find the goal expectations that best reproduce the de-vigged markets.

    Either market alone is enough: a result market fixes the difference between the two sides and
    the totals market fixes their sum, and the Poisson structure supplies whichever is missing.
    Both together is the normal case and is over-determined, which is why the residual is returned.
    """
    if result is None and over is None:
        raise MarketError("at least one market is needed to fit a goal expectation")
    if result is not None and set(result) != {"home", "draw", "away"}:
        raise MarketError(f"a result market needs home, draw and away, got {sorted(result)}")

    best = (float("inf"), 1.0, 1.0)
    for step, span in ((COARSE_STEP, None), (FINE_STEP, COARSE_STEP)):
        low_home, low_away = (step, step) if span is None else (best[1] - span, best[2] - span)
        high_home, high_away = (
            (MAX_GOALS_EXPECTED, MAX_GOALS_EXPECTED)
            if span is None
            else (best[1] + span, best[2] + span)
        )
        for home in _grid(low_home, high_home, step):
            for away in _grid(low_away, high_away, step):
                error = _error(home, away, result, over, line)
                if error < best[0]:
                    best = (error, home, away)

    _, home, away = best
    home_win, draw, away_win = outcome_probabilities(home, away)
    return GoalExpectation(
        expected_goals_home=round(home, 4),
        expected_goals_away=round(away, 4),
        home_win_probability=round(home_win, 6),
        draw_probability=round(draw, 6),
        away_win_probability=round(away_win, 6),
        # A clean sheet for one side is the other side failing to score, which under this model is
        # simply the Poisson zero.
        clean_sheet_probability_home=round(math.exp(-away), 6),
        clean_sheet_probability_away=round(math.exp(-home), 6),
        residual=round(math.sqrt(best[0]), 6),
    )


def _grid(low: float, high: float, step: float) -> list[float]:
    lowest = max(step, low)
    count = max(0, round((min(high, MAX_GOALS_EXPECTED) - lowest) / step))
    return [round(lowest + index * step, 6) for index in range(count + 1)]


__all__ = [
    "COARSE_STEP",
    "FINE_STEP",
    "MAX_GOALS_EXPECTED",
    "GoalExpectation",
    "MarketError",
    "devig",
    "fit_goal_expectations",
    "outcome_probabilities",
    "over_probability",
]
