# E10 — Discrimination at the Head of the Ranking

**Objective:** OBJ-1, OBJ-7 · **Target:** after E9 · **Estimate:** 6–9 days
**Depends on:** E9 (live `xp_v1`, fixture-aware backtest) · **Repays debt:** D-14
**Implements:** [Model Improvement Plan §5 X2–X6, §3 D4](../05-model-improvement-plan.md)
**Status:** Planned

---

## 0. The finding this epic answers

The [backtest](../00-decision-log.md#dl-21) said one thing above all others: **`xp_v1` is best at
avoiding error and worst at making distinctions — backwards for the tool.** It has the best MAE and
the *worst* top-20 precision (0.00) of anything measured; its 0.70 calibration slope says predictions
are compressed toward a position prior. Nobody acts on the whole ranking — they act on its head, and
at the head the model adds nothing over price.

So this epic optimises a different loss from E3's. **The target metric is top-20 precision and
captaincy separation, per position — not MAE.** MAE is already the best in the table and is measuring
the wrong thing. Two positions are essentially unranked (GKP Spearman 0.04, DEF 0.16); a gain
concentrated in forwards is not a gain, so every story here is graded *per position*.

## 0.1 Gate carried in from E9 — read before starting

**No story here may start until [E9](E9-forecast-delivery-and-backtest-fidelity.md)'s definition of
done holds.** Grading a discrimination change against a backtest whose model is not the shipped model
grades the wrong object. E9 makes the shipped and graded model the same and gives the harness
fixtures; this epic spends that fidelity.

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

### E10-S3 — Penalty and set-piece duty as an explicit additive term · 1.5 days · FR-12 · pairs with [E12-S… D4]
Penalties are large, lumpy, highly identifiable points and a primary way the elite separate — and the
shrinkage of S2 erases exactly this kind of signal. Add duty as an explicit additive term at the
horizon scorer, reading the committed reference table built as **D4** in
[E12](E12-data-widening-for-priors.md).

- Duty is a **committed config/reference file**, hand-maintained — not a data source, so no
  Invariant-1 or scraping question arises (this is the D4 side; E12 owns the file, E10 owns the model
  term that consumes it).

**Acceptance:** top-20 precision **among attackers** improves when duty is an explicit term.

### E10-S4 — A goalkeeper-specific formulation · 1.5 days · FR-12 · bears on Q-15
GKP Spearman is 0.04 — a whole position essentially unranked. Model GKP xP primarily from **opponent
shot volume × team defence (M2)** plus a saves model, rather than a shrunk per-90 that clean sheets
dominate.

- Needs E9-S2's fixtures in the backtest — the formulation is fixture-driven by construction.
- [Q-15](../05-model-improvement-plan.md#9-new-open-questions-raised-by-this-plan) is the falsifier:
  a fully separate formulation versus the same chain with a saves-and-shots emphasis; graded, not
  assumed.

**Acceptance:** GKP Spearman moves off the floor.

### E10-S5 — Blended monolith as a shadow benchmark · 1 day · **shadow only** · Q-04/X6
A GBM on the same features is an *upper bound* on achievable accuracy. If the component chain's
explainability (a product requirement, [DP-10](../DESIGN-PRINCIPLES.md)) costs a large gap at the
head, that trade must be decided **explicitly**, not assumed away.

- Runs as a shadow benchmark alongside B0 and the model-free benchmark. **Never promoted over the
  chain without an explicit DP-10 decision** weighing accuracy against explicability.

**Acceptance:** the gap between the chain and the monolith at the head is reported every backtest run,
so the explainability trade is a visible number rather than an article of faith.

## 2. Definition of done

- [ ] **D-14 closed** — `minutes_brier` reported per position and beating the status-flag haircut
- [ ] Shrinkage is evidence-adaptive; top-20 precision and calibration slope improve within the stated
      MAE-regression bound
- [ ] Penalty/set-piece duty is an explicit additive term consuming E12's committed reference table
- [ ] A goalkeeper-specific formulation exists and moves GKP off the Spearman floor
- [ ] The monolith shadow benchmark reports the head-of-ranking gap every run
- [ ] **Every metric in this epic is reported per position.** A headline gain that is confined to
      forwards is recorded as such and does not count as clearing the bar
- [ ] Each promoted change cleared the [E8 §5 bar](E8-in-season-operations.md#5-the-bar-for-changing-the-model-mid-season):
      held-out backtest improves, six shadow gameweeks do not degrade, explicable in advance

## 3. The honest question

**"Would I captain differently because of this change?"** The whole epic is about the head of the
ranking and the captaincy decision that sits at its very top. A change that improves an aggregate
metric but never moves a captain pick has not touched the thing the season is actually decided on.
