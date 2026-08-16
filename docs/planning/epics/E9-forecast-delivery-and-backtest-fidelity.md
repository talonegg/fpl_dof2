# E9 — Forecast Delivery and Backtest Fidelity

**Objective:** OBJ-1, OBJ-7 · **Target:** first, ahead of E10–E12 · **Estimate:** 2–3 days
**Depends on:** E3 (harness, component chain), E7 (live publish path)
**Repays debt:** D-25 · **Implements:** [Model Improvement Plan §5 X1, §3 D1](../05-model-improvement-plan.md)
**Status:** Planned

---

## 0. Why this epic exists, and why it is first

The [first backtest](../00-decision-log.md#dl-21) produced a finding the
[Model Improvement Plan](../05-model-improvement-plan.md) turns into a programme. Two of that plan's
items are not modelling changes at all — they are the seams that make every *other* item real. Until
both land, the programme measures things it cannot deliver and cannot test.

1. **The model that is graded is not the model that is shipped.** The backtest grades `xp_v1` (the
   component chain); the pipeline publishes `xp_v0` (the cold-start model), which consumes none of the
   xG signal [DL-34](../00-decision-log.md#dl-34) promoted. The gap is **D-25** — a fixture-aware
   horizon scorer `xp_v1` does not yet have. **Until D-25 closes, every improvement in the plan is
   measured and never delivered.**
2. **The backtest is blind to fixtures.** The harness carries no fixture table, so M2 contributes
   *league-average opposition* to every prediction. The entire fixture axis (E11) is **untestable**
   until the harness carries fixtures — this is a prerequisite, not an improvement.

This epic is deliberately small and deliberately first. It is the highest-leverage work in the whole
improvement programme precisely because it is plumbing: it delivers the model already built and makes
the harness able to grade the model about to be built.

## 1. The gate this epic clears

E10, E11 and E12 all read "Backtest: metric X improves". That sentence is meaningless while the
graded model is not the shipped model (S1) and the harness cannot see fixtures (S2). **No story in
E10–E12 may start until E9's definition of done holds.** This is the same discipline E4 inherited
from E3 — measurement before the thing it measures.

## 2. Stories

### E9-S1 — Fixture-aware horizon scorer, `xp_v1` on the live path · 1.5 days · FR-12, FR-13 · **closes D-25**
Build the horizon scorer the component chain lacks, and switch the published forecast from `xp_v0` to
`xp_v1`. The scorer takes the component outputs (M1–M8) and a fixture horizon and produces the
per-gameweek expected points and **modelled variance** (Invariant 6) the contract already carries.

- The forecast stage publishes `xp_v1`; `xp_v0` remains available behind a flag as the documented
  cold-start fallback (DP-15 — degrade, never break — for the preseason path where M2 has no ratings).
- **Parity test:** the live horizon scorer must reproduce the backtest's single-gameweek `xp_v1`
  numbers under league-average opposition, to a stated tolerance. This is what proves the shipped
  model and the graded model are the same object rather than two implementations that drift.
- Ships **dark then promoted** (DP-08): published behind a flag, compared against `xp_v0` on the live
  path for the shadow window before it becomes the default the app reads.

**Acceptance:** the app's ranking is produced by `xp_v1`; the parity test is green; the model card
states which model is published and from which date.

### E9-S2 — Fixtures into the backtest fold frames · 1 day · FR-37 · **implements D1**
Join historical opponent and home/away into `fold_rows` so M2's attack/defence ratings actually enter
a scored prediction. The data is already in silver; this is plumbing, not a model change.

- Every fold frame carries the fixture each observation was played under, subject to the same
  knowability stamp every other feature carries (Invariant 5 — no look-ahead).
- The harness reports **fixture-conditioned** breakdowns: Spearman and calibration split by fixture
  difficulty band, so a fixture change can be graded where it is supposed to help.

**Acceptance:** the harness reports non-degenerate metrics under *real* opposition rather than
league-average; a fixture-difficulty breakdown appears in the backtest report. This is the gate E11
depends on — it is not "better", it is "now measurable".

## 3. Definition of done

- [ ] `xp_v1` is the model the live pipeline publishes; `xp_v0` is retained as the documented
      cold-start fallback only
- [ ] Parity test proves the live horizon scorer reproduces the backtest's `xp_v1` single-GW numbers
      under league-average opposition
- [ ] **D-25 closed** in the debt register ([E0 §6](E0-steel-thread-gw1.md#6-technical-debt-register))
- [ ] The backtest carries fixtures in every fold frame, with knowability stamps, and reports
      fixture-conditioned breakdowns
- [ ] Model card names the published model and the date it became the default
- [ ] The DL-21 guardrail is restated unchanged: no −8 hit, chip or wildcard on `xp_v1` alone until
      top-20 precision beats B0

## 4. The honest question

**"Is the app now showing the model we actually graded?"** If the answer is no, nothing downstream is
trustworthy — a season of improvements to a model the user never sees is the most expensive failure
mode this programme has, and it is the one E9 exists to foreclose.
