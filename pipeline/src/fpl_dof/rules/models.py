"""The game's rules, as data.

Invariant 2 says no FPL scoring, price or squad value may be a literal in code. This module is how
that is satisfied *without* transcribing the rulebook into YAML and hoping it stays right: almost
everything here is seeded directly from what the API itself publishes in ``game_config.scoring``,
``game_settings`` and ``element_types``.

The small remainder — the values FPL genuinely does not expose — lives in
``config/defaults/rules.yaml``, each with a comment saying why it cannot be derived. Those are the
ones to be suspicious of, and they are deliberately few:

* the divisors on saves and goals conceded (points are awarded per 3 saves, per 2 conceded, and the
  API publishes only the per-unit value);
* the Defensive Contribution match thresholds;
* the bonus points awarded to the top three BPS scorers;
* the minutes threshold separating an appearance from a full game;
* free-transfer accumulation and the points cost of an extra transfer.

Every field carries provenance: :attr:`GameRules.derived` records which values came from the API
snapshot and which came from configuration, and that record is published in the web contract
(DL-14) so the browser validator and the solver are demonstrably using the same numbers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Position(StrEnum):
    """FPL's own position codes, taken from ``element_types.singular_name_short``."""

    GKP = "GKP"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


PositionMap = dict[Position, int]


class ScoringRules(_Frozen):
    """What each event is worth.

    The per-position maps come straight from ``game_config.scoring``. The divisors and thresholds
    are supplementary — see the module docstring.
    """

    # --- from the API ---
    long_play: int
    short_play: int
    goals_scored: PositionMap
    assists: int
    clean_sheets: PositionMap
    goals_conceded: PositionMap
    saves: int
    penalties_saved: int
    penalties_missed: int
    yellow_cards: int
    red_cards: int
    own_goals: int
    defensive_contribution: PositionMap
    bonus: int = Field(description="Points per bonus point awarded. Published by the API as 1.")

    # --- supplementary: FPL publishes the per-unit value but not the unit ---
    long_play_minutes: int = Field(
        description="Minutes at or above which the full appearance score applies."
    )
    saves_per_point: int = Field(gt=0, description="Saves required per unit of the `saves` score.")
    goals_conceded_per_point: int = Field(
        gt=0, description="Goals conceded per unit of the `goals_conceded` score."
    )
    defensive_contribution_threshold: PositionMap = Field(
        description="Defensive actions required in a match to score the DefCon award."
    )
    bonus_points: tuple[int, ...] = Field(
        description="Awarded to the top BPS scorers in a match, in rank order."
    )

    def appearance_points(self, minutes: int) -> int:
        if minutes <= 0:
            return 0
        return self.long_play if minutes >= self.long_play_minutes else self.short_play


class SquadRules(_Frozen):
    """Composition, budget and formation. Entirely API-derived."""

    size: int
    starting_size: int
    budget: float = Field(description="In £m, converted from tenths at the ingestion boundary.")
    club_limit: int
    composition: PositionMap = Field(description="Exact squad count required per position.")
    formation_min: PositionMap = Field(description="Minimum in the starting XI.")
    formation_max: PositionMap = Field(description="Maximum in the starting XI.")
    sell_on_fee: float = Field(ge=0, le=1)
    sell_at_purchase_price: bool

    @model_validator(mode="after")
    def _composition_must_add_up(self) -> Self:
        total = sum(self.composition.values())
        if total != self.size:
            raise ValueError(f"composition sums to {total}, but squad size is {self.size}")
        if sum(self.formation_min.values()) > self.starting_size:
            raise ValueError("formation minimums exceed the starting XI size")
        if sum(self.formation_max.values()) < self.starting_size:
            raise ValueError("formation maximums cannot fill the starting XI")
        for position in Position:
            if self.formation_max[position] > self.composition[position]:
                raise ValueError(f"{position} formation maximum exceeds the squad allocation")
        return self

    def legal_formations(self) -> list[dict[Position, int]]:
        """Every starting XI shape the rules permit, in a stable order."""
        formations: list[dict[Position, int]] = []
        for gkp in range(self.formation_min[Position.GKP], self.formation_max[Position.GKP] + 1):
            for dfd in range(
                self.formation_min[Position.DEF], self.formation_max[Position.DEF] + 1
            ):
                for mid in range(
                    self.formation_min[Position.MID], self.formation_max[Position.MID] + 1
                ):
                    fwd = self.starting_size - gkp - dfd - mid
                    if self.formation_min[Position.FWD] <= fwd <= self.formation_max[Position.FWD]:
                        formations.append(
                            {
                                Position.GKP: gkp,
                                Position.DEF: dfd,
                                Position.MID: mid,
                                Position.FWD: fwd,
                            }
                        )
        return formations


class TransferRules(_Frozen):
    """Supplementary in full: FPL publishes none of this in a machine-readable form."""

    max_free_transfers: int = Field(gt=0)
    extra_transfer_cost: int = Field(
        description="Points deducted per transfer beyond the free ones."
    )


class ApiScoring(_Frozen):
    """Exactly the scoring values a source publishes. No supplementary values may appear here."""

    long_play: int
    short_play: int
    goals_scored: PositionMap
    assists: int
    clean_sheets: PositionMap
    goals_conceded: PositionMap
    saves: int
    penalties_saved: int
    penalties_missed: int
    yellow_cards: int
    red_cards: int
    own_goals: int
    defensive_contribution: PositionMap
    bonus: int


class ApiSquad(_Frozen):
    """Exactly the squad rules a source publishes."""

    size: int
    starting_size: int
    budget: float
    club_limit: int
    composition: PositionMap
    formation_min: PositionMap
    formation_max: PositionMap
    sell_on_fee: float
    sell_at_purchase_price: bool


class ApiRules(_Frozen):
    """What a source was able to tell us about the rules.

    Kept separate from :class:`GameRules` so the boundary between "the game said so" and "we
    configured it" is a type, not a convention.
    """

    scoring: ApiScoring
    squad: ApiSquad


class GameRules(_Frozen):
    """Everything the optimiser, the scorer and the legality validator are allowed to know."""

    season: str
    scoring: ScoringRules
    squad: SquadRules
    transfers: TransferRules
    derived: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Provenance per top-level field group: 'api' where the value came from the source "
            "snapshot, 'config' where it came from committed configuration."
        ),
    )
    source_snapshot_sha256: str | None = Field(
        default=None,
        description="Checksum of the bronze snapshot the API-derived values were read from.",
    )
