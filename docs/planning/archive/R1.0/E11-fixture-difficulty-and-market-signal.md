# E11 — Fixture Difficulty and Market Signal

**Objective:** OBJ-1 · **Target:** after E9 · **Estimate:** 5–7 days
**Depends on:** E9-S2 (fixtures in the backtest), E5 (odds adapter scaffolding)
**Implements:** [Model Improvement Plan §4 F1–F5, §3 D3](../05-model-improvement-plan.md) ·
**Closes:** OD-03
**Status:** Built and measured where measurable (S1–S6 all shipped, dark, behind
`discrimination.*` flags per DP-08); every candidate save S2 is blocked on the E8 §5 bar's six
live shadow gameweeks, which cannot exist before GW1. See DL-55 through DL-60.

---

## 0. The prerequisite that gates this whole epic

Fixture difficulty is half of what a manager plans around, and today the model is nearly blind to it.
M2 is a multiplicative `league_mean × attack(team) × defence(opponent) × home_advantage` model fitted
from **goals**; in preseason every rating is the neutral 1.0, so the live path falls back to FPL's
static 1–5 FDR. Its xG variant (`team_strength_from_xg`) is built but **dark**.

~~**None of this is measurable until [E9-S2](E9-forecast-delivery-and-backtest-fidelity.md) puts
fixtures into the backtest.** With league-average opposition, M2's attack/defence ratings never enter
a scored prediction. **No story in this epic may start until E9-S2's definition of done holds.**~~
**Gate cleared.** [E9-S2](E9-forecast-delivery-and-backtest-fidelity.md) joins each fold row's real
opponent and venue from the published calendar, scores it through `fixture_opposition`, and reports
Spearman and calibration split by fixture-difficulty band. Every "Backtest: …" gate below is now a
sentence that can be evaluated. Note the two things it does *not* say: the fixture-band numbers from
E9-S2 are a **baseline to beat, not a pass**, and no run predating it is comparable on this axis.

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

- [~] **xG-based team ratings** — built, wired, measured (DL-56): fixture-band Spearman and
      calibration both beat the goals-based path on the walk-forward backtest. **Not promoted**:
      `team_strength_from_xg` stays `false`, held for the E8 §5 shadow window. Goals-based path is
      the default and remains the fallback.
- [x] **Home advantage is fitted, config-seeded, reported in the model card** (DL-55): shipped
      un-flagged, as an Invariant-2/DP-06 correctness fix rather than a new model behaviour — the
      literal `1.12` is gone. The one honest caveat: the fixture-aware backtest found the fitted
      ~1.093 and the old 1.12 statistically indistinguishable on this window, so the "calibration
      improves" half of the story's acceptance criterion is not demonstrated, only the provenance
      half is.
- [~] **Player rates are opponent-adjusted** (DL-58): built and measured, on a simplification of
      Design §M3's share-based model (no cross-player allocation pass — recorded as a real gap,
      not hidden). Both named fixture-difficulty buckets improve on Spearman; the aggregate
      "average" fixture-band figure moved the wrong way for reasons the entry could not fully
      explain. `opponent_adjusted_rates` stays `false`, held for the shadow window.
- [~] **Promoted-club priors widened** (DL-57): the *mechanism* is built, tested and measured
      (general shrinkage only, `promoted_teams` empty in every shipped path). **Cannot be
      completed as specified**: detecting a promoted club needs a club identity that survives the
      season boundary, which the current silver model does not carry (the `team_code` gap DL-54
      already flagged). Not a same-epic fix.
- [x] **Odds adapter live within a credit budget, degrading cleanly** — **OD-03 closed** (DL-59):
      enabled by default everywhere (not CI-only), `ODDS_API_KEY` wired into `ingest-slow.yml`,
      verified locally to degrade to zero network calls with no key. The one thing outside this
      codebase's control: the key itself is an owner action (INPUTS-REQUIRED.md 4.1, ~GW10).
- [~] **Market view blended into M2, horizon-dependent, degrades cleanly** (DL-60): the *blend
      mechanism* (`TeamStrengthModel.attach_market`/`blended_expected_goals`, the horizon-decay
      weight function) is built and fully tested. **Not wired into a live scoring path**: no
      caller attaches `team_match_expectation` or threads a horizon-dependent weight through yet —
      a deliberate scope decision (see DL-60), since there is also no way to backtest this
      candidate at all (no historical odds archive exists to walk-forward against).
- [x] Every backtestable change (S1, S3, S4's general half) was graded on the fixture-aware
      backtest from E9-S2, per position and per fixture band — S2 also measured this way despite
      not needing the DP-08 shadow treatment; S6 could not be, structurally (DL-60).
- [ ] **No promoted change has cleared the E8 §5 bar.** None can, before GW1: the bar requires six
      live shadow gameweeks, which do not exist yet. Every candidate above is flagged off in the
      shipped configuration for exactly this reason. This line will not tick until real gameweeks
      have been played with each flag shadowed.

## 3. The honest question

**"Does the fixture ticker now tell me something FPL's own FDR does not?"** The published fixture grid
(`fixtures.json`, DL-37) is only worth more than the static 1–5 FDR if these ratings carry real,
tested signal. If after this epic the grid still tracks FDR, the epic added colour, not information —
and the model card must say so.

**Current answer: not yet, in the shipped default.** The backtest evidence says the ingredients for
"yes" exist — xG-based ratings and opponent-adjusted rates both measurably beat the fixture-blind
chain (DL-56, DL-58) — but every flag capable of changing the grid's arithmetic is off in the
shipped configuration, held there by the E8 §5 bar rather than by any doubt in the backtest. The
grid today is exactly what it was before this epic. It becomes a genuinely different claim only once
a live shadow window lets one of these candidates clear the bar and its default actually flips.
