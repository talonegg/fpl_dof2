"""Oracle Gap diagnostics (E14-S4).

Compares the hindsight oracle's optimal actions against each model's pre-deadline beliefs:
- Differentiates genuine model blindspots from high-variance black swan hauls;
- Surfaces captaincy traps where models backed an underperforming asset over an obvious captain.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fpl_dof.week.oracle import HindsightOptimalPlan


class DiagnosticCategory(StrEnum):
    MODEL_BLINDSPOT = "model_blindspot"
    HIGH_VARIANCE_OUTLIER = "high_variance_outlier"
    CAPTAINCY_TRAP = "captaincy_trap"


@dataclass(frozen=True, slots=True)
class PlayerDiagnostic:
    player_id: int
    player_name: str
    role: str
    actual_points: int
    category: DiagnosticCategory
    explanation: str
    models_xp: dict[str, float]
    models_trapped: list[str]
    underlying_points: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "role": self.role,
            "actual_points": self.actual_points,
            "category": self.category.value,
            "explanation": self.explanation,
            "models_xp": self.models_xp,
            "models_trapped": self.models_trapped,
            "underlying_points": self.underlying_points,
        }


def diagnose_oracle_gap(
    optimal: HindsightOptimalPlan,
    player_actuals: Mapping[int, int],
    models_xp: Mapping[str, Mapping[int, float]],
    models_captains: Mapping[str, int],
    player_underlying: Mapping[int, float] | None = None,
) -> list[PlayerDiagnostic]:
    """Analyse the divergence between hindsight optimal moves and model predictions.

    ``models_xp`` is each model's pre-deadline xP per player; a model that did not price a player
    is left out for him, never read as 0.0 (D-37). ``player_underlying`` is each player's
    underlying points (ORC-12).
    """
    diagnostics: list[PlayerDiagnostic] = []

    def xps(pid: int) -> dict[str, float]:
        return {m: round(xp[pid], 2) for m, xp in models_xp.items() if pid in xp}

    def underlying(pid: int) -> float | None:
        value = (player_underlying or {}).get(pid)
        return None if value is None else round(value, 2)

    # 1. Captaincy diagnosis
    cap_id = optimal.captain_id
    cap_actual = player_actuals.get(cap_id, 0)
    cap_xps = xps(cap_id)

    trapped: list[str] = []
    for model_name, chosen_cap in models_captains.items():
        if chosen_cap != cap_id:
            chosen_actual = player_actuals.get(chosen_cap, 0)
            if chosen_actual < cap_actual:
                trapped.append(model_name)

    if trapped:
        diagnostics.append(
            PlayerDiagnostic(
                player_id=cap_id,
                player_name=optimal.captain_name,
                role="captain",
                actual_points=cap_actual,
                category=DiagnosticCategory.CAPTAINCY_TRAP,
                explanation=(
                    f"{optimal.captain_name} scored {cap_actual} pts as optimal captain. "
                    f"Models {', '.join(trapped)} backed alternative captains who scored less."
                ),
                models_xp=cap_xps,
                models_trapped=trapped,
                underlying_points=underlying(cap_id),
            )
        )

    # 2. Transfer-in moves diagnosis
    for move in optimal.moves:
        in_id = move.player_in_id
        in_actual = player_actuals.get(in_id, 0)
        in_xps = xps(in_id)
        max_xp = max(in_xps.values()) if in_xps else 0.0
        min_xp = min(in_xps.values()) if in_xps else 0.0

        if max_xp >= 5.0 or (max_xp - min_xp) >= 2.5:
            cat = DiagnosticCategory.MODEL_BLINDSPOT
            exp = (
                f"{move.player_in_name} hauled with {in_actual} pts. Some models projected "
                f"high upside ({max_xp:.1f} xP) while others discounted the player."
            )
        else:
            cat = DiagnosticCategory.HIGH_VARIANCE_OUTLIER
            exp = (
                f"{move.player_in_name} hauled with {in_actual} pts despite modest expectations "
                f"across all models (max {max_xp:.1f} xP)."
            )

        diagnostics.append(
            PlayerDiagnostic(
                player_id=in_id,
                player_name=move.player_in_name,
                role="transfer_in",
                actual_points=in_actual,
                category=cat,
                explanation=exp,
                models_xp=in_xps,
                models_trapped=[],
                underlying_points=underlying(in_id),
            )
        )

    return diagnostics
