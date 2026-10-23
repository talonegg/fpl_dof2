"""Forecast stage — expected points per player, with uncertainty.

Reads silver, writes gold. Which model runs is the model factory's choice, made by the champion
strategy's ``forecast`` (``xp_v1``, or the ``xp_v0`` cold-start fallback with its reason, DL-46);
this stage only calls it and writes what comes back: the forecast frame, the captain policy's
price-and-position line beside it (DL-76, MOD-02), and the model card.
"""

from __future__ import annotations

import json

from fpl_dof.artefacts import (
    CAPTAIN_LINE_FILENAME,
    EXPERIMENTS_DIRNAME,
    XP_FILENAME,
    read_rules,
)
from fpl_dof.factory import (
    ForecastInputs,
    PriceDependence,
    latest_verdict,
    regress_xp_on_price,
    write_model_card,
)
from fpl_dof.factory.registry import champion, digest
from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table

log = get_logger(__name__)

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

    strategy = champion()
    result = strategy.forecast(inputs, rules, ctx.config)
    forecast = result.frame
    regression = regress_xp_on_price(forecast)

    # R-15 is a finding to report, loudly, not a gate to fail. A repricing is still a squad; it is
    # just not a forecast, and the review gate needs to know which it is looking at.
    if regression.verdict is PriceDependence.REPRICING:
        log.warning("forecast.repricing", extra={"detail": regression.message})
    elif regression.verdict is PriceDependence.THIN:
        log.warning("forecast.thin_signal", extra={"detail": regression.message})

    xp_path = ctx.layout.gold_for(season) / XP_FILENAME
    xp_path.parent.mkdir(parents=True, exist_ok=True)
    forecast.to_parquet(xp_path, index=False, compression="snappy")
    line_path = xp_path.parent / CAPTAIN_LINE_FILENAME
    line_path.unlink(missing_ok=True)  # never leave a stale line beside a new frame
    if result.captain_line is not None:
        line_path.write_text(result.captain_line.model_dump_json(indent=2), encoding="utf-8")

    card_path = xp_path.parent / MODEL_CARD_FILENAME
    strategy_digest = digest(strategy, ctx.config)
    write_model_card(
        card_path,
        forecast=forecast,
        regression=regression,
        config=ctx.config.forecast,
        rules=rules,
        run_id=ctx.run_id,
        model=result.model,
        fallback_reason=result.fallback_reason,
        backtest=latest_verdict(_experiment_records(ctx), strategy.id, strategy_digest),
        strategy_digest=strategy_digest,
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


def _experiment_records(ctx: StageContext) -> list[dict[str, object]]:
    """Every standing-backtest record held under ``ledger/experiments/`` (MOD-08).

    Read rather than recomputed: the backtest is deliberately not part of ``run`` (it is slow and
    needs the historical backfill), but its verdict has to reach the card a human reads before a
    deadline. In CI the directory is restored from the ``ledger`` branch. An unreadable file is
    reported and skipped; no records at all is how the card learns to say no verdict exists.
    """
    records: list[dict[str, object]] = []
    for path in sorted((ctx.layout.ledger / EXPERIMENTS_DIRNAME).glob("*.json")):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            log.warning("forecast.experiment_unreadable", extra={"path": str(path)})
            continue
        if isinstance(loaded, list):
            records.extend(r for r in loaded if isinstance(r, dict))
    return records
