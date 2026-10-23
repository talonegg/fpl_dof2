# FPL DOF — documentation

**FPL DOF** (Fantasy Premier League *Director of Football*) is a personal decision-support platform
for one manager's team in the 2026/27 season. It forecasts every player's expected points, with the
uncertainty around them, and turns those forecasts into advice: the squad, this week's transfers,
captain, chips, and a multi-gameweek plan, each explained against its runner-up and against doing
nothing. The owner reads the advice in a web app and makes the moves in FPL by hand — the system never
logs in to FPL and never acts on the account.

Three properties shape everything else: it costs **nothing to run** (free CI, free hosting, no paid
dependency), it has **no server** (a scheduled pipeline publishes static files that the browser reads),
and the **season is the clock** (weekly deadlines are immovable; stale and honest beats fresh and
wrong).

Each fact has one home, listed at the end of this page. Read the home; link to it; never copy it.
How to write and archive documents: [`agents/documentation.md`](agents/documentation.md).

---

## Data sources

| Source | What it provides | State |
| --- | --- | --- |
| **Official FPL API** | Players, prices, status, ownership, fixtures, per-gameweek stats including expected goals and assists, and the game's own rules | Essential: if it fails, the run stops and the last good advice stays live |
| **FPL community archive** (GitHub mirror) | Past seasons gameweek by gameweek — the backtest's history | Off by default; the backtest and the prospective harness enable it; immutable once fetched, never re-fetched unless forced (PIPE-03) |
| **football-data.co.uk** | Bookmaker match odds, past and upcoming | The `fdcouk` adapter, off by default and enabled by no workflow; the prospective harness reads its odds through it (PIPE-04, REM-07) |
| Understat, FBref | Advanced player metrics (scraped) | **Blocked** upstream (D-23) and off by default; nothing that ships depends on them; the adapters stay, dormant (PIPE-09) |
| The Odds API | Live match odds | Off by default (PIPE-09); free-tier credit cap and no history (D-20); not used by the model |

Every source sits behind an adapter in `pipeline/src/fpl_dof/sources/`, the only code allowed to know
a source exists (DP-01). Detail: [architecture §2](planning/03-solution-architecture.md#2-context-view-c4-level-1),
[design §2](planning/04-conceptual-design.md#2-data-sources).

---

## Solution architecture

```mermaid
graph LR
    SRC["Sources"] --> ING["ingest<br/>bronze snapshots"]
    ING --> TRF["transform<br/>silver tables"]
    TRF --> QG{"quality gates"}
    QG -->|"pass"| FC["forecast<br/>xP + variance"]
    QG -.->|"fail: nothing publishes"| STOP(("last good<br/>stays live"))
    FC --> DEC["decide<br/>squad · transfers ·<br/>captain · chips · plan"]
    DEC --> PUB["publish<br/>/data/v1 JSON"]
    PUB --> WEB["React app<br/>GitHub Pages"]
    WEB --> OWN(["owner submits<br/>in FPL by hand"])
```

- **Pipeline** — Python, one CLI (`fpl-dof`) run by GitHub Actions on a deadline-aware schedule. Raw
  responses are kept as immutable bronze snapshots; transform conforms them into canonical silver
  tables; quality gates block anything suspect; the forecast is a chain of small, arguable component
  models (minutes, team strength, goal involvement, defensive contribution, clean sheets, saves,
  cards, bonus); the decision layer solves
  mixed-integer programmes with PuLP for the squad, the week's transfers and a multi-gameweek plan
  with chip scenarios (the plan on HiGHS).
- **Contract** — JSON Schemas in `contracts/v1/` define every published file; Python validates
  before writing and generates the TypeScript types from the same schemas (DP-04).
- **Web app** — React and TypeScript, installable and usable offline. It reads the published files
  and nothing else; legality checks and quick re-picks run in the browser from the published rules.
- **State** — rolling raw data and the accumulated price history on the `data` branch, a permanent
  bronze archive per closed gameweek on `snapshots`, and each week's advice and prospective record on
  `ledger`, written before the deadline so the season log is evidence rather than recollection.
- **Off the main path** — the walk-forward backtest that grades the model (its verdict is in the
  model card) and a pre-registered prospective model comparison. On it, but never acted on, a
  challenger model runs in shadow in every `week` stage.

Detail: [solution architecture](planning/03-solution-architecture.md) (as built, with a module-design
review in §12) and [conceptual design](planning/04-conceptual-design.md) (each component).

---

## Where things stand

- **R1.0 — delivered.** Epics E0–E14 built the platform end to end; they are archived as records in
  [`planning/archive/R1.0/`](planning/archive/README.md).
- **R1.1.0 — delivered 2026-10-21: data pipeline uplift.** Remediated before release
  ([DL-81](decisions/DL-81.md)); its backlog is archived in [`planning/archive/R1.1.0/`](planning/archive/README.md).
  **R1.1.1 — tagged 2026-10-22:** the permanent archive verified on `main` ([DL-85](decisions/DL-85.md)). Its effect on the architecture: [architecture §13](planning/03-solution-architecture.md#13-r110--data-architecture-as-delivered).
- **R1.2.0 and R1.2.2 — tagged 2026-10-23 (R1.2.1 a hotfix, [DL-88](decisions/DL-88.md)); R1.3.0, open, and R1.4.0 follow: the modular platform.** Orchestrator, model factory and web as
  independent modules around a strategy registry ([DL-86](decisions/DL-86.md)); design in
  [`planning/05-target-architecture.md`](planning/05-target-architecture.md).
- **The season — live.** [E8 — ongoing in-season monitoring](planning/epics/E8-ongoing-in-season-monitoring.md)
  holds the season state and decision points, rewritten each gameweek.

## To-dos

Pointers, not the work itself: each line links to the home that holds the detail and the acceptance
criteria. The [release register](planning/epics/README.md) decides the order.

**This season ([E8](planning/epics/E8-ongoing-in-season-monitoring.md))**
- Keep E8's season state current; record the GW8 decision-point outcome. GW4 was recorded as
  "intuition ahead"; the response is R1.1.0 as ordered ([DL-79](decisions/DL-79.md)).
- A chip calendar for set 1 before GW15; set 1 expires at the GW19 deadline.

**The modular platform — R1.2.0 to R1.4.0 ([DL-86](decisions/DL-86.md))**
- Stories and order in the [backlog](planning/epics/R1.2.0-modular-platform-backlog.md). It takes in
  P1, P3, P6, P9, P10, W1–W5, O1, O2 and F1–F5 from
  [architecture §12](planning/03-solution-architecture.md#12-module-design--review-of-2026-10-17).

**Design fixes not yet scheduled ([architecture §12](planning/03-solution-architecture.md#12-module-design--review-of-2026-10-17))**
- One planning horizon: `xp_horizon` reads `decision.horizon` (D-29, [DL-78](decisions/DL-78.md)).
- Shared MILP legality constraints and a solver setting that is actually read (P2); `week/` facades
  and scheduling (P7); very large files (P8); the data layer importing components (W6).

**Open debt ([debt register](planning/debt-register.md))** — most visibly D-13 (the forecast does not
yet beat the model-free benchmark at the head of the ranking) and D-23 (scraped sources blocked).

**Decisions pending** — none open ([decisions](decisions/README.md)). The 2026-10-17 walkthrough
settled DL-11, DL-72 and OD-04 and recorded DL-76 to DL-79.

---

## Where each fact lives

| The fact | Its home |
| --- | --- |
| The ten binding design principles — amendment-controlled, never edited by an agent | [`DESIGN-PRINCIPLES.md`](DESIGN-PRINCIPLES.md) |
| Product, modelling and delivery guidance (DP-07, 08, 09, 10, 12) — editable | [`guiding-principles.md`](guiding-principles.md) |
| Invariants, commands, code layout | [`CLAUDE.md`](../CLAUDE.md) |
| A decision and its reasons (`DL-nn`); open decisions (`OD-nn`) | [`decisions/`](decisions/README.md) — one file per entry, with an index |
| Purpose, objectives, scope, requirements (`FR-nn`, `NFR-nn`) and their status, constraints, assumptions, definition of done | [Charter](planning/01-project-charter.md) |
| Blueprint (B1–B7), season calendar, RAID log (`R-nn`, `I-nn`) | [Project plan](planning/02-project-plan-and-blueprint.md) |
| Shortcuts taken and what repays each (`D-nn`) | [Debt register](planning/debt-register.md) |
| Structure, stack, hosting, data flow, the web contract, orchestration — as built; the module-design review; R1.1.0's data architecture | [Solution architecture](planning/03-solution-architecture.md) |
| The target design: orchestrator, model factory and web as independent modules, the 2026-10-22 code review | [Target architecture](planning/05-target-architecture.md) |
| Each component's design: sources, data layer, models, the strategy registry, optimiser, UX, testing, extensibility; open questions (`Q-nn`) | [Conceptual design](planning/04-conceptual-design.md) |
| Releases (`Rx.y.z`): what is being built now, how to choose what next, and the branching and release model | [Release register](planning/epics/README.md); the procedure is the `release` skill |
| R1.2.0 and R1.2.2 (tagged), then R1.3.0 and R1.4.0: the modular platform's stories | [`planning/epics/R1.2.0-modular-platform-backlog.md`](planning/epics/R1.2.0-modular-platform-backlog.md) |
| Where the season stands (rewritten each gameweek), the weekly loop, and the bar for changing the model mid-season | [E8 — ongoing in-season monitoring](planning/epics/E8-ongoing-in-season-monitoring.md) |
| Environment variables and secrets handling | [`environment.md`](environment.md) |
| FPL scoring, prices, chips; the FPL API | The `fpl-rules` and `fpl-api` skills in `.claude/skills/` |
| The published artefacts' shape | `contracts/v1/*.schema.json`; behaviour pinned in both languages: [`contracts/conformance/`](../contracts/conformance/README.md) |
| The pre-registered prospective model comparison | [`prospective/`](../prospective/README.md) |
| Browser and deployed-site verification | [`web/verify/README.md`](../web/verify/README.md) |
| Model quality right now (the backtest verdict) | `data/gold/season=2026-27/model-card.md`, generated by each run — not a document |
| Closed releases (R1.0: epics E0–E14; R1.1.0: the data pipeline backlog) and superseded plans | [`planning/archive/`](planning/archive/README.md) — records, never updated |

## Where to start, by task

| Task | Read first |
| --- | --- |
| Design a module, add a source, change a model or the optimiser, alter a contract | `DESIGN-PRINCIPLES.md`, then the matching section of the conceptual design and the [target architecture](planning/05-target-architecture.md) |
| Add a data source | [Design §14.1](planning/04-conceptual-design.md#141-adding-a-data-source) |
| Change the forecast | [Design §5](planning/04-conceptual-design.md#5-analytical-models), the model card, [E8 §5](planning/epics/E8-ongoing-in-season-monitoring.md#5-the-bar-for-changing-the-model-mid-season) |
| Change the optimiser | [Design §6](planning/04-conceptual-design.md#6-decision-engine) |
| Pick up a to-do | Its home above; the release register for order |
| Branch, open a pull request, promote, tag or hotfix | The `release` skill (`.claude/skills/release/`); policy in [DL-80](decisions/DL-80.md) |
| Understand why something is the way it is | The `DL-nn` the code cites: `docs/decisions/DL-nn.md` |
| Record a decision | [`decisions/README.md`](decisions/README.md#writing-an-entry) |
