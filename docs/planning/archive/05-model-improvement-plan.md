# 05 — Model Improvement Plan

**Status:** Proposed · **Date:** 2026-08-16 · **Author:** research pass against the shipped
implementation and the first backtest results.

This document is a **research-grounded improvement programme**, not a new epic. It reads the code as
built and the numbers it produced, states where the forecast is weak and *why*, and lays out a
prioritised, falsifiable set of changes for the two things the season is judged on: **pre-GW1 squad
construction** and **post-GW1 weekly recommendations**. Every proposal here is an experiment with a
promotion gate, routed through the discipline already written down in
[E8 §5](epics/E8-in-season-operations.md#5-the-bar-for-changing-the-model-mid-season) and
[DP-08 / DP-12](../DESIGN-PRINCIPLES.md). Nothing here is promoted by argument; it is promoted by a
backtest, or it is not promoted.

It also records the design for a long-standing loose end the owner raised: **FPL team and league IDs
must be enterable through the UI and never persisted in the repository** — §6, decided in
[DL-44](00-decision-log.md#dl-44).

---

## 1. What the results actually say

The first walk-forward backtest ([DL-21](00-decision-log.md#dl-21), 72 deadlines / 54,045
observations across 2024/25–2025/26) is the ground truth this plan is built on.

| Model | MAE | Spearman | Top-20 precision | Calibration slope |
| --- | --- | --- | --- | --- |
| **xp_v1** (components) | **1.927** | 0.231 | **0.00** | 0.70 |
| B0 — price + position | 1.965 | 0.214 | 0.05 | 0.61 |
| **Model-free — trailing 6** | 2.115 | **0.291** | 0.05 | 0.39 |
| Mean — a constant | 1.985 | −0.040 | 0.00 | −3.60 |

Four facts drive everything below, in order of leverage.

**1. The model that is *graded* is not the model that is *shipped*.** The backtest grades `xp_v1`
(the component chain). The pipeline publishes `xp_v0` (the cold-start model), which consumes none of
the xG signal DL-34 measured and promoted. The gap between them is [D-25](epics/E0-steel-thread-gw1.md#6-technical-debt-register)
— a fixture-aware horizon scorer `xp_v1` does not yet have. **Until D-25 closes, every improvement
in this document is measured and never delivered.** This is the highest-leverage item in the plan and
it is not a modelling change; it is one wiring seam.

**2. The model is best at avoiding error and worst at making distinctions — backwards for the tool.**
`xp_v1` has the best MAE and the *worst top-20 precision* of anything measured. Shrinking every thin
estimate toward a position prior avoids being badly wrong about anyone and avoids distinguishing
anyone; the 0.70 calibration slope says predictions are compressed. Nobody acts on the whole ranking
— they act on its head — and at the head the model adds nothing over price. **The target metric is
top-20 precision and captaincy separation, not MAE.** MAE is already the best in the table and is
measuring the wrong thing.

**3. The backtest is blind to fixtures, which is half of what a manager plans around.** The harness
carries no fixture table, so M2 contributes *league-average opposition* to every prediction. Fixture
difficulty — the entire subject of §4 below — is a live input that is **currently untestable**.
No fixture-difficulty change can be evaluated until the harness carries fixtures. This makes
"fixtures into the backtest" a prerequisite, not an improvement (§4.0).

**4. Two positions are essentially unranked.** Spearman by position: FWD 0.27, MID 0.27, DEF 0.16,
**GKP 0.04**. Goalkeepers are near-random, and defenders are weak. Any honest improvement measures
itself *per position*, because a gain concentrated in forwards leaves the two hardest positions where
they are.

---

## 2. The improvement thesis, in one sentence

**Deliver the model we already have (close D-25), then spend every subsequent change on discrimination
at the head of the ranking and on the two probabilistic quantities the whole forecast rests on —
minutes and fixture difficulty — measuring each per position against a backtest that can finally see
fixtures.**

Everything in §3–§5 is a specialisation of that sentence.

---

## 3. Data collection

The forecast is **signal-starved**, not under-modelled. The official feed's own `expected_goals` /
`expected_assists` are the only advanced signals reaching the model; every scraped or purchased source
is blocked ([D-23](epics/E0-steel-thread-gw1.md#6-technical-debt-register): Understat `robots.txt`
disallows the site, FBref returns Cloudflare 403; no `ODDS_API_KEY`). Defensive Contribution — the
best signal-to-noise component in the design — exists for one season only.

| # | Change | Why it is worth it | Cost / blocker | Gate |
| --- | --- | --- | --- | --- |
| **D1** | **Fixtures into the backtest fold frames** | Prerequisite for the entire fixture axis (§4); without it M2 is untestable | Data plumbing only — join historical opponent + home/away into `fold_rows`, already in silver | Not a model change; ships when the harness reports non-degenerate `spearman` under real opposition |
| **D2** | **Reconstruct DefCon history from BPS action counts (Q-13)** | Widens M4's training window from one season to several; M4 is absent from ~half the current window (DL-21 caveat) | FPL recorded tackles/CBI in the BPS breakdown long before scoring DefCon — no new source | Backtest: DEF and DM Spearman improves with M4 present across the window |
| **D3** | **Odds adapter live (E5-S4)** | The single most accurate near-term fixture signal; unblocks the market view of M2 (§4.2) | `ODDS_API_KEY` as an Actions **secret** (free tier ~500 req/mo; credit budget already enforced in-adapter) | Backtest: near-horizon clean-sheet and goals calibration improves when the market view is blended |
| **D4** | **Penalty and set-piece duty as a committed reference table** | Penalties are large, lumpy and highly identifiable points — a primary way the elite separate; currently unmodelled (Design §M3) | A small **committed config/reference file**, hand-maintained; not a data source, so no Invariant-1 or scraping question | Backtest: top-20 precision among attackers improves when duty is an explicit additive term |
| **D5** | **Re-measure the prior-season prior with real advanced history** | `features.prior_season` is built but dark; the [DL-31](00-decision-log.md#dl-31) probe moved Spearman ~0.001 — but it used official-feed *totals* as a stand-in, not xG/DefCon. D2 changes the input | Depends on D2 (and ideally an unblocked xG source) | Backtest, per DP-08: promoted only if it earns its place with real inputs |

**What is deliberately *not* pursued.** Re-attempting Understat/FBref scraping against an explicit
`robots.txt`/Cloudflare refusal (NFR-10, D-23) — the refusals are respected, not worked around. The
value those sources would add is re-tested only if a *polite, permitted* path appears; the official
feed's xG plus D2/D4 recover most of the modelling intent without them.

---

## 4. Fixture-difficulty modelling

Today: M2 is a multiplicative `league_mean × attack(team) × defence(opponent) × home_advantage`
model, fitted from **goals** (its xG variant `team_strength_from_xg` is built but dark). In preseason
every rating is the neutral 1.0, so the live path falls back to FPL's static 1–5 FDR via the
`fixture_difficulty` multipliers. The published fixture grid (`fixtures.json`, DL-37) is model-derived
and anchored on the ratio to the league mean — good — but it inherits M2's blindness in August.

### 4.0 Prerequisite — the backtest must carry fixtures (D1)

Restated because it gates this whole section: **no change in §4 was measurable until D1 landed.**
With league-average opposition, M2's attack/defence ratings never entered a scored prediction.
**D1 is delivered by [E9-S2](epics/E9-forecast-delivery-and-backtest-fidelity.md)**: fold frames
carry the fixture each observation was played under (stamped `AT_DEADLINE`, built from the calendar
rather than from who was picked), and the harness reports Spearman and calibration by
fixture-difficulty band. §4's gates are now evaluable.

| # | Change | Why | Gate |
| --- | --- | --- | --- |
| **F1** | **Promote xG-based team ratings** (`team_strength_from_xg = True`) | xG regresses far less than goals, so ratings are more stable — most sharply in the early season a manager plans hardest around | Backtest (post-D1): fixture-conditioned Spearman and clean-sheet calibration beat the goals-based ratings |
| **F2** | **Blend the market view of M2** (odds-implied team goal expectations, de-vigged) | Design-of-record §M2; the most accurate near-term signal. Blend weight is a function of horizon — near GW defers to market, distant to ratings | Backtest (needs D3): near-horizon calibration improves; degrades cleanly to F1 when the credit budget is exhausted (DP-15) |
| **F3** | **Widened priors for promoted / heavily rebuilt clubs** | A promoted side's September is weak evidence about their April; the half-life decay handles recency but not the structural uncertainty of a new squad | Backtest: August/September fixture calibration for promoted clubs improves without harming the rest |
| **F4** | **Opponent-adjusted player rates** (allocate M2 team xG across players, Design §M3) | Currently a player's own rate is multiplied by a blunt fixture multiplier at the horizon scorer; the design-of-record instead *shares out* the team's expected goals. Sharper, and it is what makes a differential in a good fixture visible | Backtest: within-position Spearman improves in high- and low-difficulty fixtures specifically |
| **F5** | **Empirical home advantage** in place of the single 1.12 constant | Home advantage is measurable and has drifted post-2020; one constant is a guess where a fitted value is cheap | Backtest: clean-sheet and goals calibration improve; report the fitted value in the model card |

---

## 5. xPts prediction — discrimination at the head

This is where the DL-21 finding bites, and where the season is won or lost. Every item here is aimed
at the **head of the ranking**, per fact 2.

| # | Change | Why | Gate |
| --- | --- | --- | --- |
| **X1** | **Close D-25: ship `xp_v1` to the live path** | The model the backtest grades must be the model the app publishes. Build the fixture-aware horizon scorer `xp_v1` lacks. **Highest leverage in the plan** | Live path publishes `xp_v1`; parity test that the horizon scorer reproduces the backtest's single-GW numbers under league-average opposition |
| **X2** | **Close D-14: measure minutes calibration, then improve M1** | Minutes are the largest single error source and their calibration is *unmeasured* (`minutes_brier` always null). Then add rotation/congestion, injury-return ramp, live chance-of-playing%, and European-rotation handling (Q-08) | Backtest: Brier score reported and beating the status-flag haircut (satisfies the E3-S3 acceptance never actually met, DL-22) |
| **X3** | **Reduce over-shrinkage at the head** | The 0.70 calibration slope says the top is compressed. Make shrinkage evidence-adaptive — shrink *less* for high-minutes, high-confidence players where signal exists — so the elite spread out instead of collapsing toward the position prior | Backtest: top-20 precision and calibration slope improve **without** MAE regressing so far it signals overfitting |
| **X4** | **Penalty / set-piece duty as an explicit additive term** (pairs with D4) | The lumpiest identifiable points; a primary separator of premiums the shrinkage erases | Backtest: top-20 precision among attackers improves |
| **X5** | **A goalkeeper-specific formulation** | GKP Spearman is 0.04 — a whole position essentially unranked. Model GKP xP primarily from opponent shot volume × team defence (M2) plus a saves model, rather than a shrunk per-90 that clean sheets dominate | Backtest: GKP Spearman moves off the floor |
| **X6** | **A blended monolith as a shadow benchmark (Q-04)** | A GBM on the same features is an *upper bound* on achievable accuracy. If the component chain's explainability (a product requirement, DP-10) costs a large gap at the head, that trade must be decided explicitly, not assumed | Shadow only; never promoted over the chain without an explicit DP-10 decision |

**Why not just adopt trailing form, which wins on Spearman.** Because "wins on rank correlation" is
not "is better to own" (DL-21): form has calibration slope 0.39 and the worst MAE — it is a momentum
signal that buys whoever just scored, at the top of the price rise. The conclusion is not "use form";
it is that `xp_v1` has not yet earned trust for expensive decisions, and X1–X5 are how it does.

---

## 6. Pre-GW1 versus post-GW1 — the two regimes need different levers

The improvements above are not uniform across the season. The single most important structural fact
is that **preseason has no current-season data**, so the two problems are genuinely different models.

### 6.1 Pre-GW1 — squad construction (cold start)

The model card's own diagnostic is encouraging on one axis and damning on the other: **R² of xP on
(price, position) is 0.466** — xP adds real information beyond price — yet **top-20 precision is 0.0**,
so the *ordering of the elite* is still no better than price. Everything rides on priors.

Priority levers, pre-GW1:

1. **D4/X4 — penalty and set-piece duty.** The cheapest large gain available before a ball is kicked,
   and it is pure prior knowledge.
2. **D5 — prior-season xG/DefCon prior, re-measured with real history (D2).** The right way to
   separate two similarly-priced players who both "look good" is what they actually did last season,
   position-relative.
3. **F3 — promoted-club priors.** August is when promoted clubs are most mispriced and most planned
   around.
4. **X2 — role certainty.** A nailed-on starter versus a rotation risk is the biggest pre-GW1 ranking
   error, and preseason status flags say almost nothing (model card, known weaknesses).
5. **Wide, honest uncertainty** — kept deliberately wide in GW1–4 (Design §5 cold start) so the
   optimiser makes no confident early decision it should not.

### 6.2 Post-GW1 — weekly recommendations

Current-season evidence arrives, and the model should **blend the preseason prior toward it in
proportion to how much evidence exists** (E8 §5: prefer shrinkage to refitting — it beats a fresh fit
on ten noisy gameweeks nearly every time).

Priority levers, post-GW1:

1. **X1 — the live `xp_v1` path** must exist, or none of the in-season signal reaches the app.
2. **F2 — odds-blended near-horizon fixtures.** The near GW is where the market view is most accurate
   and most decision-relevant.
3. **X2 — minutes with rotation/congestion.** In-season is where rotation and injury returns actually
   move, and where a calibrated M1 pays off week to week.
4. **M4 / DefCon.** The most stable week-to-week component (Design §M4) — its value is highest exactly
   in the weekly cadence, where stability is what a transfer decision needs.
5. **The DL-21 guardrail stands:** no −8 hit, chip or wildcard is justified by `xp_v1` alone until
   top-20 precision beats B0. E4's risk dial and chip planner inherit that constraint unchanged.

---

## 7. FPL team and league IDs — UI entry, never persisted (DL-44)

**The requirement.** The owner's FPL team ID and mini-league ID must be **enterable through the UI**
and **never persisted in the repository**. They are public identifiers (NFR-11), not secrets — but
they are personal, and hard-coding them in `config/local.yaml` (as the local scaffold currently does)
is both a persistence smell and a single-user assumption baked into the wrong layer.

**The constraint that shapes every option.** [Invariant 8](../../CLAUDE.md) — *the browser never calls
an external API*. The SPA reads published static artefacts and nothing else; it cannot fetch the
owner's picks or a league's standings itself, and the FPL API sends no permissive CORS headers even if
it were allowed to. So "enter the ID in the UI and see your data" cannot mean "the browser fetches it".

**The design (see DL-44 for the full reasoning and rejected alternatives):**

1. **Pipeline side — runtime variables, not committed config.** The pipeline reads
   `FPL_DOF_TEAM_ID` / `FPL_DOF_LEAGUE_ID` from **GitHub Actions repository variables** (public values,
   the correct home for a non-secret identifier) through the environment overrides that already exist
   on `EntryConfig`. `config/local.yaml` remains the *local-dev* path and is already gitignored.
   **Nothing about the owner's identity enters git.**

2. **Browser side — a Settings view backed by `localStorage`.** A new Settings screen lets the owner
   type their team ID and league ID; the values live in browser `localStorage` only — never
   transmitted, never committed. Because of Invariant 8 the setting does two invariant-clean things:

   - **Personalises already-published artefacts** — highlights the owner's row in the league table,
     badges "my squad", and filters the scout to owned players. It can only personalise what the
     pipeline already published; when the published league artefact was built for a different league
     than the one entered, the view says so plainly (DP-09/DP-15), consistent with DL-40's treatment
     of the absent league.
   - **Composes an owner-triggered pipeline run** — the Settings view builds a `workflow_dispatch`
     deep link (or copyable inputs) so the repo owner can dispatch a run with those IDs. **No token
     ever reaches the client** (Invariant 10 preserved); the owner authenticates to GitHub
     themselves.

3. **Why this is honest rather than a fudge.** For a single-user tool the ID the *pipeline* consumes
   and the ID the *user types in the browser* normally coincide, but they are genuinely two things:
   one is a build-time input to a CI job, the other is local personalisation plus a dispatch
   convenience. Pretending the browser can fetch personalised data would require either a backend
   (DL-03 forbids it) or a client-side call to the FPL API (Invariant 8 forbids it). This design gives
   the owner UI entry and repository-clean persistence without breaking either.

**Implementation is a follow-up, sequenced but not yet built.** It spans the web app (Settings view,
`localStorage`, league-row highlighting), a documented Actions-variable path in E7's workflows, and a
charter requirement. Proposed stories: a Settings story in E6's surface and an operations note in E7;
tracked here until scheduled. See INPUTS-REQUIRED for the variable names.

---

## 8. Sequencing and gates

Ordered by leverage, not by area. Each row is gated; nothing promotes on argument.

| Order | Item | Kind | Unblocks / depends on |
| --- | --- | --- | --- |
| 1 | **X1** — ship `xp_v1` live (close D-25) | Wiring | Delivers everything else; depends on nothing |
| 2 | **D1** — fixtures into the backtest | Plumbing | Gates all of §4 |
| 3 | **X2** — minutes calibration + M1 (close D-14) | Model | Largest error source |
| 4 | **D2** — DefCon history from BPS (Q-13) | Data | Strengthens M4 and D5 |
| 5 | **F1** — xG team ratings live | Model | Needs D1 |
| 6 | **X3 / X4 / D4** — anti-shrinkage + penalty duty | Model | Head-of-ranking gains |
| 7 | **D3 → F2** — odds live, then market blend | Data → model | Needs an Actions secret |
| 8 | **X5** — goalkeeper formulation | Model | Needs D1 |
| 9 | **D5 / X6** — prior-season prior re-measured; monolith shadow | Model | Needs D2 |

**The one rule that governs all of it (E8 §5):** a change is promoted only when the backtest
regression improves on a *held-out* season, live rolling accuracy does not degrade over **six** shadow
gameweeks, and the change is **explicable in advance**. A change that only improves the metric found a
pattern in this season's noise.

---

## 9. New open questions raised by this plan

| ID | Question | Bears on | Resolve by |
| --- | --- | --- | --- |
| ~~Q-14~~ | ~~Does evidence-adaptive shrinkage (X3) widen the head of the ranking without overfitting, and at what confidence threshold does the trade turn?~~ — **Answered on the backtest: the trade turns at a shrinkage strength of ≈0.4, and it does not widen the head.** The gain there is +0.0035 ± 0.0023 over 72 folds and the top 20 changes in 11 of them; the calibration slope degrades monotonically because shrinking less must lower it at fixed information content. See [DL-49](00-decision-log.md#dl-49) | X3 | Resolved |
| Q-15 | Is the goalkeeper position better served by a fully separate formulation (X5) or by the same chain with a saves-and-shots emphasis? | X5 | Backtest |
| Q-16 | Should the mini-league / team ID entered in the browser ever be allowed to *seed* a `workflow_dispatch` automatically, or must every run stay owner-initiated? | §7 | Owner decision; security review |

Q-13 (DefCon reconstruction) and Q-04 (blended monolith) are pulled forward from
[Design §15](04-conceptual-design.md#15-open-design-questions) as D2 and X6 respectively.
