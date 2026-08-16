# E11 — Fixture Difficulty and Market Signal

**Objective:** OBJ-1 · **Target:** after E9 · **Estimate:** 5–7 days
**Depends on:** E9-S2 (fixtures in the backtest), E5 (odds adapter scaffolding)
**Implements:** [Model Improvement Plan §4 F1–F5, §3 D3](../05-model-improvement-plan.md) ·
**Closes:** OD-03
**Status:** Planned

---

## 0. The prerequisite that gates this whole epic

Fixture difficulty is half of what a manager plans around, and today the model is nearly blind to it.
M2 is a multiplicative `league_mean × attack(team) × defence(opponent) × home_advantage` model fitted
from **goals**; in preseason every rating is the neutral 1.0, so the live path falls back to FPL's
static 1–5 FDR. Its xG variant (`team_strength_from_xg`) is built but **dark**.

**None of this is measurable until [E9-S2](E9-forecast-delivery-and-backtest-fidelity.md) puts
fixtures into the backtest.** With league-average opposition, M2's attack/defence ratings never enter
a scored prediction. **No story in this epic may start until E9-S2's definition of done holds.** This
is the restated §4.0 prerequisite from the improvement plan, made a hard gate.

## 1. Stories

### E11-S1 — Promote xG-based team ratings · 1.5 days · FR-11 · promotes `team_strength_from_xg`
xG regresses far less than goals, so ratings built from it are more stable — most sharply in the early
season a manager plans hardest around. The flag exists and is dark; this story earns its promotion.

- Ships dark then promoted (DP-08): compared against the goals-based ratings on the fixture-aware
  backtest before it becomes the default.

**Acceptance:** fixture-conditioned Spearman and clean-sheet calibration beat the goals-based ratings
on a held-out season.

### E11-S2 — Empirical home advantage · 0.5 day · FR-11
Replace the single `1.12` constant with a fitted value. Home advantage is measurable and has drifted
post-2020; one constant is a guess where a fitted value is cheap.

- **Invariant 2 applies** — the fitted value is config seeded from the fit, not a literal in code.

**Acceptance:** clean-sheet and goals calibration improve; the fitted value is reported in the model
card (DP-09).

### E11-S3 — Opponent-adjusted player rates · 2 days · FR-11, FR-12 · Design §M3
Today a player's own rate is multiplied by a blunt fixture multiplier at the horizon scorer. The
design-of-record instead *shares out* the team's expected goals (from M2) across its players — sharper,
and it is what makes a differential in a good fixture actually visible in the ranking.

**Acceptance:** within-position Spearman improves specifically in **high- and low-difficulty
fixtures** — the buckets where fixture information is supposed to do its work.

### E11-S4 — Widened priors for promoted / heavily rebuilt clubs · 1 day · FR-11
A promoted side's September is weak evidence about their April; the half-life decay handles recency
but not the structural uncertainty of a new squad. Widen the prior for these clubs specifically.

**Acceptance:** August/September fixture calibration for promoted clubs improves **without harming the
rest** — a gain that degrades the established clubs is not a gain.

### E11-S5 — Odds adapter live · 1 day · OD-03, [D3] · needs `ODDS_API_KEY` secret
Bring the E5 odds adapter into live operation: de-vigged, credit-budgeted, cached hard. The single
most accurate near-term fixture signal, and the prerequisite for the market blend in S6.

- `ODDS_API_KEY` is an Actions **secret** (Invariant 10 — never in the repo, never in the client
  bundle). Free tier ~500 req/month; `FPL_DOF_ODDS_CREDIT_BUDGET` enforced in the adapter.
- **This closes OD-03** (odds provider + credit budget) once the provider is chosen.

**Acceptance:** the adapter fetches within budget in CI; a run with the key absent degrades cleanly to
the ratings-only path (DP-15), never fails.

### E11-S6 — Blend the market view of M2 · 1.5 days · FR-11 · Design §M2
Blend odds-implied, de-vigged team goal expectations into M2. **Blend weight is a function of
horizon** — the near gameweek defers to the market, the distant horizon to the ratings.

**Acceptance:** near-horizon clean-sheet and goals calibration improve when the market view is
blended, and the blend **degrades cleanly to S1's ratings** when the credit budget is exhausted
(DP-15). Both halves are required — an improvement that breaks when the budget runs out is not shippable.

## 2. Definition of done

- [ ] xG-based team ratings promoted on backtest evidence; goals-based path retained as fallback
- [ ] Home advantage is a fitted, config-seeded value reported in the model card
- [ ] Player rates are opponent-adjusted by sharing out M2 team xG, improving high/low-difficulty buckets
- [ ] Promoted-club priors widened without harming established clubs
- [ ] Odds adapter live within a credit budget, degrading cleanly when the key or budget is absent —
      **OD-03 closed**
- [ ] Market view blended into M2 with a horizon-dependent weight, degrading cleanly to ratings-only
- [ ] Every change graded on the **fixture-aware** backtest from E9-S2, per position and per fixture band
- [ ] Each promoted change cleared the [E8 §5 bar](E8-in-season-operations.md#5-the-bar-for-changing-the-model-mid-season)

## 3. The honest question

**"Does the fixture ticker now tell me something FPL's own FDR does not?"** The published fixture grid
(`fixtures.json`, DL-37) is only worth more than the static 1–5 FDR if these ratings carry real,
tested signal. If after this epic the grid still tracks FDR, the epic added colour, not information —
and the model card must say so.
