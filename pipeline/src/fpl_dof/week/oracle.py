"""The hindsight oracle transfer and lineup solver (E14-S3).

Solves the exact multi-gameweek transfer MILP formulation using the owner's pre-deadline
squad state (selling values, bank, free transfers) and the finished gameweek's actual points.
Identifies the mathematical ceiling: optimal single transfer, optimal 2 transfers, and overall best.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from fpl_dof.config.models import OptimiserConfig, TransferConfig
from fpl_dof.frames import as_int
from fpl_dof.optimise.transfer import recommend_transfers
from fpl_dof.rules.models import GameRules
from fpl_dof.squad.state import SquadState


@dataclass(frozen=True, slots=True)
class HindsightMove:
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    selling_price: float
    buying_price: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "player_out_id": self.player_out_id,
            "player_out_name": self.player_out_name,
            "player_in_id": self.player_in_id,
            "player_in_name": self.player_in_name,
            "selling_price": self.selling_price,
            "buying_price": self.buying_price,
        }


@dataclass(frozen=True, slots=True)
class HindsightOptimalPlan:
    transfers_count: int
    moves: tuple[HindsightMove, ...]
    starting: tuple[int, ...]
    captain_id: int
    captain_name: str
    points_before_hits: int
    hit_points: int
    net_points: int
    gain_over_roll: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "transfers_count": self.transfers_count,
            "moves": [m.as_dict() for m in self.moves],
            "starting": list(self.starting),
            "captain_id": self.captain_id,
            "captain_name": self.captain_name,
            "points_before_hits": self.points_before_hits,
            "hit_points": self.hit_points,
            "net_points": self.net_points,
            "gain_over_roll": self.gain_over_roll,
        }


@dataclass(frozen=True, slots=True)
class HindsightOptimalResult:
    gameweek: int
    baseline_roll: HindsightOptimalPlan
    optimal_single: HindsightOptimalPlan | None
    optimal_overall: HindsightOptimalPlan
    all_options: tuple[HindsightOptimalPlan, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "gameweek": self.gameweek,
            "baseline_roll": self.baseline_roll.as_dict(),
            "optimal_single": self.optimal_single.as_dict() if self.optimal_single else None,
            "optimal_overall": self.optimal_overall.as_dict(),
            "all_options": [opt.as_dict() for opt in self.all_options],
        }


def solve_hindsight_optimal(
    gameweek: int,
    state: SquadState,
    pool: pd.DataFrame,
    rules: GameRules,
    *,
    max_transfers: int = 2,
) -> HindsightOptimalResult:
    """Solve the hindsight-optimal lineup and transfers given actual gameweek points."""
    pool_df = pool.copy()
    if "xp_horizon" not in pool_df.columns:
        pool_df["xp_horizon"] = pool_df["xp_next"]
    if "start_probability" not in pool_df.columns:
        pool_df["start_probability"] = 1.0

    # Ensure pool has required player names map
    names = {
        as_int(row.player_id): str(row.web_name)
        for row in pool_df[["player_id", "web_name"]].itertuples()
    }

    # Solver configuration: zero floor, no threshold on gain over hit in hindsight
    opt_cfg = OptimiserConfig(
        enforce_start_probability_floor=False,
        bench_weight=0.001,
        captain_multiplier=2,
    )
    transfer_cfg = TransferConfig(
        max_transfers=max_transfers,
        min_gain_over_hit=0.0,
    )

    rec = recommend_transfers(
        players=pool_df,
        state=state,
        rules=rules,
        transfer_config=transfer_cfg,
        optimiser_config=opt_cfg,
    )

    plans: list[HindsightOptimalPlan] = []
    baseline_opt = rec.options[0]

    for opt in rec.options:
        moves = tuple(
            HindsightMove(
                player_out_id=m.player_out_id,
                player_out_name=m.player_out_name,
                player_in_id=m.player_in_id,
                player_in_name=m.player_in_name,
                selling_price=m.selling_price,
                buying_price=m.buying_price,
            )
            for m in opt.moves
        )
        plan = HindsightOptimalPlan(
            transfers_count=opt.transfers,
            moves=moves,
            starting=opt.starting,
            captain_id=opt.captain_id,
            captain_name=names.get(opt.captain_id, f"Player {opt.captain_id}"),
            points_before_hits=round(opt.gross_expected_points),
            hit_points=opt.hit_points,
            net_points=round(opt.net_expected_points),
            gain_over_roll=round(opt.net_expected_points - baseline_opt.net_expected_points, 2),
        )
        plans.append(plan)

    baseline_roll = plans[0]
    optimal_single = plans[1] if len(plans) > 1 else None
    optimal_overall = max(plans, key=lambda p: p.net_points)

    return HindsightOptimalResult(
        gameweek=gameweek,
        baseline_roll=baseline_roll,
        optimal_single=optimal_single,
        optimal_overall=optimal_overall,
        all_options=tuple(plans),
    )
