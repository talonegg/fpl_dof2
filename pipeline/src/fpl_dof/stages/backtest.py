"""Backtest stage — run the walk-forward replay and write the evidence.

Not part of ``run``. It is slow, it needs the historical backfill, and its output is a *finding*
rather than an artefact the weekly pipeline consumes. Making it a separate command keeps the
deadline path fast and keeps the backtest honest: nobody is tempted to skip it because it was
making the Friday run late.

The report it writes is the thing that closes D-01. Until it exists, the forecast is unvalidated by
construction and no expensive decision should rest on it.
"""

from __future__ import annotations

import json

from fpl_dof.forecast.backtest import BacktestResult, walk_forward
from fpl_dof.forecast.xp_v1 import ComponentPredictor
from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.silver.store import read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.stages.transform import read_rules

log = get_logger(__name__)

REPORT_FILENAME = "backtest.json"


class NoHistoryError(RuntimeError):
    """There is nothing to walk forward over."""


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    history = read_table_optional(ctx.layout.silver, season, Table.PLAYER_GAMEWEEK)

    if history is None or history.empty:
        raise NoHistoryError(
            "no per-gameweek history is available, so there is nothing to backtest. The official "
            "API publishes none for prior seasons (DL-19) — enable the archive source and set "
            "sources.backfill_seasons, then re-run ingest and transform."
        )

    predictor = ComponentPredictor(ctx.config.forecast, rules)
    result = walk_forward(
        history,
        predictor,
        forecast_config=ctx.config.forecast,
        backtest_config=ctx.config.backtest,
        seasons=ctx.config.backtest.training_seasons or None,
    )

    directory = ctx.layout.gold / f"season={season.replace('/', '-')}"
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / REPORT_FILENAME
    report_path.write_text(json.dumps(result.as_dict(), indent=2), encoding="utf-8")

    predictions_path = directory / "backtest-predictions.parquet"
    result.predictions.to_parquet(predictions_path, index=False, compression="snappy")

    card_path = directory / "backtest-card.md"
    card_path.write_text(_card(result, ctx), encoding="utf-8")

    # Logged at warning when the model loses, because that is the headline finding and it must not
    # scroll past as routine output.
    if not result.beats_b0 or not result.beats_model_free:
        log.warning("backtest.no_edge", extra={"verdict": result.verdict()})
    else:
        log.info("backtest.edge", extra={"verdict": result.verdict()})

    return StageResult(
        metrics={
            "folds": len(result.folds),
            "observations": len(result.predictions),
            "model_spearman": _round(result.model.spearman),
            "b0_spearman": _round(result.b0.spearman),
            "model_free_spearman": _round(result.model_free.spearman),
            "mae_skill_score": _round(result.model.mae_skill_score),
            "beats_b0": str(result.beats_b0),
            "beats_model_free": str(result.beats_model_free),
        },
        outputs=[
            Output(path=report_path),
            Output(path=predictions_path, rows=len(result.predictions)),
            Output(path=card_path),
        ],
    )


def _round(value: float) -> float:
    return 0.0 if value != value else round(float(value), 5)  # NaN-safe


def _card(result: BacktestResult, ctx: StageContext) -> str:
    """A model card for the backtest itself: what was measured, against what, and the verdict."""
    lines = [
        "# Backtest report",
        "",
        f"Run `{ctx.run_id}`. Walk-forward replay over {len(result.folds)} gameweek deadlines, "
        f"{len(result.predictions)} player-gameweek observations.",
        "",
        "## The verdict",
        "",
        result.verdict(),
        "",
        "## Why these comparisons and not absolute thresholds",
        "",
        "Charter v1.0 carried absolute tier-2 thresholds. They were replaced (DL-13) because they",
        "would have passed a model with no edge: `MAE <= 2.1` is reachable by predicting a",
        "constant, and a Spearman of 0.30 across all positions is roughly what price alone gives",
        "you — price *is* FPL's own expected-value estimate. So every number below is relative.",
        "",
        "| Model | Observations | MAE | Spearman | MAE skill vs B0 | Top-20 precision |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for metrics in (result.model, result.b0, result.model_free, result.mean_baseline):
        lines.append(
            f"| {metrics.name} | {metrics.observations} | {_fmt(metrics.mae)} | "
            f"{_fmt(metrics.spearman)} | {_fmt(metrics.mae_skill_score)} | "
            f"{_fmt(metrics.top_n_precision)} |"
        )

    lines += [
        "",
        "## What each benchmark is for",
        "",
        "- **B0 (price + position)** — the test of whether this project knows anything price does",
        "  not. Losing to B0 means the forecast is an expensive restatement of `now_cost`.",
        "- **model-free (trailing 6)** — pick the last six gameweeks' top scorers. Depends on",
        "  nothing this project predicts, which makes it the honest bar; it is roughly what an",
        "  unaided manager does.",
        "- **mean** — a constant. Included because it is startling how well it scores on absolute",
        "  metrics, which is the whole reason the thresholds are now relative.",
        "",
        "The third benchmark the plan carried — *highest xP, one transfer per week* — is",
        "**circular** and is not reported here as a benchmark. It runs on this project's own",
        "forecast, so if the forecast is poor both sides of the comparison are poor. It measures",
        "the optimiser, not the model.",
        "",
        "## Breakdowns",
        "",
        "### Spearman by position",
        "",
        "| Position | Model | B0 |",
        "| --- | --- | --- |",
    ]
    positions = sorted(set(result.model.spearman_by_position) | set(result.b0.spearman_by_position))
    for position in positions:
        lines.append(
            f"| {position} | {_fmt(result.model.spearman_by_position.get(position, float('nan')))} "
            f"| {_fmt(result.b0.spearman_by_position.get(position, float('nan')))} |"
        )

    lines += [
        "",
        "### Spearman by price band",
        "",
        "| Band | Model | B0 |",
        "| --- | --- | --- |",
    ]
    bands = sorted(set(result.model.spearman_by_price_band) | set(result.b0.spearman_by_price_band))
    for band in bands:
        lines.append(
            f"| {band} | {_fmt(result.model.spearman_by_price_band.get(band, float('nan')))} "
            f"| {_fmt(result.b0.spearman_by_price_band.get(band, float('nan')))} |"
        )

    lines += [
        "",
        "## Known limits of this measurement",
        "",
        "- **Defensive Contribution exists in 2025/26 only.** Any fold before it cannot use M4, so",
        "  the model is measured without its best component over most of the window. D-11.",
        "- **No season used the 2026/27 BPS matrix.** M8 is structural rather than trained, and",
        "  bonus accuracy measured here is against a scoring regime that no longer applies.",
        "- **Opponent strength is league-average within the backtest.** The harness carries no",
        "  fixture table, so M2 contributes less here than it does at inference.",
        "- **The deadline is approximated by the gameweek's earliest kickoff**, which is up to",
        "  90 minutes later than FPL's published deadline. Conservative: it can only exclude",
        "  information, never admit it.",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in result.warnings)
    if not result.warnings:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def _fmt(value: float) -> str:
    return "—" if value != value else f"{value:.3f}"
