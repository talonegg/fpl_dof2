# E10 — Discrimination at the Head of the Ranking

**Objective:** OBJ-1, OBJ-7 · **Target:** after E9 · **Estimate:** 6–9 days
**Depends on:** E9 (live `xp_v1`, fixture-aware backtest) · **Repays debt:** D-14
**Implements:** [Model Improvement Plan §5 X2–X6, §3 D4](../05-model-improvement-plan.md)
**Status:** All five stories landed — E10-S1 ([DL-48](../00-decision-log.md#dl-48)), E10-S2
([DL-49](../00-decision-log.md#dl-49)), E10-S3 ([DL-50](../00-decision-log.md#dl-50)), E10-S4
([DL-51](../00-decision-log.md#dl-51)) and E10-S5 ([DL-53](../00-decision-log.md#dl-53)). **Four
candidates flagged off on the evidence and one benchmark permanently on.** No flag was promoted by
any story, which is the honest outcome of an epic that measured five things and found none of them
cleared its bar. S5 is the one that changes the plan: it measured the *ceiling* on this feature set
at the head, and the ceiling ties B0 — so the binding constraint is the data (E12), not the
formulation.
**S4 opened D-26 — no backtest in this project had ever resolved a fixture. Closed by
[DL-52](../00-decision-log.md#dl-52); coverage is now 1.0. Every level recorded below was measured
under league-average opposition and is re-based by DL-52's conversion table** — the overall
Spearman reads 0.251 rather than 0.231, GKP 0.101 rather than 0.044, and top-20 precision 0.122
rather than 0.127. No conclusion changes: nothing here was promoted, and S1's arms were re-run to
confirm it

---

## 0. The finding this epic answers

The [backtest](../00-decision-log.md#dl-21) said one thing above all others: **`xp_v1` is best at
avoiding error and worst at making distinctions — backwards for the tool.** It has the best MAE and
the *worst* top-20 precision of anything measured. Nobody acts on the whole ranking — they act on its
head, and at the head the model adds nothing over price.

**Three corrections to this section, all found by doing the work**
([DL-49](../00-decision-log.md#dl-49), [DL-52](../00-decision-log.md#dl-52)):

- The **0.00** this section originally quoted was a defect in the metric, not a fact about the model.
  Pooled across all 72 folds, top-20 precision is 0.00 for every model that could ever exist. Measured
  per gameweek, as it always should have been, `xp_v1` scores **0.127 against B0's 0.166** — still the
  finding, and now a number that can move.
- **The 0.70 calibration slope does not say predictions are compressed.** A slope of actual on
  predicted below 1 says they are too *spread out* for their information content; B0 has a worse slope
  (0.606) and a better head. The compression at the head is real and is what this epic is about, but
  the slope is not the instrument that measures it — **top-20 precision per position, against B0, is.**
- **"Two positions are essentially unranked" was substantially a statement about a null column**
  ([DL-52](../00-decision-log.md#dl-52)). The harness resolved no fixture at all, so every row was
  scored against league-average opposition. With the fixture join repaired and *no model change*,
  GKP Spearman reads **0.101** rather than 0.04 and DEF **0.220** rather than 0.16 — GKP already
  beats B0's 0.087. What survives is the head: top-20 precision **0.122 against B0's 0.166**, which
  fixtures do not explain and this epic still has to move.

So this epic optimises a different loss from E3's. **The target metric is top-20 precision and
captaincy separation, per position — not MAE.** MAE is already the best in the table and is measuring
the wrong thing. No position is now *unranked* — the two that looked it were a broken fixture join
(GKP 0.101, DEF 0.220 once repaired) — but a gain concentrated in forwards is still not a gain, so
every story here is graded *per position*.

## 0.1 Gate carried in from E9 — read before starting

**No story here may start until [E9](E9-forecast-delivery-and-backtest-fidelity.md)'s definition of
done holds.** Grading a discrimination change against a backtest whose model is not the shipped model
grades the wrong object. E9 makes the shipped and graded model the same and gives the harness
fixtures; this epic spends that fidelity.

**This gate was not actually held, and four stories ran before anyone checked it.** E9-S2's fixture
line was ticked because the code was written, not because a fixture had ever resolved
([DL-51](../00-decision-log.md#dl-51), [DL-52](../00-decision-log.md#dl-52)). It holds now —
coverage 1.0 — and the lesson is cheaper to record than to repeat: **a gate carried in from another
epic is checked by running it, not by reading its checkbox.**

## 1. Stories

### E10-S1 — Minutes calibration, then a better M1 · 2 days · FR-10 · **closes D-14**
Minutes are the largest single source of forecast error and their calibration is currently
*unmeasured* — `minutes_brier` is always null, which is why the [E3-S3 acceptance was never actually
met](../00-decision-log.md#dl-22). **Measure first, then improve.**

- Report the Brier score for the `{0, 1–59, 60+}` distribution, per position and minutes band. This
  alone closes D-14 and satisfies the acceptance E3-S3 recorded but never met.
- Then improve M1: rotation/congestion (fixture density), injury-return ramp, live chance-of-playing%,
  and European-rotation handling ([Q-08](../04-conceptual-design.md#15-open-design-questions)).

**Acceptance:** Brier score reported and **beating the E0 status-flag haircut** — the bar E3-S3 set.

**Outcome — 2026-08-20 · met, and the by-band split is the more valuable half.**
[DL-48](../00-decision-log.md#dl-48). M1 beats the haircut in **every position** with the candidate
flag off (Brier 0.35877 vs 0.44476, skill +0.193, 54,045 observations over 72 folds), so **D-14 is
closed by measurement alone** — no model change was needed for it, which is why *measure first* was
the right order. `discrimination.minutes_v2` improves Brier (0.34822), Spearman (0.23070 → 0.24075),
MAE and calibration slope (0.701 → 0.727) in every position, **and leaves top-20 precision at 0.00** —
so it stays flagged off (DP-08, [DL-47](../00-decision-log.md#dl-47)).

The finding: M1 beats the haircut by being much better about **non-appearances** (0.190 vs 0.384) and
is *worse* than E0's crude heuristic about players who actually played 60+ (0.421 vs 0.298) — and the
candidate makes that half worse still, because every adjustment moves mass out of the 60+ state. **The
head of the ranking is made of players who play 60+ minutes.** This is [DL-21](../00-decision-log.md#dl-21)'s
compression showing up inside the minutes component, and it hands S2 a falsifier it did not have.

**European rotation is not implemented and was not faked:** nothing in silver carries a European
fixture or competition label, so [Q-08](../04-conceptual-design.md#15-open-design-questions) stays
open and is now blocked on a data question (E12), not a modelling one. Fixture *density* — the
observable shadow a midweek tie casts on the Premier League calendar — is implemented in its place.

**Re-run on repaired fixtures ([DL-52](../00-decision-log.md#dl-52)); the conclusion holds.** The
levels above are re-based — off 0.25058, on 0.25946, top-20 0.12153 → 0.12361 against B0's 0.166 —
but the shape is unchanged, and one assumption behind the re-run turned out to be wrong: **the
congestion prior never read the broken fixture columns.** `matches_last{N}d` counts the player's own
prior kickoffs, touching no club and no calendar, which is why the minutes Brier, its per-position
split and its per-band split come back **identical to DL-48 to five decimal places**. What did
change is that the aggregate gain is now shown to exceed the noise — paired per gameweek, **t = 3.9
(DEF), 4.7 (MID), 3.4 (FWD)** — which DL-48 could only say was untested. It is still not at the
head: precision moves +0.002 overall, MID's goes *down*, and the `long`-band deficit that was the
reason to refuse promotion is bit-identical. **`minutes_v2` stays off.**

### E10-S2 — Reduce over-shrinkage at the head · 2 days · FR-12 · bears on Q-14
The 0.70 calibration slope says the top is compressed. Make shrinkage **evidence-adaptive**: shrink
*less* for high-minutes, high-confidence players where signal genuinely exists, so the elite spread
out instead of collapsing toward the position prior.

- The shrinkage weight becomes a function of evidence (minutes played, sample size), not a constant.
- Falsifier stated in advance ([Q-14](../05-model-improvement-plan.md#9-new-open-questions-raised-by-this-plan)):
  the confidence threshold at which the trade turns is found *on the backtest*, not chosen.

**Acceptance:** top-20 precision and calibration slope improve **without** MAE regressing so far it
signals overfitting — a regression in MAE past a stated bound is the overfitting tripwire, not a
success.

**Outcome — 2026-08-21 · not met, and the metric fix is worth more than the model change.**
[DL-49](../00-decision-log.md#dl-49). Top-20 precision was **pooled across all 72 folds**, where the
twenty highest observed scores are twenty separate 20-point hauls and no calibrated expectation can
reach them — so it read 0.00 for `xp_v1`, for B0, and for every model that could ever be written.
Fixed to per gameweek (a defect, so unflagged), it reads **`xp_v1` 0.127, B0 0.166, trailing-six
0.144**: the model is **worse than price at the head by 0.039 ± 0.010**, which is DL-21's finding as
a number that can move rather than a zero that never could. The captaincy hit rate had the same
defect. Each position's head is now as deep as that position goes into a squad.

Q-14 **is answered on the backtest**: the trade turns at a strength of ≈0.4, where top-20 precision
peaks at 0.13056 before falling away. It does not clear the bar. The gain is +0.00347 ± 0.00228
paired over 72 folds (t = 1.52), and **the top 20 changed at all in only 11 of those 72 gameweeks**.
The calibration slope moves the *wrong* way, monotonically, in every position — because a slope
below 1 means predictions are too **spread out** for their information content, not compressed, so
shrinking less must lower it unless correlation rises with it, and correlation moved in the fourth
decimal. B0 settles it: a worse slope (0.606) and a better head. The MAE tripwire was set at +1%
relative and never bound (worst arm +0.29%).

**So `adaptive_shrinkage` stays flagged off, and the acceptance criterion itself needs revisiting
before S3 and S4 are graded**: "calibration slope improves" is not a coherent goal for a change that
widens the predicted distribution. The deficiency the numbers show is **correlation (0.19), not
scale** — which is the case *for* S3, S4 and S5, all of which add information, and against any
further rescaling.

### E10-S3 — Penalty and set-piece duty as an explicit additive term · 1.5 days · FR-12 · pairs with [E12-S… D4]
Penalties are large, lumpy, highly identifiable points and a primary way the elite separate — and the
shrinkage of S2 erases exactly this kind of signal. Add duty as an explicit additive term at the
horizon scorer, reading the committed reference table built as **D4** in
[E12](E12-data-widening-for-priors.md).

- Duty is a **committed config/reference file**, hand-maintained — not a data source, so no
  Invariant-1 or scraping question arises (this is the D4 side; E12 owns the file, E10 owns the model
  term that consumes it).

**Acceptance:** top-20 precision **among attackers** improves when duty is an explicit term.

**Outcome — 2026-08-21 · not met, and the per-position split is again the finding.**
[DL-50](../00-decision-log.md#dl-50). The committed table (E12-S2, **D4 closed**) holds 40 dated
penalty spells, none written from recollection: the historical ones are FPL's own `penalties_order`
as it stood at the **end of the previous season**, so each was knowable before the season it is
applied to, and the 2026/27 ones are FPL's pre-season field, tiered `likely` for exactly that
reason. Entries hindsight shows were wrong — Toney, Eze — are kept, because they are what a manager
would have believed and filtering them out would be the look-ahead the dates exist to prevent.

**The term separates midfielders and blurs forwards, monotonically, at every strength.** MID
0.13889 → 0.14484 (paired +0.00595, t = 1.76) at the argued strength and +0.01190 at t = 2.18 when
the double-count correction is undone; FWD 0.15972 → 0.15625 → 0.14931, never significant and never
once in the other direction. GKP and DEF are untouched, correctly — no goalkeeper or defender is in
the table. **So the criterion fails on its own words**: it improves among midfielders, and §0 is
explicit that a gain confined to one position does not clear the bar. B0 still wins every position's
head, by 0.25 to 0.15 among forwards.

The reading: among forwards duty is **already priced in**, because nearly every leading forward
takes his club's penalties, so the term only reshuffles a four-deep head. Among midfielders it
separates, because most midfielders do not take penalties and the handful who do are exactly the
ones running ahead of a prior built from midfielders who score rarely. **The information is in the
contrast with the prior, not in the penalty** — which is the first real support
[DL-49](../00-decision-log.md#dl-49)'s "correlation, not scale" redirection has had, since no
rescaling arm in S1 or S2 moved a per-position head by two standard errors, and an argument for S4
rather than for anything aimed at forwards.

**The official feed already publishes `penalties_order` for all twenty clubs**, and the archive's
season-end snapshots carry it — which is where this file was seeded from. Reading it *as a feed* is
a source-layer change and an E12 decision (Invariant 1), not this story's; the committed file is the
seam until then.

### E10-S4 — A goalkeeper-specific formulation · 1.5 days · FR-12 · bears on Q-15
GKP Spearman is 0.04 — a whole position essentially unranked. Model GKP xP primarily from **opponent
shot volume × team defence (M2)** plus a saves model, rather than a shrunk per-90 that clean sheets
dominate.

- Needs E9-S2's fixtures in the backtest — the formulation is fixture-driven by construction.
- [Q-15](../05-model-improvement-plan.md#9-new-open-questions-raised-by-this-plan) is the falsifier:
  a fully separate formulation versus the same chain with a saves-and-shots emphasis; graded, not
  assumed.

**Acceptance:** GKP Spearman moves off the floor.

**Outcome — 2026-08-21 · not met, and for the third story running the measurement is the finding.**
[DL-51](../00-decision-log.md#dl-51). **"Off the floor" was fixed in advance** as three conditions:
Spearman ≥ 0.10, a paired gain clearing two standard errors, and no cost in GKP precision or a
breach of DL-49's MAE tripwire.

**Shot volume does not exist in this project** — nothing on `player_gameweek` counts shots — so M2's
expected goals conceded stands in for it, named as a proxy rather than substituted silently, the
same call [DL-48](../00-decision-log.md#dl-48) made about European rotation. The measurement that
justifies the story: across the archive's regular keepers, saves per 90 have an sd of 0.64 on a mean
of 3.1, while saves per expected goal conceded have an sd of 0.21 on a mean of 2.1 — **half the
spread between keepers' save rates is the defence in front of them.**

**The story's own precondition does not hold, and that is the headline.** It says it needs E9-S2's
fixtures; `fplarchive/adapter.py` writes `team_id: None` on every row, so `fixture_calendar` resolves
nothing and **100% of every backtest this project has run was scored against league-average
opposition** — where this story's fixture factor is exactly 1.0 and the fixture half of both
formulations is *not measured* rather than ineffective. Opened as **D-26**; fixing it is a
source-layer change that re-bases every number in DL-48, DL-49 and DL-50, so it is its own decision.

With `team_id` reconstructed for a labelled diagnostic, **resolving fixtures alone moves GKP
Spearman from 0.04428 to 0.09948 with no model change**, DEF from 0.163 to 0.219 and the overall
from 0.231 to 0.250. §0's "GKP Spearman 0.04" was substantially a statement about a null column.

**Q-15 is answered and the two halves differ in sign, not degree.** The fully separate formulation
helps (+0.00914, t = 1.83, and most at zero fixture weight); the lighter-touch re-weighting of the
existing chain **hurts, monotonically, reaching t = −2.95** — the largest significant movement in
the epic and in the wrong direction. The reading: a keeper's clean-sheet and goals-conceded terms
already carry M2's fixture signal *with the opposite sign to saves*, so re-weighting saves by it
cancels the better-measured component. Dividing pressure out of his history is new information;
multiplying it back into his fixture is double-counting.

**So the criterion fails on both readings**: unrepaired, Spearman reaches 0.0658 against a bound of
0.10 (though GKP precision 0.213 beats B0's 0.194 at t = 2.34 — the first time any arm in this epic
has beaten B0 at a position's head, and an artefact that does not survive repair); repaired, the
level clears 0.10 but the flag-off arm was already there and the candidate adds t = 1.83.

### E10-S5 — Blended monolith as a shadow benchmark · 1 day · **shadow only** · Q-04/X6
A GBM on the same features is an *upper bound* on achievable accuracy. If the component chain's
explainability (a product requirement, [DP-10](../DESIGN-PRINCIPLES.md)) costs a large gap at the
head, that trade must be decided **explicitly**, not assumed away.

- Runs as a shadow benchmark alongside B0 and the model-free benchmark. **Never promoted over the
  chain without an explicit DP-10 decision** weighing accuracy against explicability.

**Acceptance:** the gap between the chain and the monolith at the head is reported every backtest run,
so the explainability trade is a visible number rather than an article of faith.

**Outcome — 2026-08-21 · met, and it reframes what the rest of this epic was for.**
[DL-53](../00-decision-log.md#dl-53). The gap is reported in `backtest.json`, in the backtest card,
in the stage metrics and — because DP-10 asks for *visible*, not *stored* — as a plain-language
sentence on the **model card**, written once and reproduced verbatim by both consumers.

**Explainability is not free at the head: it costs 0.04444 ± 0.01147 of top-20 precision,
t = +3.87 paired over 72 gameweeks, and +0.06565 of Spearman at t = +8.20.** That is the largest
significant movement anywhere in this epic, and it is a **deficit of the shipped model** rather than
a gain from a candidate — every arm in S1 to S4 moved the head by less than two standard errors.

**And the whole of it is forwards and midfielders.** FWD precision +0.05903 (t = 2.64) and Spearman
+0.16670 (t = 8.09); MID Spearman +0.09134 (t = 8.38); DEF level; **GKP the chain is ahead on both**.
So it is not a statement about interpretability in general, it is a statement about where the
recoverable information sits — which makes it a lead the chain can be given without becoming opaque.

**The finding worth more than the gap: the ceiling at the head *is* B0.** The monolith scores
**0.16597** and B0 scores **0.16597** — paired difference +0.00000, t = 0.00, and genuinely a
coincidence of means rather than a duplicated column (they disagree in 60 of 72 gameweeks; Spearman
0.321 against 0.214). A gradient-boosted model with every feature this project has **recovers the
chain's entire deficit to price and stops exactly there.** §0's target is to *beat* B0 at the head.
Nothing in this epic does, and now the ceiling has been measured and does not either — so the
binding constraint is the **feature set**, not the formulation, and the next place to look is
[E12](E12-data-widening-for-priors.md) rather than a sixth reformulation.

**The chain stands, and not as a preference.** The monolith is worse on MAE (1.994 vs 1.931) and
worse calibrated (0.555 vs 0.690) — [DL-21](../00-decision-log.md#dl-21)'s shape one level up. It
also cannot carry a variance (Invariant 6) or a component decomposition (DP-09), and promoting it
would leave DL-21's guardrail exactly where it is, because tying B0 is not beating it. Q-04 is
answered on evidence rather than left open: **materially better at ranking, materially worse at
everything else.**

## 2. Definition of done

- [x] **D-14 closed** — `minutes_brier` reported per position and per observed band, and beating the
      status-flag haircut in every position (0.359 vs 0.445). [DL-48](../00-decision-log.md#dl-48)
- [ ] Shrinkage is evidence-adaptive; top-20 precision and calibration slope improve within the stated
      MAE-regression bound — **shrinkage is evidence-adaptive and graded, and the criterion is not
      met**: the precision gain at the turn point is inside the noise and the slope degrades by
      construction. [DL-49](../00-decision-log.md#dl-49), which also argues the second half of this
      criterion is the wrong test and should be replaced before S3 and S4 are graded
- [ ] Penalty/set-piece duty is an explicit additive term consuming E12's committed reference table
      — **the term exists, consumes E12-S2's table and is graded, and the criterion is not met**:
      top-20 precision rises among midfielders (t = 1.76) and falls among forwards at every
      strength, and "among attackers" is what the acceptance says.
      [DL-50](../00-decision-log.md#dl-50). Set-piece duty beyond penalties is a validated schema
      with no entries and no consumer, deliberately — nothing in silver carries set-piece volume
- [ ] A goalkeeper-specific formulation exists and moves GKP off the Spearman floor — **both
      formulations exist and are graded, and the criterion is not met**: the separate one gains
      +0.009 at t = 1.83 and the lighter-touch one *loses* at t = −2.95.
      [DL-51](../00-decision-log.md#dl-51), which also opens **D-26**: no backtest this project has
      run ever resolved a fixture, because the archive writes no `team_id`, and repairing it moves
      GKP Spearman further on its own (0.044 → 0.099) than any model change in this epic has
- [x] The monolith shadow benchmark reports the head-of-ranking gap every run — in `backtest.json`,
      the backtest card, the stage metrics and the model card, with no flag that could ever promote
      it and only two modules able to reach it. **The gap is +0.044 of top-20 precision at
      t = 3.87**, all of it in forwards and midfielders, and the monolith's 0.16597 ties B0's
      0.16597 exactly — so the ceiling on this feature set at the head *is* price.
      [DL-53](../00-decision-log.md#dl-53)
- [x] **Every metric in this epic is reported per position.** A headline gain that is confined to
      forwards is recorded as such and does not count as clearing the bar — `spearman_by_position`,
      `top_n_precision_by_position` and `calibration_slope_by_position` (all in `backtest.json`, the
      backtest card and the model card) is what let S2's duty and GKP findings be stated by
      position rather than as one misleading average in the first place.
- [ ] Each promoted change cleared the [E8 §5 bar](E8-in-season-operations.md#5-the-bar-for-changing-the-model-mid-season):
      held-out backtest improves, six shadow gameweeks do not degrade, explicable in advance

## 3. The honest question

**"Would I captain differently because of this change?"** The whole epic is about the head of the
ranking and the captaincy decision that sits at its very top. A change that improves an aggregate
metric but never moves a captain pick has not touched the thing the season is actually decided on.
