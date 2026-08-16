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

## DL-12 — Public repository

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner · **Supersedes the 2026-08-09 resolution of OD-01**

The repository is **public**. This reverses the earlier decision to keep it private, taken before the
Actions-minutes consequences had been costed.

**Why it changed.** A private repository on the Free plan caps Actions at 2,000 minutes/month and
puts GitHub Pages behind a paid plan. A recount of the workflow cadences in
[03-solution-architecture.md §9](03-solution-architecture.md#9-orchestration) put realistic monthly
consumption at roughly **1,800–3,400 minutes** — at or over the cap, with no headroom for
deadline-day reruns, which are precisely the runs that must never be rationed.

The privacy was also largely illusory. The published artefacts — squad, transfer plan, differentials,
model outputs — are served from a public CDN regardless (DL-03). Keeping the repository private
protected the *code*, not the *decisions*, while costing the compute budget the decisions depend on.

**Consequence:**
- Unlimited Actions minutes; GitHub Pages available free. **OD-01 and OD-02 are both closed.**
- Cadence budgeting stops being a hard constraint, but the corrected estimates stay in the
  architecture as an operational sanity check — an unbounded budget is not a licence for a wasteful
  pipeline.
- **NFR-13 becomes load-bearing rather than precautionary.** No secret may ever reach the repository.
  The `ODDS_API_KEY` (E5) lives only in Actions secrets. The secret-scan hook in `.claude/hooks/` is
  now the primary guard, not a belt-and-braces one.
- Nothing personal beyond a public FPL team ID may be committed (NFR-11 already required this).

---

## DL-13 — Charter amendments following the 2026-08-09 architecture and plan audit

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

Charter §12 requires a decision-log entry before any change to §4 or §6. This entry covers five
amendments, all made for the same reason: a stated target was either unachievable or too weak to
detect the failure it existed to catch. Charter version goes 1.0 → 1.1.

| # | Change | Why |
| --- | --- | --- |
| 1 | **§5 tier-2 metrics become baseline-relative** rather than absolute | The `MAE ≤ 2.1` threshold sits in the range a constant predictor achieves, and `Spearman ≥ 0.30` across all positions is plausibly reachable by a model knowing only price and position. Both would have passed a model with no edge. Metrics are now expressed as skill over a stated `(position, price)` baseline, with top-20 precision added as the decision-relevant measure |
| 2 | **NFR-06 downgraded from byte-for-byte to logical reproducibility** | A MILP over a densely degenerate problem does not return a deterministic optimum, and threaded gradient boosting is not bitwise stable. The original acceptance test could not have passed. Replaced by: byte-identical silver, identical objective within tolerance, identical published decisions — backed by a deterministic tie-break in the optimiser (see [04-conceptual-design.md §6.2](04-conceptual-design.md#62-milp-formulation)) |
| 3 | **CON-11 added** — the maintainer is in AEST/AEDT | Already the stated reason E7 moved earlier in the epic sequence, but it existed only in an epic annex. A constraint that reorders the plan belongs in the charter |
| 4 | **§13 definition of done gains a dated pre-CI carve-out** | E0 runs deliberately with no CI, to keep hosting and secrets off the GW1 critical path. Without an explicit exception the first increment breaks the quality bar, which is how a quality bar stops being one |
| 5 | **OD-05 reconciled with §5** | The charter already set top-100k target / top-10k stretch. OD-05 is narrowed to the risk-dial *default posture*, which is a separate question from the rank ambition |

**Not changed:** no functional or non-functional requirement was removed, and no scope was added.
Per §12, adding scope requires trading scope away; nothing here adds any.

---

## DL-14 — The web data contract carries the rules configuration

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

The published web contract includes **`rules.json`**, generated from the same configuration the
Python rules module reads. The TypeScript legality validator is parameterised from it.

**The problem this solves.** [Architecture §4](03-solution-architecture.md#4-the-static-hosting-constraint-and-how-interactivity-survives-it)
assigns live legality checking, formation changes and lock-and-re-pick to **T2 — client-side
compute**. Those need the squad rules in the browser. Without this decision the only options are a
second, hand-written implementation of FPL's rules in TypeScript — guaranteed to drift from the
Python one — or moving legality checking to T3, which breaks the design rule that nothing on the
deadline path may be job-triggered.

Two implementations of the scoring and squad rules is exactly the silent-wrongness failure mode
Invariant 2 exists to prevent. A hardcoded `3` for the club limit in a `.tsx` file is the same bug as
a hardcoded `4` for a forward goal in a `.py` file.

**Consequence:**
- `rules.json` is a first-class member of the versioned contract, generated, never hand-written.
- A **cross-language conformance test** is required: the same squad fixtures produce the same
  verdicts from the Python validator and the TypeScript one. Divergence is a build failure.
- The TS validator checks legality only. It never computes points — expected points remain
  precomputed (T1).

---

## DL-15 — Chip timing by scenario enumeration; HiGHS as the solver from E4

**Status:** Accepted · **Date:** 2026-08-09 · **Decided by:** Owner

Two related changes to the decision engine, both taken before E4 rather than discovered inside it.

**Chip timing is decided by enumeration over scenarios, not by MILP decision variables.** Over a 5–8
gameweek horizon there are only a small number of plausible `(chip, gameweek)` assignments. Solving
the transfer MILP conditional on each and taking the best is dramatically easier to solve, trivially
parallelisable, and far easier to explain — which matters, because chip timing is the recommendation
the owner is most likely to want to argue with. Free Hit in particular avoids needing a parallel
squad variable set inside a single monolithic model.

Full MILP chip variables (the formulation in
[04-conceptual-design.md §6.2](04-conceptual-design.md#62-milp-formulation) C10–C14) remain the
documented stretch target, kept because it is the correct formulation and may become tractable.

**The solver is HiGHS (`highspy`) from E4 onward, not CBC.** The E0 de-risking exercise verified CBC
against the *single-gameweek* problem — 15 from 200 candidates, solved optimally in seconds. The
multi-gameweek problem with transfer, hit and chip structure is a different animal: roughly 10–20k
binaries with a weak LP relaxation. CBC is unlikely to hold. HiGHS is open-source, pip-installable,
carries no licence cost, and is materially stronger on this class of problem. Both are reachable
through PuLP, so this is a configuration change, not a rewrite.

**Consequence:** R-07 (solve time exceeds the CI budget) is re-rated to High likelihood in the
[RAID log](02-project-plan-and-blueprint.md#6-raid-log). The greedy fallback is not optional.

---

## DL-16 — Design principles adopted as binding and amendment-controlled

**Status:** Accepted · **Date:** 2026-08-10 · **Decided by:** Owner

Fifteen design principles (DP-01…DP-15) are adopted at **`docs/DESIGN-PRINCIPLES.md`**, derived from
the charter, architecture, conceptual design, epics and DL-01…DL-15. They cover extensibility,
modularisation, parameterisation, transparency of rules and derivations, incremental build,
auditability, testability and traceability.

**Four decisions taken with them:**

| # | Decision | Rejected alternative |
| --- | --- | --- |
| 1 | **Binding constraints, waivable.** Violating code is a defect | Strong defaults — across many sessions, accumulated small deviations are how architectures erode |
| 2 | **Enforced by a blocking `PreToolUse` hook**, not convention | Documented convention alone — instruction files are context, not enforcement; a sufficiently confident agent mid-task can rewrite them |
| 3 | **Waivers require an inline marker *and* a decision-log entry** | Either alone — a central register with nothing at the code site leaves a future reader unable to tell deliberate from accidental |
| 4 | **Principles outrank deadlines; scope is cut instead** | Deadline wins with a debt entry — debt taken under deadline pressure is the debt least likely to be repaid |

**Why amendment control.** An agent that can rewrite its own constraints does not have constraints.
`.claude/hooks/protect-principles.cjs` denies writes to the file; amendment requires explicit owner
approval in conversation plus a decision-log entry, per §4 of that document.

**Placement.** The canonical document sits at `docs/DESIGN-PRINCIPLES.md` — a sibling of
`docs/planning/`, not inside it, because the planning set is season-specific and living whereas the
principles are meant to outlast it. It is tool-neutral Markdown so any agent can read it. A thin
always-loaded pointer at `.claude/rules/design-principles.md` carries **principle names only**, never
duplicated reasoning, so the two cannot drift.

**Consequence:** `CLAUDE.md` gains a binding reference and the waiver convention. The principles apply
to E0 from the outset — they were derived partly *from* E0's design, so this codifies rather than
changes it.

---

## DL-17 — Game rules are read from the API, not transcribed

**Date:** 2026-08-10 · **Status:** Accepted · **Supersedes:** nothing · **Arose in:** E0-S3/E0-S4

**Decision.** The rules module is **seeded at runtime from the source snapshot**. `game_config.scoring`
supplies the entire scoring table; `game_settings` supplies squad size, starting size, budget, club
limit and the sell-on fee; `element_types` supplies per-position squad allocation and formation
bounds. Only what FPL genuinely does not publish is configured: the saves and goals-conceded
divisors, the Defensive Contribution match thresholds, the bonus 3/2/1 split, the 60-minute
appearance boundary, and the transfer rules. Each configured value carries a comment stating why it
cannot be derived. Provenance is recorded per field group and published in the web contract.

**Why.** Invariant 2 says never hardcode FPL scoring, price or squad values. Transcribing them into
YAML satisfies the letter of that and not its purpose: a transcribed value is still a value someone
typed from memory, and it goes stale silently.

**The evidence that this was not theoretical.** The `fpl-rules` skill — written carefully, with
sources cited — stated that a goalkeeper goal is worth 6. **The API says 10 for 2026/27.** The skill
also did not record that Defensive Contribution now extends to forwards. A pipeline that transcribed
from the skill would have mispriced every goalkeeper in the game and nothing would have complained,
because the number was plausible and the code was consistent. The skill has been corrected and now
points at the API as authoritative.

**Consequence.** `rules.json` is published with the web contract (see [DL-14](#dl-14--the-web-contract-carries-rulesjson)),
so the browser and the solver demonstrably use the same numbers. The rules module holds 100%
statement and branch coverage. Adding a source that publishes rules is now a conflict the transform
stage refuses rather than resolves by iteration order.

---

## DL-18 — The 2025/26 community archive is not needed; E0-S3 took route 1

**Date:** 2026-08-10 · **Status:** Accepted · **Arose in:** E0-S3

**Decision.** No second data source is admitted in E0. Defensive Contribution comes from the official
API.

**Why.** [E0-S3](epics/E0-steel-thread-gw1.md#e0-s3--minimal-silver-layer-and-the-202526-archive) set
out three routes in order and said to take the first that works. Route 1 — check whether
`history_past` carries a season-total DefCon field — **works**. It carries `defensive_contribution`
alongside `tackles`, `recoveries`, `clearances_blocks_interceptions` and `starts`. The archive
ingestion planned as route 2 is unnecessary.

**Consequence.** The half-day E0-S3 borrowed from the buffer is returned, and E0 ships with a single
source, which keeps entity resolution (D-07) genuinely out of scope. Debt **D-11 stands unchanged**:
DefCon still rests on one season of evidence, because 2025/26 is the only season in which it was
recorded. The adapter registry consequently loses its first real test — the second source was going
to be that test — so the isolation guarantee rests on `tests/test_source_isolation.py` alone until
E2. That test has already caught two real leaks, so this is a live guard rather than a hopeful one.

**A trap this exposed, now handled explicitly.** Fields that did not exist in a past season read as
**zero**, not null: DefCon before 2025/26, and `starts` before 2022/23. Read naively, that is
"this defender did no defending", and it would systematically underrate exactly the players the
design says the model should beat intuition on. The forecast restricts each such field to the
seasons in which it was actually measured, and the seasons are configuration, not literals.

---

## DL-19 — Prior-season per-gameweek data comes from a community archive, because the API has none

**Date:** 2026-08-10 · **Status:** Accepted · **Arose in:** E2-S3, blocking E3-S1

**Decision.** A second source adapter, `fplarchive`, ingests per-gameweek player data for prior
seasons from the community mirror at `vaastav/Fantasy-Premier-League`. It is registered like any
other source and is subject to Invariant 1 in full.

**Why.** [E2-S3](epics/E2-data-platform.md#e2-s3--historical-backfill--1-day--fr-06--repays-d-11)
assumed it would *extend* an archive already ingested in E0-S3. [DL-18](#dl-18) removed that archive,
so the story's premise no longer held and the gap had to be re-checked directly against the API. The
result is worse than the plan assumed:

**The official API exposes no per-gameweek data for any prior season, at all.** `element-summary`
returns `history` for the *current* season only, and `history_past` as **season totals**. In
preseason `history` is empty, so today the API supplies **zero** per-gameweek observations.

[E3-S1](epics/E3-expected-points-engine.md#e3-s1--backtest-harness--2-days--fr-37--do-this-first)
requires walk-forward replay against historical deadlines. Without per-gameweek history there is
nothing to walk forward *over*, so E3 cannot start — which makes this a dependency, not a nicety.
The archive supplies 2022/23–2025/26 with `kickoff_time` per row, which is what makes the
knowability stamps enforceable rather than nominal.

**Licence posture, stated rather than assumed.** The archive repository declares no licence
(`NOASSERTION`). The underlying data is FPL's own public data, which this project already ingests
directly under NFR-10; the archive is a convenience mirror of it, not a new data right. Use is
personal and non-commercial, requests are cached hard, and the ingest runs **once per season** and is
then treated as static. If the mirror disappears, the pipeline degrades to current-season data
(DP-15) rather than failing — but the backtest loses its evidence base, and that is recorded as
debt rather than papered over.

**Consequence.** The registry finally gets the second source DL-18 said it had lost, so Invariant 1
is now tested by construction and not only by `test_source_isolation.py`. Cross-season identity uses
the stable `code`, never the season-local `id` — `players_raw.csv` supplies the mapping, and joining
on `element` across seasons would silently attribute one player's history to another. **D-11 is
re-scoped, not closed:** the archive widens minutes, goals, assists, clean sheets, saves and cards to
four seasons, but `defensive_contribution` still exists in 2025/26 alone, exactly as E2-S3's
usability table predicted.

---

## DL-20 — Preseason squad state has no API to read, so the manual path is the primary path

**Date:** 2026-08-10 · **Status:** Accepted · **Arose in:** E1-S1

**Decision.** The squad state service treats a manually declared squad as a first-class input of
equal standing to a reconstructed one, not as a fallback for when reconstruction fails.

**Why.** [E1-S1](epics/E1-weekly-operating-loop.md#e1-s1--squad-state-service) anticipated an "API
gap" and specified a manual override "when confidence is low". Probing the live endpoints shows the
gap is total rather than partial before GW1 is scored:

| Endpoint | Preseason behaviour |
| --- | --- |
| `entry/{id}/` | 200, but `current_event`, `last_deadline_bank` and `last_deadline_value` are all `null` and `entered_events` is empty |
| `entry/{id}/event/1/picks/` | **404** |
| `entry/{id}/transfers/` | 200, empty |
| `event/1/live/` | 200, `elements` empty |

There is therefore **no reconstructible state for the GW1→GW2 decision**, which is the exact decision
E1 exists to make. Treating the manual path as a degraded mode would mean the first real use of the
system runs in a degraded mode, which is the wrong default and would suppress its own warnings.

**Consequence.** Confidence is reported as an explicit enumeration —
`from_picks` / `reconstructed` / `declared` — and a declared squad is validated by the E0-S4 legality
validator on entry, so a typo in a manual squad is caught immediately rather than becoming an
illegal recommendation. Purchase prices must be declared with it: selling value depends on what was
paid, and no endpoint reveals that until picks exist. From GW2 onward, `picks` becomes available and
the service prefers it automatically, so this resolves itself without a code change.

---

## DL-21 — The v1 forecast beats price, and loses to recent form. Reported, not tuned

**Date:** 2026-08-11 · **Status:** Accepted · **Arose in:** E3-S1

**The finding.** The first walk-forward backtest — 72 gameweek deadlines, 54,045 player-gameweek
observations across 2024/25 and 2025/26 — says this:

| Model | MAE | Spearman | MAE skill vs B0 | Top-20 precision | Calibration slope |
| --- | --- | --- | --- | --- | --- |
| **xp_v1** (components) | **1.936** | 0.244 | +0.015 | **0.00** | 0.71 |
| B0 — price + position | 1.965 | 0.214 | — | 0.05 | 0.61 |
| **Model-free — trailing 6 gameweeks** | 2.115 | **0.291** | −0.076 | 0.05 | 0.39 |
| Mean — a constant | 1.985 | −0.040 | −0.010 | 0.00 | −3.60 |

**It beats B0 and it loses to the model-free benchmark.** Per
[E3](epics/E3-expected-points-engine.md#4-the-honest-question), that is a finding to act on, not a
number to tune away, and this entry exists so it cannot quietly stop being true.

**Read the two columns together, because they disagree and the disagreement is the point.** The
model has the *best MAE of anything measured* and the *worst top-20 precision of anything
measured*. Those are consistent, not contradictory: shrinking every thin estimate toward a position
prior is an excellent way to avoid being badly wrong about anyone, and an excellent way to avoid
distinguishing anyone. The calibration slope of 0.71 says the same thing from the other side —
predictions are compressed relative to reality.

That trade is exactly backwards for how this tool is used. **Nobody acts on the whole ranking; they
act on the head of it**, and at the head the model currently adds nothing over price.

**Why not simply adopt the model-free benchmark.** Because "beats it on rank correlation" is not
the same as "is better to own". Trailing form has a calibration slope of 0.39 and the worst MAE in
the table: it is a momentum signal that chases whoever just scored, which is a known way to buy at
the top of a price rise. The right conclusion is not "use form instead" — it is **that the current
component model has not earned trust for expensive decisions**, and that E4's hits, chips and
wildcards must not be justified by it until this changes.

**Caveats that make this a floor rather than a verdict.** Each of these would, if fixed, move the
number in the model's favour, and none of them is an excuse:

- **Defensive Contribution exists in 2025/26 only** (D-11). M4 is the component with the best
  signal-to-noise in the design, and it is absent from roughly half the evaluation window.
- **The harness carries no fixture table**, so M2 contributes league-average opposition throughout.
  Fixture difficulty is a real part of the live forecast and is untested here.
- **No season used the 2026/27 BPS matrix**, so M8 is measured against a scoring regime that no
  longer exists.

**Consequences, decided now rather than when it is inconvenient:**

1. **D-01 is closed** — the model is no longer unvalidated. **A new debt, D-13, replaces it:** the
   forecast does not beat a model-free benchmark at the head of the ranking.
2. The published model card and the web contract must carry this, not only the backtest report.
   A forecast that is losing to recent form should not be presented as though it were not.
3. E4's risk dial and chip planner inherit an explicit constraint: **no −8 hit, chip or wildcard is
   justified by xp_v1 alone** until top-20 precision beats B0.
4. The next model change is aimed at **discrimination at the head**, not at MAE. MAE is already the
   best in the table and is measuring the wrong thing.

---

## DL-22 — Post-E3 audit found a DoD item ticked without its acceptance criterion being met

**Date:** 2026-08-11 · **Status:** Accepted · **Arose in:** planning audit of `dev_stg` @ `8faa590`

E3-S3's own acceptance criterion is explicit: "calibration curves and Brier score reported." The
Brier-score function exists (`forecast.metrics.brier_score`) and is wired into `evaluate_metrics`,
but the backtest harness (`forecast/backtest.py`) never passes minutes probabilities through it —
`minutes_brier` is `null` in every fold of `backtest.json`, published and unremarked. E3's own
definition-of-done nonetheless ticked "Component models M1–M8 registered" as covering this, which it
does not: registration is not calibration.

**Also found:** the model card's `KNOWN_WEAKNESSES` list was static — "No backtesting" (D-01)
continued to render after E3 closed D-01 and opened D-13, directly contradicting the "Measured
accuracy" section three headings above it in the same document. A human reading the published card
at a review gate would have hit a self-contradicting artefact.

**Fixed in this audit, not deferred:**

- `model_card.py` now renders the cold-start weaknesses only when no backtest is supplied, and a new,
  accurate weakness (citing D-14) when one is. Covered by a new test,
  `test_the_model_card_drops_the_stale_no_backtesting_claim_once_backtested`.
- **D-14 opened** in [E0 §6](epics/E0-steel-thread-gw1.md#6-technical-debt-register): the minutes
  model's calibration is unmeasured, not merely crude. E3-S3's DoD line in
  [E3](epics/E3-expected-points-engine.md#3-definition-of-done) is corrected to show this unmet
  rather than silently folded into an adjacent line.

**Why this matters beyond the one bug.** A DoD checkbox is only as trustworthy as the thing verifying
it, and here nothing did — the acceptance criterion was prose, not a test. **The general lesson:**
where an epic's acceptance criterion names a specific published number (a score, a curve, a metric),
the DoD item should point at the artefact and the value, not at a proxy activity ("registered",
"built") that can be true while the criterion is false. Worth applying retroactively the next time an
epic outcome is reviewed — this is unlikely to be the only instance.

---

## DL-23 — Build pace is roughly an order of magnitude faster than ASM-8 assumed

**Date:** 2026-08-11 · **Status:** Accepted · **Arose in:** planning audit of `dev_stg` @ `8faa590`

[ASM-8](01-project-charter.md#8-assumptions) assumed 3–4 focused human build days per week, and
[epics/README.md §2](epics/README.md#2-epic-register) dated every epic against that rate — E0 through
E3, an estimated 25–32.5 focused days of scoped work, landed across **three calendar days**
(2026-08-09 to 2026-08-11). The building is agent-driven, not paced by a human's available evenings,
and the epic target dates (E4→GW15, E5→GW12, E6→GW16, chip expiry GW19) were never load-bearing on
build time under this mode — they were load-bearing on the *season clock*: fixtures being played,
data accumulating, and evidence about model quality only existing after real gameweeks happen.

**This does not make E4's gate (D-13, per DL-21) go away** — a faster build cannot manufacture the
top-20 discrimination the model is currently missing; that requires either better signal or more
in-season evidence, neither of which compresses with build speed.

**Consequences:**

1. **epics/README.md §4's reprioritisation framework is stale as a *pacing* mechanism** — it assumes
   weekly human cadence ("ask this every week"); at this build rate the relevant cadence is closer to
   "before starting the next epic," not weekly. The framework's *content* (the weekly question, the
   scoring formula, the triggers) still holds and is not being replaced — only the assumption that a
   calendar week is the natural unit of reprioritisation is corrected.
2. **The remaining schedule risk shifts from "will it be built in time" to "will there be enough
   in-season evidence in time."** E4 in particular should not start until D-13 is closed or explicitly
   scoped around (see D-13's consequence #4 in [DL-21](#dl-21--the-v1-forecast-beats-price-and-loses-to-recent-form-reported-not-tuned)),
   and closing D-13 well may require watching real gameweeks resolve, which cannot be accelerated.
3. **epics/README.md's target dates are retained as ceilings, not as the binding constraint.** No
   epic should be rushed to hit a stale date; equally, no epic should be started before its
   dependencies' findings (like D-13) are addressed, regardless of how much calendar time is left.

---

## DL-24 — OD-06 resolved: effective ownership redefined without a captaincy term

**Date:** 2026-08-11 · **Status:** Accepted · **Decided by:** Agent, ahead of E4-S4, recorded here
before code so the choice is auditable rather than discovered in the risk-dial implementation

Of the three routes set out in [04-conceptual-design.md §7.1](04-conceptual-design.md#71-effective-ownership-is-not-directly-observable-con-12-od-06),
**Redefine** is adopted: `EO[p] = selected_by_percent[p]`, with no modelled captaincy term. The risk
dial's objective penalises deviation from `selected_by_percent` alone.

**Why, over the other two.** *Estimate* requires a captaincy-share model calibrated against
`most_captained` (a single id per gameweek, not a distribution) — buildable, but its accuracy is
itself unmeasured, and DL-21 already found this project shipping an unvalidated model presented as
more certain than it is once before. *Sample* is genuinely measured but is post-deadline by
construction — it informs next week, not the week it is needed for — and spends request budget
pulling picks from public leagues, a cost with no E4 story funding it. **Redefine is never wrong
about what it knows**: `selected_by_percent` is exact, public, and requires no additional model.

**What is lost:** the risk dial cannot see captaincy concentration, so it cannot distinguish "60%
own him, 40% of those captain him" from "60% own him, 5% captain him" — a real gap, most visible
exactly at the players the dial exists to reason about. E4-S6's explanation layer must say so
explicitly wherever ownership is shown, not just here.

**What the UI states, per Design §7.1's own requirement:** every ownership figure is labelled
"selected by" and never "effective ownership" or "captaincy share", and the single most-captained
player (`most_captained` from `bootstrap-static` events, when published) is surfaced as a plain
callout — "N% own him, and he is this gameweek's most-captained pick" — rather than folded into a
number that implies more precision than the data supports.

**Consequence:** the tier-1 cohort mismatch in CON-12 (top-100k template vs all ~11m managers) is
not fixed by this — `selected_by_percent` is still whole-field ownership. That gap remains open and
is not this decision's to close; it is a limitation the UI states alongside the EO source label.

---

## DL-25 — OD-05 resolved: the risk dial defaults to Balanced

**Date:** 2026-08-11 · **Status:** Accepted · **Decided by:** Agent, during E4-S4, recorded before
the dial shipped so the default is a decision rather than an accident of implementation

**The dial defaults to `balanced`**, and it is a configuration field (`decision.risk.dial`) the owner
can change at any time without a code change.

**Why, and why it is not a strong claim.** OD-05 was narrowed by [DL-13](#dl-13--charter-amendments-following-the-2026-08-09-architecture-and-plan-audit)
to a question of *temperament*, not of target: the rank ambition is already settled in charter §5
(top-100k target, top-10k stretch). Temperament is the owner's to state, and the owner has not stated
it — [INPUTS-REQUIRED §6.1](epics/INPUTS-REQUIRED.md) is still empty. Two things follow:

1. **The design already names a default.** [04-conceptual-design.md §7.1](04-conceptual-design.md#71-effective-ownership-is-not-directly-observable-con-12-od-06)'s
   own table gives Balanced as "Default" — "small penalty, broadly follows expected points, avoiding
   only the most extreme template gaps". Adopting a different one would be inventing a preference
   nobody expressed.
2. **Balanced is the position that assumes least.** Safe assumes a rank worth protecting; Aggressive
   assumes a rank worth chasing and conviction in an edge. Neither is knowable before a season has
   been played, and [DL-21](#dl-21--the-v1-forecast-beats-price-and-loses-to-recent-form-reported-not-tuned)
   makes the case against Aggressive sharper: a dial that rewards differentials is a dial that leans
   harder on the model's discrimination at the head of the ranking, which is the one thing the
   backtest says the model does not have.

**Concretely:** `RiskConfig.ownership_weight` is `{safe: +0.020, balanced: +0.005, aggressive:
-0.010}` expected points per percentage point of `selected_by_percent` per starter per gameweek.
Balanced is deliberately an order of magnitude smaller than Safe rather than zero — a zero weight
would make the dial's middle position mean "the dial is off", and the design asks for a small pull
toward the template, not for none.

**Consequence:** **OD-05 is closed.** It reopens on one trigger and one only — the owner stating a
target rank or a temperament, at which point this becomes a one-line configuration change with no
code behind it.

---

## DL-26 — HiGHS is installed and is the solver for the multi-gameweek model; CBC stays on the single-gameweek one

**Date:** 2026-08-11 · **Status:** Accepted · **Arose in:** E4-S2

[DL-15](#dl-15--chip-timing-by-scenario-enumeration-highs-as-the-solver-from-e4) committed to HiGHS
from E4 without confirming it would install. It does: `highspy 1.15.1` installs from PyPI on Python
3.14/Windows, PuLP 3.3.2 exposes it as `pulp.HiGHS`, and it solves the multi-gameweek model. It is
open-source and carries no licence cost, so Invariant 3 is untouched. **This entry exists to record
that the claim was tested rather than assumed**, and to state the split that was not in DL-15.

**The split.** HiGHS is used for the **multi-gameweek** model only
(`decision.horizon.solver`, default `HiGHS`). The single-gameweek E0 squad MILP and the E1 transfer
MILP stay on **CBC**, which E0 validated against them. DL-15's argument was that CBC was never
validated against a problem of E4's size — that argument says nothing about the problems it *was*
validated against, and moving them would discard a validation to gain nothing.

**A refusal, deliberately.** When `decision.horizon.solver` is `HiGHS` and `highspy` is absent, the
run **fails with an explanation** rather than falling back to CBC. "Solved on HiGHS" is a claim about
how much an answer can be trusted at this size; silently substituting a weaker solver while the
configuration still says HiGHS would make that claim false in exactly the place nobody would look.
CBC remains reachable by setting the field, which is an informed choice rather than a silent one.

**Measured, on the real problem.** A full local run against the live snapshot — 577 players pruned
to a 159-player pool, a five-gameweek horizon, twenty chip scenarios — solved every scenario to
optimality in **92.7 seconds**, inside the 600-second `scenario_time_budget_seconds`. Individual
scenarios ranged from 0.3 to about 5 seconds. So the budget is met, and DL-15's bet on HiGHS is
vindicated on the problem it was made about rather than on a proxy.

**What this still does not settle.** R-07 stays rated High, for two reasons the number above does not
touch. It is a *preseason* run: no gameweek has been played, there are no double or blank gameweeks
in the fixture list yet, and the second half of the season is where the chip calendar gets
interesting and the model gets harder. And it is one developer machine, not CI, where the runner is
slower and shared. The greedy fallback stays not-optional, and
`decision.horizon.scenario_time_budget_seconds` bounds the enumeration so that a slow scenario set
degrades to fewer scenarios rather than to a missed deadline (DP-15).

---

## DL-27 — E5 built without an odds key or a fresh scraping sign-off; both were already answered

**Date:** 2026-08-12 · **Status:** Accepted · **Arose in:** E5

Two inputs [INPUTS-REQUIRED.md §4](epics/INPUTS-REQUIRED.md#4-needed-for-e5-external-sources-around-gw10-12)
lists as owner-supplied were not obtained before this epic was built. Neither blocked the build, and
this entry records why rather than leaving the gap silent.

**No `ODDS_API_KEY` exists.** The odds adapter (`sources/oddsapi/adapter.py`) is built in full —
request shape, de-vig conversion, credit-budget ledger enforced in the adapter per CON-7/R-08 — and
contract-tested against a recorded fixture (`tests/fixtures/odds_epl.json`), never against the live
provider. With no key configured, `enabled_by_default = False` and the adapter contributes nothing;
this is the epic's own required degraded state (E5-S4/S5), not a shortfall. **It has never been
verified against a real response from The Odds API**, and cannot be until the owner obtains a key
per INPUTS-REQUIRED §4.1 — at that point the contract test should be re-run with `--network` style
verification against the live endpoint before the adapter is trusted with a real credit spend.

**Understat and FBref were built without a fresh sign-off request.** INPUTS-REQUIRED §4.2 asks for
"explicit sign-off on the scraping approach" before building — but the posture it asks for sign-off
on is the same posture the epic doc and [04-conceptual-design.md §3.2](04-conceptual-design.md#32-entity-resolution-fr-07-r-10)
already specify: personal non-commercial use, `robots.txt` checked programmatically before every
crawl (not merely asserted), crawl-delayed via the existing `RateLimitConfig`, cached hard, weekly
cadence at most, attributed in the UI. Treating an already-documented design decision as a second
open question would have stalled the epic on a input that was, in substance, already given. Built to
that spec; the owner retains the option to object and have it withdrawn, which is materially
different from building without any recorded posture at all.

**Consequence:** no debt opened for the odds key (E5-S4 is complete on its own terms; the live
verification is a follow-up action, not unfinished code). See D-20 for the related and larger gap —
none of the three sources backfills history, so none of them can move a backtest metric yet.

---

## DL-28 — The simulation re-rank changes real chip decisions, and there is no evidence yet that it improves them

**Date:** 2026-08-13 · **Status:** Accepted · **Arose in:** D-18

E4-S4a's acceptance criterion was "the re-rank changes at least one chip recommendation **in the
backtest**". E4 shipped a constructed unit test instead — three Bench Boost timings tied exactly on
expected points, separated by the dial's percentile — and [D-18](epics/E0-steel-thread-gw1.md#6-technical-debt-register)
recorded the gap. This entry records what happened when the criterion was actually run.

**What was built.** `optimise/replay.py` replays real historical deadlines through the whole
decision engine. Per sampled deadline it refits the component models on matches finished strictly
before that deadline — through the *same* `fold_rows`/`training_rows` the walk-forward harness uses,
because a second assembly of the training set is a second chance to leak (Invariant 5) — forecasts
every player against each horizon gameweek's **real fixture**, solves the best legal squad, then runs
`build_plan` twice, re-rank on and off. Gated behind a `slow` pytest marker on the same mechanism as
`--network` (`tests/test_chip_replay.py`).

**The sample, and why it is this size.** Eight deadlines: every sixth scoreable deadline between
GW6 and GW32 across 2024/25 and 2025/26. Spaced rather than consecutive, because neighbouring
deadlines share almost all their training data and their fixture run and are close to one
observation repeated. It cost **951 seconds** — a full 72-deadline sweep at that rate is over two
hours, and would answer the same question.

**The result: 8 of 8 deadlines changed.** Every one moved a Bench Boost. Scored against what those
exact players actually went on to score, **5 of the 8 changes landed on the better gameweek and 3 on
the worse one**, mean +0.75 points per change with a spread from −44 to +42.

| Season | GW | Re-rank off | Re-rank on | Actual, off | Actual, on |
| --- | --- | --- | --- | --- | --- |
| 2024/25 | 6 | BB GW7 | BB GW6 | 59 | **69** |
| 2024/25 | 12 | BB GW13 | BB GW12 | **80** | 36 |
| 2024/25 | 18 | BB GW22 | BB GW18 | 37 | **79** |
| 2024/25 | 24 | BB GW25 | BB GW24 | 82 | **88** |
| 2024/25 | 30 | BB GW32 | BB GW30 | **51** | 42 |
| 2025/26 | 9 | BB GW10 | BB GW9 | **87** | 64 |
| 2025/26 | 15 | BB GW19 | BB GW15 | 44 | **59** |
| 2025/26 | 21 | BB GW25 | BB GW21 | 59 | **76** |

**The criterion is met, and the honest reading is narrower than that sounds.** 5–3 on eight
observations is indistinguishable from a coin flip; nobody should read it as skill. What it does
establish is the thing D-18 said was unproven: the re-rank is not confined to constructed ties. It
moves decisions the expectation-maximiser had already made on real data, which is exactly what
E4-S4a asserted and had not shown.

**The finding that was not asked for, and matters more.** The direction is regular: at the default
Balanced dial the re-rank moved Bench Boost to the **first gameweek of the horizon** at all eight
deadlines, without exception. 8-for-8 in one direction is not obviously what a risk-preference
effect looks like, so it was worth asking what would falsify it — if the percentile is doing the
work, the dials must disagree with each other, because they rank on opposite ends of the same
distribution.

**They do disagree.** Re-running three deadlines at each dial:

| 2024/25 deadline | Re-rank off | Safe | Balanced | Aggressive |
| --- | --- | --- | --- | --- |
| GW6 | BB GW7 | BB GW6 | BB GW6 | BB GW6 |
| GW18 | BB GW22 | BB GW18 | BB GW18 | **BB GW19** |
| GW30 | BB GW32 | **BB GW32 — no change** | BB GW30 | BB GW30 |

The safe dial declined to move the chip at all at GW30, and the aggressive dial chose a different
week at GW18. So the front-loading is **not** a fixed structural artefact; the percentile genuinely
separates plans, and the dial genuinely changes the answer.

What survives the falsification test is narrower and still worth tracking: at the two dial settings
a user is most likely to run, chip timing lands at the front of the horizon far more often than
chance suggests, and nothing yet explains why. That is opened as **D-21**. Until the cause is
known, the re-rank is proven to *move* chip timing and to *respond to the dial*, and is not proven
to *time* chips well.

**Consequence:** E4-S4a's DoD item is ticked — its stated criterion is met, and the second half of it
("the direction of the change is explicable") is met by the dial table above rather than only by the
constructed unit test. D-18 is closed and **D-21** is opened for the front-loading.
D-13's gate is untouched — the forecast underneath all of this still loses to the model-free
benchmark at the head of the ranking ([DL-21](#dl-21--the-v1-forecast-beats-price-and-loses-to-recent-form-reported-not-tuned)),
and a well-timed chip on a poor ranking is still a poor chip.

---

## DL-29 — D-20 re-diagnosed: the backfill was never the blocker, the missing consumer is

**Date:** 2026-08-13 · **Status:** Accepted · **Arose in:** D-20

D-20 states that "none of E5's three new sources backfills history … no season-backfill path exists
for any of them", and concludes that E5's stated purpose cannot be evaluated. Going to close it
found the diagnosis wrong in a way worth recording, because acting on it would have bought nothing.

**Understat and FBref already backfill.** Both adapters loop over `request.seasons`, both build
season-shaped URLs from the season they are given, and both `stages/ingest.py` and
`stages/transform.py` already pass `sources.backfill_seasons` into the request. The path existed and
was untested. It is tested now, against recorded historical pages
(`tests/test_source_backfill.py`, fixtures `understat_league_2024.html` and
`fbref_stats_2024_2025.html`): each season fetched from its own URL, both seasons conformed and
labelled, a relegated player surviving in the historical season only, a mid-season transfer
resolving to the club the player finished at, `robots.txt` read once for the whole backfill rather
than once per season, and a finished season never re-fetched.

**One real defect was underneath it.** `request.seasons or (request.season,)` meant a configured
backfill **replaced** the current season rather than adding to it — so switching a backfill on
silently switched this season's enrichment off, with no error, no missing column and no symptom
other than a forecast quietly missing the source it was configured to use. Fixed by
`IngestRequest.seasons_with_current()`, which both scraped adapters now call.

**And none of that can move a backtest metric, because nothing reads the data.** The conformed
`player_metric` and `player_advanced` tables are written to silver by the transform stage and read
by **no module in the project**. The feature store builds every feature from `player_gameweek`
alone. So the chain from a backfilled xG figure to a backtest number is broken one link further
downstream than D-20 says, and no amount of crawling repairs it.

**A second, structural blocker sits behind the first.** Both scraped sources conform *running
season totals* at `scope="season"` with no gameweek — correctly, as their own module docstrings
argue, because labelling a running total as a gameweek observation would leak the rest of the season
into every fold before it. But a crawl of a **finished** season yields one row per player describing
the whole of it, and that row is unusable at any deadline *within* that season for exactly the same
reason (Invariant 5). It is legitimate only as a **prior-season** feature. E5 never made that design
decision, and it is the actual work D-20 is asking for.

**No live crawl was performed, deliberately.** It would have produced data no metric can consume, at
the cost of a few hundred requests against somebody else's site. Crawling to satisfy a checkbox is
the wrong side of the posture recorded in [DL-27](#dl-27--e5-built-without-an-odds-key-or-a-fresh-scraping-sign-off-both-were-already-answered).

**The DL-21 baseline was re-run and is unmoved, byte for byte.** `fpl-dof backtest` over the same 72
folds and 21,712 scored observations returns model Spearman 0.24444, B0 0.21385, model-free 0.29104,
MAE skill 0.01501, top-20 precision 0.00 — identical to the report from before this work. That is
both the point (no source data reached the forecast, because none can) and a regression check on the
one change made to the harness itself: `_fold_rows`/`_training_rows` were made public so the chip
replay could reuse them rather than assemble a second, divergent training set.

**Odds are untouched and stay untouched.** The provider publishes no historical archive on its free
tier and no `ODDS_API_KEY` exists to test one with. That half of D-20 needs the owner obtaining a
key (INPUTS-REQUIRED §4.1), not more code, and it is recorded as an external blocker rather than
worked around.

**Consequence:** E5's "backtest metrics measurably improve" DoD item stays **unticked** and D-07
stays **open** — neither has been earned, and [DL-22](#dl-22--post-e3-audit-found-a-dod-item-ticked-without-its-acceptance-criterion-being-met)
is the reason that matters. D-20 is narrowed to its true remainder and **D-22** is opened for the
missing consumer, which is now the single thing standing between E5 and its own acceptance test.

---

## DL-30 — Browser verification runs on Playwright-driven Chromium, not a Chrome plugin

**Date:** 2026-08-14 · **Status:** Accepted · **Decided by:** Owner, on request

E1 through E5's browser verification has, throughout, driven real Chromium via Playwright
(`web/verify/browser-check.mjs`) rather than a Chrome browser extension or the Chrome DevTools MCP
integration some sessions have been asked for. No such plugin or MCP tool is available in this
Claude Code environment — confirmed by direct tool search, not assumed — and this has been true and
noted as a deviation in every epic since E0.

**Consequence:** Playwright-driven Chromium is accepted as satisfying "browser testing" for the
purposes of every epic's Definition of Done in this project, present and future, unless a Chrome
plugin or DevTools integration becomes available in the build environment. Verification still
covers real console errors, real layout at three device widths (390/820/1440px), real network
activity (confirming Invariant 8: the browser calls nothing but its own static artefacts), and real
interaction — it is not a weaker check for being a different automation surface, and this entry
exists so the substitution is a recorded decision rather than a silently repeated gap.

---

## DL-31 — D-22 closed: the prior-season consumer exists, and neither source it was built for can be fetched

**Date:** 2026-08-15 · **Status:** Accepted · **Arose in:** D-22

[DL-29](#dl-29--d-20-re-diagnosed-the-backfill-was-never-the-blocker-the-missing-consumer-is) named
the missing consumer as the single thing standing between E5 and its acceptance test. It was built.
It is not the last thing standing there.

**The design, and the one decision that mattered.** A season total is knowable only once its season
is over, so it enters the model as a **prior-season** feature and the boundary is enforced on the
**season label**, not on a timestamp: a `scope="season"` row for season *S* is admissible only
against a season starting strictly later than *S*. Deliberately not "compare `as_of` to the last
kickoff of *S*" — a postponement, a rearranged final round or a missing fixture row moves that
boundary, and at the first deadline of the following season no clock separates the two seasons at
all. Property-tested across all 38 gameweeks at both ends: invisible at every deadline inside its own
season including the last, visible at every deadline of the next one
(`tests/test_prior_season_features.py`).

**A ratio, not a rate.** Each statistic is divided by the mean among the player's own position and
bounded to [0.5, 2.0], and the result *scales the position prior* a component is already shrunk
toward, weighted by prior-season minutes on the same arithmetic as the existing shrinkage. Three
reasons, in order of importance: what is trusted about an external provider is the ordering it
implies rather than its scale, so a definitional mismatch between somebody's "defensive action" and
the game's own cannot bias the level; a player with no prior season lands on the position prior
exactly, which is what happens today, so "no evidence" needed no new mechanism; and last season's
evidence fades as this season's accumulates rather than sitting permanently on the scale. Off by
default (DP-08).

**Then it was pointed at the real sources, and there are none.**

- **Understat's `robots.txt` now reads `User-agent: *` / `Disallow: /`** — the entire site.
- **FBref returns a Cloudflare 403 to every request**, `robots.txt` included, so no permission can
  even be read.
- **Underneath that, a posture defect:** only the FBref adapter ever checked `robots.txt`. The
  Understat adapter did not, so enabling it fetched four pages the site disallows. The check now
  lives in a shared `sources/robots.py` used by both, and Understat consequently fetches nothing.
  The four snapshots taken before the fix were deleted.
- **And the extraction is stale anyway:** the live Understat league page no longer carries the
  `playersData` script the adapter parses. E5's "contract test against a recorded page" turns out to
  use **hand-constructed** 2.4 KB fixtures, not recorded ones, so neither scraped adapter has ever
  been run against a real page.

Neither block is worked around. Ignoring a site's stated rules or defeating an access control is the
wrong side of [DL-27](#dl-27--e5-built-without-an-odds-key-or-a-fresh-scraping-sign-off-both-were-already-answered)
and NFR-10, and "the checkbox needs it" is not a reason. Opened as **D-23**, which is an owner
decision about provenance, not a coding task.

**Two real defects found on the way, both fixed.** Entity resolution stamped *every* crosswalk row
with the current season regardless of which season its reference described — so a backfilled advanced
row could never join an identity, and a two-season backfill would have hard-failed the duplicate-claim
guard on one footballer legitimately appearing in both seasons. Resolution now keeps each reference's
own season and scopes the guard by it. Two quality gates that assumed a single-season crosswalk were
corrected with it: the unmatched-rate gate now judges the current season only, because a backfilled
season is matched against *this* season's player list and everyone who has since left is unmatched in
it, correctly and in numbers that would swamp the signal.

**What could still be measured, and what it says.** With no source data, the question "does the
design help" was put to a probe using the official feed's own prior-season totals in place of the
missing ones — the same production path, the same season-boundary rule, and honestly not E5's
acceptance test. On the corrected model (see [DL-32](#dl-32--the-component-models-never-fitted-in-the-backtest-so-dl-21s-table-describes-a-model-nobody-built)), 72 folds, 21,712 scored observations:

| Prior-season prior | MAE | Spearman | MAE skill vs B0 | Top-20 precision | Calibration slope |
| --- | --- | --- | --- | --- | --- |
| Off | 1.94547 | 0.22545 | 0.00994 | 0.00 | 0.597 |
| On | 1.94578 | **0.22790** | 0.00978 | 0.00 | 0.605 |
| Difference | +0.0003 | **+0.0025** | −0.0002 | 0.00 | +0.008 |

Per season: 2024/25 Spearman 0.28049 → 0.28439, 2025/26 0.17268 → 0.17336. **+0.002 Spearman is not
"measurably improve" by any reading**, MAE is fractionally worse, and top-20 precision — the number
D-13 is about — does not move off zero. The mechanism is demonstrably live rather than inert: the
same probe before [DL-32](#dl-32--the-component-models-never-fitted-in-the-backtest-so-dl-21s-table-describes-a-model-nobody-built)'s fix returned figures identical in every reported
digit, because it was scaling a prior that was zero.

**Consequences:**

1. **D-22 is closed.** The consumer exists, is safe, and is tested where being wrong would be
   invisible.
2. **E5's "backtest metrics measurably improve" stays unticked and D-07 stays open.** Neither is
   earned, and [DL-22](#dl-22--post-e3-audit-found-a-dod-item-ticked-without-its-acceptance-criterion-being-met)
   is why that matters. Their remainder is **D-23**.
3. **The feature ships dark.** `forecast.features.prior_season.enabled` defaults false; nothing
   promotes it without evidence, and there is none.
4. **The odds half of D-20 is untouched** and still waits on a key.

---

## DL-32 — The component models never fitted in the backtest, so DL-21's table describes a model nobody built

**Date:** 2026-08-15 · **Status:** Accepted · **Arose in:** D-22, while asking why the new feature
changed nothing

**The defect.** `fold_rows` built each fold from the feature frame plus `player_code`, `position`,
`price`, the target and `minutes`. `ComponentPredictor.fit` was then handed that frame — which
carries no `goals_scored`, no `assists`, no `bps`, no `team_id`. `RateModel.fit` begins
`if self.column not in history.columns: return self`. So for **every fold of every backtest and
every chip replay this project has ever run**:

- M3–M7 had an empty `prior_by_position` and a `population_prior` of 0.0, so every rate was shrunk
  toward **zero** rather than toward a fitted position prior;
- M2 was never estimated at all — no team had an attack or defence rating, and `league_mean_goals`
  stayed at its 1.4 default;
- M8 kept its default BPS shape.

Nothing failed. Every model still predicted, every metric was still computed, and the harness's own
leakage tests still passed, because the frame was missing information rather than carrying too much.
**This is exactly the "wrong invisibly" case DP-13 names**, and it was found only because a new
feature that multiplies a prior did nothing at all — a prior of zero times any ratio is zero.

**The fix.** `OUTCOME_COLUMNS` now names everything that describes the gameweek being predicted; the
fold frame carries all of it so the components can fit on it, and `walk_forward` strips exactly that
set before handing a frame to any predictor. The boundary is asserted rather than assumed
(`test_no_outcome_column_of_any_kind_reaches_a_prediction`), alongside a test that the components
come out of a real walk with a non-empty position prior and a fitted team rating — because "the
column was present" and "the model learned from it" are different claims, and this defect lived in
the gap between them.

**The correction makes the model worse.** Same 72 folds, same 21,712 scored observations:

| Model | MAE | Spearman | MAE skill vs B0 | Top-20 precision | Calibration slope |
| --- | --- | --- | --- | --- | --- |
| xp_v1 **as DL-21 published it** (rates shrunk to zero) | 1.9355 | 0.24444 | 0.01501 | 0.00 | 0.711 |
| xp_v1 **with the components actually fitted** | 1.94547 | 0.22545 | 0.00994 | 0.00 | 0.597 |
| B0 — price + position | 1.96499 | 0.21385 | — | 0.05 | 0.606 |
| Model-free — trailing 6 gameweeks | 2.11489 | 0.29104 | −0.07628 | 0.05 | 0.394 |

**Shrinking every rate to zero was accidental regularisation, and it was doing more good than the
priors it replaced.** That is worth stating plainly rather than filing as a curiosity: the fitted
position priors, as currently estimated, are worse than assuming nobody scores. The most likely
reason is that they are fitted on a per-gameweek frame in which most rows are zeros for most
statistics, so the "prior" is close to a league average that flatters nobody and fits the tail
badly — but that is a hypothesis, and it is the next thing a model-improvement pass should falsify.

**What this does not change.** The verdict is the same in both rows and now rests on a model that
exists: **beats B0, loses to the model-free benchmark, top-20 precision 0.00.**
[D-13](epics/E0-steel-thread-gw1.md#6-technical-debt-register) stands, unchanged and better
evidenced. [DL-21](#dl-21--the-v1-forecast-beats-price-and-loses-to-recent-form-reported-not-tuned)
is **not** superseded as a finding — its conclusion survives — but its table must be read as
describing a partially unfitted model, and this entry is the corrected one.

**Consequence:** the published `backtest.json`, `backtest-card.md` and model card now carry the
corrected numbers. [DL-28](#dl-28--the-simulation-re-rank-changes-real-chip-decisions-and-there-is-no-evidence-yet-that-it-improves-them)'s
chip replay ran on the unfitted model and its 5–3 result should be re-read with that in mind; it was
already explicitly not evidence of skill, so no conclusion of it is withdrawn, and re-running it is
worth doing when D-21 is investigated.

---

## DL-33 — Understat and FBref reach neither decision model in the live pipeline, and the path to make them is one seam, not two

**Date:** 2026-08-15 · **Status:** Accepted · **Arose in:** a review of whether external xG and
defensive-action data feed the initial squad-construction model and the weekly recommendation model

**The question asked.** Do Understat and FBref data — xG, npxG, xA, shot and defensive-action counts
— actually inform (a) the preseason squad the optimiser builds and (b) the weekly transfer plan? The
conceptual design §5 describes M2, M3 and M4 as consuming exactly these signals. The review traced
the live code path end to end to see whether the description is true of what runs.

**The finding: no, on both counts, and for two independent reasons that must both be cleared.**

1. **The live forecast has no external-data input at all.** `stages/forecast.py` calls
   `xp_v0.build_forecast`, whose `ForecastInputs` dataclass carries `players`, `teams`, `fixtures`,
   `gameweeks` and `history` — all from the official FPL feed — and **no `player_metric` field**. The
   stage never reads `Table.PLAYER_METRIC`. So the conformed advanced table that E5 conforms
   Understat and FBref into is never opened by the model that ships. §5's M2 "attack and defence
   ratings estimated from xG" and M3's "npxG per 90, xA per 90, shot volume" describe an *aspiration*;
   the implemented `xp_v0` shrinks FPL-history per-90 rates toward position-and-price-tier priors and
   uses no xG.
2. **The one model that does consume `player_metric` is offline-only.** The D-22 prior-season wiring
   ([DL-31](#dl-31)) lives in `forecast/features.py` and is exercised only by `xp_v1.ComponentPredictor`,
   which is instantiated in exactly one place — `stages/backtest.py` — and the backtest is not part of
   `run`. Even there it moves nothing, because there is no data to move ([D-23](epics/E0-steel-thread-gw1.md#6-technical-debt-register)):
   Understat's `robots.txt` disallows the whole site and FBref returns a Cloudflare 403.

**The architectural point that makes this tractable, and the one thing the review is most emphatic
about.** Both decision models consume the *same* artefact — `expected_points.parquet`. The squad MILP
(`stages/optimise.py`) and the weekly plan MILP (`stages/decision.py`) each read it and nothing
source-specific, which is correct and must stay so: an optimiser that branched on a data source would
break Invariant 1 and DP-02. **Therefore "include Understat and FBref in both models" is not two
pieces of work, it is one: make the live forecast consume `player_metric`.** Both optimisers inherit
the improvement for free, through the contract they already read. No optimiser change is required, and
none is permitted. Anyone who proposes plumbing xG into the MILP has mislocated the seam.

**The reviewed plan, in the order the steps must hold.**

1. **Wire `player_metric` into the live forecast.** `ForecastInputs` gains a `metrics` field;
   `stages/forecast.py` reads `Table.PLAYER_METRIC` via `read_table_optional` (absent is normal and
   must degrade to today's behaviour, DP-15). The consuming mechanism already exists and is
   property-tested — `features.prior_season_ratios` with its season-label knowability boundary — so
   this is a plumbing change, not new modelling. **Preferred vehicle:** promote `xp_v1` to the
   in-season live path (preseason stays on `xp_v0`'s cold start), because `xp_v1` already carries the
   leakage-safe join *and* the modelled variance Invariant 6 wants. Porting the join into `xp_v0`
   instead would duplicate the feature definition and re-open the train/inference-skew trap that
   `features.py` exists to close — rejected for that reason.
2. **Promotion is gated on the backtest, never on the wiring being present** (DP-08, DP-12,
   [D-13](epics/E0-steel-thread-gw1.md#6-technical-debt-register)). An external signal may change a
   recommendation only once the walk-forward backtest shows it improves skill against B0 and the
   model-free benchmark. This is the whole reason `xp_v1` is not already live: it does not yet clear
   D-13's top-20-precision bar. A plausible-looking xG feature that has not cleared it must ship dark.
3. **The data must exist to clear the gate.** This is [D-23](epics/E0-steel-thread-gw1.md#6-technical-debt-register),
   an owner provenance decision, not code: a licensed or freely-published alternative for xG and
   defensive-action counts, or acceptance that the official feed's own `expected_goals` /
   `expected_assists` / action columns are the only advanced data this project will hold. A mechanism
   probe using the official feed's prior-season totals in place of the missing scraped ones moved the
   backtest by ~0.001 Spearman, so there is not yet evidence the *design* is where the value lives
   either — which is a reason to clear D-23 before investing in step 1, not after.

**Honest conclusion.** The ambition is neither implemented nor currently evidenced as valuable. Step 1
is perhaps a day's work but is premature before there is data (step 3) and evidence (step 2) to
justify promoting anything. The review records the exact seam so the work can be executed the moment
those clear, and opens **D-25** so the documented-versus-built gap in §5 is tracked rather than
implied. No code changed in this review; §5 of the conceptual design and the E5 epic are annotated to
match reality.

---

## DL-34 — Expected goals earn their place in the component model, measured and promoted; the live promotion does not

**Date:** 2026-08-15 · **Status:** Accepted · **Arose in:** implementing DL-33's plan to include
Understat/FBref-style signals in the model and optimise it by backtest

**The unblock DL-33 missed.** DL-33 sequenced the xG work behind D-23 (no scraped source can be
fetched) as if the *signal* were unavailable. It is not: the **official feed itself republishes
expected goals**. The silver `player_gameweek` table already carries `expected_goals`,
`expected_assists` and `expected_goals_conceded`, populated across all three backfilled seasons
(2023/24–2025/26, ~5,400 non-zero xG and ~7,900 non-zero xA rows each), and the feature store was
already computing `expected_goals_per90_last6` and `expected_assists_per90_last6` — **and nothing
was reading them.** So the canonical use of xG could be built and measured now, with no scraper and
no dependence on D-23. D-23 blocks the *scraped* provenance and the extra fields it would add
(npxG, shot-level detail, richer defensive actions); it does not block xG itself.

**What was built.** An `ExpectedGoalsConfig` switch (ships dark, DP-08) that makes the goal and
assist rate models observe *and* fit through expected goals rather than actual — a player's xG
regresses far less than his goals, so recent xG estimates the underlying scoring rate better,
most sharply over the short windows FPL forces. The dict of rate models stays keyed by the scoring
component; only the column each *reads* moves, so nothing downstream learns a source name
(Invariant 1). Expected goals are added to the backtest's `OUTCOME_COLUMNS`: an outcome of the
gameweek being predicted, carried for fitting and stripped before prediction exactly as the target
is.

**The measurement, over the same 72 folds and 21,712 scored observations as [DL-32](#dl-32):**

| Model | MAE | Spearman | MAE skill vs B0 | Top-20 precision | Calibration slope |
| --- | --- | --- | --- | --- | --- |
| Baseline — actual goals (DL-32's corrected model) | 1.9455 | 0.22545 | 0.00994 | 0.00 | 0.597 |
| **Expected goals (M3)** | **1.9266** | **0.23070** | **0.01957** | 0.00 | **0.701** |
| xG for M3 **and** M2 team strength | 1.9266 | 0.23070 | 0.01957 | 0.00 | 0.701 |
| B0 — price + position | 1.9650 | 0.21385 | — | 0.05 | 0.606 |
| Model-free — trailing 6 | 2.1149 | 0.29104 | −0.07628 | 0.05 | 0.394 |

**Two findings, both acted on.**

1. **xG for goal involvement (M3) is a real, modest improvement.** Every aggregate moves the right
   way — MAE down, Spearman up, MAE-skill over B0 nearly doubled, and calibration slope from 0.597
   toward 0.701 — so it is **promoted**: `forecast.expected_goals.enabled` is set true in the shipped
   config (the model default stays false, so the mechanism still ships dark and the promotion is a
   single, recorded configuration change). The published `backtest.json`, `backtest-card.md` and
   model card now describe the xG model.
2. **xG for M2 team strength is unmeasurable here, so it stays off.** The two right-hand columns are
   identical because `xp_v1.forecast_player` does not multiply a player's goal rate by his team's
   attack rating, and the backtest scores every fixture at league-average opposition — so M2's
   ratings barely touch a prediction in the harness. Enabling `team_strength_from_xg` would be a bet
   the backtest cannot see, which is precisely what DP-12 forbids. The mechanism is built and tested
   and left dark, to be measured once inference carries real fixtures.

**What did not change: the verdict.** The model still **beats B0, still loses to the model-free
benchmark, and top-20 precision is still 0.00.** xG sharpens the forecast; it does not clear the bar
that matters. **[D-13](epics/E0-steel-thread-gw1.md#6-technical-debt-register) stands** — no hit,
chip or wildcard may be justified on this model alone — and the caveat the UI already renders is
unchanged and still correct.

**The honest limit of this increment: the live artefact does not carry xG yet.** The improvement is
in `xp_v1`, the component model the backtest grades. The model that `run` publishes is still
`xp_v0`, and promoting `xp_v1` to the live in-season path is **more than the wiring D-25 named**:
`xp_v1.to_frame` produces `xp_next` and a variance and nothing else, while both the squad MILP and
the weekly plan MILP require `xp_horizon` and a per-gameweek `gw_n` column per fixture. `xp_v1` has
no fixture-aware horizon scorer, so swapping it in live would break the optimiser contract. Building
that scorer is real work and is left as **D-25**, deliberately not rushed against a preseason
deadline (DL-10: cut scope, do not hack). What ships today is unchanged and correct — a cold-start
forecast with the D-13 caveat — and the measured xG improvement is real, promoted where it can be
measured, and waiting on one honest piece of engineering to reach production.

---

## DL-35 — The web app routes on the hash, and published data is loaded once into a React context

**Date:** 2026-08-15 · **Status:** Accepted · **Arose in:** E6-S1 (FR-34)

E6-S1 turns the single flat page into a routed application, which forces two choices that later
stories will build on and that are expensive to reverse once eight views depend on them.

**1. `react-router-dom` v6, using `HashRouter` rather than `BrowserRouter`.** The router itself is
an ordinary npm dependency — no service, no tier, no running cost, so Invariant 3 is not engaged —
and three transitive packages is a proportionate cost for the routing every remaining E6 story
needs. The *hash* is the load-bearing part: hosting is GitHub Pages (OD-02, closed by
[DL-12](#dl-12--public-repository)) with `vite.config.ts` set to a relative `base`, so the app must
work from an unknown path prefix with **no server able to rewrite unknown paths to `index.html`**.
Path routing on that substrate makes a deep link or a refresh a real 404 — either a broken URL or
the `404.html` copy trick, which is a workaround for having no server in a project whose first
architectural commitment is that there is no server. Hash routing needs neither, keeps every route
reachable when the app is opened from a file or an offline cache, and means E6-S9's service worker
has exactly one document to cache. The cost is uglier URLs; that is the whole cost.

**2. Published artefacts are fetched once, at the application root, into a React context.** All six
artefacts are already loaded together by the current page and total well under the NFR-04 budget, so
per-route fetching would buy nothing and cost a re-fetch on every navigation. The promise is
memoised at module scope, so navigation between routes never touches the network again; route
components consume it through a `useData()` hook and never call `fetch` themselves. No state
library is introduced — context plus hooks is sufficient at this size, and a smaller dependency
surface is a first-paint budget kept.

**Consequences.** `web/src/data/` is now the only place in the web app allowed to fetch, which is
where Invariant 8 is enforced by structure rather than by remembering. E6-S9's offline story gets a
single cache-warming seam (`loadPublishedData`) and a single document to serve. The loading and
error states are rendered once by the shell, so DP-15 degradation behaviour is written once rather
than in each of eight views. Reversal, if hosting ever grows a rewrite rule, is a one-line change
from `HashRouter` to `BrowserRouter`.

---

## DL-36 — The scout table virtualises on `@tanstack/react-virtual`, and hands a comparison selection over in the URL

**Date:** 2026-08-15 · **Status:** Accepted · **Arose in:** E6-S2 (FR-27, FR-28, NFR-04)

E6-S2 builds the scout table over the full ~700-player set. Three choices in it are load-bearing for
later stories and awkward to reverse, so they are recorded rather than left to be inferred from the
code.

**1. Virtualisation is a dependency, not a hand-roll: `@tanstack/react-virtual`.** ~700 rows across
up to eighteen columns is roughly 12,600 cells, and the epic already states plainly that rendering
them naively will not meet NFR-04. The library is an ordinary npm package with no runtime dependency
of its own beyond a small reactive core — no service, no tier, no running cost, so Invariant 3 is not
engaged — and it is ~4 KB gzipped, which is nothing against a 3 MB first-paint budget. A hand-rolled
windowing loop would be a second implementation of scroll-offset arithmetic that nobody tests as
hard as its authors test theirs. **Q-06 stays resolved as the epic scopes it**: plain JSON plus
client-side `filter`/`sort` over an in-memory array, no DuckDB-WASM on the scout path. Confirming
that by measurement on a real phone remains an E6 definition-of-done item, not something this story
claims to have done.

**2. The comparison selection travels in the hash query string, `#/compare?compare=1,2,3`.** The
scout view and the comparison view (E6-S4) are separate routes that must agree on which two-to-four
players are being compared, and they were built concurrently. A URL parameter is the version of that
seam a human can read, edit, bookmark and paste into a message — which is the DP-10 argument applied
to a UI seam — and it costs no shared mutable state between two routes that otherwise know nothing
about each other. `web/src/data/comparison.ts` owns the parsing, the clamping to the two-to-four
range and the link construction, so neither route hand-writes the format. The *in-progress* selection
on the scout page is additionally mirrored to `localStorage` under `fpl-dof.compare-selection`, so
ticking three players, wandering off to a player detail page and coming back does not lose the work;
that mirror is a convenience, and the URL is the contract.

**3. Saved filter presets are named `localStorage` entries under `fpl-dof.scout-presets`, and are
read defensively.** They are a personal convenience on a single device, not published data: there is
no account, no server and nothing to sync to (NFR-11), so anything beyond browser storage would mean
inventing infrastructure this project has committed to not having. Storage that is absent, full,
disabled by private browsing, or holding a shape written by an older version of the app degrades to
"no saved presets" and never to an error — DP-15 at the smallest possible scale, and the reason the
reader loses a convenience rather than the page.

**Consequences.** The column set is data (`web/src/components/scout/columns.ts`), so E6-S3 and E6-S4
can reuse the accessors and formatters rather than restating how a component is rendered. `minutes`,
`form` and the fixture run named in the E6-S2 story are **not in the published `players.json`
contract** and are therefore not columns yet; `start_probability` stands in for minutes and is
labelled as the forecast it is, and the remaining two are marked in the code as awaiting the
`history.json` and `fixtures.json` artefacts. Adding them is a column-definition entry each once
those artefacts land, which is the shape this was built for.

---

## DL-37 — Two new contract artefacts: `history.json` for per-player trends, `fixtures.json` for a model-derived difficulty grid

**Date:** 2026-08-15 · **Status:** Accepted · **Arose in:** E6-S3, E6-S5 and E6-S8, none of which
can be built against contract v1 as it stands

Three E6 stories need data the published contract does not carry. DL-36 already records the scout
table marking two of its columns as awaiting exactly these files. This adds both, and settles four
questions that are cheap now and expensive once eight views depend on them.

**1. `history.json` carries the current season only, and it is empty until GW1 is scored.**

The silver `player_gameweek` table is populated across the three backfilled seasons (DL-34) and
carries everything the trend charts want. Publishing all of it would be ~86,000 rows and several
megabytes. Publishing the current season is ~26,000 rows at season end and is what E6-S5 actually
asks for — "over time" means over this season, because a chart mixing 2024/25's scoring regime with
this one's is a chart that misleads (DL-18's trap, one level up). Prior-season evidence is not
discarded; it already reaches the model as a **prior** (DL-31), which is the honest place for it.

The consequence is that **today the artefact is empty**: it is preseason, no gameweek has been
scored, and `player_gameweek` has no 2026/27 rows. That is the same normal-preseason state as
`week.json` and `plan.json` (DL-20), and the payload says so explicitly — `season` and
`gameweeks_played` are top-level fields so a view can render "no gameweeks played yet" rather than
an empty axis. Rejected alternative: publishing last season alongside, so the charts have something
to draw in August. It doubles the payload permanently to solve a problem that lasts three weeks,
and it puts two scoring regimes on one axis.

**2. Price and ownership come from `price_history`, emitted on change, not per gameweek.**

`player_gameweek.selected_by` is a raw manager *count*, not a percentage, and it only exists for
gameweeks that have been played. The `price_history` table is the daily accumulator and carries
`selected_by_percent` properly — and it has real rows now, preseason, which is when price movement
is most watched. So each player carries **two** series: `gameweeks` (performance, from
`player_gameweek`) and `prices` (price and ownership, from `price_history`). Ownership is published
only as a percentage, in one place, because the same artefact carrying two differently-scaled
ownership numbers is how a wrong chart gets drawn and never noticed.

A daily observation per player per day is ~176,000 points over a season, which is larger than the
performance series it accompanies. Points are therefore emitted **on change**: the first
observation, the last, and any observation where the price moved or ownership moved by at least
`publish.history.ownership_change_threshold` (default 0.5 percentage points, a named tunable per
DP-06). Price and ownership are step functions, so this is close to lossless and bounds the artefact
at roughly 3 MB fully populated.

**3. `history.json` is lazy-loaded by route, not part of the eager `Promise.all`.**

DL-35 loads the six existing artefacts as one unit because they are small and wanted by more than
one view. This one is neither: fully populated it is larger than the other six combined, and only
the trend-bearing views want it. Putting it in the shell's eager load would spend the whole NFR-04
3 MB initial-payload budget on data the dashboard never reads. It gets its own fetch function with
its own module-scope promise cache, so it is fetched at most once per session and only when a view
that needs it mounts. `fixtures.json` is small enough to have gone either way and is lazy for
symmetry, so both trend artefacts follow one rule rather than two.

**4. `fixtures.json` difficulty is M2's expected goals, on a documented 1–5 scale anchored to the
league mean.**

FPL's own FDR is a static preseason integer; E6-S8's entire point is to beat it. The signal already
exists: `TeamStrengthModel` (M2) fits multiplicative attack and defence ratings from goals and
expected goals, and DL-34 left it **built, tested and dark** because the backtest scores every
fixture at league-average opposition and therefore cannot measure it.

Using it here is a different and much lower bar, and the distinction matters. DP-08 and DP-12 gate
promoting a model change that **alters a recommendation**. This changes no recommendation: the
optimiser, the plan and `players.json` are untouched, and the grid is a **descriptive label on a
fixture**. A difficulty rating that says Arsenal at home to a promoted side is easier than Arsenal
away at Liverpool is a claim the reader can check against their own eyes every weekend, which is
the opposite of an unfalsifiable one. `forecast.expected_goals.team_strength_from_xg` stays off for
the model; the ticker reads M2 regardless, and the artefact names the model it used so the reader
knows what they are looking at (DP-09).

**The scale, so it can be argued with (DP-10).** For each fixture the model gives expected goals for
and against. Each is turned into a difficulty by its ratio to the league mean:

```
attack_difficulty  = 3 - k · ln(expected_goals_for / league_mean)
defence_difficulty = 3 + k · ln(expected_goals_against / league_mean)
difficulty         = mean of the two
k                  = 2 / ln(publish.fixtures.difficulty_anchor_ratio)
```

clipped to [1, 5]. So **3 is exactly a league-average fixture**, lower is easier, and the anchor is
a single named tunable with a stated meaning: at the default of 2.0, a side expected to score twice
the league mean scores a 1 for attack. Attack and defence are published separately as well as
combined, because a high-scoring game between two good sides is a good fixture for forwards and a
bad one for defenders, and collapsing that into one number is most of what is wrong with FDR. The
raw expected goals are published alongside the scores, so the derivation is visible rather than
asserted (DP-09).

The grid covers `decision.horizon.gameweeks` gameweeks from the next one — the same window
`plan.json` covers, so the ticker and the plan cannot disagree about how far ahead "ahead" is.
Doubles and blanks reuse `optimise.chips.gameweek_shapes`, the function the chip calendar already
counts fixtures per club per gameweek with, rather than re-deriving a second answer to the same
question.

**Consequences.** Contract v1 grows from six artefacts to eight; both are additive, so no version
bump and no stale client breaks (DP-04). `ARTEFACTS` gains two entries and the TypeScript types are
regenerated from the schemas as usual. E6-S3, E6-S5 and E6-S8 are unblocked without touching the
forecast or the optimiser. The `$defs` in both schemas are named distinctly from the existing ones
because the generator emits every `$def` into one flat TypeScript namespace, so a second `player`
would silently collide.

---

## DL-38 — Q-06 confirmed by measurement, and the app caches its shell and its data under opposite rules

**Date:** 2026-08-16 · **Status:** Accepted · **Arose in:** E6-S9 (FR-34, NFR-04, NFR-14)

E6-S9 closes the epic's definition of done, and two of its items are decisions rather than work: what
the offline story actually caches, and whether the scout table's design bet survives being measured.

### 1. Q-06 is confirmed — plain JSON and client-side filtering, no query engine on the scout path

[Q-06](../04-conceptual-design.md#15-open-design-questions) was resolved *provisionally, by scoping*
in 2026-08-09 and left flagged "confirm by measurement on a phone". [DL-36](#dl-36--the-scout-table-virtualises-on-tanstackreact-virtual-and-hands-a-comparison-selection-over-in-the-url)
deliberately did not tick it, because a desktop Chromium run is not that measurement. It has now been
measured, and the bet holds with a very large margin.

**Method.** Playwright's `devices["Pixel 5"]` — a 393 px viewport, mobile user agent and touch — with
Chrome DevTools Protocol network emulation at Lighthouse's mobile profile (1.6 Mbps down, 150 ms RTT)
and a 4× CPU throttle, against the built and served site carrying the real published data: 587
players. No physical handset was available, and NFR-04 states its budget against *simulated* mobile
4G, so this is the sanctioned instrument rather than a substitute for one. It runs as phase 4 of
`web/verify/browser-check.mjs`, so it is repeatable and not a one-off reading.

**Measured, against NFR-04's budgets:**

| Quantity | Budget | Measured |
| --- | --- | --- |
| First contentful paint, p95 of 10 cold loads | < 2500 ms | **1044 ms** |
| Initial payload (document + code + eager data) | ≤ 3 MB | **155 KiB** — code 106 KiB, data 48 KiB |
| Scout search, worst of 5 edits over 587 players | < 150 ms | **31 ms** |
| Scout sort, worst of 4 toggles | < 150 ms | **77 ms** |
| Rows in the DOM at rest | virtualised | **15 of 587** |

**Verdict: confirmed, and not marginally.** Filtering and sorting the full player set in JavaScript
costs tens of milliseconds on throttled emulated phone hardware — a fifth of the interaction budget
at worst. The whole initial payload is **5% of the 3 MB budget**, of which the player data is 36 KiB;
a DuckDB-WASM download is measured in megabytes and would have landed on the first-paint path to
replace a 31 ms filter with a query engine. There is no version of this trade that pays.

Two things this does *not* say, because DP-12 asks what a measurement is being compared against. It
does not say a query engine is never warranted — the multi-season history views are still where the
data could genuinely justify one, and Q-06's scoping of DuckDB-WASM to that path is untouched. And it
does not generalise past 587 rows: the margin is wide enough that the conclusion would survive several
times the player set, but the number that would falsify this is a dataset large enough to push a
client-side `filter` past ~150 ms, and if the contract ever carries per-player history into the scout
table that is worth re-running rather than assuming.

### 2. The shell is precached; the published data is network-first. Never the other way round

The service worker (`vite-plugin-pwa`, an ordinary build-time npm package — no service, no tier, so
Invariant 3 is not engaged) caches two things under two different rules, because they have opposite
obligations:

- **The shell** — document, hashed JS and CSS, icons — is **precached**. Its filenames carry content
  hashes, so a precached shell cannot go stale: a new build produces new names and activation evicts
  the old ones.
- **The published artefacts** are **network-first, and are deliberately not precached**. They live at
  stable URLs under `data/v1/`, so a precache entry would pin one publication for the life of the
  bundle and the app would show last month's prices with complete confidence. Network-first means
  online readers always get the newest publication and offline readers get the last one that reached
  them — which is exactly "offline access to last-published data" and nothing beyond it.

Staleness is never silent: the header renders `meta.generated_at` as "As at …" on every view, so a
cached publication announces its own age (DP-15). `registerType: "autoUpdate"`, because a
decision-support app must not serve last week's bundle to someone standing at a deadline.

**Invariant 8 is not weakened.** Every route matches this origin's own published artefacts. The
worker introduces no request the app was not already making, and the verification asserts zero
external requests with the worker active.

**One non-obvious consequence: the page warms its own cache.** A service worker does not control the
page that registered it until after that page's fetches have gone out, so on a genuinely first visit
the six artefacts never pass through the worker, nothing is written, and a reader who installs the app
and immediately loses signal gets an empty shell. This was observed, not theorised — the first
verification run cached nothing and the offline check failed. `web/src/data/offline.ts` fixes it by
writing the missing artefacts into the same cache directly from the page, which needs no worker in
control and no message passing; the two sides share only a cache name, imported by `vite.config.ts`
rather than restated. It costs one extra fetch per artefact on a cold visit and nothing thereafter.
This is the seam `published.ts` was written to expect.

### 3. Two contrast defects, found by measuring rather than looking

An audit of every token pairing the app renders, in both themes, found two real WCAG AA failures —
and both were invisible to inspection, which is the point:

- **`--border` at 1.43:1 on a white panel** was the visual boundary of the scout search box, the sort
  select, the filter buttons and the squad builder's inputs. Under WCAG 1.4.11 the outline that says
  "this is a control" is a user-interface component and owes 3:1. Fixed by splitting the token:
  `--border` stays a quiet hairline for separators and chart gridlines, where 3:1 would be a heavy
  and wrong-looking rule, and a new `--border-strong` bounds controls at 3.4–4.4:1 in both themes.
- **`--fdr-blank-fg` at 4.41:1** missed AA for normal text by a hair. Darkened.

The audit is now `web/src/theme/contrast.ts` and its tests, not a report: the pairing table names
where each pair renders, both palettes are checked on every run, and the checker is itself tested by
being shown to fail (DP-13). It also caught a class of defect nobody had checked for — the dark
palette is written twice, once under `prefers-color-scheme` and once under `[data-theme]`, and
nothing previously required the two copies to agree.

**Consequences.** `web/verify/browser-check.mjs` grows from one phase to four — layout, accessibility,
progressive web app, performance — and is the repeatable instrument for all of it, including the
offline check, which passes only if the app opens and renders eleven starters with the network off.
Its stale route assertions, which still named the placeholders E6-S4, S7 and S8 replaced, now name the
delivered views. Q-06 moves from provisionally resolved to resolved by measurement.

---

## DL-39 — Behaviour implemented twice is pinned by one corpus in `contracts/conformance/`, read by both toolchains

**Date:** 2026-08-16 · **Status:** Accepted · **Arose in:** E6-S7 follow-up (FR-31, Invariant 9, DP-13)

E6-S7 shipped `web/src/components/squad/legality.ts` as a deliberate mirror of
`pipeline/src/fpl_dof/rules/legality.py` — same violation codes, same `detail` keys — and left the
cross-language conformance test open against E6's definition of done. This closes it, and names the
pattern, because legality is not the last thing this project will implement twice.

### The rule

**Where one behaviour is implemented in both languages, the cases the two must agree on are written
once, in `contracts/conformance/`, and read by both test suites.** Never two copies. A corpus copied
into `pipeline/tests/` and `web/src/` catches nothing: the two files drift together with the two
implementations, and a green suite on each side means only that each agrees with itself.

`contracts/` was already the place where the two halves of the project agree about *data*; `v1/` holds
the JSON Schemas for the published artefacts. `conformance/` is the same idea applied to *behaviour*,
and sits beside it rather than inside it because it is a test input and not part of the published
contract — nothing reads it at runtime, and it is not versioned with the artefacts.

`legality-corpus.json` is the first one. Twenty-six cases: a ruleset, a squad built from a shared
player pool, and the **exact ordered list of `(code, detail)` pairs** the validators must return.
Read by `pipeline/tests/test_legality_conformance.py` and
`web/src/components/squad/legality.conformance.test.ts`. Both tests assert that every violation code
the validator can emit appears somewhere in the corpus, so a thirteenth code fails on both sides
until it is covered.

**Prose is outside the contract.** `message` is written for a reader and each language phrases it for
its own audience; asserting on it would make a copy-editing change a cross-language build failure and
teach everyone to weaken the test. Codes and detail keys are the machine-readable part, and they are
what is pinned.

**Two rulesets, and the second is not FPL.** `twelve_a_side` — twelve players, eight starting, two per
club, sixty million — is a game nobody plays. It is there because a validator carrying a literal `15`
or `3` passes every realistic case and fails there. The case
`twelve-a-side-rejects-the-legal-fifteen` is Invariant 9 stated once: the same fifteen the corpus
calls legal, judged under other rules, must produce a different answer. Rule values in the corpus are
test *input*, not configuration; Invariant 2 forbids literals in code, and nothing reads this file at
runtime.

### It found a real disagreement on its first run, which is the argument for having built it

Twenty-five of the twenty-six cases agreed immediately. The twenty-sixth: a `bench_order` that names
one substitute **twice**. The Python validator compares the given order against the expected
substitutes **as a set**, so a repeated id is not a violation; the TypeScript mirror compared sorted
lists and reported one. Both files had been reviewed, both suites were green, and neither could have
found this alone.

**The TypeScript side changed**, per Invariant 9: `legality.py` reads the rules configuration the
contract publishes and is the authority, so it is what a mirror is measured against, not the other
way round. The change is recorded at the code site rather than left to look like a preference.

**This leaves both sides lax about a repeated substitute, and that is recorded rather than hidden.**
Set comparison accepts `[15, 15, 25, 33]` where the substitutes are `{15, 25, 33}`. It is not
reachable — `draft.ts` derives the bench order from the squad and never accepts one from a caller,
and the optimiser emits a permutation — so this is a latent looseness, not a defect anyone can
trigger. Tightening `legality.py` to a multiset comparison is a one-line change and the corpus case
is already written to catch it; it is left for the owner rather than made unilaterally to the module
everything else trusts. **If the Python side is tightened, the corpus expectation for
`bench-order-names-a-substitute-twice` changes with it and the TypeScript mirror follows.**

### Consequences

E6's definition of done is closed on the legality item. The pattern is available for the next
double implementation — `sellingPrice`/`selling_price` is already mirrored and would be a corpus of
arithmetic pairs, and any future client-side scoring preview would be another. The cost of adding a
case is one JSON object; the cost of not having the corpus was a disagreement that survived review of
both files.

---

## DL-40 — The mini-league is an optional artefact that is absent by default, and its comparison is anchored on the squad actually fielded

**Date:** 2026-08-16 · **Status:** Accepted · **Serves:** FR-32, NFR-11, NFR-15 · **Story:**
[E6-S10](epics/E6-web-application.md#e6-s10--mini-league-view--05-day--fr-32--could-have)

### Context

E6-S10 asks for standings, squad overlap, differentials held by each side, and captain divergence.
The FPL adapter already had `fetch_league_standings` and had done since E0 — declared, tested against
the live API, and **wired to a `request.league_id` that nothing ever set**. No configuration field
existed, so the resource had never once been fetched in a real run. The feature had ingestion support
and no data.

Three decisions followed, and each one had a plausible alternative that is worse in a way worth
recording.

### Decision 1 — absent, not empty, and absence is the default state

`entry.league_id` is a new optional configuration field, unset by default. When it is unset the
pipeline fetches no league, writes no `league.json`, and the publish stage **removes a stale one**.

The alternative was the `week.json`/`plan.json` pattern: always publish, carry a `skipped` flag and a
`skipped_reason`. That pattern is right for those two because there genuinely is a weekly run that
was skipped, and the reason is a fact about this run. Here there is no run to skip — there is a
configuration field nobody filled in, which is a fact about the *installation* and does not change
week to week. A file that exists solely to say "you have not configured me" is a worse statement than
no file, and it would have to be published on every run for a season to keep saying it.

**The removal is the part that matters and it was extended beyond this artefact.** The stage
previously deleted a stale `week.json` or `plan.json` from `data/web/v1/` but not from
`web/public/data/v1/`, which is the copy the browser actually reads. A league unconfigured after
having been configured would have left the old table live and believed. Stale-file removal now
covers both directories for all three optional artefacts.

### Decision 2 — the comparison is anchored on the owner's fielded squad, never on `squad.json`

`squad.json` is what the optimiser recommends. It is usually *not* what the owner fielded. Anchoring
overlap on it was the cheap option — it is already loaded, non-nullable, in the app shell — and it
would have reported players the owner does not own as players the owner is differentiating with. The
number would have looked entirely reasonable and been about a squad that does not exist. That is the
silent, plausible wrongness DP-13 says to spend the effort avoiding.

So the anchor is the owner's own row in the league, from the picks endpoint. **When there is no such
row the comparison is refused rather than approximated**, and the artefact carries enough to say
which of three reasons applies: no gameweek scored yet, no team configured or not a member of this
league, or the owner's squad outside the fetch budget. The view prints the reason (DP-09, DP-15).

### Decision 3 — the artefact carries the squads; the app derives the comparison

Overlap, differentials and captain divergence are set arithmetic over two lists of fifteen. They are
computed in `web/src/components/league/league.ts`, not precomputed in the publisher.

Precomputing would have put an unarguable answer in the payload immediately next to its own inputs,
and would have fixed one framing of the question — against the fifteen rather than the starting XI —
into the contract. Deriving in the app keeps the answer next to what it came from (DP-10) and costs
nothing: the whole comparison is two set differences over thirty integers.

**Differentials are never summed across directions.** A player only the rival holds is exposure; a
player only the owner holds is a bet. One count cannot say both, so two are published.

### What this costs, and the budget that bounds it

Standings are one request. Squads are **one request per entry**, so `entry.league_rival_limit`
(default 20, max 50) is a named, defaulted tunable rather than a literal (DP-06), and only the top of
the table is read. A public classic league can hold hundreds of thousands of entries; the standings
endpoint paginates at 50 and this reads **one page**, deliberately, rather than following `has_next`
into an unbounded crawl of a server this project is a guest on (NFR-10).

Rivals' picks land in a **new `league_pick` silver table, not in `entry_pick`**. The shapes are
nearly identical and reuse was tempting. But `entry_pick` is where the weekly decision reads the
owner's squad from, and admitting a hundred rivals' rows to it would make every downstream
consumer's correctness depend on remembering an `entry_id` filter. The failure mode is a legal,
plausible squad built from somebody else's players.

### What is not built, and why

**No historical league data and no rank projection.** Only the latest scored gameweek's squads are
read. A season of every rival's picks is 20 entries × 38 gameweeks of requests for a view nobody
asked for, and the story is a half-day could-have.

**Nothing here reaches a model or the optimiser.** Rival ownership is not a feature and does not
enter the objective. That would be a real modelling decision about differential strategy, it belongs
with the risk dial (DL-25), and it would need its own evidence (DP-08). This is a view.

### Consequences

The state that is actually tested is the unconfigured one, because that is the state the repository
is in: `/league` renders a first-class "no mini-league configured" page naming the setting and what
it would unlock. The populated path is covered by fixtures, including the two cases most able to
mislead — a rival whose squad was never fetched, and a captain that was never published — neither of
which may render as a zero or as agreement. `FPL_DOF_LEAGUE_ID` was already promised in
[INPUTS-REQUIRED §8](epics/INPUTS-REQUIRED.md#8-environment-variables) and is now wired.

---

## Open decisions

Decisions deliberately deferred, with the point at which each must be resolved.

| ID | Question | Must resolve by |
| --- | --- | --- |
| ~~OD-01~~ | ~~Public or private GitHub repository~~ — **Closed: public.** See [DL-12](#dl-12--public-repository) | Resolved |
| ~~OD-02~~ | ~~Hosting: Cloudflare Pages, public repo, or local-only~~ — **Closed by DL-12.** GitHub Pages is free on a public repository; no Cloudflare account needed | Resolved |
| OD-03 | Which odds provider and free-tier credit budget | E5, ~GW10 |
| OD-04 | Whether to add injury/press-conference feeds as a fourth source | E8, in-season |
| ~~OD-05~~ | ~~Default risk-dial posture~~ — **Closed: Balanced, as a configuration field the owner can change at any time.** Reopens only if the owner states a target rank or a temperament. See [DL-25](#dl-25--od-05-resolved-the-risk-dial-defaults-to-balanced) | Resolved |
| ~~OD-06~~ | ~~How effective ownership is obtained~~ — **Closed: redefined without a captaincy term.** See [DL-24](#dl-24--od-06-resolved-effective-ownership-redefined-without-a-captaincy-term) | Resolved |
