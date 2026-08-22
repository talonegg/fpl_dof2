"""The model card.

Written on every run, not once at design time, so it always describes the model that actually
produced the squad sitting next to it (DP-09). It carries the method, the tunables actually in
force, the R-15 diagnostic result, and — at least as importantly — the known weaknesses.

**Which model produced this frame is told to the card, never inferred.** The card used to decide it
was describing `xp_v1` whenever a `backtest.json` existed on disk, which is not evidence about
anything: the backtest is run separately, and its report survives runs of a completely different
model. A card that names the wrong model is worse than one that names none, because it is read
before a deadline by someone with no way to check it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.diagnostics import PriceDependence, PriceRegression, top_by_xp
from fpl_dof.forecast.xp_v0 import MODEL_NAME as XP_V0
from fpl_dof.forecast.xp_v1 import MODEL_NAME as XP_V1
from fpl_dof.frames import as_float, as_int
from fpl_dof.rules.models import GameRules

Weakness = tuple[str, str]

#: DL-21's guardrail, restated verbatim on every card and binding regardless of which model ran.
DL21_GUARDRAIL = (
    "**No -8 hit, chip or wildcard is justified by `xp_v1` alone until top-20 precision beats "
    "B0.** The backtest found the forecast beats a price-and-position baseline overall and loses "
    "to trailing form at the head of the ranking, which is exactly where an expensive decision is "
    "made (DL-21). That constraint is unchanged by `xp_v1` becoming the published model (DL-46): "
    "publishing the model that was graded fixes a delivery defect, it does not improve the grade."
)

MODEL_TITLES = {
    XP_V1: "expected points v1 — the component chain",
    XP_V0: "expected points v0 — the cold start",
}

COLD_START_WEAKNESS = (
    "No backtesting",
    "This forecast has never been validated against anything (debt D-01, a knowing breach of "
    "blueprint principle B7). Do not trust it for expensive decisions. E3 repays this.",
)

BACKTESTED_WEAKNESS = (
    "Minutes are measured now, and they are still the largest single error source",
    "Since E10-S1 the backtest reports the Brier score for the `{0, 1-59, 60+}` distribution, per "
    "position and per observed band, against the E0 status-flag haircut — so debt **D-14** is "
    "closed and E3-S3's acceptance criterion is satisfied by an actual number rather than by a "
    "ticked box. Measuring it is not improving it: every other component is multiplied by these "
    "probabilities, so read the minutes section of the backtest report before trusting a forecast "
    "for anyone whose minutes are in doubt. The candidate M1 that adds rotation, injury-return and "
    "availability-split behaviour is flagged off by default and is not what produced this card "
    "(DP-08, DL-47).",
)

#: True of whichever model ran.
SHARED_WEAKNESSES: list[Weakness] = [
    (
        "Defensive Contribution rests on one season",
        "2025/26 is the only season in which it was recorded (D-11). The highest signal-to-noise "
        "component has the thinnest evidence behind it.",
    ),
    (
        "No season used the 2026/27 BPS matrix",
        "The Bonus Points System was revised for 2026/27 — the tackle penalty removed, clearances "
        "devalued, goalkeeper saves restructured — so every bonus estimate here is fitted against "
        "a scoring regime that no longer applies, and is biased toward the players the old matrix "
        "favoured.",
    ),
    (
        "Single-gameweek scoring, summed over a horizon",
        "Each gameweek is scored against its own fixtures and the results are added. The model "
        "itself carries no transfer planning, chip modelling or rollover logic; that lives in the "
        "decision layer, which is a separate concern by design (DP-02).",
    ),
]

#: Weaknesses that belong to one model and would be a false claim on the other.
WEAKNESSES_BY_MODEL: dict[str, list[Weakness]] = {
    XP_V1: [
        (
            "The fixture axis is now measured, and has not yet been improved",
            "M2's attack and defence ratings decide every fixture on this card, and since E9-S2 "
            "they decide the graded prediction too: the harness joins each observation's real "
            "opponent and venue, and reports Spearman and calibration split by fixture difficulty. "
            "That makes the fixture axis measurable, which is not the same as good — read the "
            "fixture-band table in the backtest report before treating a fixture swing as an edge, "
            "and note that any run predating E9-S2 was scored against a league-average opponent "
            "and is not comparable on that axis.",
        ),
        (
            "The variance is modelled from minutes, and only from minutes",
            "The band is a mixture over the three minutes states, which is where nearly all of the "
            "spread genuinely lives. Within a state the scoring variance is a Poisson-shaped "
            "stand-in rather than a fitted quantity, so treat the standard deviation as a "
            "well-founded ordering of who is uncertain, not as a distribution to read a "
            "probability off.",
        ),
        (
            "The component chain is fitted on this season alone",
            "M1-M8 read the current season's per-gameweek rows, so early in a season every rate is "
            "mostly its position prior. That is why the run falls back to `xp_v0` below "
            "`forecast.published.cold_start_minimum_gameweeks`, and why the first weeks after that "
            "threshold are the thinnest evidence this model ever runs on.",
        ),
    ],
    XP_V0: [
        (
            "No minutes model with measured calibration",
            "Expected minutes come from last season's start rate shrunk toward a price-tier prior "
            "(D-02, D-12). Rotation risk and injury returns are mispriced. `xp_v1`'s M1 is the "
            "model that fixes this, and it is what the pipeline publishes once the season has "
            "enough history to fit it.",
        ),
        (
            "Preseason status flags say almost nothing",
            "Nearly every player is flagged available in preseason, so the availability haircut "
            "does very little work. Real injury and rotation news must come from the human review "
            "gate.",
        ),
        (
            "Fixture difficulty is FPL's own rating",
            "Team strength_attack and strength_defence are all zero in preseason, so the fixture's "
            "own 1-5 difficulty is the only signal available (D-05). `xp_v1` replaces it with a "
            "fitted attack/defence model.",
        ),
        (
            "Uncertainty is a heuristic band, not a modelled variance",
            "A coefficient of variation by confidence tier (D-09). It is deliberately wide, and it "
            "is not a distribution you should compute a probability from. `xp_v1` models the "
            "variance instead.",
        ),
    ],
}


def known_weaknesses(model: str, *, backtested: bool) -> list[Weakness]:
    """The weaknesses that are actually true of this card's model, headline first."""
    headline = BACKTESTED_WEAKNESS if backtested else COLD_START_WEAKNESS
    return [headline, *WEAKNESSES_BY_MODEL.get(model, []), *SHARED_WEAKNESSES]


def write_model_card(
    path: Path,
    *,
    forecast: pd.DataFrame,
    regression: PriceRegression,
    config: ForecastConfig,
    rules: GameRules,
    run_id: str,
    model: str,
    fallback_reason: str | None = None,
    backtest: Mapping[str, object] | None = None,
    component_description: Mapping[str, object] | None = None,
) -> Path:
    """Describe ``model``, which is the model that produced ``forecast``.

    ``model`` is a required argument rather than something worked out here: the card's whole job is
    provenance, and provenance that is deduced is provenance that can be wrong.
    """
    lines: list[str] = []
    add = lines.append

    add(f"# Model card — {MODEL_TITLES.get(model, model)}")
    add("")
    add(f"**Run:** `{run_id}` · **Season:** {rules.season} · **Players scored:** {len(forecast)}")
    add(
        f"**Next gameweek:** {as_int(forecast['next_gameweek'].iloc[0])} · "
        f"**Horizon:** {as_int(forecast['horizon_gameweeks'].iloc[0])} gameweeks"
    )
    add("")
    add(_published_statement(model, config.published.default_since, fallback_reason))
    add("")
    add("## The guardrail this card does not lift")
    add("")
    add(DL21_GUARDRAIL)
    add("")
    # The backtest harness only ever grades xp_v1 (`stages/backtest.py` fits a single
    # `ComponentPredictor`), so a `backtest.json` on disk is never evidence about xp_v0. Showing it
    # under an xp_0 card's "This forecast" row would be the exact D-25 mismatch this card exists to
    # prevent — the numbers on the card would belong to a different model than the one that ran.
    graded_this_model = model == XP_V1 and backtest is not None
    if graded_this_model:
        assert backtest is not None
        add("## Measured accuracy")
        add("")
        # The card is what a human actually reads before a deadline. A backtest finding that lives
        # only in backtest.json is a finding nobody sees at the moment it matters (DL-21).
        add(str(backtest.get("verdict", "")))
        add("")
        graded = backtest.get("model") or {}
        b0 = backtest.get("b0") or {}
        free = backtest.get("model_free") or {}
        if isinstance(graded, Mapping) and isinstance(b0, Mapping) and isinstance(free, Mapping):
            add("| Model | MAE | Spearman | Top-20 precision |")
            add("| --- | --- | --- | --- |")
            rows: list[tuple[str, Mapping[str, object]]] = [
                ("This forecast", graded),
                ("B0 — price + position", b0),
                ("Model-free — trailing 6", free),
            ]
            # E10-S5. The shadow monolith sits in the same table as the baselines rather than in a
            # footnote, because DP-10's trade is only decided honestly if the reader sees the
            # number at the same moment they see the model's own.
            monolith = backtest.get("monolith")
            if isinstance(monolith, Mapping):
                rows.append(("Monolith — shadow benchmark, never published", monolith))
            # Read the precision column as "of the twenty players ranked highest in a gameweek,
            # this share were genuinely in that gameweek's top twenty". Until E10-S2 it was pooled
            # across every gameweek at once, where it is 0.00 for any model and says nothing about
            # this one (DL-49) — so a card produced before that change is not comparable here.
            for label, metrics in rows:
                add(
                    f"| {label} | {metrics.get('mae')} | {metrics.get('spearman')} | "
                    f"{metrics.get('top_n_precision')} |"
                )
            add("")
            for line in _explainability_lines(backtest):
                add(line)
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
    for line in _what_this_model_is(model):
        add(line)
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
    # The tiers are the same four in both models, but they count different minutes: xp_v1 knows
    # only this season, xp_v0 knows only previous ones. Saying which is what stops "low" being read
    # as the same statement about the same player in September as it was in July.
    evidence = (
        "minutes played this season" if model == XP_V1 else "recency-weighted prior-season minutes"
    )
    add(f"Evidence is measured in **{evidence}**.")
    add("")
    add("| Confidence tier | Players | Meaning |")
    add("| --- | --- | --- |")
    meanings = {
        "high": f"at least {config.confidence_minutes_high} minutes of evidence",
        "medium": f"at least {config.confidence_minutes_medium} minutes",
        "low": "some evidence, but little",
        "none": "none at all — new signing, promoted club or yet to feature; pure prior",
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

    if component_description:
        add("## Component internals")
        add("")
        add(
            "What each component actually learned this run — not the tunable it was configured "
            "with, but the value fitting produced (DP-09). A tunable can be wrong twice: once if "
            "it is a bad choice, and once if the fit it was supposed to enable never touched it."
        )
        add("")
        add("| Component | Value |")
        add("| --- | --- |")
        for key, learned in _flatten(dict(component_description)):
            add(f"| `{key}` | {learned} |")
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
    for title, detail in known_weaknesses(model, backtested=graded_this_model):
        add(f"- **{title}.** {detail}")
    add("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _explainability_lines(backtest: Mapping[str, object]) -> list[str]:
    """What the chain's interpretability costs, in the card a human reads before a deadline.

    [DP-10](../../../docs/DESIGN-PRINCIPLES.md) requires that a materially better monolith makes
    the interpretability trade a *recorded decision* rather than an assumption. A number that lives
    only in `backtest.json` is not a decision anybody is making — it is a field nobody opens — so
    the sentence the harness writes is reproduced here verbatim rather than reworded, because two
    wordings of one finding is two chances to word one of them reassuringly (E10-S5, DL-53).

    Absent for a card produced before E10-S5, and absent is printed as nothing rather than as a
    zero gap: "not measured" and "no cost" are opposite claims.
    """
    gap = backtest.get("explainability_gap")
    if not isinstance(gap, Mapping):
        return []
    statement = gap.get("statement")
    if not isinstance(statement, str) or not statement:
        return []
    return [statement, ""]


def _published_statement(model: str, since: dt.date, fallback_reason: str | None) -> str:
    """Which model produced these numbers, and since when.

    Stated in one sentence at the top because the single most expensive thing a reader of this file
    can get wrong is believing it describes a different model than it does (DL-46).
    """
    if fallback_reason is None:
        return (
            f"**Published model: `{model}`**, the pipeline's default publish target since "
            f"{since.day} {since:%B %Y} (DL-46). This is the model the walk-forward backtest "
            "grades, and the ranking the app shows is produced by it."
        )
    return (
        f"**Published model: `{model}` — the cold-start fallback (DP-15).** `{XP_V1}` has been the "
        f"default publish target since {since.day} {since:%B %Y} (DL-46), and it did not run "
        f"this time: {fallback_reason}. Everything below describes `{model}`, which is *not* "
        "the model the "
        "backtest grades. Treat it accordingly."
    )


def _what_this_model_is(model: str) -> Sequence[str]:
    """The method, in the terms the model actually works in."""
    if model == XP_V1:
        return [
            "A chain of fitted components, each estimating one thing and combined through the "
            "rules module. Nothing here is a hand-set multiplier: every rate is estimated from "
            "this season's per-gameweek rows and shrunk toward its position prior by how much "
            "evidence stands behind it.",
            "",
            "- **M1 — minutes.** P(no appearance), P(1-59), P(60+), fitted per position and "
            "recent-appearance band, with the availability flag applied afterwards as news rather "
            "than folded into history.",
            "- **M2 — team strength.** Multiplicative attack and defence ratings with a home "
            "advantage, time-decayed. They set each fixture's expected goals, and through a "
            "Poisson on that, the clean-sheet probability.",
            "- **M3-M7 — per-90 rates.** Goals, assists, Defensive Contribution, saves and cards, "
            "each shrunk toward its position prior. Goal involvement is observed through expected "
            "goals where that is enabled (DL-34).",
            "- **M8 — bonus.** Expected bonus from expected BPS, structural rather than trained.",
            "",
            "The total is a **mixture over the minutes states**, which is where the variance comes "
            "from: a player with a real chance of not appearing carries a large probability mass "
            "at exactly zero, and that dominates any amount of scoring noise (Invariant 6).",
            "",
            "Each gameweek of the horizon is scored against *that gameweek's* fixtures, from the "
            "published calendar: a blank scores nothing and a double scores twice.",
        ]
    return [
        "Preseason has no current-season data, so there is nothing to fit. This is entirely a "
        "prior-construction exercise: take what a player did last season, decide how much of it "
        "to believe, adjust for who they are playing and whether they will play at all, and "
        "convert to points using the rules module.",
        "",
        "Signal stack, in descending weight:",
        "",
        "1. Prior-season per-90 rates — goals, assists, clean sheets, saves, cards, bonus.",
        "2. Per-90 Defensive Contribution, from 2025/26 only.",
        "3. FPL's own price, as a market-implied prior, via the group that thin samples shrink to.",
        "4. Position-and-price-tier baselines for players with no top-flight history.",
        "5. An availability haircut from the FPL status flag.",
        "6. Fixture difficulty across the horizon.",
    ]


def _flatten(value: object, prefix: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        out: list[tuple[str, object]] = []
        for key, item in value.items():
            out.extend(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return [(prefix, value)]
