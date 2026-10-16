"""Realized recommendation scoring and model ranking (E14-S2).

Scores candidate models' pre-deadline advice against finished gameweek actual points
using official FPL rules:
- Prioritized bench auto-substitutions respecting formation minimums and maximums;
- Armband double points on captain, with fallback to vice-captain if captain played 0 minutes;
- Transfer hit penalties (-4 pts per transfer over free transfers).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fpl_dof.rules.models import GameRules, Position


@dataclass(frozen=True, slots=True)
class PlayerPerformance:
    player_id: int
    position: Position
    minutes: int
    points: int


@dataclass(frozen=True, slots=True)
class AdvisedLineup:
    starting: tuple[int, ...]
    bench_order: tuple[int, ...]
    bench_gkp: int | None
    captain: int
    vice_captain: int
    transfers_made: int = 0
    free_transfers: int = 1
    expected_points: float = 0.0


@dataclass(frozen=True, slots=True)
class ScoredLineup:
    final_starting: tuple[int, ...]
    points_before_hits: int
    hit_points: int
    net_points: int
    captain_id: int
    vice_used: bool
    armband_points: int
    autosubs_in: tuple[int, ...]
    autosubs_out: tuple[int, ...]
    expected_points: float
    prediction_delta: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_starting": list(self.final_starting),
            "points_before_hits": self.points_before_hits,
            "hit_points": self.hit_points,
            "net_points": self.net_points,
            "captain_id": self.captain_id,
            "vice_used": self.vice_used,
            "armband_points": self.armband_points,
            "autosubs_in": list(self.autosubs_in),
            "autosubs_out": list(self.autosubs_out),
            "expected_points": self.expected_points,
            "prediction_delta": self.prediction_delta,
        }


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


def score_lineup(
    advised: AdvisedLineup,
    perfs: Mapping[int, PlayerPerformance],
    rules: GameRules,
) -> ScoredLineup:
    """Score a single advised lineup against player match performances."""
    squad_rules = rules.squad
    starting = list(advised.starting)
    autosubs_in: list[int] = []
    autosubs_out: list[int] = []

    # 1. Goalkeeper substitution
    gkp_starters = [pid for pid in starting if pid in perfs and perfs[pid].position == Position.GKP]
    if gkp_starters:
        start_gkp = gkp_starters[0]
        if perfs[start_gkp].minutes == 0 and advised.bench_gkp is not None:
            sub_gkp = advised.bench_gkp
            if sub_gkp in perfs and perfs[sub_gkp].minutes > 0:
                idx = starting.index(start_gkp)
                starting[idx] = sub_gkp
                autosubs_out.append(start_gkp)
                autosubs_in.append(sub_gkp)

    # 2. Outfield substitutions
    # Go through 0-minute outfield starters and bench order candidates
    used_subs: set[int] = set()
    outfield_starters_0min = [
        pid
        for pid in starting
        if pid in perfs and perfs[pid].position != Position.GKP and perfs[pid].minutes == 0
    ]

    for zero_pid in outfield_starters_0min:
        for sub_pid in advised.bench_order:
            if sub_pid in used_subs or sub_pid not in perfs or perfs[sub_pid].minutes == 0:
                continue

            # Test formation validity if sub_pid replaces zero_pid
            tentative_starting = [p for p in starting if p != zero_pid] + [sub_pid]
            counts = Counter(perfs[p].position for p in tentative_starting if p in perfs)

            is_valid = True
            for pos in (Position.DEF, Position.MID, Position.FWD):
                c = counts.get(pos, 0)
                if not (squad_rules.formation_min[pos] <= c <= squad_rules.formation_max[pos]):
                    is_valid = False
                    break

            if is_valid:
                idx = starting.index(zero_pid)
                starting[idx] = sub_pid
                used_subs.add(sub_pid)
                autosubs_out.append(zero_pid)
                autosubs_in.append(sub_pid)
                break

    # 3. Points calculation
    base_points = sum(perfs[pid].points for pid in starting if pid in perfs)

    # 4. Captaincy / Armband
    captain_id = advised.captain
    vice_used = False
    armband_points = 0

    cap_perf = perfs.get(advised.captain)
    vice_perf = perfs.get(advised.vice_captain)

    if cap_perf and cap_perf.minutes > 0:
        captain_id = advised.captain
        armband_points = cap_perf.points * 2
        extra_captain_pts = cap_perf.points
    elif vice_perf and vice_perf.minutes > 0:
        captain_id = advised.vice_captain
        vice_used = True
        armband_points = vice_perf.points * 2
        extra_captain_pts = vice_perf.points
    else:
        extra_captain_pts = 0

    points_before_hits = base_points + extra_captain_pts
    extra_transfers = max(0, advised.transfers_made - advised.free_transfers)
    hit_points = extra_transfers * 4
    net_points = points_before_hits - hit_points
    delta = round(net_points - advised.expected_points, 2)

    return ScoredLineup(
        final_starting=tuple(starting),
        points_before_hits=points_before_hits,
        hit_points=hit_points,
        net_points=net_points,
        captain_id=captain_id,
        vice_used=vice_used,
        armband_points=armband_points,
        autosubs_in=tuple(autosubs_in),
        autosubs_out=tuple(autosubs_out),
        expected_points=advised.expected_points,
        prediction_delta=delta,
    )


def score_model_recommendations(
    models_advice: Mapping[str, AdvisedLineup],
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
