"""Forecast stage — expected points per player, with uncertainty.

Reads silver, writes gold. Which model runs is the model factory's choice, made by the champion
strategy's ``forecast`` (``xp_v1``, or the ``xp_v0`` cold-start fallback with its reason, DL-46);
this stage only calls it and writes what comes back: the forecast frame, the captain policy's
price-and-position line beside it (DL-76, MOD-02), and the model card.
"""

from __future__ import annotations

import json

from fpl_dof.factory.registry import champion
from fpl_dof.forecast.diagnostics import PriceDependence, regress_xp_on_price
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.model_card import write_model_card
from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.stages.transform import read_rules

log = get_logger(__name__)

XP_FILENAME = "expected_points.parquet"
CAPTAIN_LINE_FILENAME = "captain_line.json"
MODEL_CARD_FILENAME = "model-card.md"


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
        as_of=ctx.as_of,
    )

    result = champion().forecast(inputs, rules, ctx.config.forecast)
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
    line_path = xp_path.parent / CAPTAIN_LINE_FILENAME
    line_path.unlink(missing_ok=True)  # never leave a stale line beside a new frame
    if result.captain_line is not None:
        line_path.write_text(result.captain_line.model_dump_json(indent=2), encoding="utf-8")

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
        component_description=result.component_description,
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
        outputs=[
            Output(path=xp_path, rows=len(forecast)),
            *([Output(path=line_path)] if result.captain_line is not None else []),
            Output(path=card_path),
        ],
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
