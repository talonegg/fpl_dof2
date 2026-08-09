# FPL DOF — Documentation

**FPL DOF** (Fantasy Premier League *Director of Football*) is a personal decision-support platform
for the 2026/27 Fantasy Premier League season: it ingests the data, forecasts what each player is
worth, solves for the best legal squad and transfer plan over a multi-gameweek horizon, and explains
its reasoning well enough to be overruled with confidence.

**Status:** Planning baselined 2026-08-09; charter at v1.1. **Building.**
[DL-10](00-decision-log.md#dl-10--build-a-steel-thread-to-gw1-rather-than-deferring-the-build) resolved
the GW1 question in favour of a steel thread to the 21 August deadline — the plan of record is
**[epics/](epics/README.md)**.

---

## The documents

Read in order. Each builds on the one before.

| # | Document | Answers |
| --- | --- | --- |
| 00 | [Decision Log](00-decision-log.md) | What was decided, and what remains open |
| 01 | [Project Charter](01-project-charter.md) | Why we are building it, what "done" and "successful" mean, and every numbered requirement · **v1.1** |
| 02 | [Project Plan and Blueprint](02-project-plan-and-blueprint.md) | The seven design principles, the season calendar, and the RAID log. ⚠️ **Its phase plan, milestones and estimates are superseded by the epics** — the document opens with a table saying which sections are still live |
| 03 | [Solution Architecture](03-solution-architecture.md) | How it is structured, what it is built with, where it runs, and how it stays free |
| 04 | [Conceptual Design](04-conceptual-design.md) | Every logical component: sources, data layer, models, optimiser, UX, orchestration, testing, observability |
| — | [AI Tooling Plan](ai/README.md) | How Claude Code is configured to build it: `CLAUDE.md`, path-scoped rules, skills, subagents and enforcement hooks |
| — | **[Implementation Plan (Epics)](epics/README.md)** | **The plan of record: steel thread to GW1, then eight incremental epics, with a prioritisation framework and the [inputs needed from you](epics/INPUTS-REQUIRED.md)** |

---

## The shape of it, in one diagram

```mermaid
graph LR
    SRC["FPL API<br/>Understat / FBref<br/>Bookmaker odds"] -->|"pluggable adapters"| PIPE["Scheduled Python pipeline<br/>conform → forecast → optimise"]
    PIPE --> ART[("Versioned static<br/>data artefacts")]
    ART --> APP["React SPA / PWA<br/>on a free CDN"]
    APP --> USER(["The manager"])
    USER -->|"decides and submits"| FPL(["fantasy.premierleague.com"])
```

Scheduled CI jobs do all the work and publish files. A static app reads them. There is no server, no
database and no bill.

---

## Decisions in force

| | |
| --- | --- |
| **Season** | 2026/27 — GW1 deadline 21 Aug 2026 18:30 BST; chip set 1 expires at the GW19 deadline, 2 Jan 2027 |
| **Build** | Steel thread to GW1, then eight incremental epics (DL-10) |
| **Hosting** | Static site plus scheduled jobs. **Public repository, GitHub Pages** (DL-12). Zero cost, no operated servers |
| **Stack** | Python for data, modelling and optimisation; TypeScript + React for the web app |
| **Sources** | Official FPL API, Understat/FBref, bookmaker odds — behind a pluggable adapter layer built for future sources |
| **Decision engine** | Multi-gameweek MILP on HiGHS, with chip timing decided by scenario enumeration (DL-15) |
| **Objective** | Expected points, with a selectable rank-aware risk dial |
| **Users** | Single user, configurable team ID, public endpoints only. No accounts, no credentials |

Full rationale and rejected alternatives in the [Decision Log](00-decision-log.md).

---

## Where to start reading

| If you want to know… | Read |
| --- | --- |
| **What gets built, in what order** | **[Epics](epics/README.md)** — the plan of record |
| What is needed from the owner, and when | [INPUTS-REQUIRED](epics/INPUTS-REQUIRED.md) |
| How GW1 is being reached | [E0 — steel thread](epics/E0-steel-thread-gw1.md) |
| How it runs for free | [Architecture §4](03-solution-architecture.md#4-the-static-hosting-constraint-and-how-interactivity-survives-it) |
| How the forecast actually works | [Design §5](04-conceptual-design.md#5-analytical-models) |
| How the optimiser is formulated | [Design §6](04-conceptual-design.md#6-decision-engine) |
| How the model gets judged, and against what | [Charter §5 tier 2](01-project-charter.md#tier-2--model-quality-obj-7) |
| How to add a new data source later | [Design §14](04-conceptual-design.md#14-extensibility) |
| What could go wrong | [Plan §6 — RAID log](02-project-plan-and-blueprint.md#6-raid-log) |
