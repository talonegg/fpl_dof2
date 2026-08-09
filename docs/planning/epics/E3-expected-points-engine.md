# E3 — Expected Points Engine

**Objective:** OBJ-1, OBJ-7 · **Target:** ~GW10 · **Estimate:** 7–10 days
**Depends on:** E2 (history, quality) · **Repays debt:** D-01, D-02, D-05, D-09

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

- [ ] Backtest harness runs walk-forward with no look-ahead, proven by the leakage audit
- [ ] **B0 baseline built, and every tier-2 metric reported relative to it**
- [ ] Tier-2 thresholds met — **or consciously recalibrated with evidence and a decision-log entry**
- [ ] Model beats the **model-free** benchmark, or that finding is stated plainly and acted on
- [ ] All eight component models registered with both aggregator and explanation decomposition
- [ ] Model cards for each component: inputs, method, measured accuracy, known failure modes
- [ ] Per-component training windows honour the scoring-regime table in [E2-S3](E2-data-platform.md) —
      M4 on 25/26 only unless Q-13 succeeded, M8 structural rather than learned from historical bonus
- [ ] D-01, D-02, D-05, D-09 and D-12 closed in the E0 debt register

## 4. The honest question

**"Does this beat doing something simple?"** If after E3 the answer is no, that is a finding to act
on, not a bug to tune away — and the right response is to trust the tool less and your own judgement
more, while keeping the scout UI, which has standalone value regardless.

B0 and the model-free benchmark exist so that this question has an *answer* rather than an
impression. A project like this one fails most often not by building a bad model but by never
constructing the comparison that would have revealed it.
