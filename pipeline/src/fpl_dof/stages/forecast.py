"""Forecast stage — expected points per player, with uncertainty.

Reads silver, writes gold. Pure computation between the two: no network, no source names.

**Which model runs.** ``xp_v1`` — the component chain the walk-forward backtest grades — publishes,
and ``xp_v0`` is the cold-start fallback and nothing else (DL-46, closing D-25). The fallback fires
only when the current season is too young for M1-M8 to be fitted, and when it fires it says so: in
the log, in the stage metrics, in the model card, and in the ``model`` column of the artefact.
A silent fallback would be a season spent looking at a model nobody chose (DP-15).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast import live, xp_v0
from fpl_dof.forecast.diagnostics import PriceDependence, regress_xp_on_price
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.model_card import write_model_card
from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.stages.transform import read_rules

log = get_logger(__name__)

XP_FILENAME = "expected_points.parquet"
MODEL_CARD_FILENAME = "model-card.md"


@dataclass(frozen=True, slots=True)
class Forecast:
    """The frame, and the provenance of which model produced it."""

    frame: pd.DataFrame
    model: str
    fallback_reason: str | None


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    silver = ctx.layout.silver

    inputs = ForecastInputs(
        players=read_table(silver, season, Table.PLAYER),
        teams=read_table(silver, season, Table.TEAM),
        fixtures=read_table(silver, season, Table.FIXTURE),
        gameweeks=read_table(silver, season, Table.GAMEWEEK),
        history=read_table(silver, season, Table.PLAYER_SEASON_HISTORY),
        # Both optional and both legitimately absent: there are no per-gameweek rows for a season
        # nobody has played, and no advanced metrics unless a source that supplies them is enabled.
        player_gameweek=read_table_optional(silver, season, Table.PLAYER_GAMEWEEK),
        metrics=read_table_optional(silver, season, Table.PLAYER_METRIC),
    )

    result = build(inputs, rules, ctx.config.forecast)
    forecast = result.frame
    regression = regress_xp_on_price(forecast)

    # R-15 is a finding to report, loudly, not a gate to fail. A repricing is still a squad; it is
    # just not a forecast, and the review gate needs to know which it is looking at.
    if regression.verdict is PriceDependence.REPRICING:
        log.warning("forecast.repricing", extra={"detail": regression.message})
    elif regression.verdict is PriceDependence.THIN:
        log.warning("forecast.thin_signal", extra={"detail": regression.message})

    xp_path = ctx.layout.gold / f"season={season.replace('/', '-')}" / XP_FILENAME
    xp_path.parent.mkdir(parents=True, exist_ok=True)
    forecast.to_parquet(xp_path, index=False, compression="snappy")

    card_path = xp_path.parent / MODEL_CARD_FILENAME
    write_model_card(
        card_path,
        forecast=forecast,
        regression=regression,
        config=ctx.config.forecast,
        rules=rules,
        run_id=ctx.run_id,
        model=result.model,
        fallback_reason=result.fallback_reason,
        backtest=_previous_backtest(ctx, season),
    )

    below_floor = int(
        (forecast["start_probability"] < ctx.config.forecast.minimum_start_probability_for_xi).sum()
    )
    return StageResult(
        metrics={
            "model": result.model,
            "cold_start_fallback": str(result.fallback_reason is not None),
            "players": len(forecast),
            "r_squared_on_price": round(regression.r_squared, 4),
            "price_dependence": regression.verdict.value,
            "mean_xp_next": round(float(forecast["xp_next"].mean()), 3),
            "max_xp_next": round(float(forecast["xp_next"].max()), 3),
            "below_start_floor": below_floor,
        },
        outputs=[Output(path=xp_path, rows=len(forecast)), Output(path=card_path)],
    )


def build(inputs: ForecastInputs, rules: GameRules, config: ForecastConfig) -> Forecast:
    """Run ``xp_v1``, or ``xp_v0`` and a stated reason.

    Pure, and separate from :func:`run`, because "which model is the app showing" is the question
    E9 exists to answer and it should be answerable without a pipeline context (DP-03).
    """
    reason = _cold_start_reason(inputs, config)
    if reason is None:
        try:
            frame = live.build_forecast(inputs, rules, config)
        except live.ColdStartError as exc:
            reason = str(exc)
        else:
            frame["model"] = live.MODEL_NAME
            return Forecast(frame=frame, model=live.MODEL_NAME, fallback_reason=None)

    log.warning(
        "forecast.cold_start_fallback",
        extra={"model": xp_v0.MODEL_NAME, "instead_of": live.MODEL_NAME, "reason": reason},
    )
    frame = xp_v0.build_forecast(inputs, rules, config)
    frame["model"] = xp_v0.MODEL_NAME
    return Forecast(frame=frame, model=xp_v0.MODEL_NAME, fallback_reason=reason)


def _cold_start_reason(inputs: ForecastInputs, config: ForecastConfig) -> str | None:
    """Why the component chain cannot be trusted yet, or ``None`` if it can."""
    minimum = config.published.cold_start_minimum_gameweeks
    try:
        _, deadline, _ = live.next_deadline(inputs.gameweeks, config)
    except live.ColdStartError as exc:
        return str(exc)
    played = live.completed_gameweeks(inputs.player_gameweek, before=deadline)
    if played >= minimum:
        return None
    return (
        f"{played} completed gameweek(s) of 2026/27 history, below the {minimum} the component "
        "chain needs before its fitted rates say more than its priors do"
    )


def _previous_backtest(ctx: StageContext, season: str) -> dict[str, object] | None:
    """The most recent backtest report, if one has ever been run.

    Read rather than recomputed: the backtest is deliberately not part of ``run`` (it is slow and
    needs the historical backfill), but its verdict has to reach the card a human reads before a
    deadline. A stale verdict is still the last thing that was actually measured; no verdict at all
    is how an unvalidated model gets presented as a validated one.
    """
    from fpl_dof.stages.backtest import REPORT_FILENAME

    path = ctx.layout.gold / f"season={season.replace('/', '-')}" / REPORT_FILENAME
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        log.warning("forecast.backtest_unreadable", extra={"path": str(path)})
        return None
    return loaded if isinstance(loaded, dict) else None
