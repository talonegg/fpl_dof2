# Decision Log

Architecture and product decisions for **FPL DOF** (Fantasy Premier League Director of Football).
Newest entries at the bottom. Each decision is immutable once accepted — to change one, add a
superseding entry and mark the original `Superseded by DL-nn`.

| Field | Meaning |
| --- | --- |
| **Status** | `Accepted` / `Superseded` / `Proposed` |
| **Date** | Date the decision was taken |
| **Decided by** | Who made the call |

---

## DL-01 — Season objective is the 2026/27 campaign, starting at GW1

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

The product exists to maximise points across the **2026/27 Premier League season**. Season starts
Friday **21 August 2026**; the **GW1 deadline is 18:30 BST on 21 August 2026**. Chip set 1 expires at
the GW19 deadline (13:30 GMT, Saturday 2 January 2027). Final match round is Sunday 30 May 2027.

**Consequence:** the season calendar, not a sprint calendar, is the project's master clock. Every
milestone is expressed relative to gameweek deadlines.

---

## DL-02 — This engagement produces planning documentation only

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

No implementation code is written yet. Deliverables are the charter, plan/blueprint, architecture and
conceptual design. Build cadence is decided after review.

**Consequence:** the plan carries two tracks — a **GW1 fast lane** (viable only if build starts almost
immediately) and a **full build** track — so the decision can be taken with the trade-offs visible.
See [02-project-plan-and-blueprint.md](02-project-plan-and-blueprint.md) §7.

---

## DL-03 — Static site plus scheduled jobs; no always-on server

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

Scheduled CI jobs (GitHub Actions) ingest data, run models and the optimiser, and publish
**precomputed static artefacts**. A static single-page app served from a CDN reads those artefacts.
There is no application server, no managed database and no runtime backend.

**Rejected alternatives:** serverless full-stack on a free tier (account limits, cold starts, free-tier
database pausing); self-hosted at home (machine must stay on, ops burden); hybrid CI + small API
(more moving parts than the benefit justifies at this scale).

**Consequence:** interactive "what-if" re-optimisation must run **client-side in the browser** or be
triggered as a CI job. This is an explicit architectural constraint, addressed in
[03-solution-architecture.md](03-solution-architecture.md) §4 and §9.

---

## DL-04 — Python for data and analytics, TypeScript/React for the web app

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

Ingestion, transformation, modelling and optimisation in Python (pandas, scikit-learn/LightGBM,
PuLP/HiGHS). Front end in TypeScript with React and Vite.

**Rejected alternatives:** all-TypeScript (weak optimisation and ML ecosystem for a multi-gameweek
MILP); Python end-to-end with Streamlit/Dash (weaker mobile UX for the scouting experience, which is
a first-class requirement).

**Consequence:** a two-language monorepo with a strictly defined **data contract** at the boundary —
Python only ever writes versioned JSON/Parquet; the front end never calls a Python process.

---

## DL-05 — Data sources: FPL API, Understat/FBref, bookmaker odds — behind a pluggable adapter layer

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

Launch sources are the **official FPL API**, **Understat/FBref** advanced statistics, and **bookmaker
odds**. The owner explicitly required a *modular and extensible design to enable easy onboarding of
future data sources*.

**Consequence:** source adapters are a first-class architectural component with a formal interface,
registry and conformance test suite. No model or application code may reference a source directly;
everything consumes the conformed silver layer. Adding a source must not require changes outside its
own adapter module plus a config entry — this is a testable design constraint, specified in
[04-conceptual-design.md](04-conceptual-design.md) §14.

---

## DL-06 — Decision engine is a multi-gameweek MILP with explicit chip planning

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

A mixed-integer linear program maximises discounted expected points over a rolling 5–8 gameweek
horizon, subject to full FPL rules: budget and selling-price mechanics, squad composition, the
three-per-club limit, formation legality, free-transfer accrual and rollover to a maximum of five,
−4 point hits, and the timing of Wildcard, Free Hit, Triple Captain and Bench Boost.

**Rejected alternatives:** single-gameweek optimisation (structurally short-sighted — churns transfers
and mistimes chips); fully stochastic scenario optimisation as the *initial* core (too heavy for CI
compute limits before the deterministic core is proven).

**Consequence:** the expected-points interface must expose **variance as well as mean** from day one,
so a distributional/simulation layer can be added later without reworking the optimiser.

---

## DL-07 — Objective is expected points with a selectable, rank-aware risk dial

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

The core objective is expected points. A user-facing risk setting adjusts the objective between
**safe** (hug the template, manage effective ownership to protect rank) and **aggressive** (seek
low-ownership differentials). The ownership bet implied by every recommendation is surfaced in the UI.

**Consequence:** ownership and effective ownership are modelled entities, not display fields, and the
optimiser objective carries a tunable ownership-deviation term.

---

## DL-08 — Single user, any team ID, public endpoints only

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

One user. The FPL team ID is configuration, not a hardcoded constant, so any public team can be
loaded — enabling mini-league and rival analysis. **No authentication, no accounts, no FPL
credentials and no personal data are stored or transmitted.**

**Consequence:** the authenticated `my-team` endpoint is out of scope. Current-squad state before a
deadline must be reconstructed from the last finished gameweek's public picks plus the public
transfers feed, with a manual override path. This is a known functional gap, designed for explicitly
in [04-conceptual-design.md](04-conceptual-design.md) §4.3.

---

## DL-09 — Documentation lives as Markdown in the repository

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

All project documentation is Markdown under `docs/`, version-controlled alongside the code. No
externally published copies.

**Consequence:** diagrams use Mermaid so they render in GitHub and IDE preview without a toolchain.
Documents are expected to be read by AI coding agents as well as humans, so requirements are
numbered and traceable.

---

## DL-10 — Build a steel thread to GW1 rather than deferring the build

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner · **Supersedes DL-02**

Implementation starts immediately, targeting a working end-to-end system that produces the GW1 squad
before the deadline of **Fri 21 Aug 2026 18:30 BST (Sat 22 Aug 03:30 AEST)**. This resolves the open
choice in [02-project-plan-and-blueprint.md §7](02-project-plan-and-blueprint.md#7-the-gw1-decision)
in favour of building for GW1.

The approach is a **steel thread**, not the "fast lane" described in Plan §7 Track B: a thin but
complete and working path through every architectural layer, where every line written is kept. The
expensive structural parts — adapter isolation, medallion layers, config-driven rules, versioned
contracts — are built in from the start because they are cheap now and expensive to retrofit.

**Rejected alternative:** Track A (build properly, pick GW1 by hand). Sound reasoning, but the owner
wants the GW1 squad to come from the tool.

**Consequence:** [Blueprint B7](02-project-plan-and-blueprint.md#b7--validate-before-you-believe) —
*validate before you believe* — is knowingly breached for GW1, because there is no time to backtest
and preseason has no current-season data. Mitigations are specified in
[epics/README §5](epics/README.md#5-guardrails-carried-from-the-planning-set): wide uncertainty
labelling, a mandatory human review gate, consensus sanity-checking, and backtesting as the first
deliverable of E3. The full plan is in [docs/planning/epics/](epics/README.md).

---

## DL-11 — Store and compute in UTC; render in local time only at the UI edge

**Status:** Proposed · **Date:** 2026-08-09 · **Awaiting:** Owner confirmation

The owner is in Australia (AEST, UTC+10). FPL expresses all deadlines in UK time, so deadlines land
at roughly 03:30 local for Friday-night and midweek gameweeks, and around 20:00 local for standard
Saturday ones.

**Decision:** all storage, scheduling arithmetic and model reasoning use UTC. Local time appears only
at the presentation edge. Deadline displays show **both** UK and local time, plus an explicit
"decide by" time in the local evening.

**Why it matters beyond display:** the UK leaves BST in late October (to UTC+0) while Australia enters
AEDT in early October (to UTC+11). The offset moves from +9 to +11 within a few weeks. Any code
reasoning in local time breaks during that window.

**Consequences:** changes FR-26 (dashboard countdown) to require dual-timezone display; makes E7
automation a requirement rather than a convenience, since the owner will be asleep for many
deadlines, moving it earlier in the epic sequence.

---

## Open decisions

Decisions deliberately deferred, with the point at which each must be resolved.

| ID | Question | Must resolve by |
| --- | --- | --- |
| ~~OD-01~~ | ~~Public or private GitHub repository~~ — **Resolved 2026-08-09: private.** Consequence: GitHub Pages needs a paid plan, and Actions is capped at 2,000 min/month, which raises the stakes on OD-02 | Resolved |
| OD-02 | Hosting: Cloudflare Pages, make the repo public, or local-only. See [epics/INPUTS-REQUIRED §5](epics/INPUTS-REQUIRED.md#5-needed-for-e7-automation-and-hosting-around-gw6-8) | E7, ~GW6 |
| OD-03 | Which odds provider and free-tier credit budget | E5, ~GW10 |
| OD-04 | Whether to add injury/press-conference feeds as a fourth source | E8, in-season |
| OD-05 | Target overall rank — determines how aggressively the risk dial should default | E4, before the risk dial ships |
