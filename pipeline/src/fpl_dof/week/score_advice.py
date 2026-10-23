"""Ranking each strategy's advice by what it actually scored (E14-S2).

The scoring itself is :func:`fpl_dof.rules.realised.score_lineup`, the one realised-points scorer
(ORC-04). This module only reads a ledger entry into a :class:`~fpl_dof.rules.realised.Lineup` and
ranks the scored lineups.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fpl_dof.rules.models import GameRules
from fpl_dof.rules.realised import Lineup, PlayerPerformance, ScoredLineup, score_lineup


@dataclass(frozen=True, slots=True)
class ModelRankScore:
    model_name: str
    rank: int
    score: ScoredLineup

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "rank": self.rank,
            "score": self.score.as_dict(),
        }


def score_model_recommendations(
    models_advice: Mapping[str, Lineup],
    perfs: Mapping[int, PlayerPerformance],
    rules: GameRules,
) -> list[ModelRankScore]:
    """Score all candidate models and rank them descending by net points."""
    scored_models: list[tuple[str, ScoredLineup]] = []
    for name, advised in models_advice.items():
        res = score_lineup(advised, perfs, rules)
        scored_models.append((name, res))

    # Sort descending by net points, then gross points, then name
    scored_models.sort(key=lambda item: (-item[1].net_points, -item[1].points_before_hits, item[0]))

    ranked: list[ModelRankScore] = []
    for rank_idx, (name, sc) in enumerate(scored_models, start=1):
        ranked.append(ModelRankScore(model_name=name, rank=rank_idx, score=sc))

    return ranked


def recorded_free_transfers(entry: Mapping[str, Any]) -> int | None:
    """The free transfers a ledger entry recorded for the owner, or ``None`` when it did not."""
    state = entry.get("squad_state")
    value = state.get("free_transfers") if isinstance(state, Mapping) else None
    return None if value is None else int(value)


def lineup_from_advice(
    advised: Mapping[str, Any],
    *,
    transfers_made: int,
    free_transfers: int | None,
    recommendation: Mapping[str, Any] | None = None,
) -> Lineup | None:
    """A ledger ``advised`` block as a scorable lineup, or ``None`` when it names no XI."""
    starting = tuple(advised.get("starting") or ())
    recorded_hit = (recommendation or {}).get("hit_points")  # recorded non-positive
    if not starting:
        return None
    captain = advised.get("captain") or starting[0]
    return Lineup(
        starting=starting,
        bench_order=tuple(advised.get("bench_order") or ()),
        bench_gkp=advised.get("reserve_goalkeeper"),
        captain=captain,
        vice_captain=advised.get("vice_captain") or captain,
        transfers_made=transfers_made,
        free_transfers=free_transfers,
        hit_points=None if recorded_hit is None else abs(int(recorded_hit)),
        expected_points=float(advised.get("expected_points") or 0.0),
    )
