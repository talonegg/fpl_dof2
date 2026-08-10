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

## Open decisions

Decisions deliberately deferred, with the point at which each must be resolved.

| ID | Question | Must resolve by |
| --- | --- | --- |
| ~~OD-01~~ | ~~Public or private GitHub repository~~ — **Closed: public.** See [DL-12](#dl-12--public-repository) | Resolved |
| ~~OD-02~~ | ~~Hosting: Cloudflare Pages, public repo, or local-only~~ — **Closed by DL-12.** GitHub Pages is free on a public repository; no Cloudflare account needed | Resolved |
| OD-03 | Which odds provider and free-tier credit budget | E5, ~GW10 |
| OD-04 | Whether to add injury/press-conference feeds as a fourth source | E8, in-season |
| OD-05 | **Default risk-dial posture.** Narrowed by [DL-13](#dl-13--charter-amendments-following-the-2026-08-09-architecture-and-plan-audit): the rank *ambition* is settled in charter §5 (top-100k target, top-10k stretch). What remains open is how aggressively the dial should default, which is a temperament question, not a target question | E4, before the risk dial ships |
| OD-06 | **How effective ownership is obtained.** `selected_by_percent` is public; captaincy share is not exposed by any FPL endpoint, so `EO = selected_by% + captained_by%` is not directly computable. Three candidate routes are set out in [04-conceptual-design.md §7](04-conceptual-design.md#7-risk-and-ownership-model) | E4, with the risk dial |
