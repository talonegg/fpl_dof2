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

    # Optional, and absent is normal: no scraped source is enabled by default, and the forecast
    # degrades to the position priors it has always used when the table is not there (DP-15).
    metrics = read_table_optional(ctx.layout.silver, season, Table.PLAYER_METRIC)

    predictor = ComponentPredictor(ctx.config.forecast, rules)
    result = walk_forward(
        history,
        predictor,
        forecast_config=ctx.config.forecast,
        backtest_config=ctx.config.backtest,
        seasons=ctx.config.backtest.training_seasons or None,
        metrics=metrics,
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
            "fixture_coverage": _round(result.fixture_coverage),
            "top_n_precision": _round(result.model.top_n_precision),
            "b0_top_n_precision": _round(result.b0.top_n_precision),
            "calibration_slope": _round(result.model.calibration_slope),
            # E10-S5. On the stage's metrics rather than only in the report, so the gap shows up in
            # the run manifest and a change in it is visible without opening a markdown file.
            "monolith_spearman": _round(result.monolith.spearman),
            "monolith_top_n_precision": _round(result.monolith.top_n_precision),
            "monolith_mae": _round(result.monolith.mae),
            "explainability_gap": _round(result.explainability_gap),
            "adaptive_shrinkage": str(ctx.config.forecast.discrimination.adaptive_shrinkage),
            "minutes_v2": str(ctx.config.forecast.discrimination.minutes_v2),
            "duty_term": str(ctx.config.forecast.discrimination.duty_term),
            "duty_entries": len(ctx.config.forecast.duty.entries),
            "gkp_v2": str(ctx.config.forecast.discrimination.gkp_v2),
            "gkp_mode": ctx.config.forecast.discrimination.goalkeeper.mode,
            "minutes_brier": _round(
                float("nan")
                if result.minutes_calibration is None
                else result.minutes_calibration.brier
            ),
            "minutes_brier_haircut": _round(
                float("nan")
                if result.minutes_calibration is None
                else result.minutes_calibration.baseline_brier
            ),
            "beats_status_haircut": str(
                result.minutes_calibration is not None and result.minutes_calibration.beats_baseline
            ),
            "prior_season_prior": str(ctx.config.forecast.features.prior_season.enabled),
            "prior_season_rows": 0 if metrics is None else len(metrics),
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
    for metrics in (
        result.model,
        result.b0,
        result.model_free,
        result.mean_baseline,
        result.monolith,
    ):
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
        "- **monolith (shadow, GBM)** — a gradient-boosted model on exactly the same features, as",
        "  an upper bound on what this data is worth to a model nobody can interrogate. It is a",
        "  **benchmark and never a candidate**: it does not reach `optimise`, the decision layer",
        "  or the published ranking (E10-S5, DL-53). Its MAE skill column is measured against the",
        "  component chain rather than against B0, so it reads as skill over what we ship.",
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
        "### Spearman and calibration by fixture difficulty (E9-S2)",
        "",
        "How hard the fixture was, as the ratio of the goals M2 expects *against* the player's",
        "club to the goals it expects *for* them: 1.0 is even, and the bands cut at",
        f"{ctx.config.backtest.fixture_difficulty_band_ratio:g} and its reciprocal. The strength",
        "model used for the banding is fitted by the harness on pre-deadline matches only, and",
        "separately from the graded model, so the bands mean the same thing from one run to the",
        "next. This is the axis a fixture change (E11) has to show up on.",
        "",
        f"Fixtures resolved: {_pct(result.fixture_coverage)} of scored observations. The remainder",
        "were scored against league-average opposition and are banded `unresolved`.",
        "",
        "| Band | Model Spearman | B0 Spearman | Model calibration |",
        "| --- | --- | --- | --- |",
    ]
    fixture_bands = sorted(
        set(result.model.spearman_by_fixture_band) | set(result.b0.spearman_by_fixture_band)
    )
    for band in fixture_bands:
        lines.append(
            f"| {band} | {_fmt(result.model.spearman_by_fixture_band.get(band, float('nan')))} "
            f"| {_fmt(result.b0.spearman_by_fixture_band.get(band, float('nan')))} "
            f"| {_fmt(result.model.calibration_by_fixture_band.get(band, float('nan')))} |"
        )
    if not fixture_bands:
        lines.append("| — | — | — | — |")

    lines += _head_section(result, ctx)
    lines += _explainability_section(result)
    lines += _minutes_section(result, ctx)

    lines += [
        "",
        "## Known limits of this measurement",
        "",
        "- **Defensive Contribution exists in 2025/26 only.** Any fold before it cannot use M4, so",
        "  the model is measured without its best component over most of the window. D-11.",
        "- **No season used the 2026/27 BPS matrix.** M8 is structural rather than trained, and",
        "  bonus accuracy measured here is against a scoring regime that no longer applies.",
        "- **Opponent strength is real, where the calendar could supply it (E9-S2).** Each fold",
        "  row is scored against the fixture it was actually played under; the share above says",
        "  how often that succeeded, and the `unresolved` band is what was left on league-average",
        "  opposition. Before E9-S2 every prediction here was league-average, so numbers from",
        "  earlier runs are not comparable on the fixture axis.",
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


def _head_section(result: BacktestResult, ctx: StageContext) -> list[str]:
    """The head of the ranking, per position — the axis E10 exists to move (E10-S2, DL-49).

    Reported against B0 rather than absolutely, because the finding [DL-21] recorded is precisely
    that the model is *worse* than price at the head while being better everywhere else, and only
    the comparison says that.
    """
    discrimination = ctx.config.forecast.discrimination
    candidate = "on" if discrimination.adaptive_shrinkage else "off"
    duty = "on" if discrimination.duty_term else "off"
    goalkeeper = "on" if discrimination.gkp_v2 else "off"
    entries = len(ctx.config.forecast.duty.entries)
    top_n = ctx.config.backtest.top_n_precision
    lines = [
        "",
        "## The head of the ranking (E10)",
        "",
        f"Top-{top_n} precision: of the {top_n} players ranked highest **in a gameweek**, how many",
        f"were genuinely in that gameweek's top {top_n}. Averaged over gameweeks, not pooled over",
        "them — pooled, the highest observed scores are individual 20-point hauls and no",
        "calibrated expectation can ever reach them, so the figure is 0.00 for every model and",
        "grades nothing (DL-49).",
        "",
        "Calibration slope: the regression of actual on predicted. **Below 1 means the forecast is",
        "compressed** — it is failing to spread players out, which is the whole of DL-21's finding",
        "and the thing E10 attacks.",
        "",
        f"The candidate `discrimination.adaptive_shrinkage` is **{candidate}** for this run "
        "(DP-08, DL-47).",
        "",
        f"The candidate `discrimination.duty_term` is **{duty}** for this run, against a committed "
        f"duty table holding **{entries}** entries (E10-S3, DL-50). The entry count is printed "
        "because a table that has quietly emptied produces a candidate that is inert for a reason "
        "nothing else in this report would show — which grades as *no effect* and means *not "
        "measured* (DP-15).",
        "",
        f"The candidate `discrimination.gkp_v2` is **{goalkeeper}** for this run, in "
        f"`{discrimination.goalkeeper.mode}` mode (E10-S4, DL-51). It changes the GKP row of the "
        "per-position table below and nothing else: a goalkeeper's saves stop being a "
        "fixture-blind per-90 and become the pressure M2 expects in his fixture. **Pressure is "
        "expected goals conceded, standing in for shots faced, because nothing in silver counts "
        "shots** — a proxy named rather than substituted (DP-09).",
        "",
        "| | Model | B0 | Model-free |",
        "| --- | --- | --- | --- |",
        f"| Top-{top_n} precision | {_fmt(result.model.top_n_precision)} "
        f"| {_fmt(result.b0.top_n_precision)} | {_fmt(result.model_free.top_n_precision)} |",
        f"| Captaincy hit rate | {_fmt(result.model.captaincy_hit_rate)} "
        f"| {_fmt(result.b0.captaincy_hit_rate)} | {_fmt(result.model_free.captaincy_hit_rate)} |",
        f"| Calibration slope | {_fmt(result.model.calibration_slope)} "
        f"| {_fmt(result.b0.calibration_slope)} | {_fmt(result.model_free.calibration_slope)} |",
        "",
        "### Per position",
        "",
        "Each position's head goes as deep as that position goes into a squad, so the depth is the",
        "same relative depth everywhere: a single top-20 applied inside a position that fields two",
        "players a week would be all of them, and every model would score about 1.0.",
        "",
        "| Position | Precision, model | Precision, B0 | Calibration, model | Calibration, B0 |",
        "| --- | --- | --- | --- | --- |",
    ]
    positions = sorted(
        set(result.model.top_n_precision_by_position)
        | set(result.model.calibration_slope_by_position)
    )
    for position in positions:
        lines.append(
            f"| {position} "
            f"| {_fmt(result.model.top_n_precision_by_position.get(position, float('nan')))} "
            f"| {_fmt(result.b0.top_n_precision_by_position.get(position, float('nan')))} "
            f"| {_fmt(result.model.calibration_slope_by_position.get(position, float('nan')))} "
            f"| {_fmt(result.b0.calibration_slope_by_position.get(position, float('nan')))} |"
        )
    if not positions:
        lines.append("| — | — | — | — | — |")
    return lines


def _explainability_section(result: BacktestResult) -> list[str]:
    """What the chain's interpretability costs, priced every run (E10-S5, DL-53).

    DP-10 says to prefer the formulation you can argue with *where two designs are close in
    expected quality*, and that a materially better monolith makes the trade a recorded decision.
    Both halves need a number, and a number that is only recomputed when somebody remembers to ask
    is a number that stops being true. So this section is unconditional.
    """
    description = result.monolith_description
    degraded = description.get("degraded")
    features = description.get("features")
    lines = [
        "",
        "## The explainability trade (E10-S5)",
        "",
        result.gap_statement(),
        "",
        "**The monolith is a shadow benchmark and never a promotion candidate.** Unlike every",
        "other E10 story it has no `discrimination` flag, because there is nothing a future review",
        "could switch on — the epic is explicit that it is never promoted over the chain without",
        "an explicit DP-10 decision weighing accuracy against explicability. Its configuration",
        "lives in `backtest.monolith`, which nothing on the forecast, optimise or publish path",
        "reads, so",
        "the guarantee is structural rather than a default somebody could change.",
        "",
        "**Same features, same folds, same strip.** It is fitted by the same walk-forward loop on",
        "the same training frame the chain gets, and predicts on the same outcome-stripped frame.",
        "It reads exactly the columns the feature store declares as inputs — an allow-list, so a",
        "new outcome column cannot reach it by default — and nothing else. The one thing it does",
        "*not* get is M2: the chain turns the opponent's id into fitted attack and defence ratings",
        "pooled over every match that club has played, and the monolith gets the raw club as a",
        "category and has to rediscover that from splits. So the gap below is what a monolith does",
        "with what the chain is handed, not with a fixture-difficulty feature it was given.",
        "",
        f"Model: `{description.get('library', '—')}`, "
        f"{len(features) if isinstance(features, list) else 0} features, "
        f"{description.get('training_rows', 0)} rows in the final fold's training window.",
        "",
    ]
    if degraded:
        lines += [
            f"> **Degraded: {degraded}.** The gap above is a statement about a constant, not about",
            "> the chain. An inert benchmark reads as *no cost to explainability*, which is the",
            "> most reassuring possible way to have measured nothing (DP-15).",
            "",
        ]

    lines += [
        "| | Chain (`xp_v1`) | Monolith | Gap |",
        "| --- | --- | --- | --- |",
        f"| Top-{result.top_n} precision | {_fmt(result.model.top_n_precision)} "
        f"| {_fmt(result.monolith.top_n_precision)} | {_fmt(result.explainability_gap)} |",
        f"| Spearman | {_fmt(result.model.spearman)} | {_fmt(result.monolith.spearman)} "
        f"| {_fmt(result.monolith.spearman - result.model.spearman)} |",
        f"| MAE | {_fmt(result.model.mae)} | {_fmt(result.monolith.mae)} "
        f"| {_fmt(result.monolith.mae - result.model.mae)} |",
        f"| Calibration slope | {_fmt(result.model.calibration_slope)} "
        f"| {_fmt(result.monolith.calibration_slope)} "
        f"| {_fmt(result.monolith.calibration_slope - result.model.calibration_slope)} |",
        f"| Captaincy hit rate | {_fmt(result.model.captaincy_hit_rate)} "
        f"| {_fmt(result.monolith.captaincy_hit_rate)} "
        f"| {_fmt(result.monolith.captaincy_hit_rate - result.model.captaincy_hit_rate)} |",
        "",
        "A positive gap on precision, Spearman or captaincy means the monolith is better and the",
        "chain is paying for its interpretability. On MAE and calibration slope, *lower* and",
        "*closer to 1* are better respectively, so read those two rows on their own terms.",
        "",
        "### Per position",
        "",
        "E10 §0 grades everything per position, and this most of all: a gap concentrated in one",
        "position is a statement about that position's formulation — a lead worth chasing inside",
        "the chain — rather than about interpretability in general.",
        "",
        "| Position | Precision, chain | Precision, monolith | Gap | Spearman, chain "
        "| Spearman, monolith |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    gaps = result.explainability_gap_by_position
    positions = sorted(
        set(result.model.top_n_precision_by_position) | set(result.monolith.spearman_by_position)
    )
    for position in positions:
        lines.append(
            f"| {position} "
            f"| {_fmt(result.model.top_n_precision_by_position.get(position, float('nan')))} "
            f"| {_fmt(result.monolith.top_n_precision_by_position.get(position, float('nan')))} "
            f"| {_fmt(gaps.get(position, float('nan')))} "
            f"| {_fmt(result.model.spearman_by_position.get(position, float('nan')))} "
            f"| {_fmt(result.monolith.spearman_by_position.get(position, float('nan')))} |"
        )
    if not positions:
        lines.append("| — | — | — | — | — | — |")
    return lines


def _minutes_section(result: BacktestResult, ctx: StageContext) -> list[str]:
    """M1's calibration against the E0 status-flag haircut (E10-S1, closes D-14).

    The section E3-S3's acceptance criterion always asked for and
    [DL-22](../../../docs/planning/00-decision-log.md) found had never been written, because
    ``minutes_brier`` was null in every report the harness had ever produced.
    """
    candidate_state = "on" if ctx.config.forecast.discrimination.minutes_v2 else "off"
    lines = [
        "",
        "## Minutes calibration (E10-S1, closes D-14)",
        "",
        "Brier score for the `{0, 1-59, 60+}` distribution — the multiclass form, so a model that",
        "is right about *whether* a player features and wrong about *how long* is scored for both.",
        "Zero is perfect, 2 is the worst possible, and the comparison is what the number is for.",
        "",
        "**Measured on every prediction, not on the scored subset.** The accuracy metrics above",
        "drop players who did not feature; here those rows are the majority of the population and",
        "they are the thing being calibrated. Scored only where somebody played, every minutes",
        "model looks excellent, because the answer is always yes.",
        "",
        f"The candidate `discrimination.minutes_v2` is **{candidate_state}** for this run "
        "(DP-08, DL-47).",
        "",
    ]
    calibration = result.minutes_calibration
    if calibration is None:
        lines += [
            "Not measured: the predictor exposes no minutes distribution. This is an absence, not",
            "a zero — nothing here says the minutes model is good or bad.",
        ]
        return lines

    lines += [
        "### The baseline",
        "",
        "**The E0 status-flag haircut**: a start rate times an availability haircut read off the",
        "FPL status flag, plus a fixed prior that a non-starter appears at all. That is all E0 had",
        "(debt D-02), and beating it is the acceptance criterion E3-S3 set. The archive carries no",
        "status flag, so availability is 1.0 for every historical row — faithful rather than a",
        "straw man, because the haircut's weakness was never the flag: nearly every player is",
        "flagged available, and what E0's estimate actually rested on was the start rate, which is",
        "reproduced here **unshrunk** so the baseline is the strongest honest version of itself.",
        "",
        f"Observations: {calibration.observations}.",
        "",
        "| | M1 | Status-flag haircut | Skill |",
        "| --- | --- | --- | --- |",
        f"| **Overall** | {_fmt(calibration.brier)} | {_fmt(calibration.baseline_brier)} | "
        f"{_fmt(calibration.skill_score)} |",
        "",
        f"**Beats the haircut: {'yes' if calibration.beats_baseline else 'no'}.**",
        "",
        "### By position",
        "",
        "Per position because a gain confined to one position is not a gain (E10 §0).",
        "",
        "| Position | M1 | Status-flag haircut |",
        "| --- | --- | --- |",
    ]
    for position in sorted(set(calibration.by_position) | set(calibration.baseline_by_position)):
        lines.append(
            f"| {position} | {_fmt(calibration.by_position.get(position, float('nan')))} "
            f"| {_fmt(calibration.baseline_by_position.get(position, float('nan')))} |"
        )

    lines += [
        "",
        "### By what actually happened",
        "",
        "Conditioned on the *observed* band, so the two failure modes separate: being wrong about",
        "non-appearances and being wrong about how long a player who featured lasted. The second",
        "is the half a captaincy decision rests on and the half an aggregate hides.",
        "",
        "| Observed | M1 | Status-flag haircut |",
        "| --- | --- | --- |",
    ]
    for band in ("none", "short", "long"):
        if band not in calibration.by_band and band not in calibration.baseline_by_band:
            continue
        lines.append(
            f"| {band} | {_fmt(calibration.by_band.get(band, float('nan')))} "
            f"| {_fmt(calibration.baseline_by_band.get(band, float('nan')))} |"
        )
    return lines


def _fmt(value: float) -> str:
    return "—" if value != value else f"{value:.3f}"


def _pct(value: float) -> str:
    return "—" if value != value else f"{value * 100:.1f}%"
