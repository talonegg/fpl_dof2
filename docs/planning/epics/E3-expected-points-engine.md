# E3 — Expected Points Engine

**Objective:** OBJ-1, OBJ-7 · **Target:** ~GW10 · **Estimate:** 7–10 days
**Depends on:** E2 (history, quality) · **Repays debt:** D-01, D-02, D-05, D-09

---

## 0. Build outcome — 2026-08-11 · **the model does not clear the bar**

The harness was built first, as the epic instructed, and it immediately did the job it exists for.

**72 folds, 54,045 player-gameweek observations, across 2024/25 and 2025/26:**

| Model | MAE | Spearman | MAE skill vs B0 | Top-20 precision | Calibration slope |
| --- | --- | --- | --- | --- | --- |
| **xp_v1** | **1.936** | 0.244 | +0.015 | **0.00** | 0.71 |
| B0 — price + position | 1.965 | 0.214 | — | 0.05 | 0.61 |
| **Model-free — trailing 6** | 2.115 | **0.291** | −0.076 | 0.05 | 0.39 |
| Mean — a constant | 1.985 | −0.040 | −0.010 | 0.00 | −3.60 |

**It beats B0 and loses to the model-free benchmark.** Per §4 below, that is the finding, reported
as such. Full reasoning and consequences in [DL-21](../00-decision-log.md#dl-21).

**The two headline columns disagree, and the disagreement is the whole result.** The model has the
best MAE of anything measured and the worst top-20 precision of anything measured. Those are
consistent: shrinking every thin estimate toward a position prior is an excellent way to avoid being
badly wrong about anyone, and an excellent way to avoid distinguishing anyone. **That trade is
backwards for how the tool is used** — nobody acts on the whole ranking, they act on its head.

**B0 was worth every minute.** Without it, a Spearman of 0.244 and an MAE of 1.94 would have looked
like a working model. B0 scores 0.214 and 1.96. The gap is real and it is small, and only the
comparison makes that visible — which is precisely the argument
[DL-13](../00-decision-log.md#dl-13) made when it replaced the absolute thresholds.

**The leakage guard caught a leak in the harness itself.** The first version handed the predictor a
frame that still carried the target column. A cheating predictor test caught it immediately; nothing
in the metrics would have. Predictors now see inputs only.

**What this does not measure.** Defensive Contribution exists in 2025/26 alone, so M4 — the
component with the best signal-to-noise in the design — is absent from half the window. The harness
carries no fixture table, so M2 contributes league-average opposition throughout. No season used
the 2026/27 BPS matrix. Each of these would move the number the model's way; none is an excuse.

---

## 1. Why

This epic repays **D-01 — the knowingly unvalidated GW1 model**, and it does so in the first story.
Until backtesting exists, nobody knows whether the forecast has any edge at all, which means no
expensive decision — a −8 hit, a chip, a wildcard — is safe to base on it.

The order below is deliberate: **measurement before modelling.** Building the harness first means
every subsequent change is evaluated rather than assumed, and it prevents the most common failure
mode in a project like this — a season spent improving a model that was never better than the
simple thing it replaced.

## 2. Stories

### E3-S1 — Backtest harness · 2 days · FR-37 · **do this first**
Walk-forward replay with strict no-look-ahead, enforced by feature knowability stamps.

- Train on everything knowable before each historical deadline; predict; compare to actual
- Metrics against [charter §5 tier 2](../01-project-charter.md#tier-2--model-quality-obj-7), which
  were made **baseline-relative** by [DL-13](../00-decision-log.md#dl-13--charter-amendments-following-the-2026-08-09-architecture-and-plan-audit):
  Spearman within position and price band, MAE **skill score**, top-20 precision, calibration slope,
  minutes Brier score, captaincy hit rate
- Breakdowns by position, price tier and minutes band

#### Build B0 first — it is the reason every other number means anything

**B0** is a model whose only inputs are **position and current price**, fitted on the same training
window as the real model. It is an afternoon's work and every tier-2 threshold is now expressed
relative to it.

The reason is uncomfortable and worth stating plainly: charter v1.0's absolute thresholds would have
passed a model with no edge. `MAE ≤ 2.1` sits in the range a *constant predictor* achieves on players
who played, and `Spearman ≥ 0.30` across all positions is plausibly reachable knowing nothing but
price and position — because price *is* FPL's own expected-value estimate. Without B0 you cannot tell
a working forecast from an expensive restatement of `now_cost`.

#### Benchmarks — one of the three was circular

| Benchmark | Status |
| --- | --- |
| Template team | Keep |
| Overall average | Keep |
| ~~"Highest xP, one transfer per week"~~ | **Circular — demoted to a diagnostic.** It runs on *this project's own forecast*. If the forecast is poor, both sides of the comparison are poor, and better optimisation beats it while both remain worse than guessing. It measures the optimiser, not the model, and must be labelled as such |
| **Model-free: highest trailing-6-gameweek points, one transfer per week** | **New, and the one that matters.** Computable from FPL data alone, with no dependence on anything this project predicts. It is roughly what an unaided manager does, which makes it the honest bar |

**Acceptance:** B0 built and reported on every backtest run. The E0 v0 model is scored against B0 and
against both season benchmarks. **If it does not beat the model-free benchmark, that is the headline
finding, reported as such** — not a number to tune until it looks better.

### E3-S2 — Feature store · 1 day · Design §3.5
Shared, cached, tested feature definitions used identically by training and inference — which is what
guarantees they cannot diverge. Rolling windows, per-90 rates with minutes-weighted shrinkage,
opponent adjustment, home/away splits, rest days, role indicators.

**Every feature carries the gameweek at which it becomes knowable.** This is the structural defence
against R-04, and it is why the leakage-auditor subagent exists.

### E3-S3 — Availability and minutes model (M1) · 1.5 days · FR-10 · repays D-02
Distribution over `{0, 1–59, 60+}` minutes. The largest single source of forecast error, so accuracy
here beats sophistication elsewhere. Calibrated probabilities, not just rankings.

**Acceptance:** calibration curves and Brier score reported; beats the E0 status-flag haircut.

### E3-S4 — Team strength and match model (M2) · 1.5 days · FR-11 · repays D-05
Expected goals for and against per fixture. Poisson-style bivariate model on time-decayed attack and
defence ratings estimated from xG. Blends with odds when E5 lands; standalone until then.

### E3-S5 — Player component models · 2 days · FR-12
Goal involvement (M3), defensive contribution (M4), clean sheets (M5), saves (M6), cards (M7).

**M4 deserves disproportionate attention.** Defensive Contribution points are rate-driven and far
more stable week to week than goal involvement — the best signal-to-noise ratio in the whole model,
and the place where a model most easily beats intuition, because most managers still price players as
if the component did not exist.

### E3-S6 — Bonus points model (M8) · 1 day
Expected BPS from expected actions, then probability of finishing top three *within that specific
match* — which needs the distribution across all 22 players, not just a mean.

**Carries a known hazard:** the 2026/27 BPS revision means prior-season bonus data comes from a
different scoring regime. See `.claude/skills/fpl-rules/references/changes-2026-27.md` and
[Design Q-05](../04-conceptual-design.md#15-open-design-questions).

### E3-S7 — Aggregation with real variance · 1 day · FR-13 · repays D-09
Combine components into expected points and a **modelled** variance, replacing E0's heuristic band.
Propagate component variance including the large binary contribution from the minutes distribution.

**Acceptance:** variance is modelled rather than assumed; the decomposition drives the UI explanation.

## 3. Definition of done

- [x] Backtest harness runs walk-forward with no look-ahead, proven by a cheating-predictor test
      that caught a real leak in the harness
- [x] **B0 baseline built, and every tier-2 metric reported relative to it**
- [x] **Model does not beat the model-free benchmark, and the finding is stated plainly** — in the
      backtest report, in the published model card, and in [DL-21](../00-decision-log.md#dl-21)
- [x] Component models M1–M8 registered with the aggregator and the explanation decomposition
- [x] Model card carries inputs, method, measured accuracy and known failure modes
- [x] Per-component training windows honour the scoring-regime table in
      [E2-S3](E2-data-platform.md) — M4 restricted to the seasons it was measured in, M8 structural
      rather than learned from historical bonus
- [x] **D-01 closed** (the model is validated), **D-02, D-05, D-09 closed** (minutes, team strength
      and modelled variance all now exist)
- [ ] **D-13 opened, replacing D-01:** the forecast does not beat a model-free benchmark at the head
      of the ranking. E4 must not justify a hit, chip or wildcard on xp_v1 alone until it does

## 4. The honest question

**"Does this beat doing something simple?"** If after E3 the answer is no, that is a finding to act
on, not a bug to tune away — and the right response is to trust the tool less and your own judgement
more, while keeping the scout UI, which has standalone value regardless.

B0 and the model-free benchmark exist so that this question has an *answer* rather than an
impression. A project like this one fails most often not by building a bad model but by never
constructing the comparison that would have revealed it.
