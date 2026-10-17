# Project Plan and Blueprint — FPL DOF

**Companion to:** [01-project-charter.md](01-project-charter.md) · **Baselined:** 2026-08-09

This document covers *how the thing gets built*: the blueprint that shapes the work, the season
operating calendar, and the RAID log. Architecture and component design live in documents 03 and 04.

The live sections are §1 (blueprint B1–B7), §2 (delivery strategy), §5 (season calendar), §6 (the
RAID log) and §9. The phase plan, milestones, GW1 decision and estimates (§3, §4, §7, §8) were
superseded by the epics ([DL-10](../decisions/DL-10.md)) and are archived in
[02-superseded-sections.md](archive/02-superseded-sections.md) (DL-74). The plan of record is
[the epic register](epics/README.md); the technical debt register is [its own page](debt-register.md).

---

## 1. The blueprint

Seven principles. Every phase and every design choice downstream is answerable to them.

### B1 — The season is the clock

There is no sprint calendar. There are 38 deadlines, and the first is on **21 August 2026 at
18:30 BST**. Work is planned backwards from deadlines, and anything that cannot be finished before a
deadline is explicitly parked rather than half-built.

### B2 — Every phase exits usable

No phase ends with a half-connected system. Phase 1 ends with browsable data; phase 2 ends with a
usable expected-points table; phase 3 ends with a squad you could actually enter. This is the primary
defence against R-05 (stalling mid-build). A partially built system that still helps is a success; a
fully designed system that never ships is not.

### B3 — Precompute everything, serve static

The zero-cost constraint (DL-03) is not a limitation to work around, it is the design. Anything that
*can* be computed on a schedule *is* computed on a schedule and published as a file. Only genuinely
interactive exploration runs in the browser.

### B4 — Sources are plugins; the core knows nothing about them

Per DL-05. Ingestion is the only layer that knows a source exists. Everything downstream consumes a
conformed model. The test of this is mechanical: **adding a source must touch exactly one new adapter
module and one config entry.** If it touches anything else, the abstraction has failed.

### B5 — Predict, then optimise — never conflate the two

The expected-points engine answers "what is this player worth?" The optimiser answers "given those
values, what is the best legal set of decisions?" They are separate packages with a typed contract
between them. This keeps both testable, and it is what allows a stochastic layer to be swapped in
later without touching the solver (DL-06).

### B6 — Explainability is a feature, not documentation

The system's job is to make the owner a better manager, not to replace them. Every number the UI
shows must be traceable to its inputs, and every recommendation must show what it beat and by how
much. A recommendation that cannot be explained will not be trusted, and will not be followed.

### B7 — Validate before you believe

No model output is trusted until it has been backtested walk-forward against a held-out season and
beaten a naive benchmark. Building the optimiser on an unvalidated forecast is the fastest route to
confident, expensive, wrong decisions (R-04).

---

## 2. Delivery strategy

**Vertical slices, thin then thick.** Build the narrowest end-to-end path first — FPL API → conformed
table → naive forecast → static JSON → a table on a page — then thicken each layer in turn. This
surfaces integration problems in week one rather than week six.

**Three workstreams run in parallel** where dependencies allow:

| Stream | Covers | Runs |
| --- | --- | --- |
| **WS-A — Data platform** | Adapters, conformed model, entity resolution, quality gates, history backfill | Phases 0–1, then continuous maintenance |
| **WS-B — Intelligence** | Expected-points models, backtesting, optimiser, chip strategy, risk model | Phases 2–3, then continuous improvement |
| **WS-C — Product** | Web app, scouting, planner, explainability, PWA, data health | Phases 1–4, then continuous |

Cross-cutting concerns (orchestration, observability, testing, docs) are **not a stream and not a
phase**. They are built into every increment via the definition of done (charter §13). A project of
this size cannot afford an "add monitoring later" phase, because later never arrives.

---

## 3. Phase plan

**Superseded** and archived, with its text unchanged, in
[02-superseded-sections.md](archive/02-superseded-sections.md) (DL-74).

---

## 4. Milestones

**Superseded** and archived, with its text unchanged, in
[02-superseded-sections.md](archive/02-superseded-sections.md) (DL-74).

---

## 5. Season operating calendar

| Date | Event | What the system must be doing |
| --- | --- | --- |
| 2026-08-09 | Today | Planning baselined; build decision pending |
| **2026-08-21 18:30 BST** | **GW1 deadline** | OBJ-2. See §7 for whether this is reachable |
| 2026-08-21 | Season starts | First live gameweek data; models get real signal |
| GW2–GW4 | Early season | Highest price volatility and highest forecast uncertainty; treat model output sceptically |
| GW4–GW8 | Settling | Minutes data becomes meaningful; priors give way to observed form |
| GW10–GW12 | First checkpoint | First honest read on live model accuracy |
| Autumn | Congestion | European and cup fixtures; rotation risk matters most |
| **2027-01-02 13:30 GMT** | **GW19 deadline** | **Chip set 1 expires — all four must be used** |
| Jan | Second chip set opens | Re-plan the chip calendar for the run-in |
| Feb–Apr | Blanks and doubles | Fixture-schedule modelling matters most; Free Hit and Bench Boost timing |
| 2027-05-30 | Final match round | Season outcome measured against charter §5 |

---

## 6. RAID log

### Risks

| ID | Risk | Impact | Likelihood | Response | Owner |
| --- | --- | --- | --- | --- | --- |
| R-01 | GW1 passes before the system is usable | High | High | Choose a track in §7 consciously; re-baseline OBJ-2 if the full track is chosen | Owner |
| R-02 | FPL API changes shape or blocks automated access | High | Medium | Adapter isolation; contract tests on recorded responses; snapshot everything; polite rate limits and honest client identification | Owner |
| R-03 | Model adds no real edge over intuition | High | **Confirmed, partially** *(2026-08-11)* | Backtest before trusting (B7) — it ran, and found the edge is real on average (beats B0) but absent exactly where decisions are made (loses to a trailing-form heuristic at the head of the ranking). See **R-15a** and [DL-21](../decisions/DL-21.md). Scout UI retains standalone value regardless | Owner |
| R-04 | Overfitting produces confident wrong forecasts | Medium | High | Walk-forward validation; held-out season; in-season calibration monitoring | Owner |
| R-05 | Build stalls mid-season, leaving a half-built system | Medium | Medium | B2 — every phase exits usable | Owner |
| R-06 | Scraped sources break on a layout change | Medium | High | Contract tests catch it; NFR-15 keeps the pipeline running; cached data covers the gap | Owner |
| R-07 | Optimiser solve time exceeds the CI budget | Medium | **High** *(raised 2026-08-09)* | Candidate pruning; time limits; warm starts; greedy fallback. **Re-rated because the E0 de-risking exercise validated CBC on the *single-gameweek* problem only.** The E4 multi-gameweek model with transfers, hits and chips is ~10–20k binaries with a weak relaxation. Mitigated structurally by [DL-15](../decisions/DL-15.md): HiGHS instead of CBC, and chip timing by scenario enumeration instead of MILP variables | Owner |
| R-08 | Odds free-tier credits exhausted mid-month | Low | Medium | Credit budgeting in the adapter; cache aggressively; degrade to xG-only team strength | Owner |
| R-09 | Scheduled jobs fire late and miss a deadline | Medium | Medium | Never schedule close to a deadline; run at T−3h and T−45m; manual dispatch always available | Owner |
| R-10 | Entity resolution silently mismatches players across sources | High | Medium | Curated override file; assertion that unmatched rate stays below a threshold; unmatched report in data health | Owner |
| R-11 | Free tiers change terms or limits | Medium | Low | No lock-in: static output is portable; local execution is always a fallback | Owner |
| R-12 | Motivation decays once the novelty fades | Medium | Medium | Weekly loop is deliberately small — one improvement per week; the system must be useful even if development stops | Owner |
| R-13 | Published artefacts grow past free-tier limits | Medium *(raised)* | **High** *(raised 2026-08-09)* | **Re-rated because "pruning" was under-specified.** Deleting files from a Git branch tip does not shrink the pack — history retains every blob. Requires a concrete mechanism: an orphan `data` branch force-pushed with truncated history, plus a separate small append-only branch for the per-gameweek permanent snapshots. See [03-solution-architecture.md §7.3](03-solution-architecture.md#73-storage-volume-and-retention-mechanics) | Owner |
| R-14 | **Cold-start coverage** — roughly a quarter to a third of the GW1 player pool (three promoted clubs plus overseas signings) has no Premier League history, so their expected points come entirely from positional and price-tier priors | Medium | **High** — it is a certainty, the only question is the size | Confidence tier published per player; deliberately wide uncertainty on prior-less players; the E0-S8 human gate weights these hardest; an early Wildcard corrects most of the damage once real minutes arrive | Owner |
| R-15 | ~~**Expected points collapses onto price**~~ **Measured, 2026-08-11 — did not materialise as stated.** R² of xP on (price, position) = 0.483 ([model-card.md](../../data/gold/season=2026-27/model-card.md), verdict "informative") — the model adds real information beyond price. **A related but distinct failure materialised instead**, captured as **R-15a** below | Was High; the literal risk is now closed by measurement | — | Diagnostic ran as designed in E0-S5 and again in E3's backtest; the R-15 mechanism (price as a signal producing a flat objective) did not occur | Owner |
| R-15a | **New, 2026-08-11 — the model under-discriminates at the head of the ranking specifically** — MAE is best-in-class (1.936, beats B0's 1.965) but top-20 precision is worst-in-class (0.00 vs B0's and the model-free benchmark's 0.05). Shrinking every thin estimate toward a position prior avoids being badly wrong on average and avoids distinguishing anyone at the top, which is backwards for how the tool is used (nobody acts on the whole ranking). See [DL-21](../decisions/DL-21.md) | High — the optimiser and captaincy calls act on exactly this part of the ranking | Confirmed, not hypothetical | Debt **D-13** ([E0 §6](debt-register.md)); E4 must not justify a hit, chip or wildcard on `xp_v1` alone until top-20 precision beats B0 (gate written into [E4 §0](archive/R1.0/E4-decision-engine.md#0-gate-carried-in-from-e3--read-before-starting)); next model work targets head discrimination, not MAE | Owner |
| R-16 | **Solution churn between runs** — a degenerate MILP returns a different but equally optimal squad on each run, destroying trust faster than a wrong recommendation would | Medium | High without mitigation | Deterministic incumbency tie-break in the objective ([Design §6.2](04-conceptual-design.md#62-milp-formulation)); a transfer must clear a stated margin, not merely tie | Owner |
| R-17 | **In-season overfitting** — monthly retraining on ~10 gameweeks of live data is a small, noisy sample, and "improving" the model mid-season is where a working system most easily gets worse | Medium | Medium | Shadow mode by default; a stated evidence bar for promotion ([E8 §5](epics/E8-ongoing-in-season-monitoring.md)); prefer shrinkage toward the preseason model over refitting | Owner |

### Assumptions

Tracked in charter §8 (ASM-1 … ASM-7). ASM-1 and ASM-6 are the load-bearing ones: no public API and
no human acting on the advice both invalidate the project outright.

### Issues

| ID | Issue | Impact | Status |
| --- | --- | --- | --- |
| I-01 | Only 12 days to the GW1 deadline, and no code exists | OBJ-2 at risk | **Closed** — resolved by [DL-10](../decisions/DL-10.md). Building the steel thread; [E0](archive/R1.0/E0-steel-thread-gw1.md) carries the schedule |
| I-02 | Pre-deadline squad state is not publicly exposed (CON-10) | FR-25 partially blocked | **Open** — designed for in [E1-S1](archive/R1.0/E1-weekly-operating-loop.md#e1-s1--squad-state-service) |
| I-03 | Repo visibility undecided (OD-01) | Gated free CI minutes and Pages | **Closed** — [DL-12](../decisions/DL-12.md): public repository. Unlimited Actions minutes, free Pages, OD-02 closed with it |
| I-04 | Odds provider and credit budget undecided (OD-03) | Blocks E5-S4 | **Closed** — the Odds API free tier, [DL-59](../decisions/DL-59.md) |
| I-05 | **Effective ownership is not computable from public FPL data** (CON-12) | FR-16, FR-21 and the whole risk dial rest on it | **Closed** — effective ownership redefined without a captaincy term, [DL-24](../decisions/DL-24.md) |
| I-06 | **DL-11 (UTC storage, dual-timezone display) is still `Proposed`** | Changes FR-26 and the E7 scheduling design; CON-11 already records the underlying constraint | **Open** — needs one confirmation from the owner. Costs nothing; blocking nothing yet; will block E1-S4 |

### Dependencies

| ID | Dependency | Type | Note |
| --- | --- | --- | --- |
| D-01 | Official FPL API | External, critical | No contract, no SLA, no versioning |
| D-02 | Understat / FBref | External, degradable | Personal-use terms; polite access required |
| D-03 | Odds provider free tier | External, degradable | Credit-capped |
| D-04 | GitHub Actions | Platform, critical | Compute for the entire pipeline |
| D-05 | Static host (Pages or Cloudflare Pages) | Platform, critical | Delivery surface |
| D-06 | Historical gameweek data for backfill | External, important | Required for training and backtesting |
| D-07 | Owner's availability | Internal, critical | The only labour resource |

---

## 7. The GW1 decision — **closed**

**Superseded** and archived, with its text unchanged, in
[02-superseded-sections.md](archive/02-superseded-sections.md) (DL-74).

---

## 8. Estimation summary

**Superseded** and archived, with its text unchanged, in
[02-superseded-sections.md](archive/02-superseded-sections.md) (DL-74).

---

## 9. What "good" looks like at the end

- A GitHub repository that, unattended, keeps a static site current with fresh data, forecasts and a
  transfer recommendation for every one of the 38 deadlines.
- A scout UI good enough that the owner reaches for it instead of the official site.
- A backtest report that honestly states how much edge the model has, including if the answer is
  "not much".
- A decision log that explains why every significant choice was made.
- £0.00 spent.
