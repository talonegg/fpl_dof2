# Project Plan and Blueprint — FPL DOF

**Companion to:** [01-project-charter.md](01-project-charter.md) · **Baselined:** 2026-08-09 ·
**Revised:** 2026-10-17

How the work is run: the blueprint, the delivery strategy, the season calendar and the RAID log.
Architecture is in [03](03-solution-architecture.md), component design in
[04](04-conceptual-design.md).

> **Status at 2026-10-17, GW7 deadline day.** In season. R1.0 (epics E0–E14) is delivered and
> archived; R1.1.0, the data pipeline uplift, is delivered, R1.2.x and R1.3.x tagged and R1.4.0, the UI redesign, open; where the season stands is
> [E8's season state](epics/E8-ongoing-in-season-monitoring.md). The plan of record is the
> [release register](epics/README.md); shortcuts are in the [debt register](debt-register.md).
> §3, §4, §7 and §8 were superseded by the epics (DL-10) and archived in
> [02-superseded-sections.md](archive/02-superseded-sections.md) (DL-74).

---

## 1. The blueprint

Seven planning principles. Where one restates a design principle, the DP is the authority: binding
in [`DESIGN-PRINCIPLES.md`](../DESIGN-PRINCIPLES.md), guidance in
[`guiding-principles.md`](../guiding-principles.md).

### B1 — The season is the clock

There is no sprint calendar: there are 38 immovable deadlines (§5). Work is planned backwards from
the next one; what cannot be finished before it is parked, not half-built. When a principle meets a
deadline, scope is cut ([DL-10](../decisions/DL-10.md)).

### B2 — Every phase exits usable

DP-07: every release and epic is a sequence of vertical slices, each leaving a working system. The
defence against R-05.

### B3 — Precompute everything, serve static

Zero cost is the design ([DL-03](../decisions/DL-03.md)). Whatever can be computed on a schedule is,
and is published as a file; the browser reads those files and calls nothing else (Invariant 8). Only
genuinely interactive exploration runs in the browser (03 §4).

### B4 — Sources are plugins; the core knows nothing about them

DP-01, binding. Adding a source is one adapter module and one config entry
([Design §14.1](04-conceptual-design.md#141-adding-a-data-source)); anything more means the
abstraction has failed. The live breach is I-08.

### B5 — Predict, then optimise — never conflate the two

DP-02, binding. The forecast says what a player is worth; the optimiser decides, across a typed
contract that carries variance ([DL-06](../decisions/DL-06.md), Invariant 6). The one dependency
running the wrong way is 03 §12 P1.

### B6 — Explainability is a feature, not documentation

DP-09, with DP-10 for the formulation choices it implies. A recommendation that cannot be explained
will not be followed.

### B7 — Validate before you believe

No forecast is trusted until a walk-forward backtest shows it beats a dumb baseline (DP-12), and no
change is promoted without evidence (DP-08, the
[E8 §5 bar](epics/E8-ongoing-in-season-monitoring.md#5-the-bar-for-changing-the-model-mid-season)).
The verdict is on the model card ([DL-21](../decisions/DL-21.md)); R-15a is what it forbids today.

---

## 2. Delivery strategy

**Releases of vertical slices.** Work ships in releases `Rx.y.z`, each a set of slices that exit
usable (B2). Planning and closing a release, choosing the next piece of work and when to stop
building are in the [release register](epics/README.md#choosing-what-to-build-next).

| Release | State |
| --- | --- |
| **R1.0** — E0–E14 | Delivered: the steel thread to GW1 ([DL-10](../decisions/DL-10.md)), then the full system. [Archived](archive/README.md), except E8 |
| **R1.1.0** — data pipeline uplift | Delivered 2026-10-21, after [remediation](archive/R1.1.0/R1.1.0-data-pipeline-backlog.md#4-remediation-plan) ([DL-81](../decisions/DL-81.md)); R1.1.1 verified the permanent archive on `main` ([DL-85](../decisions/DL-85.md)). Its architecture, and the 03 §12 findings it depends on: [03 §13](03-solution-architecture.md#13-r110--data-architecture-as-delivered) |
| **R1.2.0 – R1.4.0** — modular platform | R1.2.x and R1.3.x tagged, R1.4.0 open ([DL-86](../decisions/DL-86.md), [DL-95](../decisions/DL-95.md)): orchestrator, model factory and web as independent modules around a strategy registry. Design: [05](05-target-architecture.md); stories: [backlog](archive/R1.2.0/R1.2.0-modular-platform-backlog.md) |
| **E8** — in-season monitoring | Live to GW38 beside whichever release is open; says when the season's evidence should change what is built |

**Cross-cutting concerns are not a release.** Orchestration, observability, testing and
documentation ship in every increment through the definition of done (charter §13).

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

The shape of 2026/27. The dated decision points and their outcomes are
[E8's](epics/E8-ongoing-in-season-monitoring.md#decision-points). Deadline times come from the API
and move with broadcast picks: read the live one from `week.json`.

| When | Event | What it means | At 2026-10-17 |
| --- | --- | --- | --- |
| **2026-08-21 18:30 BST** | **GW1 deadline**; season starts | First live data | Passed |
| GW2–GW4 | Early season | Highest price volatility and forecast uncertainty; treat output sceptically | Passed |
| GW4–GW8 | Settling | Minutes data becomes meaningful; priors give way to observed form | **Now** |
| 2026-10-25 | UK clocks go back | Deadlines move to UTC+0 while Australia is on UTC+11 ([DL-11](../decisions/DL-11.md), I-06) | Ahead |
| GW10–GW12 | First checkpoint | First honest read on live accuracy | Ahead |
| Autumn | Congestion | European and cup fixtures; rotation risk matters most | Under way |
| **GW19 deadline** | **Chip set 1 expires** | Unused set-1 chips are lost. The API gave **18:30 GMT, Fri 1 Jan 2027** on 2026-10-17 (pre-season: 13:30 GMT, Sat 2 Jan) | Ahead |
| GW20 | Chip set 2 opens | Re-plan chips for the run-in | Ahead |
| Feb–Apr | Blanks and doubles | Fixture structure matters most; Free Hit and Bench Boost timing | Ahead |
| 2027-05-30 | Final round, GW38 | Season measured against charter §5 | Ahead |

---

## 6. RAID log

### Risks

All owned by the owner.

| ID | Risk | Impact | Likelihood | Response |
| --- | --- | --- | --- | --- |
| R-01 | GW1 passes before the system is usable | High | **Closed** | The steel thread shipped (DL-10), but GW1–GW4 were decided without the tool; the live loop was repaired by DL-66 to DL-69 |
| R-02 | FPL API changes shape or blocks automated access | High | Medium | Adapter isolation; contract tests on recordings; immutable bronze; polite, identified access; a drift canary halts ingest on a changed shape (PIPE-08) |
| R-03 | Model adds no real edge over intuition | High | **Materialised, partly** | Beats price on average, not at the head (R-15a, model card). Trailing form is published beside it ([DL-70](../decisions/DL-70.md)); the scout UI stands alone |
| R-04 | Overfitting produces confident wrong forecasts | Medium | High | Weekly walk-forward backtest in CI ([DL-68](../decisions/DL-68.md)); held-out seasons; shadow mode (R-17) |
| R-05 | Build stalls mid-season, leaving a half-built system | Medium | Low | R1.0 closed working; every R1.1.0 item exits usable (B2) |
| R-06 | Scraped sources break | Medium | **Materialised** | Understat and FBref refuse access (D-23, [DL-31](../decisions/DL-31.md)); degraded per NFR-15, and nothing shipped depends on them because the API carries xG ([DL-46](../decisions/DL-46.md)). Both off by default (PIPE-09) |
| R-07 | Optimiser solve time exceeds the CI budget | Medium | High | HiGHS, chips by enumeration ([DL-15](../decisions/DL-15.md), [DL-26](../decisions/DL-26.md)); pruning; greedy fallback; no from-scratch solve in season ([DL-67](../decisions/DL-67.md)). High until D-19 is re-checked after the first double gameweek |
| R-08 | Odds free-tier credits exhausted | Low | **Materialised** | The Odds API's cap is restrictive and it has no history (D-20); runs degrade without it. Odds come from football-data.co.uk through the `fdcouk` adapter ([DL-73](../decisions/DL-73.md), PIPE-04); The Odds API is off by default (PIPE-09) |
| R-09 | Scheduled jobs fire late and miss a deadline | Medium | Low | Mitigated by the day-before run and the deadline guard; manual dispatch always available ([03 §9](03-solution-architecture.md#9-orchestration)) |
| R-10 | Entity resolution silently mismatches across sources | High | Low | Three-tier resolution and an unmatched-rate gate (D-07). No external player source is reachable; the live exposure is club names for football-data.co.uk, resolved in its adapter |
| R-11 | Free tiers change terms or limits | Medium | Low | Static output is portable; local execution is the fallback |
| R-12 | Motivation decays once the novelty fades | Medium | Medium | One improvement a week ([E8 §2](epics/E8-ongoing-in-season-monitoring.md#2-the-weekly-loop)); useful even if development stops |
| R-13 | Published artefacts grow past free-tier limits | Medium | Low | Mitigated: `data` is an orphan branch rebuilt and force-pushed; permanent stores are small and append-only ([03 §7.3](03-solution-architecture.md#73-storage-volume-and-retention-mechanics), [DL-42](../decisions/DL-42.md)). The window is read from configuration; immutable prior-season bronze is kept beyond it (REM-10) |
| R-14 | **Cold start** — promoted clubs and new signings have no Premier League history, so priors set their expected points | Medium | **Materialised, receding** | Confidence tier per player; wide uncertainty; the `xp_v0` fallback below the cold-start threshold (D-25). Shrinks as minutes accrue |
| R-15 | ~~Expected points collapses onto price~~ | — | **Closed** | The model card's price-dependence diagnostic shows information beyond price. What occurred instead is R-15a |
| R-15a | **Weak discrimination at the head of the ranking** — better than B0 on average, not better than B0 or trailing form in each gameweek's top 20 ([DL-21](../decisions/DL-21.md); metric corrected by [DL-49](../decisions/DL-49.md), finding stood) | High — captaincy, hits and chips act there | **Materialised** | D-13. No hit, chip or wildcard on the forecast alone until top-20 precision beats B0, restated on every model card. Candidates sit in shadow (E8 season state) |
| R-16 | **Solution churn** — a degenerate MILP returns a different, equally optimal answer each run | Medium | Low | Incumbency tie-break ([Design §6.2](04-conceptual-design.md#62-milp-formulation)); a transfer must clear a stated margin |
| R-17 | **In-season overfitting** — retraining on few noisy gameweeks makes the model worse | Medium | Medium | Shadow mode; the E8 §5 bar (DP-08); shrinkage over refitting |

### Assumptions

Tracked in charter §8 (ASM-1 … ASM-8). ASM-1 and ASM-6 are load-bearing: no public API, or no human
acting on the advice, ends the project. ASM-2 and ASM-3 failed and were absorbed (R-06, R-08).

### Issues

| ID | Issue | Impact | Status |
| --- | --- | --- | --- |
| I-01 | 12 days to the GW1 deadline, and no code | OBJ-2 at risk | **Closed** — DL-10 |
| I-02 | Pre-deadline squad state is not public (CON-10) | FR-25 partly blocked | **Closed, accepted** — declared preseason, reconstructed from public data in season ([DL-20](../decisions/DL-20.md), 03 §14) |
| I-03 | Repo visibility undecided (OD-01) | Free CI and Pages | **Closed** — [DL-12](../decisions/DL-12.md) |
| I-04 | Odds provider undecided (OD-03) | Blocked E5-S4 | **Closed** — [DL-59](../decisions/DL-59.md); in practice superseded (R-08) |
| I-05 | Effective ownership not computable from public data (CON-12) | FR-16, FR-21, the risk dial | **Closed** — [DL-24](../decisions/DL-24.md) |
| I-06 | DL-11 (UTC storage, dual-zone display) is still `Proposed` | The code follows it; the record does not | **Closed** — accepted 2026-10-17 |
| I-07 | Clock and "next gameweek" incoherent (03 §12 P4) | After a deadline, forecast and advice may name different gameweeks; blocks PIPE-01, PIPE-10 | **Closed** — PIPE-12: one `as_of` per run, one gameweek predicate ([DL-84](../decisions/DL-84.md)) |
| I-08 | football-data.co.uk handled outside `sources/`, unseen by the isolation test (03 §12 P5) | Breaches Invariant 1 / DP-01 | **Closed** — PIPE-04: the `fdcouk` adapter; scripts read through `sources.LiveFeed` (REM-06) |
| I-09 | The app does not check what it reads; `contract_version` never read (03 §12 W1) | A contract change renders wrong instead of degrading (DP-04, DP-15) | **Open** |
| I-10 | TypeScript copies without a corpus have drifted, e.g. bench order (03 §12 W2) | App and pipeline disagree about one squad | **Open** |
| I-11 | Deploy runs after every pipeline completion, even guard-only skips (03 §12 O1) | Redundant builds of an unchanged contract | **Closed** — ORC-03: deploy is `pipeline.yml`'s last job, run only when that run published ([DL-94](../decisions/DL-94.md)) |

### Dependencies

| ID | Dependency | Type | Note |
| --- | --- | --- | --- |
| D-01 | Official FPL API | External, critical | No contract, SLA or versioning. Failure stops the run; the last good publication stays live |
| D-02 | Understat / FBref | External, lost | Both refuse access (D-23); `robots.txt` honoured; off by default (PIPE-09) |
| D-03 | The Odds API free tier | External, degradable | Capped, no history (D-20); off by default (PIPE-09) |
| D-04 | GitHub Actions and the state branches | Platform, critical | All compute, free for a public repo ([DL-12](../decisions/DL-12.md)); state on `data`, `snapshots`, `ledger` (03 §7.3) |
| D-05 | GitHub Pages | Platform, critical | Delivery surface (DL-12) |
| D-06 | FPL community archive (GitHub mirror) | External, important | Prior seasons for training and backtest ([DL-19](../decisions/DL-19.md)); immutable once fetched (PIPE-03) |
| D-07 | Owner's availability | Internal, critical | The only labour, and the actuator at every deadline (ASM-6) |
| D-08 | football-data.co.uk | External, degradable | Match odds through the `fdcouk` adapter, for the prospective harness (DL-73, PIPE-04) |

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

The season is judged by [charter §5](01-project-charter.md#5-success-criteria); E8 closes on its
[definition of done](epics/E8-ongoing-in-season-monitoring.md#7-definition-of-done). Beyond those:

- A repository that, unattended, keeps a static site current with fresh data, forecasts and a
  recommendation before every deadline.
- A scout UI the owner reaches for instead of the official site.
- A model card and season log that say honestly how much edge the model has, even if "not much".
- A decision log that explains every significant choice.
- £0.00 spent.
