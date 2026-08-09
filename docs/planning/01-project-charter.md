# Project Charter — FPL DOF

**Project:** FPL DOF — a decision-support platform for Fantasy Premier League
**Season in scope:** 2026/27 (21 August 2026 – 30 May 2027)
**Document status:** Baselined 2026-08-09 · **Version 1.1**, amended 2026-08-09 per [DL-13](00-decision-log.md#dl-13--charter-amendments-following-the-2026-08-09-architecture-and-plan-audit)
**Owner / sole stakeholder:** Repository owner (also the FPL manager whose team it serves)

---

## 1. Purpose and vision

Fantasy Premier League is a constrained optimisation problem played under uncertainty, with a hard
weekly deadline. Most managers lose points not because they lack football knowledge but because they
make decisions from incomplete information under time pressure: they miss a price change, misjudge a
fixture run, take a −4 that was never worth it, or burn a chip in an average gameweek.

**FPL DOF is a personal "director of football".** It ingests the data, forecasts what each player is
worth, solves for the best legal squad and transfer plan over a multi-week horizon, and explains its
reasoning well enough that the manager can overrule it with confidence.

The system is a **decision-support tool, not an autopilot.** Every recommendation is accompanied by
its expected-points decomposition, the alternatives considered, and the ownership risk it implies.
The human makes the final call at the deadline.

---

## 2. Business case

| Driver | Detail |
| --- | --- |
| **Value** | Better rank and total points across a 38-gameweek season, and materially less time spent each week on manual research |
| **Cost** | £0 per month of running cost is a hard requirement (see NFR-01). Investment is the owner's build time |
| **Alternative considered** | Subscribing to an existing FPL analytics service. Rejected: recurring cost, no control over the model, no bespoke constraints, and no learning value |
| **Secondary benefit** | The repository is a genuine end-to-end data platform — ingestion, modelling, optimisation, delivery, observability — with real deadlines and a measurable outcome |

---

## 3. Objectives

Objectives are SMART. Each is traceable to requirements in §6 and to success criteria in §5.

| ID | Objective | Measure | Target date |
| --- | --- | --- | --- |
| **OBJ-1** | Maximise total FPL points in the 2026/27 season | Final points and overall rank | 30 May 2027 |
| **OBJ-2** | Produce an optimal, rule-legal 15-player squad for GW1 within a £100.0m budget | A squad is generated, explained and submitted before the GW1 deadline | 21 Aug 2026, 18:30 BST |
| **OBJ-3** | Recommend transfers every gameweek, accounting for availability, fixtures, price and predicted performance | A ranked, explained transfer recommendation exists before every deadline of the season | Every GW deadline |
| **OBJ-4** | Plan chip usage rather than react to it | A live chip calendar exists for both chip sets; set 1 fully used by the GW19 deadline | 2 Jan 2027 |
| **OBJ-5** | Provide a scouting interface for searching, filtering, comparing and trending player statistics | Scout UI usable on laptop and mobile, covering all Premier League players | Phase 4 exit |
| **OBJ-6** | Run at zero monthly cost, with no server to operate | Monthly infrastructure spend is £0.00 | Continuous |
| **OBJ-7** | Beat credible benchmarks, demonstrably | Backtested season score exceeds the template-team and overall-average benchmarks | Phase 2 exit, re-checked each half-season |

### Explicitly non-objectives

- Winning any specific mini-league. The system optimises the owner's team; other managers' behaviour
  is modelled only through ownership.
- Being a general-purpose football analytics platform.
- Serving other users, publishing content, or generating revenue.
- Automated team submission. Requires FPL credentials; excluded by DL-08.

---

## 4. Scope

### 4.1 In scope

- Ingestion from the official FPL API, Understat/FBref advanced statistics, and a bookmaker odds feed.
- A pluggable source-adapter framework so further sources can be added without touching downstream code.
- A conformed data layer covering players, teams, fixtures, appearances, per-gameweek performance,
  advanced metrics, odds and price history, plus full history for backtesting.
- An expected-points engine: availability/minutes, team strength, goal involvement, defensive
  contribution, bonus, saves and cards — producing a mean **and a variance** per player per fixture.
- A multi-gameweek MILP optimiser covering squad selection, transfers, hits, captaincy, bench order
  and chip timing, with a rank-aware risk dial.
- A responsive web application: dashboard, squad builder, transfer planner, scout, fixture ticker,
  model explainability and data health.
- Scheduled orchestration, data quality gates, structured logging, run metadata and lineage.
- A backtesting harness over historical seasons with walk-forward validation.
- Documentation and a test suite proportionate to a single-maintainer project.

### 4.2 Out of scope

- User accounts, authentication, and any use of the authenticated FPL `my-team` endpoint.
- Automated submission of transfers or team selection to the FPL site.
- Live in-play features during matches (live scores, live rank tracking).
- Draft FPL, other fantasy formats, other leagues or competitions.
- Native mobile applications. A responsive PWA covers the mobile requirement.
- Any paid data feed, paid hosting tier, or paid model API.

### 4.3 Deferred (candidates for a later phase)

| Item | Reason for deferral |
| --- | --- |
| Injury and press-conference news feeds | Valuable but source-unstable; adapter framework makes it a later drop-in (OD-04) |
| Full stochastic / Monte-Carlo optimisation | Deterministic MILP must be proven first; interface is designed to accept it (DL-06) |
| Multi-user support | Conflicts with zero-cost static hosting; no current need |
| Player-level bookmaker props (anytime scorer, shots on target) | Free-tier credit cost; revisit if the odds budget allows |

---

## 5. Success criteria

Three tiers. Tier 1 is the outcome that matters; tiers 2 and 3 are the leading indicators that the
system is doing its job.

### Tier 1 — Season outcome (OBJ-1)

| Level | Criterion |
| --- | --- |
| **Threshold** | Finish above the overall average score for the season |
| **Target** | Finish inside the **top 100k** overall rank |
| **Stretch** | Finish inside the **top 10k** overall rank |

This settles the rank *ambition*. It does not settle how aggressively the risk dial should default —
that is OD-05, and it is a temperament question rather than a target one.

### Tier 2 — Model quality (OBJ-7)

Measured on walk-forward backtests and, in-season, on rolling out-of-sample gameweeks.

**Every threshold here is expressed relative to a stated baseline, deliberately.** FPL points are
extremely noisy at player-gameweek granularity, and absolute thresholds on that noise are worse than
useless — they look rigorous while passing a model with no edge. Two examples from the original
version 1.0 of this charter, both corrected below:

- An absolute `MAE ≤ 2.1` sits in the range a **constant predictor** achieves on players who played.
- An absolute `Spearman ≥ 0.30` across all positions is plausibly reachable by a model knowing
  nothing but **price and position**, because price is FPL's own expected-value estimate and position
  explains much of the scoring rate.

#### The baseline

**B0** — a model whose only inputs are the player's position and current price, fitted on the same
training window as the real model. B0 is computed and reported by the backtest harness (E3-S1) on
every run. It costs almost nothing and it is the number that makes every other number mean something.

| Metric | Threshold | Target | Notes |
| --- | --- | --- | --- |
| Spearman rank correlation, **within position and price band**, predicted vs actual, per gameweek | ≥ B0 + 0.05 | ≥ B0 + 0.12 | Banding removes the trivially-learnable structure that forwards outscore defenders |
| **Skill score** — % reduction in MAE versus B0, per player-gameweek | ≥ 5% | ≥ 12% | Replaces the absolute MAE threshold. Absolute MAE is still *reported*, as a diagnostic, never as a gate |
| **Top-20 precision** — of the model's top 20 by expected points, how many finish in the actual top 20 | ≥ B0 + 2 players | ≥ B0 + 4 players | The decision-relevant measure: the optimiser only ever acts on the top of the ranking |
| Calibration slope of predicted vs realised (regression of actual on predicted) | 0.85 – 1.15 | 0.95 – 1.05 | Absolute, and correctly so — calibration is a property of the model, not a comparison |
| Minutes-model calibration — Brier score over the `{0, 1–59, 60+}` bands | ≥ 10% better than a "last-3-appearances" rule | ≥ 20% better | Promoted into tier 2 because minutes uncertainty is the largest single source of expected-points error |
| Captaincy hit rate — chosen captain is in the top 3 scorers of the owner's squad | ≥ 45% | ≥ 55% | **Backtest gate only.** Over a single season n = 38, so the standard error on a 50% rate is roughly 8 points — 45% and 55% are not distinguishable in-season and must not be reacted to as though they were |
| Backtested season score vs template-team benchmark | Beats it | Beats it by ≥ 100 pts | |
| Backtested season score vs a **model-free** benchmark — highest trailing-6-gameweek points, one transfer per week | Beats it | Beats it by ≥ 60 pts | The bar an unaided manager actually clears. A benchmark built on this project's own forecast cannot measure whether the forecast is any good |

These remain **provisional and expected to be recalibrated after the first backtest**, with the
recalibration recorded in the decision log. What is *not* negotiable is the form: relative to B0, not
absolute.

### Tier 3 — System quality (OBJ-6, and the non-functionals)

| Metric | Target |
| --- | --- |
| Monthly running cost | £0.00 |
| Scheduled pipeline success rate | ≥ 98% of runs |
| Data freshness at any deadline minus 2 hours | < 3 hours old |
| Deadline coverage — a current recommendation exists before the deadline | 38 / 38 gameweeks |
| Front-end p95 first contentful paint, mobile 4G | < 2.5 s |
| Unrecoverable data loss events | 0 |

---

## 6. Requirements

Requirements are numbered for traceability. `MoSCoW` column: **M**ust / **S**hould / **C**ould.

### 6.1 Functional requirements

#### Data acquisition and management

| ID | Requirement | MoSCoW | Objective |
| --- | --- | --- | --- |
| FR-01 | Ingest the official FPL API: players, teams, positions, gameweek events, fixtures, per-player histories, per-gameweek live stats, set-piece notes and game settings | M | OBJ-1..5 |
| FR-02 | Ingest advanced statistics from Understat and/or FBref: xG, npxG, xA, shots, key passes, progressive actions and defensive actions | M | OBJ-1, OBJ-3 |
| FR-03 | Ingest bookmaker odds for Premier League fixtures and derive team-level goal expectations and clean-sheet probabilities | M | OBJ-1, OBJ-3 |
| FR-04 | Provide a formal source-adapter interface with a registry, so a new source is onboarded by adding one adapter module plus a configuration entry, with **no changes to transformation, model or application code** | M | DL-05 |
| FR-05 | Retain immutable raw snapshots of every source response, addressable by run and timestamp, sufficient to fully reproduce any published output | M | NFR-6 |
| FR-06 | Backfill historical seasons to support model training and backtesting | M | OBJ-7 |
| FR-07 | Resolve player and team identities across sources into a single canonical entity, with a curated manual override file for unresolved cases | M | FR-02, FR-03 |
| FR-08 | Enforce schema, range, referential and freshness quality gates; a failing gate must block publication rather than release bad data | M | NFR-7 |
| FR-09 | Track player price changes and compute selling value including the 50% sell-on fee on profit | M | OBJ-3 |

#### Prediction

| ID | Requirement | MoSCoW | Objective |
| --- | --- | --- | --- |
| FR-10 | Forecast availability and minutes as a distribution over the 0 / 1–59 / 60+ bands, using FPL status flags, chance-of-playing, recent minutes and rotation patterns | M | OBJ-1, OBJ-3 |
| FR-11 | Forecast per-fixture team goals scored and conceded, blending odds-implied expectations with a rolling xG-based team-strength model | M | OBJ-1 |
| FR-12 | Forecast per-player expected points for each upcoming fixture, decomposed by scoring component (appearance, goals, assists, clean sheet, defensive contribution, bonus, saves, cards) | M | OBJ-1, OBJ-3 |
| FR-13 | Emit an uncertainty estimate (variance or predictive interval) alongside every expected-points figure | M | DL-06, OBJ-7 |
| FR-14 | Handle the preseason cold start — no current-season minutes — using priors from prior seasons, transfer/promotion adjustments, FPL's own initial pricing and early ownership as market signals | M | OBJ-2 |
| FR-15 | Implement the 2026/27 scoring rules exactly, including Defensive Contribution points and the revised Bonus Points System, sourcing rule parameters from the API where exposed rather than hardcoding them | M | OBJ-1 |
| FR-16 | Model ownership and effective ownership per player | M | OBJ-1, DL-07 |

#### Optimisation and recommendation

| ID | Requirement | MoSCoW | Objective |
| --- | --- | --- | --- |
| FR-17 | Generate an optimal 15-player initial squad within budget, satisfying all FPL squad rules | M | OBJ-2 |
| FR-18 | Optimise transfers over a rolling multi-gameweek horizon, correctly modelling free-transfer accrual, rollover to a maximum of five, and −4 point hits | M | OBJ-3 |
| FR-19 | Recommend starting XI, formation, captain, vice-captain and bench order for each gameweek | M | OBJ-1 |
| FR-20 | Recommend chip timing across both chip sets for Wildcard, Free Hit, Triple Captain and Bench Boost, honouring the GW19 expiry of set 1 | M | OBJ-4 |
| FR-21 | Expose a risk dial that shifts the objective between template-safe and differential-aggressive, and display the ownership bet each recommendation implies | M | OBJ-1, DL-07 |
| FR-22 | Accept user constraint overrides: lock a player in, ban a player, cap or fix budget, force a formation, exclude a club, force or forbid a chip in a given gameweek | S | OBJ-3 |
| FR-23 | Explain every recommendation — expected-points decomposition, the runner-up options and the marginal gain over doing nothing | M | Vision |
| FR-24 | Always evaluate and present the "no transfer, roll it" option as a first-class candidate | M | OBJ-3 |
| FR-25 | Load the current squad, bank, free-transfer count and chips used for a configurable team ID, reconstructing pre-deadline state from public endpoints, with a manual override for the gap described in DL-08 | M | DL-08 |

#### User experience

| ID | Requirement | MoSCoW | Objective |
| --- | --- | --- | --- |
| FR-26 | Dashboard showing the current squad, its expected points, the recommended action for the next deadline and a countdown | M | OBJ-3 |
| FR-27 | Scout view — search, filter and sort all Premier League players by position, club, price, form, ownership, expected points, underlying statistics and fixture difficulty | M | OBJ-5 |
| FR-28 | Compare two or more players side by side across statistics and expected points | M | OBJ-5 |
| FR-29 | Plot performance trends over time — points, xG, xA, minutes, defensive contributions, price, ownership — as charts | M | OBJ-5 |
| FR-30 | Fixture ticker with a model-derived difficulty rating over the next N gameweeks, sortable by team and by run quality | S | OBJ-3 |
| FR-31 | Transfer planner showing the multi-gameweek plan and chip calendar, with the ability to explore alternatives | S | OBJ-3, OBJ-4 |
| FR-32 | Mini-league and rival comparison for a configurable league ID | C | DL-08 |
| FR-33 | Data health and model performance page — freshness, run status, quality-gate results and rolling accuracy metrics | S | NFR-7 |
| FR-34 | Work on laptop and mobile browsers; installable as a PWA with the last-published data available offline | M | NFR-3 |

#### Platform operations

| ID | Requirement | MoSCoW | Objective |
| --- | --- | --- | --- |
| FR-35 | Refresh data, models and recommendations on a schedule, with cadence increasing as a deadline approaches | M | OBJ-3 |
| FR-36 | Provide manual on-demand execution of any pipeline stage for deadline-day reruns | M | OBJ-3 |
| FR-37 | Provide a backtesting harness that replays historical seasons with strict walk-forward discipline and no look-ahead | M | OBJ-7 |
| FR-38 | Alert the owner when a scheduled run fails or a quality gate blocks publication | S | NFR-7 |
| FR-39 | Run the full pipeline locally on the owner's Windows machine with the same code path as CI | M | NFR-9 |

### 6.2 Non-functional requirements

| ID | Requirement | Acceptance |
| --- | --- | --- |
| NFR-01 | **Zero running cost.** No paid hosting, database, data feed or API tier | Monthly spend £0.00 |
| NFR-02 | **No operated servers.** Nothing that must be kept running, patched or restarted | Architecture contains no long-lived compute |
| NFR-03 | **Multi-device access.** Usable on a laptop browser and a mobile browser, and reachable on the local network during development | Manual verification on both form factors |
| NFR-04 | **Performance.** p95 first contentful paint < 2.5 s on simulated mobile 4G; scout table interactions < 150 ms; initial data payload ≤ 3 MB with per-player detail lazy-loaded | Lighthouse and manual measurement |
| NFR-05 | **Freshness.** Player prices, status flags and ownership no more than 3 hours stale at deadline minus 2 hours | Freshness assertion in the quality gate |
| NFR-06 | **Reproducibility, logically.** Replaying a run from its recorded raw snapshots, code commit and configuration reproduces (a) a **byte-identical silver layer**, (b) the **same objective value** within solver tolerance, and (c) the **same published decisions** — squad, transfers, captain, chip. Byte-identical gold and web artefacts are *not* claimed: a MILP over a degenerate problem does not return a deterministic optimum, and threaded gradient boosting is not bitwise stable. Determinism of the *decision* is delivered by an explicit tie-break in the optimiser objective, not by hoping the solver is stable | Replay test in CI asserting (a), (b) and (c) |
| NFR-07 | **Observability.** Every run emits structured logs, a machine-readable manifest, quality-gate results and model metrics; all are queryable and surfaced in the app | Data health page renders from the manifest |
| NFR-08 | **Testability.** Scoring rules, price mechanics, transfer accounting and optimiser constraints are pure, unit-tested functions. Optimiser outputs are property-tested for FPL rule legality | Coverage ≥ 80% on the pipeline package; 100% on rules and constraint modules |
| NFR-09 | **Local/CI parity.** The same commands and code run locally and in CI; no CI-only code paths | Documented single-command local run |
| NFR-10 | **Legal and ethical data use.** Respect `robots.txt`, apply rate limiting and caching to scraped sources, identify the client honestly, use data for personal non-commercial purposes only, and attribute sources | Documented per source; rate limits enforced in the adapter base class |
| NFR-11 | **Privacy.** No FPL credentials are collected, stored or transmitted. No personal data beyond a public team ID | Code review; no auth code exists |
| NFR-12 | **Maintainability.** A single maintainer with intermittent availability can operate and extend the system; conventions are explicit enough for an AI coding agent to follow | Onboarding a new source measured against FR-04 |
| NFR-13 | **Security.** API keys live only in CI secrets, never in the repository or the client bundle. Published artefacts contain no secrets | Secret scanning in CI |
| NFR-14 | **Accessibility.** Keyboard navigable, sufficient colour contrast, charts readable without relying on colour alone, and legible in both light and dark themes | Axe audit on key views |
| NFR-15 | **Graceful degradation.** Failure of any single non-FPL source degrades model quality but must not break the pipeline or the app | Fault-injection test per adapter |

---

## 7. Constraints

| ID | Constraint | Impact |
| --- | --- | --- |
| CON-1 | GW1 deadline is 21 Aug 2026, 18:30 BST — immovable | Determines whether OBJ-2 is achievable at all; see plan §7 |
| CON-2 | Zero budget | Rules out paid feeds, managed databases and paid hosting tiers |
| CON-3 | No always-on compute (DL-03) | Interactive re-optimisation must be client-side or job-triggered |
| CON-4 | CI compute is time- and minute-limited | Optimiser must solve within minutes, not hours; drives candidate pruning |
| CON-5 | The FPL API is undocumented and unversioned | Schema drift is a live risk; contract tests and snapshots are mandatory |
| CON-6 | Understat and FBref are scraped, not licensed APIs | Rate limits, layout fragility and personal-use-only terms |
| CON-7 | Odds free tiers are credit-capped | Fetch cadence must be budgeted, not naive |
| CON-8 | Single part-time maintainer | Scope must be ruthlessly phased; automation over manual process |
| CON-9 | Windows development host, no Docker installed | Tooling must work natively on Windows or via CI |
| CON-10 | Pre-deadline squad state is not publicly exposed by the FPL API | Requires reconstruction plus a manual override (FR-25) |
| CON-11 | **The maintainer is in Australia (AEST/AEDT); every FPL deadline is in UK time.** Friday-night and midweek deadlines fall around 03:30 local, standard Saturday ones around 20:00 local. The offset moves from +9 to +11 within a few weeks each October, as the UK leaves BST and Australia enters AEDT | Automation is a requirement, not a convenience — the owner is asleep for a large share of deadlines. All scheduling arithmetic is UTC. FR-26 shows both zones. See [DL-11](00-decision-log.md#dl-11--store-and-compute-in-utc-render-in-local-time-only-at-the-ui-edge) |
| CON-12 | **Effective ownership is not directly computable.** `selected_by_percent` is public; captaincy share is exposed by no FPL endpoint, and overall ownership is a poor proxy for the top-100k template the tier-1 target implies | FR-16 and FR-21 rest on an estimated or redefined EO. See OD-06 |

## 8. Assumptions

| ID | Assumption | If false |
| --- | --- | --- |
| ASM-1 | The FPL API remains publicly accessible without authentication at current endpoints | Project is not viable in its current form; would need a licensed feed |
| ASM-2 | Understat and FBref remain accessible to polite, rate-limited, personal-use access | Model degrades to FPL-only signals; NFR-15 keeps the system running |
| ASM-3 | A bookmaker odds free tier remains available with a workable credit cap | Fall back to the xG-based team-strength model alone |
| ASM-4 | 2026/27 scoring rules are as published: Defensive Contribution retained, BPS revised, chips in two sets with set 1 expiring at the GW19 deadline, five-transfer rollover cap, no AFCON allowance | Rules module is isolated and parameterised specifically so this is a contained change |
| ASM-5 | Historical per-gameweek data for prior seasons is obtainable for training and backtesting | Model starts from priors only; backtest scope narrows |
| ASM-6 | The owner reviews recommendations and submits the team manually before each deadline | OBJ-1 is not achievable; the system produces advice nobody acts on |
| ASM-7 | Free CI and static hosting tiers remain sufficient for this workload | Fall back to running the pipeline locally on a schedule |
| ASM-8 | **The maintainer sustains 3–4 focused build days per week** from mid-August to ~GW30, on top of the ~0.5 day/week operating loop. This is what the epic target gameweeks assume, and it has no slack — the sequence to GW15 is ~60 focused days in 15 calendar weeks | The epic targets are wrong and must be re-baselined rather than quietly missed. The **chip calendar is the exposure that matters**, because GW19 expiry is irreversible — which is why a minimal chip-expiry tracker ships in E2, ahead of the real optimiser. See [plan §8](02-project-plan-and-blueprint.md#the-availability-assumption--asm-8) |

---

## 9. Stakeholders and roles

| Role | Who | Responsibility |
| --- | --- | --- |
| Sponsor / Product Owner | Repository owner | Sets objectives, approves scope changes, makes the final call at every deadline |
| Architect / Engineer | Owner, AI-assisted | Designs and builds all components |
| Model owner | Owner | Validates model quality, signs off backtest results |
| Operator | Owner | Responds to failed runs and blocked quality gates |
| End user | Owner | Uses the app to decide transfers |

Single-person project. Governance is deliberately lightweight — see §12.

---

## 10. Key dates

| Date | Event | Significance |
| --- | --- | --- |
| 2026-08-09 | Charter baselined | Today. 12 days to the GW1 deadline |
| 2026-08-21 18:30 BST | **GW1 deadline** | OBJ-2 hard deadline |
| 2026-08-21 | Season starts, Arsenal v Coventry City | First live data |
| 2027-01-02 13:30 GMT | **GW19 deadline** | Chip set 1 expires (OBJ-4) |
| 2027-05-30 | Final match round | OBJ-1 measured |

---

## 11. High-level risks

Full RAID log in [02-project-plan-and-blueprint.md](02-project-plan-and-blueprint.md) §6. The five
that could kill the project:

| ID | Risk | Impact | Likelihood | Response |
| --- | --- | --- | --- | --- |
| R-01 | GW1 arrives before anything is usable, so the flagship objective is missed | High | **High** — 12 days | Accept and re-baseline OBJ-2, or trigger the fast-lane track in plan §7 |
| R-02 | FPL API changes shape or starts blocking automated access | High | Medium | Adapter isolation, recorded-response contract tests, cached snapshots, polite rate limiting |
| R-03 | The model is not actually better than intuition, so the whole edifice adds no value | High | Medium | Backtest against benchmarks before trusting it (OBJ-7); ship the scout UI, which has standalone value regardless |
| R-04 | Overfitting to historical data produces confident, wrong forecasts | Medium | High | Strict walk-forward validation, held-out season, calibration monitoring in-season |
| R-05 | Build stalls mid-season and the half-built system is worse than no system | Medium | Medium | Every phase must exit in a usable state; scout UI and expected-points table ship before the optimiser |

---

## 12. Governance and change control

- **Cadence.** Weekly, aligned to the gameweek: review last week's recommendation against the actual
  outcome, check model drift, decide the coming week's build increment.
- **Decisions.** Any architectural or product decision is recorded in
  [00-decision-log.md](00-decision-log.md) before implementation. Superseding, never editing.
- **Scope change.** Changes to §4 or §6 require a new decision-log entry stating what is being traded
  away. Adding scope without removing scope is the primary failure mode for a solo project.
- **Baselines.** This charter is baselined at 2026-08-09. Material changes bump the version and note
  what changed.
- **Quality bar.** The definition of done in §13 applies to every increment; "it works on my machine
  once" does not count.

---

## 13. Definition of done

An increment is done when all of the following hold.

1. The requirement IDs it satisfies are listed in the pull request or commit message.
2. Unit tests cover the new logic; rules, price and constraint code is fully covered.
3. It runs end-to-end in CI on a clean checkout, not only locally.
4. It emits structured logs and contributes to the run manifest.
5. Relevant quality gates exist and pass, and its failure mode has been tested.
6. Documentation under `docs/` is updated in the same change.
7. Any decision it embodies is in the decision log.
8. The user-visible result has been checked on both a laptop and a mobile viewport.

### The one dated exception — E0

**Item 3 does not apply to [epic E0](epics/E0-steel-thread-gw1.md), the steel thread to GW1.** E0 runs
entirely locally and deliberately has no CI, because standing up workflows, hosting and secrets before
21 August would put OD-03 and the hosting decision on the critical path of a fixed deadline for no
gain in squad quality.

This exception is **narrow, dated and single-use**:

- It covers E0 only, and expires when E0 does — 22 August 2026.
- Items 1, 2 and 4–8 still apply to E0 in full. Item 8 is satisfied by E0-S7 unless that story is cut
  under the emergency-cut plan, in which case it is waived with the cut.
- **[E7](epics/E7-automation-and-hosting.md) repays it**, tracked as debt item D-08. The first CI
  workflow must run the E0 code path unchanged; any E0 code that turns out not to run in CI is a
  defect against the debt register, not a new requirement.

Recorded so that the first increment does not break the quality bar silently, which is how a quality
bar stops being one. No further exceptions without a decision-log entry.

---

## 14. Approval

| Item | Value |
| --- | --- |
| Charter version | **1.1** |
| Baselined | 2026-08-09 (v1.0) |
| Amended | 2026-08-09 (v1.1) — see [DL-13](00-decision-log.md#dl-13--charter-amendments-following-the-2026-08-09-architecture-and-plan-audit) |
| Approved by | Repository owner |
| Next review | At GW1 outcome, or on any change to §4 |

### Change history

| Version | Date | What changed |
| --- | --- | --- |
| 1.0 | 2026-08-09 | Initial baseline |
| 1.1 | 2026-08-09 | §5 tier-2 metrics made baseline-relative and given a defined baseline B0, with top-20 precision, a minutes-calibration gate and a model-free season benchmark added; NFR-06 downgraded from byte-for-byte to logical reproducibility; CON-11 (maintainer timezone) and CON-12 (effective ownership not computable) added; §13 given a dated pre-CI carve-out for E0; §5 tier 1 reconciled with OD-05; `NFR-1` typo in §2 corrected. No requirement removed; no scope added |
