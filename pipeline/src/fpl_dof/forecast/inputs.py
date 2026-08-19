"""What a forecast model is given. One shape, whichever model runs.

Both expected-points models read from the same silver tables; they disagree only about which of
them they need. Keeping the container common means the forecast stage assembles its inputs once and
the choice of model is a choice of function, not a second assembly of the same data — which is the
sort of duplication that ends with two models being fed subtly different worlds.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class ForecastInputs:
    """Silver tables, as the forecast sees them.

    ``player_gameweek`` and ``metrics`` are optional because both are legitimately absent: there are
    no per-gameweek rows for a season nobody has played yet, and no advanced metrics unless a source
    that supplies them is enabled. ``xp_v1`` needs the first and the cold-start ``xp_v0`` does not,
    which is exactly the condition that decides which model publishes (DL-46).
    """

    players: pd.DataFrame
    teams: pd.DataFrame
    fixtures: pd.DataFrame
    gameweeks: pd.DataFrame
    history: pd.DataFrame
    """Per-*season* career totals. The cold-start model's whole evidence base."""

    player_gameweek: pd.DataFrame | None = None
    """Per-gameweek rows for the current season. What M1-M8 are fitted on."""

    metrics: pd.DataFrame | None = None
    """The conformed advanced table, when a source supplies one. Feeds the prior-season prior."""


__all__ = ["ForecastInputs"]
