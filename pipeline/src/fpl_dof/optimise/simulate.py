"""E4-S4a — simulation re-rank. Most of the stochastic layer, none of the solver work.

This sits between the MILP's linear risk proxy and the full stochastic optimiser deferred in DL-06,
and it needs no solver change at all. The chip enumeration in :mod:`fpl_dof.optimise.chips` already
produces a pool of top-k plans; this samples each one many times and re-ranks them on whatever the
risk dial actually asks for.

**Why the mean is not good enough, which is the whole point.** Bench Boost and Triple Captain are
variance plays. An expectation-maximiser cannot distinguish a Triple Captain on a 6.0-xP explosive
forward from one on a 6.0-xP metronomic midfielder, and those are not the same bet — the difference
*is* the chip. So the score is a percentile of the simulated distribution, chosen by the dial, and
never the mean: re-ranking on the mean could only ever reproduce the ordering the MILP already
produced by maximising it.

**Correlated within a match, which is the other half of the point.** Two defenders from one club
share a single clean sheet; a thrashing is shared too. Sampling players independently would produce
a portfolio variance that is far too small and would make every re-rank look reassuring. Each match
draws one shared multiplicative shock, and each player draws his own on top of it.

The distribution is a product of two Gamma variates with mean 1, which gives three properties worth
having and one worth admitting:

* non-negative, which points are;
* right-skewed, which points are — the upside tail is what a chip is buying;
* mean exactly ``mu`` and variance exactly ``sigma^2``, so it agrees with the forecast contract it
  is fed (Invariant 6) rather than quietly re-scaling it;
* and it is **not** a model of football. It is a variance-and-correlation structure wrapped around
  the forecast's own mean and standard deviation, and it can say nothing the forecast did not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from fpl_dof.config.models import SimulationConfig
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlayerDraw:
    """One player in one gameweek: the forecast's mean and standard deviation, and his match."""

    player_id: int
    mean: float
    standard_deviation: float
    match_key: str
    """Everyone sharing this key shares a correlated shock. A club's fixture, in practice."""

    multiplier: float = 1.0
    """1 for a starter, 2 or 3 for a captain, and the bench weight for a bench player."""


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """What the sampling says about one plan."""

    mean: float
    median: float
    percentiles: dict[str, float]
    score: float
    """The value the dial is ranked on. A percentile, never the mean — see the module docstring."""

    draws: int

    def as_dict(self) -> dict[str, object]:
        return {
            "mean": round(self.mean, 3),
            "median": round(self.median, 3),
            "percentiles": {k: round(v, 3) for k, v in self.percentiles.items()},
            "score": round(self.score, 3),
            "draws": self.draws,
        }


def simulate(
    entries: Sequence[PlayerDraw],
    config: SimulationConfig,
    *,
    dial: str,
    seed_offset: int = 0,
) -> SimulationResult:
    """Sample a plan's points many times, correlated within a match, and score it for the dial."""
    if not entries:
        empty = {"p10": 0.0, "p30": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
        return SimulationResult(mean=0.0, median=0.0, percentiles=empty, score=0.0, draws=0)

    rng = np.random.default_rng(config.seed + seed_offset)
    draws = config.draws

    means = np.array([entry.mean for entry in entries], dtype=float)
    sds = np.array([entry.standard_deviation for entry in entries], dtype=float)
    weights = np.array([entry.multiplier for entry in entries], dtype=float)

    keys = sorted({entry.match_key for entry in entries})
    index = {key: position for position, key in enumerate(keys)}
    match_index = np.array([index[entry.match_key] for entry in entries], dtype=int)

    # Coefficient of variation, split between the shock everyone in a match shares and the shock
    # that is the player's own. Var(f·g) = (1+v_f)(1+v_g) - 1 for independent unit-mean factors,
    # which is what keeps the total variance equal to the sigma the forecast supplied.
    safe_means = np.where(means > 0, means, 1.0)
    total_variance = np.where(means > 0, (sds / safe_means) ** 2, 0.0)
    match_variance = config.match_variance_share * total_variance
    player_variance = np.maximum((1.0 + total_variance) / (1.0 + match_variance) - 1.0, 0.0)

    # One shared factor per match, drawn once per sample and applied to everyone in that match.
    # Its dispersion is the mean of its members', because a match has one shock, not one per player.
    match_dispersion = np.zeros(len(keys))
    for position in range(len(keys)):
        members = match_variance[match_index == position]
        match_dispersion[position] = float(members.mean()) if members.size else 0.0

    shared = _unit_gamma(rng, match_dispersion, draws)[:, match_index]
    individual = _unit_gamma(rng, player_variance, draws)
    sampled = means * shared * individual
    totals = (sampled * weights).sum(axis=1)

    percentiles = {
        "p10": float(np.percentile(totals, 10)),
        "p30": float(np.percentile(totals, 30)),
        "p50": float(np.percentile(totals, 50)),
        "p75": float(np.percentile(totals, 75)),
        "p90": float(np.percentile(totals, 90)),
    }
    quantile = config.percentile_by_dial.get(dial, 0.5)
    return SimulationResult(
        mean=float(totals.mean()),
        median=percentiles["p50"],
        percentiles=percentiles,
        score=float(np.percentile(totals, quantile * 100.0)),
        draws=draws,
    )


def _unit_gamma(rng: np.random.Generator, variance: np.ndarray, draws: int) -> np.ndarray:
    """Gamma variates with mean 1 and the given variance. Variance 0 returns exactly 1.

    Gamma rather than a truncated normal because points are non-negative and right-skewed, and
    because the shape parameter falls straight out of the mean and variance without a fit.
    """
    shape = np.where(variance > 0, 1.0 / np.maximum(variance, 1e-12), 1.0)
    sampled = rng.gamma(shape, 1.0 / shape, size=(draws, variance.size))
    return np.where(variance > 0, sampled, 1.0)


def match_key(team_id: int, gameweek: int, opponent_ids: Sequence[int] = ()) -> str:
    """A stable key for "the same match", used to correlate draws.

    Keyed on the *pair* of clubs where the fixture is known, so that a forward and the opposing
    goalkeeper share a shock: a thrashing is one event, and treating the two sides of it as
    independent is the same error as treating two defenders as independent, in the other direction.
    """
    if opponent_ids:
        clubs = sorted({int(team_id), *(int(o) for o in opponent_ids)})
        return f"gw{gameweek}:" + "v".join(str(club) for club in clubs)
    return f"gw{gameweek}:team{int(team_id)}"


def rank(
    scores: Mapping[str, SimulationResult],
    milp_order: Sequence[str],
) -> tuple[str, ...]:
    """Re-rank plan keys on their simulated score, with the MILP order as the tie-break.

    The MILP order is kept as the tie-break rather than discarded, so that plans the simulation
    genuinely cannot separate do not shuffle between runs (R-16).
    """
    position = {key: index for index, key in enumerate(milp_order)}
    return tuple(
        sorted(
            scores,
            key=lambda key: (-scores[key].score, position.get(key, len(position)), key),
        )
    )


__all__ = [
    "PlayerDraw",
    "SimulationResult",
    "match_key",
    "rank",
    "simulate",
]
