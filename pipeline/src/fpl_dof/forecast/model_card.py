"""The model card.

Written on every run, not once at design time, so it always describes the model that actually
produced the squad sitting next to it (DP-09). It carries the method, the tunables actually in
force, the R-15 diagnostic result, and — at least as importantly — the known weaknesses.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.diagnostics import PriceDependence, PriceRegression, top_by_xp
from fpl_dof.frames import as_float, as_int
from fpl_dof.rules.models import GameRules

COLD_START_WEAKNESS = (
    "No backtesting",
    "This forecast has never been validated against anything (debt D-01, a knowing breach of "
    "blueprint principle B7). Do not trust it for expensive decisions. E3 repays this.",
)

BACKTESTED_WEAKNESS = (
    "Minutes-model calibration is unmeasured",
    "The Brier-score plumbing exists (`forecast.metrics.brier_score`), but the backtest harness "
    "does not yet pass minutes probabilities through it, so `minutes_brier` is always null and "
    "E3-S3's own acceptance criterion — calibration curves and Brier score reported — is not "
    "actually satisfied. Tracked as debt D-14, found in the post-E3 audit rather than closed "
    "by it.",
)

KNOWN_WEAKNESSES = [
    (
        "No minutes model with measured calibration",
        "Expected minutes come from last season's start rate shrunk toward a price-tier prior "
        "(D-02, D-12). Rotation risk and injury returns are mispriced.",
    ),
    (
        "Preseason status flags say almost nothing",
        "Nearly every player is flagged available in preseason, so the availability haircut does "
        "very little work. Real injury and rotation news must come from the human review gate.",
    ),
    (
        "Defensive Contribution rests on one season",
        "2025/26 is the only season in which it was recorded (D-11). The highest signal-to-noise "
        "component has the thinnest evidence behind it.",
    ),
    (
        "Bonus is extrapolated from a superseded BPS matrix",
        "Bonus per 90 comes from last season's bonus, but the Bonus Points System was revised for "
        "2026/27 — the tackle penalty removed, clearances devalued, goalkeeper saves restructured. "
        "Bonus is therefore biased toward the players the old matrix favoured.",
    ),
    (
        "Fixture difficulty is FPL's own rating",
        "Team strength_attack and strength_defence are all zero in preseason, so the fixture's own "
        "1-5 difficulty is the only signal available (D-05). An xG-based model replaces it in E3.",
    ),
    (
        "Uncertainty is a heuristic band, not a modelled variance",
        "A coefficient of variation by confidence tier (D-09). It is deliberately wide, and it is "
        "not a distribution you should compute a probability from.",
    ),
    (
        "Single-gameweek scoring, summed over a horizon",
        "No transfer planning, no chip modelling, no rollover logic (D-03, D-04).",
    ),
]


def write_model_card(
    path: Path,
    *,
    forecast: pd.DataFrame,
    regression: PriceRegression,
    config: ForecastConfig,
    rules: GameRules,
    run_id: str,
    backtest: Mapping[str, object] | None = None,
) -> Path:
    lines: list[str] = []
    add = lines.append

    if backtest is not None:
        add("# Model card — expected points v1 (backtested)")
    else:
        add("# Model card — expected points v0 (cold start)")
    add("")
    add(f"**Run:** `{run_id}` · **Season:** {rules.season} · **Players scored:** {len(forecast)}")
    add(
        f"**Next gameweek:** {as_int(forecast['next_gameweek'].iloc[0])} · "
        f"**Horizon:** {as_int(forecast['horizon_gameweeks'].iloc[0])} gameweeks"
    )
    add("")
    if backtest is not None:
        add("")
        add("## Measured accuracy")
        add("")
        # The card is what a human actually reads before a deadline. A backtest finding that lives
        # only in backtest.json is a finding nobody sees at the moment it matters (DL-21).
        add(str(backtest.get("verdict", "")))
        add("")
        model = backtest.get("model") or {}
        b0 = backtest.get("b0") or {}
        free = backtest.get("model_free") or {}
        if isinstance(model, Mapping) and isinstance(b0, Mapping) and isinstance(free, Mapping):
            add("| Model | MAE | Spearman | Top-20 precision |")
            add("| --- | --- | --- | --- |")
            for label, metrics in (
                ("This forecast", model),
                ("B0 — price + position", b0),
                ("Model-free — trailing 6", free),
            ):
                add(
                    f"| {label} | {metrics.get('mae')} | {metrics.get('spearman')} | "
                    f"{metrics.get('top_n_precision')} |"
                )
            add("")
            if not backtest.get("beats_model_free", True):
                add(
                    "**The head of the ranking is where this is weakest, and the head is where the "
                    "tool is used.** Top-20 precision is what matters for a captaincy or transfer "
                    "decision, and on that measure the forecast currently does not beat picking "
                    "recent form. Treat its ordering as a prompt to look, not as a reason to act "
                    "(DL-21)."
                )
                add("")

    add("## What this model is")
    add("")
    add(
        "Preseason has no current-season data, so there is nothing to fit. This is entirely a "
        "prior-construction exercise: take what a player did last season, decide how much of it to "
        "believe, adjust for who they are playing and whether they will play at all, and convert "
        "to points using the rules module."
    )
    add("")
    add("Signal stack, in descending weight:")
    add("")
    add("1. Prior-season per-90 rates — goals, assists, clean sheets, saves, cards, bonus.")
    add("2. Per-90 Defensive Contribution, from 2025/26 only.")
    add("3. FPL's own price, as a market-implied prior, via the group that thin samples shrink to.")
    add("4. Position-and-price-tier baselines for players with no top-flight history.")
    add("5. An availability haircut from the FPL status flag.")
    add("6. Fixture difficulty across the horizon.")
    add("")
    add("## The diagnostic that decides whether any of this is worth anything (R-15)")
    add("")
    add(
        f"**R² of xP on (price, position): {regression.r_squared:.3f}**, "
        f"over {regression.n} players."
    )
    add("")
    add(f"**Verdict: {regression.verdict.value}.** {regression.message}")
    add("")
    if regression.verdict is PriceDependence.REPRICING:
        add(
            "> This is a finding, not a number to tune. Do not adjust the model to reduce it "
            "without evidence that the adjustment improves accuracy."
        )
        add("")
    if regression.within_tier_spread:
        add("Within-price-tier spread of xP (standard deviation, points over the horizon):")
        add("")
        add("| Position / tier | Spread |")
        add("| --- | --- |")
        for key, value in sorted(regression.within_tier_spread.items()):
            add(f"| {key} | {value:.2f} |")
        add("")

    add("## Top 20 by expected points — the plausibility check")
    add("")
    top = top_by_xp(forecast, 20)
    add("| # | Player | Pos | £m | xP (horizon) | P(start) | Confidence |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for rank, (_, row) in enumerate(top.iterrows(), start=1):
        add(
            f"| {rank} | {row['web_name']} | {row['position']} | "
            f"{as_float(row['price']):.1f} | {as_float(row['xp_horizon']):.2f} | "
            f"{as_float(row['start_probability']):.0%} | {row['confidence']} |"
        )
    add("")

    add("## Coverage")
    add("")
    counts = forecast["confidence"].value_counts()
    add("| Confidence tier | Players | Meaning |")
    add("| --- | --- | --- |")
    meanings = {
        "high": f"at least {config.confidence_minutes_high} weighted minutes of evidence",
        "medium": f"at least {config.confidence_minutes_medium} weighted minutes",
        "low": "some Premier League history, but little",
        "none": "no Premier League history — new signing or promoted club; pure prior",
    }
    for tier in ("high", "medium", "low", "none"):
        add(f"| {tier} | {as_int(counts.get(tier, 0)):d} | {meanings[tier]} |")
    add("")
    below = int((forecast["start_probability"] < config.minimum_start_probability_for_xi).sum())
    add(
        f"{below} of {len(forecast)} players fall below the "
        f"{config.minimum_start_probability_for_xi:.0%} start-probability floor and are therefore "
        "barred from the starting XI."
    )
    add("")

    add("## Tunables in force")
    add("")
    add("| Parameter | Value |")
    add("| --- | --- |")
    for key, tunable in _flatten(config.model_dump()):
        add(f"| `{key}` | {tunable} |")
    add("")

    add("## Known weaknesses")
    add("")
    add("Stated because they are the reason the human review gate (E0-S8) is mandatory.")
    add("")
    weaknesses = list(KNOWN_WEAKNESSES)
    weaknesses.insert(0, BACKTESTED_WEAKNESS if backtest is not None else COLD_START_WEAKNESS)
    for title, detail in weaknesses:
        add(f"- **{title}.** {detail}")
    add("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _flatten(value: object, prefix: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        out: list[tuple[str, object]] = []
        for key, item in value.items():
            out.extend(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return [(prefix, value)]
