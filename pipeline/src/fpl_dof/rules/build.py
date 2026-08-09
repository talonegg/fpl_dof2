"""Merging what the game published with what we had to configure.

Kept out of ``sources/`` deliberately: a source reports what it can observe, and this module is
where that becomes the single set of rules the whole system obeys.
"""

from __future__ import annotations

from fpl_dof.config.models import RulesConfig
from fpl_dof.rules.models import (
    ApiRules,
    GameRules,
    Position,
    PositionMap,
    ScoringRules,
    SquadRules,
    TransferRules,
)


class RulesError(ValueError):
    """The published rules and the configured rules could not be reconciled."""


def _positions(raw: dict[str, int]) -> PositionMap:
    missing = [p for p in Position if p.value not in raw]
    if missing:
        raise RulesError(f"missing positions {[p.value for p in missing]} in {sorted(raw)}")
    return {position: int(raw[position.value]) for position in Position}


def build_game_rules(
    api: ApiRules,
    config: RulesConfig,
    *,
    source_snapshot_sha256: str | None = None,
) -> GameRules:
    """Combine API-published rules with supplementary configuration.

    Provenance is recorded per field group so the published contract can say, honestly, which
    numbers the game told us and which we decided (DP-09).
    """
    scoring = ScoringRules(
        long_play=api.scoring.long_play,
        short_play=api.scoring.short_play,
        goals_scored=api.scoring.goals_scored,
        assists=api.scoring.assists,
        clean_sheets=api.scoring.clean_sheets,
        goals_conceded=api.scoring.goals_conceded,
        saves=api.scoring.saves,
        penalties_saved=api.scoring.penalties_saved,
        penalties_missed=api.scoring.penalties_missed,
        yellow_cards=api.scoring.yellow_cards,
        red_cards=api.scoring.red_cards,
        own_goals=api.scoring.own_goals,
        defensive_contribution=api.scoring.defensive_contribution,
        bonus=api.scoring.bonus,
        long_play_minutes=config.scoring.long_play_minutes,
        saves_per_point=config.scoring.saves_per_point,
        goals_conceded_per_point=config.scoring.goals_conceded_per_point,
        defensive_contribution_threshold=_positions(
            config.scoring.defensive_contribution_threshold
        ),
        bonus_points=config.scoring.bonus_points,
    )

    squad = SquadRules(
        size=api.squad.size,
        starting_size=api.squad.starting_size,
        budget=api.squad.budget,
        club_limit=api.squad.club_limit,
        composition=api.squad.composition,
        formation_min=api.squad.formation_min,
        formation_max=api.squad.formation_max,
        sell_on_fee=api.squad.sell_on_fee,
        sell_at_purchase_price=api.squad.sell_at_purchase_price,
    )

    transfers = TransferRules(
        max_free_transfers=config.transfers.max_free_transfers,
        extra_transfer_cost=config.transfers.extra_transfer_cost,
    )

    _cross_check(scoring)

    return GameRules(
        season=config.season,
        scoring=scoring,
        squad=squad,
        transfers=transfers,
        derived={
            "scoring.events": "api",
            "scoring.thresholds": "config",
            "squad": "api",
            "transfers": "config",
            "season": "config",
        },
        source_snapshot_sha256=source_snapshot_sha256,
    )


def _cross_check(scoring: ScoringRules) -> None:
    """Catch the combinations that are individually plausible and jointly impossible."""
    if scoring.short_play > scoring.long_play:
        raise RulesError("a short appearance cannot be worth more than a full one")
    for position, award in scoring.defensive_contribution.items():
        threshold = scoring.defensive_contribution_threshold[position]
        if award > 0 and threshold <= 0:
            raise RulesError(
                f"{position} earns {award} for defensive contribution but has no threshold; "
                "the award would be granted for zero defensive actions"
            )
        if award == 0 and threshold > 0:
            raise RulesError(
                f"{position} has a defensive contribution threshold of {threshold} but earns "
                "nothing for meeting it"
            )
