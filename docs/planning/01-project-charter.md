# Project Charter — FPL DOF

**Project:** FPL DOF — a decision-support platform for Fantasy Premier League
**Season in scope:** 2026/27 (21 August 2026 – 30 May 2027)
**Document status:** Baselined 2026-08-09 · **Version 1.2**, revised 2026-10-17 · R1.0 delivered;
R1.1.0 open ([release register](epics/README.md))
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
| **Cost** | £0 per month of running cost is a hard requirement (NFR-01). Investment is the owner's build time |
| **Alternative considered** | Subscribing to an existing FPL analytics service. Rejected: recurring cost, no control over the model, no bespoke constraints, and no learning value |
| **Secondary benefit** | The repository is a genuine end-to-end data platform — ingestion, modelling, optimisation, delivery, observability — with real deadlines and a measurable outcome |

---

## 3. Objectives

Objectives are SMART. Each is traceable to requirements in §6 and to success criteria in §5.

| ID | Objective | Measure | Target date |
| --- | --- | --- | --- |
| **OBJ-1** | Maximise total FPL points in the 2026/27 season | Final points and overall rank | 30 May 2027 |
| **OBJ-2** | Produce an optimal, rule-legal 15-player squad for GW1 within a £100.0m budget | A squad is generated, explained and submitted before the GW1 deadline | 21 Aug 2026, 18:30 BST — passed (§10) |
| **OBJ-3** | Recommend transfers every gameweek, accounting for availability, fixtures, price and predicted performance | A ranked, explained transfer recommendation exists before every deadline of the season | Every GW deadline |
| **OBJ-4** | Plan chip usage rather than react to it | A live chip calendar exists for both chip sets; set 1 fully used by the GW19 deadline | 1 Jan 2027, 18:30 GMT |
| **OBJ-5** | Provide a scouting interface for searching, filtering, comparing and trending player statistics | Scout UI usable on laptop and mobile, covering all Premier League players | Delivered in R1.0 |
| **OBJ-6** | Run at zero monthly cost, with no server to operate | Monthly infrastructure spend is £0.00 | Continuous |
| **OBJ-7** | Beat credible benchmarks, demonstrably | Backtested season score exceeds the template-team and overall-average benchmarks; the verdict is on the model card (DL-21) | Every backtest run; re-checked each half-season |

### Explicitly non-objectives

- Winning any specific mini-league. The system optimises the owner's team; other managers' behaviour
  is modelled only through ownership.
- Being a general-purpose football analytics platform.
- Serving other users, publishing content, or generating revenue.
- Automated team submission. Requires FPL credentials; excluded by DL-08.

---

## 4. Scope

### 4.1 In scope

- Ingestion from the official FPL API (including its expected-goals fields, DL-34), the FPL
  community archive for past seasons (DL-19), and advanced statistics and odds wherever a free source
  can be reached politely. Each source and its state: [03 §2](03-solution-architecture.md#2-context-view-c4-level-1).
- A pluggable source-adapter framework so further sources can be added without touching downstream code.
- A conformed data layer covering players, teams, fixtures, appearances, per-gameweek performance,
  advanced metrics, odds and price history, plus full history for backtesting.
- An expected-points engine: availability/minutes, team strength, goal involvement, defensive
  contribution, bonus, saves and cards — producing a mean **and a variance** per player per fixture.
- A multi-gameweek MILP optimiser covering squad selection, transfers, hits, captaincy, bench order
  and chip timing, with a rank-aware risk dial.
- A responsive web application: dashboard, squad builder, transfer planner, scout, fixture ticker,
  model comparison and hindsight review, season log, mini-league, settings and data health.
- Scheduled orchestration, data quality gates, structured logging, run metadata and lineage.
- A backtesting harness over historical seasons with walk-forward validation.
- Documentation and a test suite proportionate to a single-maintainer project.

How each is built is in the [solution architecture](03-solution-architecture.md).

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
| Injury and press-conference news feeds | Valuable but source-unstable; adapter framework makes it a later drop-in. Not this season: the FPL API's availability fields suffice (OD-04, closed by DL-79) |
| Full stochastic / Monte-Carlo optimisation | Deterministic MILP must be proven first; interface is designed to accept it (DL-06) |
| Multi-user support | Conflicts with zero-cost static hosting; no current need |
| Player-level bookmaker props (anytime scorer, shots on target) | No free source with workable credits (D-20) |

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

This settles the rank *ambition*. How aggressively the risk dial defaults is a separate,
temperament question: Balanced (DL-25).

### Tier 2 — Model quality (OBJ-7)

Measured on walk-forward backtests and, in-season, on rolling out-of-sample gameweeks.

**Every threshold is relative to a stated baseline, deliberately.** At player-gameweek granularity
FPL points are so noisy that absolute thresholds pass a model with no edge ([DL-13](../decisions/DL-13.md)).

#### The baseline

**B0** — a model whose only inputs are the player's position and current price, fitted on the same
training window as the real model. B0 is computed and reported by the backtest harness
(`forecast/baselines.py`) on every run. It is the number that makes every other number mean something.

| Metric | Threshold | Target | Notes |
| --- | --- | --- | --- |
| Spearman rank correlation, **within position and price band**, predicted vs actual, per gameweek | ≥ B0 + 0.05 | ≥ B0 + 0.12 | Banding removes the trivially-learnable structure that forwards outscore defenders |
| **Skill score** — % reduction in MAE versus B0, per player-gameweek | ≥ 5% | ≥ 12% | Absolute MAE is *reported*, as a diagnostic, never as a gate |
| **Top-20 precision** — of the model's top 20 by expected points, how many finish in the actual top 20 | ≥ B0 + 2 players | ≥ B0 + 4 players | The decision-relevant measure: the optimiser only ever acts on the top of the ranking. Scored per gameweek (DL-49) |
| Calibration slope of predicted vs realised (regression of actual on predicted) | 0.85 – 1.15 | 0.95 – 1.05 | Absolute, and correctly so — calibration is a property of the model, not a comparison |
| Minutes-model calibration — Brier score over the `{0, 1–59, 60+}` bands | ≥ 10% better than a "last-3-appearances" rule | ≥ 20% better | Minutes uncertainty is the largest single source of expected-points error |
| Captaincy hit rate — chosen captain is in the top 3 scorers of the owner's squad | ≥ 45% | ≥ 55% | **Backtest gate only.** At n = 38 the standard error on a 50% rate is ~8 points, so in-season movement is noise |
| Backtested season score vs template-team benchmark | Beats it | Beats it by ≥ 100 pts | |
| Backtested season score vs a **model-free** benchmark — highest trailing-6-gameweek points, one transfer per week | Beats it | Beats it by ≥ 60 pts | The bar an unaided manager clears; a benchmark built on this project's own forecast cannot judge it |

The first backtest was reported against these, not tuned to them (DL-21); the verdict is on the
model card. Recalibrating a threshold is a decision; the form — relative to B0 — is not negotiable.

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

Requirements are numbered for traceability; an ID is never renumbered or reused. `MoSCoW` column:
**M**ust / **S**hould / **C**ould. **Status** (as of 2026-10-17): Met / Partial / Not built /
Deferred / Withdrawn / Unverified, with the evidence. Paths are under `pipeline/src/fpl_dof/` or
`web/src/` unless shown otherwise.

### 6.1 Functional requirements

#### Data acquisition and management

| ID | Requirement | MoSCoW | Objective | Status |
| --- | --- | --- | --- | --- |
| FR-01 | Ingest the official FPL API: players, teams, positions, gameweek events, fixtures, per-player histories, per-gameweek live stats, set-piece notes and game settings | M | OBJ-1..5 | Met: `sources/fpl` |
| FR-02 | Ingest advanced statistics from Understat and/or FBref: xG, npxG, xA, shots, key passes, progressive actions and defensive actions | M | OBJ-1, OBJ-3 | Partial: adapters built, both blocked upstream (D-23); xG/xA come from the FPL API instead (DL-34) |
| FR-03 | Ingest bookmaker odds for Premier League fixtures and derive team-level goal expectations and clean-sheet probabilities | M | OBJ-1, OBJ-3 | Partial: `sources/oddsapi` credit-capped with no history (D-20, DL-59); football-data.co.uk read only by the prospective harness (DL-73) |
| FR-04 | Provide a formal source-adapter interface with a registry, so a new source is onboarded by adding one adapter module plus a configuration entry, with **no changes to transformation, model or application code** | M | DL-05 | Met: `sources/registry.py`; one source read outside it (03 §12 P5) |
| FR-05 | Retain immutable raw snapshots of every source response, addressable by run and timestamp, sufficient to fully reproduce any published output | M | NFR-06 | Partial: bronze with lineage; kept ~30 days only — the per-gameweek permanent archive has never been written (PIPE-14); no replay proven |
| FR-06 | Backfill historical seasons to support model training and backtesting | M | OBJ-7 | Met: `sources/fplarchive`, `backtest.yml` (DL-68) |
| FR-07 | Resolve player and team identities across sources into a single canonical entity, with a curated manual override file for unresolved cases | M | FR-02, FR-03 | Met: `sources/resolve.py`; unexercised on external data (D-07) |
| FR-08 | Enforce schema, range, referential and freshness quality gates; a failing gate must block publication rather than release bad data | M | NFR-07 | Met: `quality/` |
| FR-09 | Track player price changes and compute selling value including the 50% sell-on fee on profit | M | OBJ-3 | Partial: selling value in `squad/state.py`; `price_history` loses history between CI runs (PIPE-06) |

#### Prediction

| ID | Requirement | MoSCoW | Objective | Status |
| --- | --- | --- | --- | --- |
| FR-10 | Forecast availability and minutes as a distribution over the 0 / 1–59 / 60+ bands, using FPL status flags, chance-of-playing, recent minutes and rotation patterns | M | OBJ-1, OBJ-3 | Met: M1 (DL-48) |
| FR-11 | Forecast per-fixture team goals scored and conceded, blending odds-implied expectations with a rolling xG-based team-strength model | M | OBJ-1 | Partial: xG team ratings dark (DL-56); market blend built, not wired (DL-60) |
| FR-12 | Forecast per-player expected points for each upcoming fixture, decomposed by scoring component (appearance, goals, assists, clean sheet, defensive contribution, bonus, saves, cards) | M | OBJ-1, OBJ-3 | Met: `forecast/xp_v1.py` (DL-46) |
| FR-13 | Emit an uncertainty estimate (variance or predictive interval) alongside every expected-points figure | M | DL-06, OBJ-7 | Met: modelled variance in `xp_v1` |
| FR-14 | Handle the preseason cold start — no current-season minutes — using priors from prior seasons, transfer/promotion adjustments, FPL's own initial pricing and early ownership as market signals | M | OBJ-2 | Met: priors; `xp_v0` fallback (DL-46) |
| FR-15 | Implement the 2026/27 scoring rules exactly, including Defensive Contribution points and the revised Bonus Points System, sourcing rule parameters from the API where exposed rather than hardcoding them | M | OBJ-1 | Met: `rules/`, 100% coverage gate (DL-17) |
| FR-16 | Model ownership and effective ownership per player, effective ownership estimated without a captaincy term (DL-24) | M | OBJ-1, DL-07 | Met: `optimise/risk.py` |

#### Optimisation and recommendation

| ID | Requirement | MoSCoW | Objective | Status |
| --- | --- | --- | --- | --- |
| FR-17 | Generate an optimal 15-player initial squad within budget, satisfying all FPL squad rules; preseason only, skipped in-season with a reason (DL-67) | M | OBJ-2 | Met: `optimise/squad.py` |
| FR-18 | Optimise transfers over a rolling multi-gameweek horizon, correctly modelling free-transfer accrual, rollover to a maximum of five, and −4 point hits | M | OBJ-3 | Met: `optimise/horizon.py` (DL-15) |
| FR-19 | Recommend starting XI, formation, captain, vice-captain and bench order for each gameweek | M | OBJ-1 | Met: `squad/selection.py`, `optimise/captain.py` |
| FR-20 | Recommend chip timing across both chip sets for Wildcard, Free Hit, Triple Captain and Bench Boost, honouring the GW19 expiry of set 1 | M | OBJ-4 | Met: `optimise/chips.py`; timing quality unproven (DL-28, D-21) |
| FR-21 | Expose a risk dial that shifts the objective between template-safe and differential-aggressive, defaulting to Balanced (DL-25), and display the ownership bet each recommendation implies | M | OBJ-1, DL-07 | Partial: dial set in configuration, shown not selectable in the app; most-captained callout absent (D-15) |
| FR-22 | Accept user constraint overrides: lock a player in, ban a player, cap or fix budget, force a formation, exclude a club, force or forbid a chip in a given gameweek | S | OBJ-3 | Met: optimiser configuration; lock and ban also in the app (`reoptimise.ts`) |
| FR-23 | Explain every recommendation — expected-points decomposition, the runner-up options and the marginal gain over doing nothing | M | Vision | Met: `optimise/explain.py`, `PlanPanel.tsx` |
| FR-24 | Always evaluate and present the "no transfer, roll it" option as a first-class candidate | M | OBJ-3 | Met: runners-up table |
| FR-25 | Load the current squad, bank, free-transfer count and chips used for a configurable team ID, reconstructing pre-deadline state from public endpoints, with a manual override for the gap described in DL-08 (DL-20) | M | DL-08 | Met: `squad/state.py` |
| FR-41 | Record every candidate model's advice before each deadline, then score it against actual points under the game's rules and rank the models weekly (DL-72) | S | OBJ-3, OBJ-7 | Met: `week/`, `log.json`, `/models` |
| FR-42 | After each gameweek, solve the hindsight-optimal legal transfers and XI for the owner's pre-deadline squad, and show how each model rated those moves before the deadline (DL-72) | S | OBJ-7 | Met: `week/oracle.py`, `HindsightSection.tsx` |

#### User experience

| ID | Requirement | MoSCoW | Objective | Status |
| --- | --- | --- | --- | --- |
| FR-26 | Dashboard showing the current squad, its expected points, the recommended action for the next deadline and a countdown | M | OBJ-3 | Met: `DashboardRoute.tsx` |
| FR-27 | Scout view — search, filter and sort all Premier League players by position, club, price, form, ownership, expected points, underlying statistics and fixture difficulty | M | OBJ-5 | Met: `ScoutRoute.tsx` (DL-36) |
| FR-28 | Compare two or more players side by side across statistics and expected points | M | OBJ-5 | Met: `CompareRoute.tsx` |
| FR-29 | Plot performance trends over time — points, xG, xA, minutes, defensive contributions, price, ownership — as charts | M | OBJ-5 | Met: `history.json` (DL-37) |
| FR-30 | Fixture ticker with a model-derived difficulty rating over the next N gameweeks, sortable by team and by run quality | S | OBJ-3 | Met: `FixturesRoute.tsx` (DL-37) |
| FR-31 | Transfer planner showing the multi-gameweek plan and chip calendar, with the ability to explore alternatives | S | OBJ-3, OBJ-4 | Met: `SquadRoute.tsx`, `PlanPanel.tsx` |
| FR-32 | Mini-league and rival comparison for a configurable league ID | C | DL-08 | Met: `league.json` (DL-40) |
| FR-33 | Data health and model performance page — freshness, run status, quality-gate results and rolling accuracy metrics | S | NFR-7 | Met: `/health`, `/models` (DL-41) |
| FR-34 | Work on laptop and mobile browsers; installable as a PWA with the last-published data available offline | M | NFR-3 | Met: `vite-plugin-pwa` (DL-38) |
| FR-40 | Let the owner enter their team ID and mini-league ID in a Settings view, stored only in browser `localStorage`, to personalise already-published artefacts and compose an owner-triggered pipeline dispatch link | M | OBJ-5, DL-44 | Met: `SettingsRoute.tsx` (DL-64) |

#### Platform operations

| ID | Requirement | MoSCoW | Objective | Status |
| --- | --- | --- | --- | --- |
| FR-35 | Refresh data, models and recommendations on a schedule, with cadence increasing as a deadline approaches | M | OBJ-3 | Met: workflows (03 §9) |
| FR-36 | Provide manual on-demand execution of any pipeline stage for deadline-day reruns | M | OBJ-3 | Met: `fpl-dof <stage>`, `workflow_dispatch` |
| FR-37 | Provide a backtesting harness that replays historical seasons with strict walk-forward discipline and no look-ahead | M | OBJ-7 | Met: `forecast/backtest.py` |
| FR-38 | Alert the owner when a scheduled run fails or a quality gate blocks publication | S | NFR-7 | Met: `alert-on-failure.yml` |
| FR-39 | Run the full pipeline locally on the owner's Windows machine with the same code path as CI | M | NFR-9 | Met: `fpl-dof run` |

### 6.2 Non-functional requirements

| ID | Requirement | Acceptance | Status |
| --- | --- | --- | --- |
| NFR-01 | **Zero running cost.** No paid hosting, database, data feed or API tier | Monthly spend £0.00 | Met: 03 §5.3 |
| NFR-02 | **No operated servers.** Nothing that must be kept running, patched or restarted | Architecture contains no long-lived compute | Met: static Pages plus Actions |
| NFR-03 | **Multi-device access.** Usable on a laptop browser and a mobile browser, and reachable on the local network during development | Manual verification on both form factors | Met: `web/verify/`; Vite `host: true` |
| NFR-04 | **Performance.** p95 first contentful paint < 2.5 s on simulated mobile 4G; scout table interactions < 150 ms; initial data payload ≤ 3 MB with per-player detail lazy-loaded | Lighthouse and manual measurement | Met: measured (DL-38); budgets in `verify:browser`, not run in CI |
| NFR-05 | **Freshness.** Player prices, status flags and ownership no more than 3 hours stale at deadline minus 2 hours | Freshness assertion in the quality gate | Met: `snapshot_freshness` gate; hourly `ingest-fast.yml` |
| NFR-06 | **Reproducibility, logically.** Replaying a run from its recorded raw snapshots, code commit and configuration reproduces (a) a **byte-identical silver layer**, (b) the **same objective value** within solver tolerance, and (c) the **same published decisions** — squad, transfers, captain, chip. Gold and web artefacts need not be byte-identical; the decision is made deterministic by an explicit tie-break in the optimiser objective (DL-13) | Replay test in CI asserting (a), (b) and (c) | Partial: tie-break built; no replay test; clock read several times (03 §12 P4) |
| NFR-07 | **Observability.** Every run emits structured logs, a machine-readable manifest, quality-gate results and model metrics; all are queryable and surfaced in the app | Data health page renders from the manifest | Met: `obs/`, `health.json` |
| NFR-08 | **Testability.** Scoring rules, price mechanics, transfer accounting and optimiser constraints are pure, unit-tested functions. Optimiser outputs are property-tested for FPL rule legality | Coverage ≥ 80% on the pipeline package; 100% on rules and constraint modules | Partial: 100% gated on `rules` only; no package-wide or constraint-module gate |
| NFR-09 | **Local/CI parity.** The same commands and code run locally and in CI; no CI-only code paths | Documented single-command local run | Met: CLAUDE.md commands |
| NFR-10 | **Legal and ethical data use.** Respect `robots.txt`, apply rate limiting and caching to scraped sources, identify the client honestly, use data for personal non-commercial purposes only, and attribute sources | Documented per source; rate limits enforced in the adapter base class | Partial: `sources/fetch.py`, `sources/robots.py`; football-data.co.uk fetched around them (03 §12 P5) |
| NFR-11 | **Privacy.** No FPL credentials are collected, stored or transmitted. No personal data beyond a public team ID | Code review; no auth code exists | Met: DL-44 |
| NFR-12 | **Maintainability.** A single maintainer with intermittent availability can operate and extend the system; conventions are explicit enough for an AI coding agent to follow | Onboarding a new source measured against FR-04 | Partial: the one source added since R1.0 bypassed the adapter seam (03 §12 P5) |
| NFR-13 | **Security.** API keys live only in CI secrets, never in the repository or the client bundle. Published artefacts contain no secrets | Secret scanning in CI | Partial: secrets in Actions only; scanning is a local commit hook, not a CI step |
| NFR-14 | **Accessibility.** Keyboard navigable, sufficient colour contrast, charts readable without relying on colour alone, and legible in both light and dark themes | Keyboard navigation and contrast checks on key views in both themes (`verify:browser`), token contrast tests (`theme/contrast.test.ts`), and every chart readable without colour (owner, 2026-10-17: replaces an axe audit) | Met: `web/verify/`, `theme/contrast.test.ts` |
| NFR-15 | **Graceful degradation.** Failure of any single non-FPL source degrades model quality but must not break the pipeline or the app | Fault-injection test per adapter | Met: `tests/test_source_degradation.py` |

---

## 7. Constraints

| ID | Constraint | Impact |
| --- | --- | --- |
| CON-1 | Every gameweek deadline is immovable; GW1 was 21 Aug 2026, 18:30 BST | Scheduling is deadline-aware, with a day-before run and manual dispatch as fallback (03 §9) |
| CON-2 | Zero budget | Rules out paid feeds, managed databases and paid hosting tiers |
| CON-3 | No always-on compute (DL-03) | Interactive re-optimisation must be client-side or job-triggered |
| CON-4 | CI compute is time- and minute-limited | Optimiser must solve within minutes, not hours; drives candidate pruning |
| CON-5 | The FPL API is undocumented and unversioned | Schema drift is a live risk; contract tests and snapshots are mandatory |
| CON-6 | Understat and FBref are scraped, not licensed APIs, and both now refuse automated access (D-23) | Rate limits, layout fragility and personal-use-only terms; a block is honoured, never worked around |
| CON-7 | Odds free tiers are credit-capped | Fetch cadence must be budgeted, not naive (D-20) |
| CON-8 | Single part-time maintainer | Scope must be ruthlessly phased; automation over manual process |
| CON-9 | Windows development host, no Docker installed | Tooling must work natively on Windows or via CI |
| CON-10 | Pre-deadline squad state is not publicly exposed by the FPL API | Requires reconstruction plus a manual override (FR-25, DL-20) |
| CON-11 | **The maintainer is in Australia (AEST/AEDT); every FPL deadline is in UK time**, many of them in the local small hours; the offset moves from +9 to +11 each October | Automation is a requirement — the owner is asleep for many deadlines. Scheduling arithmetic is UTC; FR-26 shows both zones ([DL-11](../decisions/DL-11.md)) |
| CON-12 | **Effective ownership is not directly computable.** `selected_by_percent` is public; captaincy share is exposed by no FPL endpoint, and overall ownership is a poor proxy for the top-100k template the tier-1 target implies | FR-16 and FR-21 rest on a redefined EO without a captaincy term ([DL-24](../decisions/DL-24.md)) |

## 8. Assumptions

| ID | Assumption | If false |
| --- | --- | --- |
| ASM-1 | The FPL API remains publicly accessible without authentication at current endpoints | Project is not viable in its current form; would need a licensed feed |
| ASM-2 | Understat and FBref remain accessible to polite, rate-limited, personal-use access. **Proved false** (D-23) | Model degrades to FPL-only signals; NFR-15 keeps the system running — as it did |
| ASM-3 | A bookmaker odds free tier remains available with a workable credit cap | Fall back to the xG-based team-strength model alone. The Odds API tier has no history (D-20); football-data.co.uk is the alternative (PIPE-04) |
| ASM-4 | 2026/27 scoring rules are as published: Defensive Contribution retained, BPS revised, chips in two sets with set 1 expiring at the GW19 deadline, five-transfer rollover cap, no AFCON allowance | Rules module is isolated and parameterised specifically so this is a contained change |
| ASM-5 | Historical per-gameweek data for prior seasons is obtainable for training and backtesting | Model starts from priors only; backtest scope narrows |
| ASM-6 | The owner reviews recommendations and submits the team manually before each deadline | OBJ-1 is not achievable; the system produces advice nobody acts on |
| ASM-7 | Free CI and static hosting tiers remain sufficient for this workload | Fall back to running the pipeline locally on a schedule |
| ASM-8 | The maintainer sustains 3–4 focused build days per week to ~GW30, plus the ~0.5 day/week operating loop. **Wrong in the favourable direction**: agent-driven building is far faster, so the season clock and evidence pace the work ([DL-23](../decisions/DL-23.md)) | Re-baseline if human pace becomes the constraint; the chip calendar is the exposure, because GW19 expiry is irreversible |

---

## 9. Stakeholders and roles

Single-person project. The repository owner is sponsor and product owner (sets objectives, approves
scope changes, makes the final call at every deadline), engineer (AI-assisted), model owner (signs off
backtest results), operator (responds to failed runs and blocked gates) and end user. Governance is
deliberately lightweight — see §12.

---

## 10. Key dates

| Date | Event | Significance |
| --- | --- | --- |
| 2026-08-09 | Charter baselined | 12 days before the GW1 deadline |
| 2026-08-21 18:30 BST | **GW1 deadline** — passed | E0 produced a legal squad in time; the owner decided GW1–GW4 without the tool, so no advice is recorded for them (DL-69) |
| 2026-10-17 10:00 UTC | GW7 deadline; R1.0 closed and archived, R1.1.0 opened | [Release register](epics/README.md) (DL-74) |
| 2027-01-01 18:30 GMT | **GW19 deadline** | Chip set 1 (GW1–19) expires (OBJ-4); set 2 covers GW20–38 |
| 2027-05-30 | Final match round | OBJ-1 measured |

The season's dated decision points and their outcomes are kept in
[E8's season state](epics/E8-ongoing-in-season-monitoring.md#decision-points).

---

## 11. High-level risks

Risks, their current ratings and responses live in the RAID log,
[02-project-plan-and-blueprint.md](02-project-plan-and-blueprint.md) §6. R-01 to R-05 are the ones
that could kill the project.

---

## 12. Governance and change control

- **Cadence.** Weekly, aligned to the gameweek: the loop in
  [E8 §2](epics/E8-ongoing-in-season-monitoring.md#2-the-weekly-loop). Build work is chosen and
  released through the [release register](epics/README.md) (`Rx.y.z`).
- **Decisions.** Any architectural or product decision is recorded in
  [`docs/decisions/`](../decisions/README.md), one file per entry, before implementation. Superseding,
  never editing.
- **Principles.** Ten binding, amendment-controlled design principles
  ([`DESIGN-PRINCIPLES.md`](../DESIGN-PRINCIPLES.md) v2.0) and five editable guiding ones
  ([`guiding-principles.md`](../guiding-principles.md)), split by [DL-75](../decisions/DL-75.md).
- **Scope change.** Changes to §4 or §6 require a new decision-log entry stating what is being traded
  away. Adding scope without removing scope is the primary failure mode for a solo project.
- **Baselines.** This charter is baselined at 2026-08-09. Material changes bump the version and are
  recorded in §14.
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
6. Documentation under `docs/` is updated in the same change, and `python scripts/docs.py check` passes.
7. Any decision it embodies is in `docs/decisions/`.
8. The user-visible result has been checked on both a laptop and a mobile viewport.

### The one dated exception — E0

No exception is in force. The only one, a pre-CI carve-out for the steel thread to GW1 under
[DL-10](../decisions/DL-10.md), expired with [E0](archive/R1.0/E0-steel-thread-gw1.md); further
exceptions need a decision-log entry.

---

## 14. Approval

| Item | Value |
| --- | --- |
| Charter version | **1.2** |
| Baselined | 2026-08-09 (v1.0) |
| Amended | 2026-08-09 (v1.1, [DL-13](../decisions/DL-13.md)); 2026-10-17 (v1.2) |
| Approved by | Repository owner (v1.0, v1.1); v1.2 drafted by an agent, pending the owner's review |
| Next review | End-of-season retrospective against §5, or on any change to §4 or §6 |

### Change history

| Version | Date | What changed |
| --- | --- | --- |
| 1.0 | 2026-08-09 | Initial baseline |
| 1.1 | 2026-08-09 | §5 tier-2 metrics made baseline-relative and given a defined baseline B0, with top-20 precision, a minutes-calibration gate and a model-free season benchmark added; NFR-06 downgraded from byte-for-byte to logical reproducibility; CON-11 (maintainer timezone) and CON-12 (effective ownership not computable) added; §13 given a dated pre-CI carve-out for E0; §5 tier 1 reconciled with OD-05; `NFR-1` typo in §2 corrected. No requirement removed; no scope added |
| 1.2 | 2026-10-17 | Rewritten to the close of R1.0: Status column on every FR and NFR; FR-41, FR-42 listed from DL-72; FR-16/17/21/25 read as amended by DL-24/67/25/20; §4.1, §7–§12 brought up to date; §13's expired E0 carve-out reduced to a pointer. No requirement removed |
