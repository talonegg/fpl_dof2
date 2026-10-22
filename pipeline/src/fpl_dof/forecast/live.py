"""The published forecast: ``xp_v1`` assembled into the frame the rest of the pipeline reads.

`DL-46 <../../../../docs/decisions/DL-46.md>`_ settled what E9-S1 delivers: ``xp_v1`` is the
model the live pipeline publishes, because the defect D-25 records is that the shipped model was not
the graded one — a delivery bug, not an unproven candidate needing a shadow window.

What this module adds over :mod:`fpl_dof.forecast.xp_v1` is **assembly, not modelling**. Not one
number here is computed differently from the way the backtest computes it; the components are fitted
through the same :func:`~fpl_dof.forecast.backtest.fold_rows` the harness uses, scored through the
same :func:`~fpl_dof.forecast.xp_v1.score_player`, and spread over the horizon by the same
:mod:`~fpl_dof.forecast.horizon` scorer the chip replay uses. What is added is everything that is
about *publishing*: player identity, availability news, a confidence tier, and the exact column set
``xp_v0`` has always produced, so every downstream consumer keeps working unchanged.

**Two deliberate seams to the cold start.**

* A player with no minutes this season still gets a row. His features are empty rather than absent,
  so each rate model returns its position prior — the same "group prior, not a zero" rule ``xp_v0``
  applies to a new signing (DP-15). Dropping him instead would make him silently unselectable.
* If the season is too young for the component chain to be fitted at all, this raises
  :class:`ColdStartError` and the stage falls back to ``xp_v0``, visibly.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.baselines import FittedBaseline
from fpl_dof.forecast.fit import (
    ColdStartError,
    fit_as_of,
    training_set,
)
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.xp_v1 import MODEL_NAME
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import GameRules
from fpl_dof.week.cadence import current_gameweek

log = get_logger(__name__)

#: Columns copied from the published player record onto every forecast row.
IDENTITY_COLUMNS = (
    "player_id",
    "web_name",
    "full_name",
    "position",
    "team_id",
    "price",
    "status",
    "news",
    "selected_by_percent",
    "chance_of_playing_next_round",
)


def completed_gameweeks(player_gameweek: pd.DataFrame | None, *, before: pd.Timestamp) -> int:
    """How many gameweeks have actually been played before ``before``.

    Counted on kickoffs rather than on a ``finished`` flag, because the kickoff is the same
    knowability boundary every feature is stamped against (Invariant 5).
    """
    if player_gameweek is None or player_gameweek.empty:
        return 0
    played = player_gameweek.dropna(subset=["kickoff_time"])
    played = played[played["kickoff_time"] < pd.Timestamp(before).tz_convert("UTC")]
    if played.empty:
        return 0
    return int(played["gameweek"].nunique())


def next_deadline(
    gameweeks: pd.DataFrame,
    config: ForecastConfig,
    as_of: dt.datetime | pd.Timestamp,
) -> tuple[int, pd.Timestamp, list[int]]:
    """The gameweek being decided, the cutoff the fit learns up to, and the forecast horizon.

    The gameweek decided is the one whose deadline is next (``current_gameweek``, PIPE-12). The
    fit stops earlier while a gameweek is in play: at the first *unfinished* gameweek's deadline,
    so a half-played gameweek's partial minutes and points never enter training (REM-08, DL-81).
    """
    if gameweeks.empty:
        raise ColdStartError("the gameweek table is empty; there is nothing to forecast")
    next_gameweek = current_gameweek(gameweeks, as_of)
    deadlines = gameweeks.set_index("gameweek")["deadline_time"]
    cutoff = pd.Timestamp(deadlines[next_gameweek])
    unfinished = gameweeks[~gameweeks["finished"].astype(bool)]
    if not unfinished.empty:
        cutoff = min(cutoff, pd.Timestamp(unfinished["deadline_time"].min()))
    last = as_int(gameweeks["gameweek"].max())
    horizon = [
        gameweek
        for gameweek in range(next_gameweek, next_gameweek + config.horizon_gameweeks)
        if gameweek <= last
    ]
    return next_gameweek, cutoff.tz_convert("UTC"), horizon


def build(
    inputs: ForecastInputs, rules: GameRules, config: ForecastConfig
) -> tuple[pd.DataFrame, FittedBaseline]:
    """Produce the expected-points table from the component chain, and B0 fitted beside it.

    The frame has exactly the shape :func:`fpl_dof.forecast.xp_v0.build_forecast` returns — one row
    per player, per-gameweek expectations, a horizon total, a component decomposition, a standard
    deviation on every mean (Invariant 6) and a confidence tier — so the optimiser, the weekly
    decision and the publisher need no knowledge of which model produced it. B0 is returned beside
    it, not in it: it is the captain policy's input (DL-76, MOD-02).
    """
    history = inputs.player_gameweek
    _next_gameweek, deadline, horizon = next_deadline(inputs.gameweeks, config, as_of=inputs.as_of)
    fitted = fit_as_of(history, deadline, config, rules)
    frame: pd.DataFrame = fitted.predict(horizon, inputs=inputs)
    return frame, fitted.b0


def build_forecast(
    inputs: ForecastInputs, rules: GameRules, config: ForecastConfig
) -> pd.DataFrame:
    """The frame alone; see :func:`build`."""
    return build(inputs, rules, config)[0]


__all__ = [
    "IDENTITY_COLUMNS",
    "MODEL_NAME",
    "ColdStartError",
    "build",
    "build_forecast",
    "completed_gameweeks",
    "next_deadline",
    "training_set",
]
