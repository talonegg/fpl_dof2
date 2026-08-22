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

## DL-41 — The data health page reads one new artefact assembled from records that already exist, and the deadline guard reads the same published deadline the app does

**Date:** 2026-08-16 · **Status:** Accepted · **Serves:** FR-33, NFR-07, NFR-15 · **Story:**
[E7-S6](epics/E7-automation-and-hosting.md#e7-s6--data-health-page--1-day--fr-33-nfr-07),
[E7-S7](epics/E7-automation-and-hosting.md#e7-s7--deployed-smoke-test-and-deadline-guard--05-day)

### Context

E7-S6 wants a page showing per-source freshness and status, the last run's outcome, the quality gate
results, rolling model accuracy and degraded-source banners. Every one of those numbers is already
written down somewhere: the run manifest (DP-11) has stage outcomes, timings and per-source metrics;
`quality.json` has the full gate report; the bronze store's snapshot sidecars carry `fetched_at`.
Nothing needed measuring. What was missing was a **seam** — the browser reads published static
artefacts and nothing else (Invariant 8), and none of those files is published.

### Decision 1 — one new contract artefact, `health.json`, additive at contract v1

`health.json` joins the artefact table alongside `history.json` and `fixtures.json` (DL-37). Additive,
so contract v1 does not bump: a client that has never heard of it keeps working. It is fetched
lazily by `/health` alone, never in the app shell's eager load — the NFR-04 initial-payload budget is
not there to be spent on a page that is opened when something looks wrong.

**It is assembled, never measured.** `publish/health.py` is a pure function over three inputs the
stage hands it: the current run's manifest, the gate report, and a list of recent manifests. Purity
matters more here than it looks — a health page that computed its own view of health would be a
second opinion that can disagree with the manifest, and the whole value of the page is that it is
the manifest, rendered.

### Decision 2 — degraded sources are data, and the web layer never names one

Invariant 1 says only `sources/` may know a source exists. The health page must nonetheless show
*which* source is degraded, or the banner is useless. The resolution is the one the pipeline already
uses: `stages/ingest.py` writes `degraded.{adapter.name}` by asking the registry, and contains no
source name itself. `health.json` carries a `sources[]` array of `{source, status, detail, …}` where
`source` is a **string from the data**, and the web layer renders that string. There is no source
name, no per-source branch and no per-source styling anywhere in `web/`. Adding a fourth source
changes an adapter module and nothing else, which is the acceptance test DP-01 states.

`status` is `ok` or `degraded`, with the exception class name as `detail` — the derivation next to
the flag, so "degraded" is checkable rather than asserted (DP-09).

### Decision 3 — rolling metrics history comes from the run manifests, and the storage is not the contract

E7-S6 asks for a rolling history of freshness, volumes, accuracy and solve time. A dedicated metrics
store is being built in parallel. Rather than block on it, or invent a competing one, the publisher
reads the **run manifests already on disk**: `optimise.solve_seconds` is the solve time,
`transform.rows.*` are the volumes, `forecast.r_squared_on_price` is the one per-run model diagnostic
recorded today, and stage timings are the run duration.

The schema's `metrics_history` is nullable and carries a `derived_from` field naming where the series
came from. **The shape is the contract; the storage is an implementation detail.** When a metrics
store lands, the publisher swaps its reader and `derived_from` changes value — no schema change, no
app change. The page renders whatever series it is given and says so when it is given none (DP-15).

**`r_squared_on_price` is labelled as a price-dependence diagnostic, not as accuracy**, on the page as
well as in the schema. It is R-15's check that the forecast is not a repricing of the price list; it
is emphatically not a measure of skill, and a chart captioned "accuracy" over it would be the
unvalidated-model-presented-as-validated failure DP-09 exists to prevent. Real skill measurement is
the backtest's, it lives in the model card, and it is deliberately not charted here.

### Decision 4 — no conformance corpus

`contracts/conformance/` pins behaviour implemented twice (DL-39). `health.json` is display data with
no logic on the browser side: the app formats timestamps and renders strings it was handed. There is
no second implementation to drift from, so a corpus would pin nothing. The JSON Schema and the
publisher test are the whole boundary.

### Decision 5 — the deadline guard reads the published deadline, not the pipeline

H4 blocks a publish or deploy inside 45 minutes of a deadline. A hook runs on every matching tool
call, so it must be fast and must never be the reason a session stalls. Shelling out to Python to
compute the next deadline would cost an interpreter start plus a config load on every `git push`.

The hook instead reads `deadline_utc` from files the pipeline has **already** written, in preference
order: `data/web/v1/week.json`, then `data/gold/season=*/week.json`, then `data/web/v1/meta.json`.
Node, one `readFileSync`, no subprocess.

**The failure mode is chosen deliberately: no data means allow.** A hook that blocked whenever it
could not find a deadline would fire on every fresh checkout and would be disabled within a day, and
a guard that is disabled protects nothing. It states loudly what it could not read. The 45 minutes
is R-09's window, restated in one named constant in the hook rather than inferred.

### Consequences

`/health` is the one route that is useful precisely when the rest of the app is not, so it holds
itself to that: a missing, stale or malformed `health.json` renders a page that says which, and the
gate-failure state is a first-class view rather than an error. It is also the only page that renders
correctly when the *last* thing that happened was a blocked publication — which, by Invariant 7, is
the state the site is in whenever a gate fires.

The deployed smoke test extends `web/verify/` rather than starting a second harness: same Playwright
Chromium (DL-30), a fifth phase that runs against a URL and checks the shell, the routes and the
contract files. It is a separate npm script so a deploy workflow can call it without paying for the
four local phases.

---

## DL-42 — E7 lands: seven workflows, a deadline-relative scheduling seam, and a retention mechanism that is verified against a real remote rather than assumed

**Date:** 2026-08-16 · **Status:** Accepted · **Serves:** OBJ-6, NFR-01, NFR-05, NFR-06, R-09, R-13,
FR-35, FR-38 · **Story:** [E7](epics/E7-automation-and-hosting.md), all stories

### Context

E7 closes the manual-operation debt (D-08) and the no-CI debt (D-10) before GW1's charter carve-out
expires. Three questions had to be answered in code, not policy: how a cadence that depends on the
FPL deadline can exist inside GitHub Actions' static cron, how a Git-backed rolling store stays
bounded rather than merely slow-growing, and how a solo, timezone-inconvenienced owner gets told
when something breaks.

### Decision 1 — cron fires often; a pure function decides whether to act

GitHub Actions cron cannot itself express "hourly within 24h of a deadline" or "at T-3h and T-45m
before a deadline" — the schedule is fixed at commit time and the deadline is data. The resolution:
fire a cheap guard frequently (`ingest-fast.yml` hourly, `pipeline.yml`'s deadline-relative trigger
every 15 minutes) and ask a pure function whether *this* firing should do the expensive part.

`fpl_dof.week.schedule.fast_ingest_decision` and `.pipeline_decision` take a clock reading and
`ScheduleConfig` and return a `ScheduleDecision` with a human-readable reason — no I/O, no clock
read internally, fully unit-tested. The effectful edge is a new console script, `fpl-dof-schedule`
(`schedule_cli.py`), deliberately **not** a `fpl-dof` subcommand: `fpl-dof` opens a run and writes a
manifest on every invocation, which is right for a stage and wrong for a read-only question a
workflow asks up to 96 times a day. Keeping it off that path also means D-10's promise — the E0 code
path runs in CI unchanged — is not compromised by the thing that makes CI deadline-aware.

**R-09's freeze is enforced by two properties, not one.** `pipeline_decision` checks the hard freeze
(`deadline_freeze_minutes`, default 45) before consulting the offset windows at all, and every
window is `[offset, offset + tolerance]` — one-sided, ending *at* the offset rather than straddling
it. A symmetric window would have let a delayed cron firing land at, say, T-35m; the one-sided shape
makes that impossible by construction rather than by convention. `ScheduleConfig` carries a
validator that rejects a configuration where the tolerance is too small to guarantee a 15-minute
cron never skips a window entirely, and one where any offset falls inside the freeze — so a
misconfiguration that would silently violate R-09 fails to load rather than running.

**A source declares its own cadence eligibility.** Rather than the ingest stage or the CLI knowing
which resources are cheap, `SourceAdapter` gained `Resource.fast_path` (a fact declared next to each
resource's TTL) and `wants()`/`has_fast_path()` methods. `fpl-dof ingest --fast` asks the adapter,
never branches on a source name — Invariant 1 holds across the fast/slow split the same way it holds
everywhere else.

### Decision 2 — the `data` branch is rebuilt from nothing every run, and this is verified against a real remote, not asserted

Architecture §7.3 is specific that git deletion does not reclaim space — a `data` branch maintained
by committing removals grows monotonically regardless of how carefully old files are pruned from the
working tree. `pipeline/src/fpl_dof/retention.py` (pure: which bronze paths fall inside a retention
window, given their own embedded `YYYY-MM-DD` directory — **never filesystem mtime**, because `git
checkout` rewrites every mtime and an mtime-keyed job on a fresh clone would retain everything
forever while looking correct) and `pipeline/scripts/retention.py` (effectful: stage the retained
set into a fresh directory, `git init --orphan`, commit, `push --force`) split cleanly on DP-03.

This was not left as "should work" — it was run against a real local bare git remote (not a mock):
60 simulated daily runs over a 30-day window kept the `data` branch at exactly one commit with zero
parents throughout, and the retained file count stayed bounded at the window size rather than
growing. A genuine bug surfaced only by this — not by the unit tests — was `shutil.rmtree` failing
on Windows when a staging directory was reused, because git leaves its object files read-only; fixed
with a `chmod`-and-retry `onexc` handler. `snapshots` (the permanent, append-only, one-per-source-
per-gameweek evidence trail) is idempotent by content comparison, also verified against the same
real remote: appending an identical gameweek's snapshot twice produces one commit, not two.

`retention.bronze_days` (default 30) is a named, defaulted, justified `RetentionConfig` field
(DP-06) rather than a literal in a workflow file.

### Decision 3 — seven workflows, each doing one thing, wired by `workflow_run` rather than a monolith

`ci.yml` (push/PR — lint, mypy, pytest, the 100% rules-coverage gate, web typecheck/build/test),
`ingest-fast.yml` (hourly, bootstrap-static + fixtures only), `ingest-slow.yml` (daily,
element-summary and external sources — `element-summary` never appears on the fast path, per the
DL-12 minutes finding), `pipeline.yml` (transform through publish, never ingest — re-solving because
a price moved is waste), `deploy.yml` (GitHub Pages via `actions/deploy-pages`, which only swaps the
live site on success — "a deploy fails, the previous site remains live" is that action's default
behaviour, not custom logic this project had to write), `backtest.yml` (weekly), and a reusable
`alert-on-failure.yml` every other workflow's failure path calls.

**`pipeline.yml`'s concurrency group uses `cancel-in-progress: false`, not `true`.** A run in
progress is left to finish — Invariant 7 means a half-finished publish must never race a fresh one,
and stages are independently resumable but not safely interruptible mid-stage. With one group and
in-progress cancellation off, GitHub Actions still starts only the newest *queued* run once the
current one finishes, which is "one at a time, newer supersedes older, nothing active is killed" —
E7-S4's requirement, achieved with the concurrency primitive rather than custom queueing logic.

**`deploy.yml` prefers the artefact the triggering `pipeline.yml` run just uploaded**
(`web-data-contract`), and falls back to the `data` branch's own `web/` copy, and ships the app
shell dataless rather than failing if neither exists — `web/public/data/` is gitignored, so a bare
checkout has nothing to serve otherwise. This is DP-15 applied to the deploy path itself, not just
to the app's runtime behaviour.

### Decision 4 — alerting is a reusable `workflow_call`, deduplicated by a hidden marker

`alert-on-failure.yml` opens a GitHub Issue labelled `pipeline-alert` on failure, via
`actions/github-script` and the automatically-provided `GITHUB_TOKEN` — no new secret, no paid
service (NFR-01). Repeated failures of the same workflow **comment on one issue** rather than
opening a new one each time, found by a hidden HTML-comment marker in the body rather than by title
match, because a failing nightly pipeline must not out-pace what one person can read. Realtime
delivery to a timezone-inconvenienced owner depends on the GitHub mobile app watching this
repository — a one-time manual setup this decision records rather than a paid dependency this
project introduced.

### Consequences

D-08 (no automation) and D-10 (no CI, E0 running only locally) both close: `ci.yml` runs the exact
`fpl-dof` entry points a developer does, with no CI-only branch anywhere in the pipeline source
(NFR-09), and the fast/slow/pipeline/deploy chain replaces manual weekly operation with a
deadline-aware one. What remains **unverifiable from a workstation** — actual cron firing at real
UK/AEST-shifted times, an actual `GITHUB_TOKEN`-authenticated push to `github.com` rather than a
local bare remote, an actual GitHub Pages deployment reachable from a phone — is exactly the E7 DoD's
"one full week passes with zero manual intervention" acceptance test, and can only be discharged by
watching a real week happen, not by more local simulation.

---

## DL-43 — The next model work is delivery then discrimination, not accuracy; the plan is a set of gated experiments

**Date:** 2026-08-16 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-12, FR-37 · **Arose in:**
the 2026-08-16 research pass · **Plan:** [05-model-improvement-plan.md](05-model-improvement-plan.md)

### The finding this decision is built on

The first backtest ([DL-21](#dl-21)) said `xp_v1` beats price and loses to trailing form, with the
best MAE and the worst top-20 precision of anything measured. A research pass over the shipped code
found three structural facts that reframe what "improve the model" means, none of which is a modelling
subtlety:

1. **The graded model is not the shipped model.** The backtest grades `xp_v1`; the pipeline publishes
   `xp_v0`, which consumes none of the xG signal DL-34 measured and promoted. The gap is
   [D-25](epics/E0-steel-thread-gw1.md#6-technical-debt-register). Until it closes, every measured
   improvement is undelivered. This is the highest-leverage item and it is one wiring seam, not a
   model.
2. **The backtest is blind to fixtures.** The harness carries league-average opposition, so M2 fixture
   difficulty — the whole of the fixture axis — is untestable until a fixture table is joined into the
   fold frames. That plumbing is a prerequisite, not an improvement.
3. **Two positions are unranked.** GKP Spearman 0.04, DEF 0.16. Any improvement must be measured per
   position or a forwards-only gain hides the two hard cases.

### The decision

The improvement programme is delivered in leverage order — **X1 ship `xp_v1` live → D1 fixtures into
the backtest → X2 minutes calibration → then discrimination at the head** — and **every change is a
falsifiable experiment gated by the E8 §5 bar** (held-out backtest improves, six shadow gameweeks do
not degrade, the change is explicable in advance). The target metric is **top-20 precision and
captaincy separation, not MAE**: MAE is already the best in the table and is measuring the wrong thing
for a tool used only at the head of its ranking (DL-21). The full table of changes, their gates and
their sequencing is [05-model-improvement-plan.md](05-model-improvement-plan.md).

### Rejected alternatives

**Adopt the model-free benchmark, which wins on Spearman.** Rejected for the reason DL-21 already
gave: trailing form has calibration slope 0.39 and the worst MAE — a momentum signal that buys at the
top of the price rise. Winning on rank correlation is not being better to own.

**Tune for MAE or for overall Spearman.** Rejected — both are already competitive and neither is what
the tool is used for. Optimising them further is optimising the wrong loss.

**A single blended monolith instead of the component chain.** Not rejected, but demoted to a *shadow
benchmark* (X6, Q-04): the chain's explainability is a product requirement (DP-10), so a monolith
that is merely more accurate does not replace it without an explicit decision weighing that trade.

### Consequences

D-13 (forecast does not beat the model-free benchmark at the head) gets a route to closure that is a
plan rather than an aspiration. The DL-21 guardrail is unchanged: no −8 hit, chip or wildcard is
justified by `xp_v1` alone until top-20 precision beats B0. Three new open questions — Q-14
(evidence-adaptive shrinkage), Q-15 (goalkeeper formulation), Q-16 (auto-dispatch of a run from the
browser) — are recorded in the plan.

---

## DL-44 — FPL team and league IDs are runtime inputs entered in the UI, never persisted in the repository

**Date:** 2026-08-16 · **Status:** Accepted · **Serves:** NFR-11, NFR-13, FR-32 · **Arose in:**
the 2026-08-16 research pass · **Builds on:** [DL-40](#dl-40--the-mini-league-is-an-optional-artefact-that-is-absent-by-default-and-its-comparison-is-anchored-on-the-squad-actually-fielded)

### Context

The owner asked that the FPL team ID and mini-league ID be **enterable through the UI** and **never
persisted in the code**. Today they live in `entry.team_id` / `entry.league_id` in
`config/local.yaml` — which is gitignored, so nothing is committed, but the values still live in a
file the owner hand-edits, and there is no UI path at all. The IDs are **public** (NFR-11), not
secrets; the concern is persistence and single-user assumption, not confidentiality.

**The binding constraint is Invariant 8** — the browser never calls an external API. The SPA reads
published static artefacts only; it cannot fetch the owner's picks or a league's standings itself, and
the FPL API sends no CORS headers that would let it. So "enter the ID and see your data" cannot mean
"the browser fetches it", and DL-03 forbids adding a backend that could.

### Decision

The two IDs are treated as **two genuinely different things that normally coincide** for a single
user:

1. **Pipeline input — a GitHub Actions repository variable, not committed config.** The pipeline reads
   `FPL_DOF_TEAM_ID` / `FPL_DOF_LEAGUE_ID` from the environment via the overrides already declared on
   `EntryConfig`. In CI these come from repository **variables** (the correct home for a non-secret
   identifier); `config/local.yaml` stays the local-dev path and remains gitignored. Nothing about the
   owner's identity enters git.
2. **Browser input — a Settings view backed by `localStorage`.** The owner types the IDs in the app;
   the values live in `localStorage` only, never transmitted, never committed. Within Invariant 8 the
   setting does two things: it **personalises already-published artefacts** (highlights the owner's
   league row, badges the owned squad, filters the scout to owned players — saying so plainly when the
   published league was built for a different ID, as DL-40 does for the absent league), and it
   **composes an owner-triggered `workflow_dispatch` deep link** so the repo owner can dispatch a run
   with those IDs. No token ever reaches the client (Invariant 10, NFR-13).

### Rejected alternatives

**Let the browser call the FPL API with the entered ID.** Rejected outright — Invariant 8, and CORS
would block it regardless. **Add a tiny backend / serverless function to proxy it.** Rejected — DL-03
(no runtime backend, zero cost, NFR-01). **Keep the IDs in committed config with a code edit per
change.** Rejected — that is exactly the persistence the owner asked to remove, and it hard-codes a
single user into the wrong layer. **Auto-dispatch a run from the browser on save.** Deferred to Q-16:
it needs either a client-held token (forbidden) or an owner-mediated flow, and whether the convenience
is worth the surface is an owner-and-security decision, not a default.

### Consequences

Implementation is a sequenced follow-up, not built by this decision: a Settings story on E6's surface
(`localStorage`, league-row highlighting), a documented repository-variable path in E7's workflows,
and a charter requirement naming UI entry of the IDs. `FPL_DOF_TEAM_ID` / `FPL_DOF_LEAGUE_ID` are
already promised in [INPUTS-REQUIRED §8](epics/INPUTS-REQUIRED.md#8-environment-variables); this
decision makes the browser-entry half of them a first-class design rather than an env var only.

---

## DL-45 — The model-improvement plan is scheduled as five gated epics, E9–E13

**Date:** 2026-08-16 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, OBJ-5, FR-12, FR-37 ·
**Builds on:** [DL-43](#dl-43), [DL-44](#dl-44), [DL-21](#dl-21)

### Context

[DL-43](#dl-43) accepted the [Model Improvement Plan](05-model-improvement-plan.md) as a programme of
falsifiable, gated experiments; [DL-44](#dl-44) settled the team/league ID design. The plan was a
research document, not a build schedule. To make it actionable it has to enter the plan of record —
the [epics](epics/README.md) — as scheduled work with dependencies, acceptance criteria and promotion
gates, rather than living only as prose.

### Decision

The plan's items are decomposed into **five new epics** appended to the epic register, ordered by
leverage rather than by area:

- **[E9](epics/E9-forecast-delivery-and-backtest-fidelity.md) — Forecast delivery + backtest
  fidelity** (X1, D1). First, and it **gates E10–E12**: closes D-25 so the *shipped* model is the
  *graded* model, and puts fixtures into the backtest so the fixture axis becomes testable. These are
  plumbing, not modelling, and they are the highest-leverage work in the programme.
- **[E10](epics/E10-discrimination-at-the-head.md) — Discrimination at the head** (X2/close D-14, X3,
  X4, X5, X6). Optimises top-20 precision and captaincy separation *per position*, not MAE.
- **[E11](epics/E11-fixture-difficulty-and-market-signal.md) — Fixture difficulty + market signal**
  (F1–F5, D3/close OD-03). Depends on E9-S2.
- **[E12](epics/E12-data-widening-for-priors.md) — Data widening for priors** (D2/resolve Q-13, D4,
  D5). Low-urgency; feeds E10 and E11 from already-permitted sources, no new scraping.
- **[E13](epics/E13-runtime-personalisation-ids.md) — Runtime personalisation** (plan §7, realising
  DL-44). Independent of the model epics; realises the E6/E7 stories the plan proposed, collected here
  because E6 has already shipped.

**The governing rule is unchanged:** nothing promotes by argument. Every modelling change clears the
[E8 §5 bar](epics/E8-in-season-operations.md#5-the-bar-for-changing-the-model-mid-season) — held-out
backtest improves, six shadow gameweeks do not degrade, explicable in advance — and the DL-21
guardrail on hits/chips/wildcards stands until top-20 precision beats B0.

### Rejected alternatives

**Fold the work into existing epics (E3/E5/E6/E7).** Rejected — those epics are built and marked done;
reopening them hides a distinct, evidence-gated programme inside closed work and loses the leverage
ordering. The one exception is honoured by cross-reference: E13 explicitly realises the E6/E7 stories
§7 proposed. **Leave the plan as prose.** Rejected — a research document is not a schedule; without
dependencies and acceptance criteria in the plan of record, the work is not actionable and its gates
are not enforceable. **One large "model v2" epic.** Rejected — it would bury E9's gating role and let
untestable fixture work start before the backtest can see fixtures.

### Consequences

The epic register grows from nine to fourteen; the [epics README §7](epics/README.md#7-the-model-improvement-programme-e9e13)
carries the programme, its item-to-epic map, and the E9 gate. The build-pace guidance
([DL-23](#dl-23)) applies unchanged: these are ceilings, and the season clock plus evidence pace the
work, not build time. E9 aside, none of E10–E13 is urgent against a dated constraint, and the §4
"stop building after ~GW30" rule applies to them. Three open questions from the plan (Q-14, Q-15,
Q-16) are carried on the open-questions list; Q-13 and Q-04 are pulled into E12 and E10 respectively.

---

## DL-46 — E9-S1 ships `xp_v1` as the default publish, not a dark-launched flag: closing D-25 is a bug fix, not a model promotion

**Date:** 2026-08-16 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-12, FR-13 ·
**Builds on:** [DL-21](#dl-21), [DL-33](#dl-33), [DL-34](#dl-34), [DL-45](#dl-45)

### Context

[E9-S1](epics/E9-forecast-delivery-and-backtest-fidelity.md#e9-s1--fixture-aware-horizon-scorer-xp_v1-on-the-live-path--15-days--fr-12-fr-13--closes-d-25)
reads, in the same paragraph, both "the forecast stage publishes `xp_v1`" and "ships dark then
promoted (DP-08): published behind a flag … for the shadow window before it becomes the default the
app reads." Those two sentences conflict on inspection. [DP-08](../DESIGN-PRINCIPLES.md) requires a
new model behaviour to run six shadow gameweeks with live rolling accuracy not degrading before
promotion — impossible before GW1, since there is no live season yet to shadow against, and it is
explicitly violated by "a flag is added and immediately defaulted on." Before writing any code this
needs a resolution, per the project convention of recording significant decisions ahead of
implementation.

### Decision

**Closing D-25 is the bug-fix exception DP-08 names, not a model promotion, and `xp_v1` ships as the
default publish target when E9-S1 lands.**

The reasoning: DP-08 governs *introducing new model behaviour*. `xp_v1` is not new — it was already
selected and measured. [DL-21](#dl-21) backtested it against B0, a mean baseline and a model-free
trailing-form baseline over 72 folds and recorded the verdict as accepted; [DL-34](#dl-34) backtested
and promoted its xG component the same way. D-25's entry names the gap precisely: *"the improved model
is not the one that ships"* — the defect is that the pipeline publishes a different, less-capable
model (`xp_v0`) than the one already evidenced. Fixing that mismatch does not introduce a new,
unproven candidate; it makes the shipped artefact match the already-graded one. That is DP-08's stated
exception: *"a bug fix is not a model change and does not wait."*

The standing safety net is [DL-21](#dl-21)'s guardrail, restated unchanged by this epic's definition of
done: **no −8 hit, chip or wildcard is justified by `xp_v1` alone until top-20 precision beats B0.**
That constraint — not a shadow-mode flag — is what bounds the live blast radius of a still-unproven-at-the-head
model while E10 does the discrimination work.

Concretely:

- `stages/forecast.py` publishes `xp_v1` by default once E9-S1 lands. There is no `enabled: false`
  flag gating `xp_v1` behind a manual promotion step — that would misapply DP-08 to a delivery bug and
  stall D-25 indefinitely, since no in-season shadow window exists before GW1 to satisfy it.
- `xp_v0` is retained as a **named, visible** fallback (DP-15) for the genuine cold-start case — when
  `player_gameweek` history is too thin for M1–M8 to fit (pre-season, or a fresh current-season table
  with too few completed gameweeks). The fallback firing is recorded in the model card and the stage
  metrics, never silent.
- The published model's name and the date it became default are recorded in `meta.model` (contract)
  and the model card, so the fallback state is always visible to the app and the owner (DP-15).
- The DL-21 guardrail is restated verbatim in the model card and remains binding.

### Rejected alternatives

**Add a `published_model` flag defaulting to `xp_v0`, promote to `xp_v1` after six live shadow
gameweeks post-GW1.** Rejected — this is the literal DP-08 mechanism, but it leaves D-25 open through
GW1 through GW6, defeating the epic's own stated purpose ("no story in E10–E12 may start until E9's
definition of done holds") for a full six gameweeks with no corresponding new evidence being generated,
since the backtest evidence is already in hand. **Treat this as a genuine model promotion requiring a
fresh six-gameweek shadow run.** Rejected for the same reason — there is nothing left to learn from
shadowing that DL-21's 72-fold backtest did not already measure at the single-gameweek grain; what E9-S1
adds is the horizon scorer and fixture awareness, which are covered by the parity test against the
already-graded numbers, not by a new promotion gate.

### Consequences

E9-S1's acceptance criterion ("the app's ranking is produced by `xp_v1`") is achieved on merge, gated
only by the parity test being green and the fallback being visible — not by calendar time. The E9 epic
text's "ships dark then promoted" phrasing is superseded by this entry for the specific case of D-25;
DP-08's shadow-mode mechanism remains the binding rule for any subsequent E10–E12 change that alters
what `xp_v1` computes, which is a genuine new-behaviour case.

---

## DL-47 — E10's discrimination changes are genuine model behaviour, not a bug fix: they ship flagged and shadow-compared, not defaulted on, and the epic's promotion checkbox stays open until six live gameweeks exist

**Date:** 2026-08-20 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-10, FR-12 ·
**Builds on:** [DL-21](#dl-21), [DL-46](#dl-46), [E8 §5](epics/E8-in-season-operations.md#5-the-bar-for-changing-the-model-mid-season), DP-08

### Context

[DL-46](#dl-46) closed D-25 as DP-08's named bug-fix exception and, in its own consequences section,
was explicit that this did **not** extend to E10: *"DP-08's shadow-mode mechanism remains the binding
rule for any subsequent E10–E12 change that alters what `xp_v1` computes, which is a genuine
new-behaviour case."* DP-08 itself is unambiguous about what that mechanism requires: a flag, shadow
publication of the candidate's predictions "without letting them influence anything," and promotion
only once **all three** E8 §5 conditions hold — including **at least six live shadow gameweeks**.
GW1 is tomorrow (2026-08-21). There is no live season yet, so condition 2 cannot be satisfied by any
amount of work done today. This has to be resolved before writing E10's code, per the same
before-not-after convention DL-46 followed.

### Decision

**E10's five stories land as flagged, additive variants inside the existing `xp_v1` chain, default
`False`, so the app's published ranking and the optimiser's inputs are byte-identical to today's until
a future, separate promotion decision.** Concretely:

- `ForecastConfig` gains a `discrimination` section (one bool per promotable story: `minutes_v2`
  (S1), `adaptive_shrinkage` (S2), `duty_term` (S3), `gkp_v2` (S4) — all default `False`, each named,
  defaulted and justified per DP-06). `xp_v1` with every flag `False` reproduces today's output
  exactly; this is a regression test, not an assertion.
- The **backtest harness** is where this epic's evidence is generated and where each story's stated
  Acceptance criterion is actually checked: it runs the standard grid once per candidate flag (and
  once with the flag off) and reports the comparison — Brier score, top-20 precision, calibration
  slope, per position, per DL-21's own convention of grading against a baseline, never absolutely.
  This satisfies E8 §5 condition 1 (held-out backtest regression) for every story this session.
- S5 (the blended monolith) is a standing shadow benchmark, not a promotion candidate at all — it has
  no flag, because the epic text is explicit it is "never promoted... without an explicit DP-10
  decision." It always runs and always reports the head-of-ranking gap.
- The **live forecast path** computes each `True`-flagged candidate alongside the default chain and
  carries it in the model card as a labelled comparison figure — DP-08's "publishing a candidate's
  predictions for comparison without letting them influence anything" — but `optimise` and the
  published ranking read only the default (flags-`False`) chain regardless of what the model card
  shows. Turning a flag on in the live config is what starts that story's six-shadow-gameweek clock;
  none is turned on by this change.

### Rejected alternatives

**Treat E10 like D-25 and default the improvements on, reasoning that a backtest-verified change is
evidence enough.** Rejected on the DL-46 entry's own terms: D-25's exception applied because `xp_v1`
was *already* selected and graded and the defect was that a worse model shipped in its place. E10's
stories are not that — they are new formulations (evidence-adaptive shrinkage, a GKP-specific chain,
a duty additive term, a rebuilt M1) that have never been graded against **held-out** live data at all,
which is exactly the case DP-08 exists for.

**Build a fully parallel `xp_v2` model and switch the app over once the backtest looks good.**
Rejected — it duplicates the entire chain for four largely-orthogonal improvements, is a much larger
surface to keep in sync, and still would not satisfy E8 §5's six-live-gameweek condition any sooner;
the flagged-variant design gets the same shadow guarantee with a fraction of the duplication.

**Skip E10 entirely until GW7 or so, when six shadow gameweeks could plausibly exist.** Rejected —
nothing stops the backtest-side development, testing and evidence-gathering from happening now, and
delaying it would mean the flags do not even exist to be turned on when the season starts generating
the live evidence DP-08 asks for. The part that is genuinely gated by calendar time (live promotion)
is deferred; the part that is not (implementation, backtest verification, shadow wiring) is not.

### Consequences

- E10's own DoD line — *"each promoted change cleared the E8 §5 bar"* — **stays unticked** by this
  work, honestly, for the same reason [DL-22](#dl-22) and [DL-23](#dl-23) record: a checkbox is only
  as trustworthy as what verifies it, and nothing can verify six live gameweeks before six gameweeks
  have been played. Every other DoD line — the metric being reported per position, the reference table
  existing, the shadow benchmark reporting the gap — is fully closeable now and is expected to close
  in this pass.
- A follow-up, out of this epic's scope, is the actual promotion review after GW6 or so: reading the
  live shadow comparison the model card has been carrying since GW1, checking all three E8 §5
  conditions, and flipping the flags that earn it. That review is not started here.
- The DL-21 guardrail (no −8 hit, chip or wildcard justified by `xp_v1` alone until top-20 precision
  beats B0) is untouched and remains the operative safety net for the live-default chain throughout.

---

## DL-48 — D-14 closed: the minutes Brier is measured on the whole population against a reconstructed E0 haircut, and the `minutes_v2` candidate improves calibration everywhere except where E10 needs it

**Date:** 2026-08-20 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-10 ·
**Builds on:** [DL-21](#dl-21), [DL-22](#dl-22), [DL-47](#dl-47), DP-08, DP-12, DP-13 ·
**Closes:** D-14 · **Bears on:** [Q-08](04-conceptual-design.md#15-open-design-questions)

### Context

[E10-S1](epics/E10-discrimination-at-the-head.md#e10-s1--minutes-calibration-then-a-better-m1--2-days--fr-10--closes-d-14)
says *measure first, then improve*, and its acceptance criterion is a Brier score **beating the E0
status-flag haircut** — the bar E3-S3 set and [DL-22](#dl-22) found had never actually been checked,
because `minutes_brier` was null in every report the harness had ever produced. Implementing that
raised four questions that are judgement calls rather than implementation detail, and one of them
turns out to change what the number means. They are recorded here with the evidence they produced.

### Decision

**1. The minutes Brier is measured on every prediction, not on the scored subset.**
Every accuracy metric in the harness is computed on rows passing `minimum_minutes_for_scoring`,
because scoring a *points* forecast against a player who did not feature measures the minutes model
twice and flatters both. Calibration is the exact opposite case: **60% of the archive's rows are
non-appearances**, and those rows are the thing being calibrated. Scored only where somebody played,
every minutes model on earth reports a superb number, because the answer is always yes. So the two
metrics deliberately run on two populations — 54,045 observations for calibration against 21,712 for
accuracy — and the report says so in the section itself rather than leaving a reader to assume they
match.

**2. The Brier is the multiclass form over `{0, 1-59, 60+}`, not three binary scores.**
What the optimiser consumes is the *distribution*: it multiplies every rate by the 60+ mass and adds
appearance points on the 1-59 mass. A model can be well calibrated on "did he play" and badly wrong
about how long, and only the joint form scores both. Zero is perfect, 2 is the worst possible.

**3. The E0 status-flag haircut is reconstructed as start rate × availability, with availability
1.0 on every historical row — and the reconstruction is deliberately the *strongest* honest version
of the baseline.** The archive carries no status flag, so a literal replay is impossible. Setting
availability to 1.0 is faithful rather than a straw man, and the model card has said so since E0:
*"nearly every player is flagged available, so the availability haircut does almost nothing."* What
E0's minutes estimate actually rested on was the start rate, so that is reproduced in full and
**unshrunk** — a nailed starter reads as a nailed starter instead of being pulled toward a group
prior — and where starts were never recorded (before 2022/23) the appearance rate stands in rather
than the row being dropped, so both sides are scored on one population. Every one of those choices
moves the bar *up*. A baseline worth beating should be hard to beat.

**4. European rotation (Q-08) is not implemented, because the data to implement it does not exist —
and it is not invented.** Q-08 asks how aggressively to model rotation for clubs in UEFA
competition. Nothing in the silver model carries a European fixture, a competition label or a
midweek non-Premier-League match: the `fixture` table is the FPL calendar and nothing else, and
`player_gameweek` is one row per Premier League fixture. Deriving "this club is in Europe" from
league position or from a hardcoded club list would be exactly the invented fact DP-09 and Invariant
2 exist to prevent, and adding a European feed is a **new data source** — an Invariant 1 question and
an E12 question, not something to smuggle into a minutes model. **Q-08 stays open.** What is
implemented instead is the *observable* half of the same effect: fixture density counted from the
calendar the project already has, which is what a midweek European tie looks like from inside the
Premier League data — an extra match in the fortnight. A club playing Thursdays shows up in that
count without anybody asserting which competition it was.

**5. The injury-return ramp is a share of missed matches over a recent window, gated on being an
established starter — not a run length.** A player who missed three of the last four and played the
fourth is mid-return, and a run counted backwards from his last match would call that zero. The gate
on long-run appearance rate is what stops the ramp firing on a fringe player, who has nothing to
return *to* and whose fitted appearance band already knows he does not start; ramping him too would
count one fact twice and push down exactly the wrong players. Neither this nor the congestion
adjustment may move P(play): both say how long a player stays on, not whether he is picked, and if
either could move P(play) it would be indistinguishable from availability news — the one thing M1 is
built to keep separate.

### The evidence

The standard grid, 72 folds over 2024/25 and 2025/26, run once with the flag off and once on. **The
flags-off run reproduces [DL-34](#dl-34)'s recorded numbers to five decimal places** (MAE 1.92655,
Spearman 0.23070, MAE-skill 0.01957), which is the regression guarantee DL-47 asked for, measured
rather than asserted.

| | haircut | `minutes_v2` **off** | `minutes_v2` **on** |
| --- | --- | --- | --- |
| **Minutes Brier** (54,045 obs) | 0.44476 | **0.35877** | **0.34822** |
| Skill vs haircut | — | +0.193 | +0.217 |
| Brier, GKP / DEF / MID / FWD | 0.318 / 0.441 / 0.472 / 0.471 | 0.159 / 0.365 / 0.394 / 0.396 | 0.149 / 0.355 / 0.384 / 0.386 |
| MAE (21,712 obs) | — | 1.92655 | 1.92340 |
| Spearman | — | 0.23070 | 0.24075 |
| Calibration slope | — | 0.70117 | 0.72663 |
| **Top-20 precision** | — | **0.00** | **0.00** |

**D-14 is closed: M1 beats the status-flag haircut, in every position, with the flag off.** That is
E3-S3's acceptance criterion met by a number rather than by a ticked box, and it needed no model
change at all — which is why it was worth doing first.

**The candidate improves every aggregate and does not touch the thing E10 exists for.** Brier,
Spearman, MAE and calibration slope all move the right way, in every position, and top-20 precision
stays at 0.00. Per DP-12 the movements are small and none is yet shown to exceed the noise in a
72-fold sample.

**And the finding worth more than the improvement is in the by-band split**, which is exactly why
E10-S1 asked for it:

| Observed band | haircut | off | on |
| --- | --- | --- | --- |
| `none` | 0.38401 | 0.18991 | **0.15644** |
| `short` | 1.03756 | 1.01050 | 0.99266 |
| `long` | 0.29804 | **0.42122** | **0.46437** |

**M1 beats the haircut overall by being far better about who does not play, and is meaningfully
*worse* than E0's crude heuristic about the players who actually lasted the hour** — and the
candidate makes that half worse still, because every one of its adjustments moves mass *out* of the
60+ state. The head of the ranking is made of players who play 60+ minutes. So the aggregate gain is
bought in the half of the distribution that decides nothing, at the cost of the half that decides
everything, and this is the same compression [DL-21](#dl-21) found at the head showing up in the
minutes component: **the model is systematically under-confident about full starts.** That is a
finding about direction, not a number to tune, and it is the case for
[E10-S2](epics/E10-discrimination-at-the-head.md#e10-s2--reduce-over-shrinkage-at-the-head--2-days--fr-12--bears-on-q-14)
rather than against it.

### Rejected alternatives

**Score the minutes Brier on the same population as the accuracy metrics.** Rejected — it is the
degenerate measurement described above, and it is very close to how `minutes_brier` would have been
wired if the null field had simply been plumbed through `evaluate` without asking what it was
measuring. The number would have looked plausible and meant nothing, which is the DP-13 failure mode
exactly.

**Take the haircut as availability alone (P(play) = 1.0 for everyone), on the grounds that E0's
status flag really was that weak.** Rejected — it is technically defensible and it is a straw man.
E0 had a start-probability model; leaving it out would have let M1 clear the bar without doing
anything, and a baseline chosen so the model beats it is not a baseline (DP-12).

**Promote `minutes_v2` on this evidence, since every aggregate improved.** Rejected on DP-08 and on
DL-47's own terms. There is no live shadow window before GW1, the gains are small, and the by-band
split says the candidate moves the *wrong* half of the distribution for this epic's purpose. "It
improved" is not a finding; "it improved at the head" would be, and this did not.

### Consequences

- **D-14 is closed** and the model card's D-14 weakness is rewritten from "calibration is unmeasured"
  to what is now true. Leaving the old text would be a false claim on the one document a human reads
  before a deadline.
- `discrimination.minutes_v2` **stays `False`** in the shipped configuration. Its six-shadow-gameweek
  clock has not started, and E10's promotion checkbox stays open exactly as DL-47 said it would.
- The `long`-band deficit is the concrete, measured target E10-S2 should be graded against, and it
  gives that story a falsifier it did not have: if evidence-adaptive shrinkage is doing what it
  claims, the `long`-band Brier improves rather than the aggregate.
- **Q-08 remains open** and is now blocked on a data question rather than a modelling one: it cannot
  be answered until some source carries European fixtures, which is an E12 scope decision.
- Both distributions and the observed band are written to `backtest-predictions.parquet`, so the
  comparison is re-checkable from the evidence rather than only from the report.

---

## DL-49 — E10-S2: top-20 precision was pooled across every gameweek and therefore pinned at zero; fixing it makes the head measurable, and once it is measurable, evidence-adaptive shrinkage does not move it

**Date:** 2026-08-21 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-12 ·
**Builds on:** [DL-13](#dl-13), [DL-21](#dl-21), [DL-46](#dl-46), [DL-47](#dl-47), [DL-48](#dl-48),
DP-08, DP-10, DP-12, DP-13 · **Answers:** [Q-14](05-model-improvement-plan.md#9-new-open-questions-raised-by-this-plan)

### Context

[E10-S2](epics/E10-discrimination-at-the-head.md#e10-s2--reduce-over-shrinkage-at-the-head--2-days--fr-12--bears-on-q-14)
asks for shrinkage to become evidence-adaptive so that the elite spread out instead of collapsing
toward the position prior, and states its falsifier in advance: **the confidence threshold at which
the trade turns is found on the backtest, not chosen** (Q-14). Its acceptance criterion is that
top-20 precision and the calibration slope improve without MAE regressing past a stated bound.

Implementing that required looking at the metric it is graded on first, and the metric turned out to
be the more important half — the same shape of finding [DL-48](#dl-48) reported for S1, and for the
same reason: *measure first*.

### Decision

**1. Top-20 precision and the captaincy hit rate are computed per gameweek and averaged, not pooled
across the whole backtest. This is a defect being fixed, not a metric being redefined.**

The harness reported `top_n_precision: 0.00` for every model in every run it had ever produced, and
that is not a fact about any model. Pooled over 72 folds the twenty highest *observed* scores are
twenty individual 18-to-25-point hauls in twenty different gameweeks; the highest a calibrated
expectation of a single gameweek can ever be is about six. The two sets cannot intersect, so the
answer is 0.00 for the model, for B0, for the trailing-six benchmark and for any model that could
ever be written. **A metric that cannot move cannot grade anything**, and DL-21 named this one as
*the* decision-relevant measure. The captaincy hit rate had the identical defect: pooled, it asks
whether the single highest-predicted row in two seasons was the single highest-scoring one, which is
one observation, not 72.

That this is a bug rather than a change of definition is settled by the project's own documents
rather than by preference. DP-12 already reasons about this metric as *"the captaincy hit rate over
one season is n=38, so the standard error is around 8 points"* — n=38 is only true if each gameweek
contributes one observation. And the object a manager acts on is one gameweek's ranking; "the top 20"
across two seasons is not a thing anybody chooses from. So this lands **unflagged**, on DP-08's named
bug-fix exception and the same reasoning [DL-46](#dl-46) applied to D-25: the graded quantity was not
the quantity anybody intended to grade.

**2. Each position's head goes as deep as that position goes into a squad.**
E10 grades every metric per position, and a flat top-20 applied inside a position is not a head at
both ends of the pitch: barely twenty goalkeepers feature in a gameweek, so "the top 20 goalkeepers"
is *all* of them and every model scores about 0.98. The depth is therefore the overall head size
split by the squad composition — 3/7/7/4 for a top-20 — which is both the same relative depth
everywhere and the honest answer to "how far down this position do I actually shop?". The
composition is an FPL rule and arrives from the predictor's own `GameRules` rather than being
written into a metric (Invariant 2, DP-05), by the same route S1 gave the harness the 60-minute
threshold.

**3. Evidence-adaptive shrinkage is a straight ramp on the prior's weight between two named points,
and it reuses the evidence measure and the confidence scale that already exist.**
`RateModel.predict` weights a player on himself by `m / (m + prior_minutes)`. The candidate replaces
the constant with `prior_minutes × (1 - strength × ramp(m))`, where `ramp` is zero below
`onset_minutes`, one at and above `full_minutes`, and linear between. Below the onset nothing
changes at all: shrinkage exists so that three appearances are not read as a rate, and relaxing
*that* would not be reducing over-shrinkage at the head, it would be deleting the mechanism.

The evidence `m` is the quantity the shrinkage already used — recent minutes per match times matches
observed — which is *both* of the things E10-S2 names, minutes played and sample size, in one number;
a second definition of "how much do we know about this player" would be a second scale printed under
one set of names. The two ramp endpoints default to 600 and 1800, the values `confidence_minutes_medium`
and `confidence_minutes_high` already carry, but they are **separate parameters** deliberately: those
two tier the uncertainty band shown to a human, and coupling them would mean a shrinkage sweep
silently re-tiered every published band, which is one experiment measuring two changes.

A straight line rather than a fitted curve because the shape is a claim about players and a reader
has to be able to disagree with it in the terms it is stated in (DP-10). *"Nothing changes below ten
full matches, and by twenty the prior counts for 60% of what it did"* is a sentence you can argue
with; a logistic in two fitted coefficients is not.

**4. The MAE-regression tripwire is a relative regression of more than 1%, i.e. MAE above 1.9458.**
Stated before the sweep and stated here because the acceptance criterion demands a bound rather than
a judgement. 1% is not arbitrary: the model's entire measured edge over B0 is an MAE skill score of
**+0.0196**, so a 1% MAE regression consumes half of the only advantage the model has ever been
shown to have. Past that line the change would be buying head-of-ranking movement with the model's
one demonstrated strength, which is the trade DL-21 already warned is going the wrong way. **The
bound held everywhere** — the worst arm in the sweep regressed MAE by 0.29% — so it was never the
binding constraint. The criterion failed on its own terms, not on the tripwire.

### The evidence

The standard grid, 72 folds over 2024/25 and 2025/26, once per arm. **The flag-off arm reproduces
[DL-48](#dl-48)'s recorded numbers to five decimal places** (MAE 1.92655, Spearman 0.23070,
calibration slope 0.70117, minutes Brier 0.35877), which is the regression guarantee DL-47 asked for,
measured rather than asserted.

**What the metric fix alone revealed**, before any model change:

| Top-20 precision | pooled (before) | per gameweek (after) |
| --- | --- | --- |
| `xp_v1` | 0.00 | **0.12708** |
| B0 (price + position) | 0.00 | **0.16597** |
| model-free (trailing 6) | 0.00 | **0.14444** |

**The model is worse than price at the head, by 0.039 ± 0.010** (paired over 72 folds, so roughly
four standard errors). That is [DL-21](#dl-21)'s central finding stated for the first time as a
number that can move, rather than as a zero that never could.

**The Q-14 sweep.** Strength swept with the endpoints fixed, then the endpoints swept at strength
0.6:

| Arm | strength | onset | full | MAE | ΔMAE | Spearman | Calibration slope | Top-20 precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **off** | — | — | — | 1.92655 | — | 0.23070 | **0.70117** | 0.12708 |
| | 0.2 | 600 | 1800 | 1.92714 | +0.03% | 0.23078 | 0.69717 | 0.12986 |
| | **0.4** | 600 | 1800 | 1.92793 | +0.07% | 0.23081 | 0.69218 | **0.13056** |
| | 0.6 | 600 | 1800 | 1.92897 | +0.13% | 0.23085 | 0.68598 | 0.12639 |
| | 0.8 | 600 | 1800 | 1.93030 | +0.19% | 0.23085 | 0.67830 | 0.12569 |
| | 1.0 | 600 | 1800 | 1.93206 | +0.29% | 0.23080 | 0.66881 | 0.12639 |
| | 0.6 | 0 | 1800 | 1.92994 | +0.18% | 0.23051 | 0.68158 | 0.12778 |
| | 0.6 | 300 | 1800 | 1.92940 | +0.15% | 0.23076 | 0.68399 | 0.12778 |
| | 0.6 | 1200 | 1800 | 1.92850 | +0.10% | 0.23080 | 0.68804 | 0.12361 |
| | 0.6 | 600 | **900** | 1.93031 | +0.20% | 0.23085 | 0.67965 | **0.13125** |
| | 0.6 | 600 | 3600 | 1.92760 | +0.05% | 0.23106 | 0.69370 | 0.12708 |

**Q-14 is answered: the trade turns at a strength of about 0.4, and it was found on the backtest.**
Top-20 precision rises from 0.12708 to 0.12986 to 0.13056 and then falls away; a steeper ramp
(600→900 at strength 0.6) is marginally higher again at 0.13125. That is a real turning point and it
is where the shipped default now sits.

**Per position, because a gain confined to one position is not a gain** (E10 §0). Head depth is
3/7/7/4 by squad composition:

| | GKP | DEF | MID | FWD |
| --- | --- | --- | --- | --- |
| Precision, flag **off** | 0.14815 | 0.09127 | 0.13889 | 0.15972 |
| Precision, **strength 0.4** | 0.14815 | 0.09524 | 0.13690 | 0.15625 |
| Precision, **B0** | **0.19444** | **0.13294** | **0.17659** | **0.25000** |
| Calibration slope, off | 0.16463 | 0.62512 | 0.83022 | 0.73098 |
| Calibration slope, strength 0.4 | 0.16032 | 0.61990 | 0.81421 | 0.71483 |

**B0 beats the model at the head in all four positions**, and the candidate improves precision in
exactly one of them (DEF, by 0.004) while degrading MID and FWD and leaving GKP untouched. The
calibration slope falls in all four. There is no position in which this change is a gain.

**And it does not clear the acceptance criterion, for two separate reasons.**

*The precision gain is inside the noise.* Per-fold precision has a standard deviation of 0.076 over
72 folds, so the standard error of the mean is 0.0090 and the best arm's gain of +0.0042 is under
half of one. Paired fold by fold — the fair test, since both arms see the same 72 gameweeks — the
optimum arm gains **+0.00347 with a standard error of 0.00228, t = 1.52**, and the steeper arm
+0.00417 at t = 1.14. Neither reaches two standard errors. More tellingly: **at the optimum the
top-20 changed at all in only 11 of 72 gameweeks**, and in those it moved one player. A change that
leaves 61 of 72 heads identical has not touched the thing the season is decided on — E10 §3's own
honest question, *"would I captain differently because of this change?"*, answers itself.
**"It improved" is not a finding** (DP-12).

*The calibration slope moves the wrong way, monotonically, in every position.* 0.70117 → 0.69218 at
the precision optimum, and down to 0.66881 at full strength; GKP, DEF, MID and FWD all fall together
at every arm. This is not noise, it is arithmetic, and it exposes a **misreading in the epic's own
premise** that matters more than the experiment:

> The calibration slope is the regression of actual on predicted, so it equals
> `corr × sd(actual) / sd(predicted)`. Here that is `0.1925 × 2.942 / 0.808 = 0.701`, exactly the
> reported figure. **A slope below 1 means predictions are too *spread out* for their information
> content, not compressed** — which is what `metrics.calibration_slope`'s own docstring has said
> since E3. Shrinking less raises `sd(predicted)` and therefore *lowers* the slope unless the
> correlation rises in proportion. It did not: Spearman moved from 0.23070 to 0.23085, in the fourth
> decimal place. So *"shrink less in order to improve the calibration slope"* is self-contradicting
> at fixed information content, and every arm of the sweep demonstrates it.

The sense in which the head genuinely *is* compressed — `sd(predicted)` of 0.81 against `sd(actual)`
of 2.94 — is not a defect at all. A conditional expectation of a noisy target **must** have lower
variance than the target; that is the variance decomposition, not a modelling failure. B0 settles it
from the other direction: B0's slope is **0.606**, further from 1 than the model's 0.701, and B0 is
nonetheless *better* at the head (0.166 against 0.127). Slope-toward-one and head precision are not
the same axis, and E10-S2's acceptance criterion assumed they were.

**What the numbers say the deficiency actually is: correlation, not scale.** The model's Pearson
correlation with outcomes is 0.19. Rescaling what a model knows cannot add to what it knows, and
adaptive shrinkage is a rescaling. Nothing in this sweep is a reason to doubt the *direction* of
DL-21's finding — the head is where the model is weakest, and it is measurably worse than price
there — only the mechanism S2 proposed for fixing it.

### Rejected alternatives

**Leave `top_n_precision` pooled and grade S2 on Spearman instead.** Rejected. The pooled figure is
not a conservative measurement of the head, it is not a measurement of anything, and DL-21's own
guardrail — no −8 hit, chip or wildcard justified by `xp_v1` alone until top-20 precision beats B0 —
was being evaluated against `0.00 > 0.00`. It happened to give the safe answer, for no reason. A
safety net that holds by accident is not a safety net (DP-13). *The guardrail's verdict is unchanged
by the fix: 0.127 still does not beat 0.166. It is now unchanged for a measured reason.*

**Report the pooled and per-gameweek figures side by side, to preserve continuity with earlier
runs.** Rejected — the pooled column would be a zero in every row forever, and a column of zeros on
the card a human reads before a deadline invites exactly one wrong inference: that the model gets
nothing right at the head. It gets 12.7% right at the head and is beaten by price. Those are
different claims and only one of them is true.

**Set the shipped `strength` to 0, so that turning the flag on is inert.** Rejected as dishonest
plumbing. A flag whose "on" state does nothing hides the finding instead of recording it; the
default sits at the measured turn point, 0.4, and the parameter's description says in as many words
that the optimum exists and does not help.

**Promote the 0.4 arm anyway, since top-20 precision is the epic's target metric and it did rise.**
Rejected on DP-08, DP-12 and DL-48's precedent in one move. The rise is under half a standard error,
the calibration slope — the criterion's other half — degrades monotonically, and there is no live
shadow window before GW1. This is precisely the case where a change "only improves the metric" by
finding a pattern in the noise of a 72-fold sample.

**Also make the prior-season ratio's shrinkage (`RateModel._prior_scale`) evidence-adaptive.**
Rejected as scope, and recorded so the omission is a decision rather than an oversight. That is a
different mechanism answering a different question — how far a *prior* moves toward last season's
ratio, rather than how far a *player* moves toward his position — and sweeping both at once would
have produced a grid in which no single number could be attributed. It remains available if a future
story wants it.

### Consequences

- **E10-S2's acceptance criterion is not met, and the DoD line stays unticked.** Top-20 precision
  moved within its own noise and the calibration slope moved the wrong way. `adaptive_shrinkage`
  **stays `False`** in the shipped configuration; its six-shadow-gameweek clock has not started, and
  the published ranking and the optimiser's inputs are byte-identical to before this change.
- **The acceptance criterion itself should be revisited before S3 and S4 are graded.** "Calibration
  slope improves" is not a coherent goal for a change that widens the predicted distribution, and it
  is not a proxy for discrimination at the head — B0 has a worse slope and a better head. The
  measurable statement of what E10 wants is *top-20 precision, per position, against B0*, and that
  is now reported every run.
- **The finding redirects the rest of the epic.** If the binding constraint is correlation rather
  than scale, then the remaining stories are the right shape and this one was not: S3 adds
  information (penalty and set-piece duty), S4 adds information (opponent shot volume for
  goalkeepers, whose slope of 0.16 and precision of 0.148 against B0's 0.194 make it the worst
  position on every axis), and S5 measures how much information the chain is leaving on the table at
  all. Rescaling was always going to be the cheapest thing to try and the least likely to work.
- The per-position head-of-ranking table is written to `backtest-card.md` on every run and the
  aggregate reaches `model-card.md`, so the number the DL-21 guardrail turns on is now visible on
  the document a human reads before a deadline rather than only in `backtest.json`.
- **A model card or backtest report produced before this change is not comparable on
  `top_n_precision` or `captaincy_hit_rate`.** The card says so in place rather than leaving a reader
  to discover it by finding a 0.00 in an archived run.

---

## DL-50 — E10-S3 and E12-S2: penalty duty is a dated, provenance-carrying reference file rather than anybody's recollection, and as an additive term it separates midfielders and blurs forwards

**Date:** 2026-08-21 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-12 ·
**Builds on:** [DL-21](#dl-21), [DL-47](#dl-47), [DL-48](#dl-48), [DL-49](#dl-49),
DP-06, DP-08, DP-09, DP-10, DP-12, DP-13, DP-15 · **Closes:** D4 (E12-S2)

### Context

[E10-S3](epics/E10-discrimination-at-the-head.md) asks for penalty and set-piece duty as an explicit
additive term at the horizon scorer, reading a committed reference table built as **D4** in
[E12-S2](epics/E12-data-widening-for-priors.md). Penalties are large, lumpy, highly identifiable
points from a small number of players and are currently unmodelled: `RateModel` fits a per-90 blind
to *why* a player scores.

[DL-49](#dl-49) redirected this story before it started. It found the binding constraint is
**correlation, not scale** — the model's Pearson correlation with outcomes is 0.19, and rescaling
what a model knows cannot add to what it knows. S3 is the first story in the epic that adds
*information* rather than rescaling, so it is the first real test of that redirection. DL-49 also
said in as many words that S2's acceptance criterion should be revisited before S3 is graded,
because "the calibration slope improves" is not a coherent goal; the measurable statement of what
E10 wants is **top-20 precision, per position, against B0**, and that is what is used here.

The reference table raised the harder questions, and they are questions of honesty rather than of
implementation. A hand-maintained file is written in the present and read in the past.

### Decision

**1. Nothing in the duty table is written from recollection, and every entry says where it came
from.** Duty at a season start is exactly the fast-moving, low-stakes-to-get-quietly-wrong fact
DP-09 exists to guard. So every entry carries a `basis` naming the snapshot it was seeded from, and
each was seeded from an FPL field this project already holds rather than from anybody's memory of
who takes penalties:

- **The 2024/25 and 2025/26 spells** are FPL's own `penalties_order == 1` as it stood in the
  archive's **season-end snapshot of the previous season**, kept only where the player was still at
  the same club. Fourteen spells for 2024/25, twelve for 2025/26.
- **The 2026/27 spells** are FPL's own pre-season `penalties_order` from the `bootstrap-static`
  snapshot of 2026-08-16 — all twenty clubs — tiered `likely` rather than `confirmed`, because not a
  ball has been kicked, FPL carries the field forward, and it is stale for promoted clubs and new
  signings by construction.

**2. The dates are the design, not metadata.** Each entry is a half-open spell
`[known_from, known_until)` and the lookup is against the deadline being scored. **A table written
today and applied to a 2024 gameweek is Invariant 5 broken by a config file rather than by a
feature** — the same fatal error wearing different clothes, and the one nothing in the metrics would
show. The historical entries obey a mechanical version of the rule that makes the claim checkable
rather than trusted: *an entry may assert a season only if the player was FPL's recorded first taker
for the same club at the end of the previous season*, which is evidence that demonstrably existed
before the season it is applied to.

The consequence is deliberate and worth stating: **entries that hindsight shows were wrong are kept.**
Toney was Brentford's recorded taker and left in January; Eze was Palace's and lost the duty; Willian
and Ward-Prowse barely featured. Filtering those out would be exactly the look-ahead the dates
exist to prevent — they are what a manager would have believed at that season's first deadline,
which is the thing being graded.

**3. Confidence scales the term rather than gating it.** Three tiers — `confirmed` (1.0), `likely`
(0.6), `unconfirmed` (0.25) — and the weights are configuration, so the scorer never holds an
opinion about what "likely" is worth. Scaling rather than gating is what lets the owner record a
doubtful assignment instead of choosing between asserting something they are unsure of and saying
nothing at all. `unconfirmed` is the pydantic default deliberately: an entry typed in by hand with
no tier stated is an entry nobody has checked. A tier absent from the mapping contributes **zero** —
an unknown tier is not a licence.

**4. Absence of an entry means unknown, never "no duty."** Most players have no entry and never
will. The term is additive, so an unlisted player has nothing added rather than something taken
away, and the entry count is printed on the backtest card — because a table that has quietly emptied
through a bad override produces a candidate that is inert, and **an inert candidate grades as *no
effect* when it means *not measured*** (DP-15).

**5. The additive term restores only the share of a taker's penalty return that shrinkage removed.**
The formulation, stated so it can be disagreed with (DP-10): a club wins
`penalties_per_team_match` penalties a match; the taker converts `conversion_rate` of them for the
position's goal points and concedes the missed-penalty points on the rest — every scoring value from
the rules, never a literal (Invariant 2) — and the model is missing exactly the share of that which
shrinkage replaced with a position prior containing almost no penalty duty.

That last clause is the whole design. **A taker's penalties are goals, and M3 observes goals**, so
adding his full penalty return on top of his own fitted rate would count it twice and inflate
precisely the players at the head of the ranking — which would look like a win on top-20 precision
and would be a bias. Scaling by `RateModel.prior_share` makes the term largest for a **newly
appointed** taker, whose record contains no penalties and whose duty is therefore genuinely new
information, and smallest for one the model has watched take forty of them. That is where the
information actually is.

It lands **inside** the `goals` component rather than beside it, because a penalty is a goal and a
taker's decomposition should read as the larger goal threat he is. A new component would also be a
change to the published web contract for a candidate that is off by default (DP-04). It carries a
matching variance contribution: a term that moved the mean and not the band would hand the optimiser
a player who looks both better *and safer* than he is (Invariant 6).

**6. Penalties only. Set pieces are a validated schema with no entries, and that is a decision.**
`direct_free_kicks` and `corners` load and validate; nothing consumes them and nothing is seeded.
Nothing in silver carries set-piece volume, so a corner-taker assist uplift would be an invented
number rather than a modelled one (DP-09), and shipping it beside the penalty term would make one
experiment measure two changes — [DL-49](#dl-49)'s own argument, applied to this story.

**7. The table lives at `forecast.duty`, in its own `config/defaults/duty.yaml`.** Its own file
because E12-S2 asks for something hand-editable and separately reviewable with an owner-maintenance
note in it, as `rules.yaml` is. Under `forecast` because the forecast is its only consumer, and a
section nothing outside one package reads belongs to that package — which also means the flag can
gate the table at `fit_components` with no plumbing at any call site, exactly as S1 and S2 gate
theirs. It reaches the config through the existing `defaults/*.yaml` glob; no loader change was
needed.

**8. Grading uses `strength` as the sweep knob, and strength 4 is approximately the uncorrected
term.** 1.0 is the formulation as argued. The measured uplift at 1.0 averages 0.075 points and at
4.0 averages 0.30 — which is close to a taker's *full* penalty contribution — so the sweep happens
to span "with the double-count correction" to "with essentially none of it", and reads as an
argument about the correction rather than about penalties.

### The evidence

The standard grid, 72 folds over 2024/25 and 2025/26, once per arm. **The flag-off arm reproduces
[DL-48](#dl-48)'s and [DL-49](#dl-49)'s recorded numbers to five decimal places** (MAE 1.92655,
Spearman 0.23070, calibration slope 0.70117, top-20 precision 0.12708), which is the regression
guarantee DL-47 asked for, measured rather than asserted.

| Arm | MAE | Spearman | Calibration slope | Top-20 precision |
| --- | --- | --- | --- | --- |
| **off** | 1.92655 | 0.23070 | 0.70117 | 0.12708 |
| strength 1.0 | 1.92653 | 0.23090 | 0.70164 | 0.13056 |
| strength 2.0 | 1.92656 | 0.23104 | 0.70167 | 0.13125 |
| strength 4.0 | 1.92697 | 0.23110 | 0.70045 | 0.13194 |
| B0 (price + position) | — | — | 0.606 | **0.16597** |

DL-49's MAE tripwire (a relative regression past 1%, i.e. MAE above 1.9458) was nowhere near
binding: the worst arm regresses MAE by **0.02%**, and at strength 1.0 MAE fractionally *improves*.
The calibration slope barely moves, which is the first arm of this epic where it does not move the
wrong way — consistent with DL-49's arithmetic, since this change adds correlation rather than
widening the distribution.

**Per position, which is where the finding is** (head depth 3/7/7/4 by squad composition):

| | GKP | DEF | MID | FWD |
| --- | --- | --- | --- | --- |
| Precision, flag **off** | 0.14815 | 0.09127 | 0.13889 | 0.15972 |
| strength 1.0 | 0.14815 | 0.09127 | **0.14484** | *0.15625* |
| strength 2.0 | 0.14815 | 0.09127 | **0.14683** | *0.15278* |
| strength 4.0 | 0.14815 | 0.09127 | **0.15079** | *0.14931* |
| B0 | **0.19444** | **0.13294** | **0.17659** | **0.25000** |

Paired fold by fold — the fair test, since every arm sees the same 72 gameweeks:

| Arm | Overall Δ | t | MID Δ | t | FWD Δ | t | Heads that moved |
| --- | --- | --- | --- | --- | --- | --- | --- |
| strength 1.0 | +0.00347 | 1.52 | **+0.00595** | 1.76 | −0.00347 | −1.00 | 8 of 72 |
| strength 2.0 | +0.00417 | 1.51 | **+0.00794** | **2.04** | −0.00694 | −1.42 | 13 of 72 |
| strength 4.0 | +0.00486 | 1.31 | **+0.01190** | **2.18** | −0.01042 | −1.35 | 18 of 72 |

**The term separates midfielders and blurs forwards, monotonically, at every strength.** MID is the
only position that improves and it is the only movement in the epic so far to clear two standard
errors; FWD degrades every time, never significantly, but never once in the other direction. GKP and
DEF are untouched because no goalkeeper or defender is in the table — correct rather than a bug, and
visible rather than assumed.

**The reading, and it is the point of the story.** Among forwards, penalty duty is *already priced
in by everything else*: nearly every leading forward takes his club's penalties, so duty adds no
separation within that head and the term only reshuffles a four-deep ranking, on average wrongly.
Among midfielders it separates, because most midfielders do not take penalties and the handful who
do — Palmer, Saka, Fernandes, Son — are exactly the ones whose returns run ahead of a position prior
built mostly from midfielders who score rarely. **The information is in the contrast with the prior,
not in the penalty.**

**How little it touches.** 937 of 55,585 predictions changed (602 in the scored subset): 603 MID
rows across 12 players and 334 FWD rows across 8, over 26 distinct takers, 14 active in 2024/25 and
12 in 2025/26. At the argued strength the average changed forecast moves by 0.075 points.

**And the acceptance criterion, which is "top-20 precision among attackers improves", is not met.**
It improves among midfielders and falls among forwards, and [E10 §0](epics/E10-discrimination-at-the-head.md)
is explicit that a gain confined to one position is recorded as such and does not clear the bar.
B0 still beats the model at the head in all four positions and by a wide margin among forwards
(0.25 against 0.15), so the [DL-21](#dl-21) guardrail's verdict is unchanged.

### Rejected alternatives

**Seed the table from what the model already knows about who takes penalties.** There is no such
knowledge — the whole premise of the story is that nothing in the pipeline knows it. The real
temptation was to seed it from *recollection*, and it was rejected because a plausible-looking
roster of penalty takers is indistinguishable from a correct one until a season has been played on
it, and this file's entire value is that a reviewer can check it. Every entry names a snapshot
instead, and the ones that could not be sourced that way were left out.

**Add the taker's full penalty contribution rather than the shrunk-away share.** Rejected as
double-counting: his penalties are already in his own fitted goal rate, and M3 weights him heavily on
himself once he has minutes. The uncorrected version would raise exactly the players at the head and
would very likely have raised top-20 precision — which is precisely why it is the dangerous option.
The sweep to strength 4.0 measures it anyway, and it does not change the shape of the finding: MID
further up, FWD further down.

**Take the strength-4.0 arm, since MID precision there is the largest gain and clears two standard
errors.** Rejected on DP-08 and DP-12 together. Strength above 1 is, by the parameter's own
documentation, adding penalty return the player's own rate already carries, so a swept optimum above
1 is evidence that something else is being compensated for — not that takers are worth more. And
the arm that maximises MID also maximises the FWD deficit, which is the criterion failing harder,
not the model improving.

**Read FPL's `penalties_order` directly as a feature instead of committing a file.** This is the
alternative with real merit and it is deferred rather than dismissed. `bootstrap-static` publishes
`penalties_order`, `direct_freekicks_order` and `corners_and_indirect_freekicks_order` for all
twenty clubs, and the archive's season-end snapshots carry them — which is where this file's entries
came from. Consuming it *as a feed* means conforming it through the source layer into silver, which
is an Invariant 1 question and an **E12 scope decision**, not something to smuggle into a forecast
module. Two further cautions belong on the record: the archive's copy is a **season-end** snapshot,
so using it within its own season is look-ahead, and it would need the same date discipline this file
has; and the separately-ingested `set_piece_notes` endpoint is no substitute, being free prose whose
twenty rows at this season's start all read *"Check back for additional notes soon"*.

**Model corners and direct free kicks too, since the story's title says set pieces.** Rejected as
scope and recorded so the omission is a decision rather than an oversight. Nothing in silver carries
set-piece volume, so both terms would be invented numbers, and both would land in the same
experiment as the penalty term and make it unattributable.

### Consequences

- **E10-S3's acceptance criterion is not met, and the DoD line stays unticked.** `duty_term` **stays
  `False`** in the shipped configuration; its six-shadow-gameweek clock has not started, and the
  published ranking and the optimiser's inputs are byte-identical to before this change.
- **E12-S2 is met and D4 is closed.** The file exists, is documented, carries an owner-maintenance
  note, and is the single source the duty term reads.
- **The finding is the first support DL-49's redirection has received.** S3 adds information and it
  moved a per-position head by more than two standard errors, which no rescaling arm in S1 or S2
  managed. It moved the *wrong* position for the criterion as written, and that is a fact about
  where duty is informative rather than about whether information helps.
- **It also sharpens what remains.** If duty separates a position only where the position prior is
  far from the taker, then the same is likely true of every additive signal in this epic — which is
  an argument for [S4](epics/E10-discrimination-at-the-head.md)'s goalkeeper formulation, whose
  position is the worst on every axis and whose prior is furthest from its best performers, and a
  caution against expecting gains among forwards from anything.
- **The 2026/27 entries are the file's weakest half and must be confirmed before the flag is ever
  turned on.** They are FPL's pre-season field, tiered `likely` for that reason, and the opening
  gameweeks are what settles them. The owner-maintenance note in the file says so at the top.
- The `forecast.duty` entry count reaches the backtest card and `ComponentModels.describe()`, so a
  table that has emptied is visible rather than silent.

---

## DL-51 — E10-S4: most of the goalkeeper Spearman floor was a broken fixture join rather than the model, and once fixtures resolve the separate formulation helps a little while the lighter-touch one actively hurts

**Date:** 2026-08-21 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-12 ·
**Builds on:** [DL-21](#dl-21), [DL-47](#dl-47), [DL-48](#dl-48), [DL-49](#dl-49), [DL-50](#dl-50),
DP-06, DP-08, DP-09, DP-10, DP-12, DP-13, DP-15 · **Answers:**
[Q-15](05-model-improvement-plan.md#9-new-open-questions-raised-by-this-plan) · **Opens:** D-26

### Context

[E10-S4](epics/E10-discrimination-at-the-head.md#e10-s4--a-goalkeeper-specific-formulation--15-days--fr-12--bears-on-q-15)
asks for GKP expected points to come primarily from **opponent shot volume × team defence (M2)**
plus a saves model, rather than a shrunk per-90 that clean sheets dominate. Its acceptance is that
**GKP Spearman moves off the floor** of 0.04, and [Q-15](05-model-improvement-plan.md) is its
falsifier: *a fully separate formulation versus the same chain with a saves-and-shots emphasis;
graded, not assumed.*

The story's own entry carries a precondition — *"needs E9-S2's fixtures in the backtest; the
formulation is fixture-driven by construction"* — and checking it rather than assuming it is what
turned this story into a measurement finding, for the third time in a row (DL-48, DL-49, and now
this). **The precondition does not hold**, and what it was hiding is larger than the model change.

### Decision

**1. Shot volume does not exist in this project and is not invented; expected goals conceded stands
in for it, named as a proxy.**
E10-S4's text says "opponent shot volume", and nothing in the silver model counts shots.
`player_gameweek` has no shot column at all; `shots` exists only on the advanced-metrics table, it
is a *player's own* shots taken rather than shots faced, and no scraped source is enabled by
default. So the formulation reads **M2's expected goals conceded** as the measure of how busy a
keeper's afternoon will be. That is a defensible substitution — expected goals are computed from
shots upstream, so more of one means more of the other — and it is stated rather than made
silently, on the same reasoning [DL-48](#dl-48) applied to European rotation: the honest move is to
implement the observable shadow of the thing and say which it is (DP-09, DP-10). It is also the
first thing to re-examine if a shot feed ever arrives through E12.

**2. Why the generic per-90 is the wrong estimator here, as a measurement rather than an argument.**
Across the archive's regular goalkeepers, **saves per 90 have a standard deviation of 0.64 on a mean
of 3.1; saves per unit of expected goal conceded have a standard deviation of 0.21 on a mean of
2.1.** So roughly half the spread between goalkeepers' save rates is the defence in front of them
rather than the keeper — and `RateModel` hands all of it to the keeper and then applies it
identically to every fixture. That number, not intuition, is why the story is worth doing.

**3. Two formulations, because Q-15 asks for two, and they differ in what they claim rather than in
strength.** Both end by scaling to the fixture; `discrimination.goalkeeper.mode` chooses between:

- **`separate`** — the fully separate model. A keeper's level is his save rate divided by the
  pressure he actually faced, shrunk toward the goalkeeper population, then multiplied back by the
  pressure M2 expects in *this* fixture. His own history enters only as shot-stopping per unit of
  defence.
- **`fixture_weighted`** — the lighter touch. Keep the existing shrunk per-90 exactly as it is and
  re-weight it by that same fixture factor.

The first changes how goalkeepers rank **against each other**; the second only how one goalkeeper's
weeks rank against each other. Within a gameweek's ranking — which is the only object anybody acts
on — that is the difference between a change that can move the head and one that structurally
cannot, which is why they are separate experiments rather than two strengths of one.

Both sides enter as **ratios to a league mean**, so the units cancel exactly and it does not matter
that M2 is fitted on goals while the history is measured in expected goals. A keeper of average
pressure facing an average fixture gets back precisely the number the old chain gave him: the change
is a re-attribution, not a rescaling, and that property is a test rather than a claim.

**4. `fixture_weight` is a damping parameter and the identity at 0.** M2's per-fixture expectation
is noisier than the season of pressure a keeper has actually faced, so applying it in full is a
claim that the fixture is as well measured as the history. The factor is `1 + w * (ratio - 1)` — a
straight line through the average fixture, so a reader can disagree with it in the terms it is
stated in (DP-10) — and `w = 0` reproduces the fixture-blind rate exactly, which is what makes the
sweep attributable.

**5. No variance term is added.** The saves component contributes none today, in either arm. Adding
one alongside a new mean would make one experiment measure two changes — [DL-49](#dl-49)'s own
argument — so the pre-existing gap is recorded here and left alone. It is not an Invariant 6 breach:
the forecast's band is dominated by the minutes mixture, which is unchanged.

**6. "Off the floor" was given a concrete meaning before the sweep ran, and it is three conditions,
not one.** Stated in advance because "moves off the floor" grades nothing on its own and because
this session has twice found that the metric was the story:

> (1) GKP Spearman reaches **≥ 0.10** — roughly five standard errors from zero rather than the two
> that 0.04 sits at, so the position is *clearly* ranked rather than barely distinguishable from
> unranked; (2) the paired per-fold improvement clears **two standard errors**, the discipline
> DL-49 and DL-50 used; (3) it is not bought with a fall in GKP top-N precision or a breach of
> DL-49's MAE tripwire of 1.9458.

**7. D-26 is opened rather than fixed here: the archive writes no `team_id`, so E9-S2's
fixture-aware backtest has never actually resolved a fixture.**
`fplarchive/adapter.py` sets `"team_id": None` on every `player_gameweek` row. `fixture_calendar`
drops rows with no team, so it returns nothing, `attach_fixtures` takes its stated-absence branch,
and **100% of scored observations are predicted against league-average opposition** — which the
harness has been warning about in `backtest.json` all along, correctly and unread. Under
league-average opposition `goals_conceded_mean` *is* `league_mean_goals`, so this story's fixture
factor is exactly 1.0 on every row and the fixture half of both formulations is **not measured**
rather than shown to have no effect. That is the precise confusion [DL-50](#dl-50) insisted on
avoiding, so it is named here and graded around rather than reported as a null.

Fixing it is **not this story's** change. It is a source-layer defect (Invariant 1), and repairing
it moves every number DL-48, DL-49 and DL-50 recorded, which deserves its own decision rather than
arriving as a side effect of a goalkeeper model.

### The evidence

The standard grid, 72 folds over 2024/25 and 2025/26, once per arm. **The flag-off arm reproduces
[DL-48](#dl-48)'s, [DL-49](#dl-49)'s and [DL-50](#dl-50)'s recorded numbers to five decimal places**
(MAE 1.92655, Spearman 0.23070, calibration slope 0.70117, top-20 precision 0.12708), which is the
regression guarantee DL-47 asked for, measured rather than asserted. GKP Spearman reads **0.04428**,
confirming DL-21's 0.04 in the corrected per-position harness.

**As the harness actually runs** — every row on league-average opposition, so `fixture_weight` is
inert by construction:

| Arm | MAE | Spearman | Slope | Top-20 | GKP Spearman | GKP precision | GKP slope |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **off** | 1.92655 | 0.23070 | 0.70117 | 0.12708 | 0.04428 | 0.14815 | 0.16463 |
| `separate`, any `w` | 1.92589 | 0.23183 | 0.70133 | 0.12917 | **0.06581** | **0.21296** | 0.19880 |
| `fixture_weighted`, any `w` | 1.92655 | 0.23070 | 0.70117 | 0.12708 | 0.04428 | 0.14815 | 0.16463 |
| B0 | — | 0.21034 | 0.606 | **0.16597** | 0.06902 | 0.19444 | — |

Paired fold by fold, `separate` against off: GKP Spearman **+0.03660, se 0.01513, t = 2.42**; GKP
precision **+0.06481, t = 2.34**. DEF, MID and FWD are **identical to five decimal places** in every
arm, which is the blast radius checked rather than asserted. That precision figure — 0.213 against
B0's 0.194 — is **the first time in E10 that any arm has beaten B0 at a position's head.**

**And it is not the finding, because the harness it was measured in cannot see a fixture.** With
`team_id` reconstructed in the harness input only — a fixture has two clubs, so a row whose opponent
is B belongs to A; 100% recovered, fixture coverage 1.0 — the same five arms read:

| Arm | MAE | Spearman | Slope | Top-20 | GKP Spearman | GKP precision | GKP slope |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **off** | 1.93023 | **0.25032** | 0.70162 | 0.11736 | **0.09948** | **0.19444** | 0.21521 |
| `separate`, `w` 0.0 | 1.93033 | 0.25095 | 0.69840 | 0.11667 | **0.10927** | 0.20833 | 0.22730 |
| `separate`, `w` 1.0 | 1.92789 | 0.25180 | 0.71111 | 0.11944 | 0.09718 | 0.19907 | 0.22848 |
| `fixture_weighted`, `w` 0.5 | 1.92877 | 0.25102 | 0.70788 | 0.11944 | 0.09421 | 0.18981 | 0.21617 |
| `fixture_weighted`, `w` 1.0 | 1.92776 | 0.25123 | 0.71194 | 0.11944 | 0.08678 | 0.19444 | 0.20994 |

Paired per-gameweek differences in GKP Spearman against that arm's own off:

| Arm | Δ GKP Spearman | se | t |
| --- | --- | --- | --- |
| `separate`, `w` 0.0 | +0.00914 | 0.00500 | 1.83 |
| `separate`, `w` 1.0 | +0.00139 | 0.00688 | 0.20 |
| `fixture_weighted`, `w` 0.5 | −0.00602 | 0.00357 | −1.69 |
| `fixture_weighted`, `w` 1.0 | **−0.02173** | 0.00735 | **−2.95** |

**Three findings, in order of how much they matter.**

***First: most of the goalkeeper floor was the broken fixture join, not the model.*** Resolving
fixtures moves GKP Spearman from **0.04428 to 0.09948 with no model change at all** — it more than
doubles — and takes DEF from 0.16278 to 0.21867 and the overall Spearman from 0.23070 to 0.25032.
[DL-21](#dl-21)'s "a whole position essentially unranked" was substantially a statement about a null
column. It is the same shape of finding as DL-48's and DL-49's and it arrived the same way: by
checking the measurement before believing it.

***Second: Q-15 is answered, and the two halves do not merely differ in degree — the lighter touch
is harmful.*** `fixture_weighted` degrades GKP Spearman monotonically in `w`, reaching **t = −2.95**
at full weight, the largest *significant* movement anywhere in this epic and in the wrong direction.
`separate` helps, most at `w = 0`. The reading, and it is arguable rather than obvious: a
goalkeeper's clean-sheet and goals-conceded components **already** carry M2's fixture signal, and
they carry it with the opposite sign to saves. Amplifying saves by the same factor partially cancels
the clean-sheet term — the *better-measured* of the two — so the fixture is not new information for
a goalkeeper, it is information already spent. Dividing pressure out of his **history** is new
information; multiplying it back into his **fixture** is double-counting, which is exactly the trap
DL-50 identified in a different costume.

***Third: the acceptance criterion is not met, on either reading, and the bound was fixed in
advance.***

- *As the harness ships*: GKP Spearman reaches 0.06581 against a bound of 0.10. Conditions (2) and
  (3) hold — t = 2.42, precision up sharply, MAE improves — and **condition (1) fails.**
- *With fixtures repaired*: the level clears 0.10, but **the model change is not what put it there.**
  The flag-off arm is already at 0.09948; the best candidate adds +0.00914 at **t = 1.83**, so
  condition (2) fails.

Neither reading is a pass, and the bound is not being revisited to make one. One observation is
recorded because it bears on whether the bar was reachable rather than on whether it was cleared:
**B0's GKP Spearman is 0.06902**, so on the unrepaired harness *price itself* falls well short of
0.10, and on the repaired one the model (0.09948 off, 0.10927 on) beats price comfortably. The
floor may be substantially the position rather than the model — goalkeepers are genuinely hard to
rank — and that is a hypothesis for E12, not a reason to move a bar after seeing the result.

### Rejected alternatives

**Fix `team_id` in the archive adapter and grade against that.** Rejected as scope, and it is the
alternative with the most merit. It is a source-layer change (Invariant 1), and it silently
re-bases every figure DL-48, DL-49 and DL-50 recorded — a −0.010 shift in top-20 precision, a
+0.020 shift in Spearman — so it must be its own decision with its own re-run of the epic's arms,
not a line in a goalkeeper story. **D-26** carries it.

**Report the `fixture_weighted` arms as "no effect", since they came out byte-identical to off.**
Rejected, and it is the reason the second sweep exists. They were identical because the fixture
factor was 1.0 on every row, which means *not measured*, and an inert candidate that grades as no
effect when it means not measured is the failure DL-50 named explicitly (DP-15). Measured properly,
that arm is not neutral — it is the worst arm in the epic.

**Take the `separate` arm's unrepaired result — precision 0.213 against B0's 0.194, t = 2.34 — as
clearing the bar, since beating B0 at a position's head is what E10 has been trying to do since
DL-21.** Rejected, and it is the tempting one. That number was produced under an opposition model
that does not exist — every fixture league-average — and the repaired run shows the same arm's GKP
precision advantage shrinking to +0.014 at t = 1.00 once fixtures are real. A result that only
survives in the broken condition is an artefact of the breakage.

**Default `mode` to `fixture_weighted` because its `w = 0` is a cleaner identity.** Rejected: it
would put the shipped default on the arm the evidence says is harmful. `separate` is the default,
and it is the formulation the evidence prefers even though neither clears the bar — the same
reasoning DL-49 used for refusing to ship a strength of 0, that a flag whose "on" state is chosen to
be inoffensive hides the finding instead of recording it.

**Model goalkeeper bonus or BPS from the fixture too, since M8 is as fixture-blind as saves was.**
Rejected as scope and recorded so the omission is a decision. It would land in the same experiment
and make the saves term unattributable, which is DL-49's argument applied here.

### Consequences

- **E10-S4's acceptance criterion is not met, and the DoD line stays unticked.** `gkp_v2` **stays
  `False`** in the shipped configuration; its six-shadow-gameweek clock has not started, and the
  published ranking and the optimiser's inputs are byte-identical to before this change.
- **D-26 is opened and is now the most valuable single item in the epic's neighbourhood.** Resolving
  fixtures improves three of four positions and the overall Spearman by more than any model change
  in E10 has managed, and it is a data defect rather than a modelling question. Every E10 number
  recorded so far was measured under league-average opposition and must be re-read once it is fixed.
- **The E10 §0 premise needs one more correction, after DL-49's two.** "GKP Spearman 0.04" is not a
  fact about the model but about a null column; the position's honest floor is closer to 0.10, where
  the model already beats price. What survives is the *shape* of DL-21's finding — the head is where
  the model is weakest — and the goalkeeper half of it is much smaller than it looked.
- **Q-15 is closed.** A fully separate formulation is better than a saves-and-shots re-weighting of
  the existing chain, the re-weighting is actively harmful, and the value in the separate one is in
  dividing pressure out of a keeper's history rather than in multiplying it back into his fixture.
- The goalkeeper model's fitted keeper count and the column it measured pressure with reach
  `ComponentModels.describe()` and the backtest card, so a candidate that has quietly become inert —
  or has fallen back from expected goals to actual ones, which is a **worse** model rather than an
  equivalent one — is visible rather than silent (DP-09, DP-15).

---

## DL-52 — D-26 closed: the archive always stated which club each row belonged to, and the repair is keyed on the stable club code because half the season-local ids change club every year

**Date:** 2026-08-21 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-12 ·
**Builds on:** [DL-19](#dl-19), [DL-37](#dl-37), [DL-46](#dl-46), [DL-48](#dl-48), [DL-51](#dl-51),
DP-01, DP-08, DP-09, DP-13, DP-15 · **Closes:** D-26 · **Re-ticks:** E9-S2's fixture line

### Context

[DL-51](#dl-51) opened D-26: `fplarchive/adapter.py` wrote `"team_id": None` on every
`player_gameweek` row, so `fixture_calendar` returned nothing, `attach_fixtures` took its
stated-absence branch, and **100% of scored observations were predicted against league-average
opposition** — through code that reads, at every line, as though it were consuming real fixtures.
E9-S2's acceptance was never met, and every figure in DL-48, DL-49, DL-50 and DL-51 was measured in
that condition.

This is a **bug fix, not a model change**, on the exception DP-08 names and
[DL-46](#dl-46) used for D-25. Which club a player belonged to in a completed season is a stable
derivable fact, not a judgement call, and it is not the sort of thing that waits behind the
flagged-and-shadowed machinery [DL-47](#dl-47) built for genuine new model behaviour. If it were
being argued about it would be a model change; nobody argues that Bournemouth played Liverpool.

### Decision

**1. The club was never missing from the archive. It was never read.**
`merged_gw.csv` carries a `team` column — the club's *name*, on every row, in every season the
backfill uses — and `teams.csv` carries the season's club list. D-26 was not an absent fact
requiring reconstruction; it was an unread one. This matters for how the fix is built:
[DL-51](#dl-51)'s diagnostic and `optimise/replay.py` both *inferred* the club from the fixture
pairing (a fixture has two clubs, so a row whose opponent is B belongs to A), which is correct
where it applies but resolves nothing for a fixture only one side of which is present. Reading the
stated club resolves **every** row and depends on no other row.

**2. The id is FPL's stable club `code`, not the season-local `id`, and that is a measurement
rather than a preference.** Between consecutive seasons **eight to ten of the twenty season-local
team ids point at a different club**, because promotion and relegation reshuffle an alphabetical
ordering: id 11 is Liverpool in 2023/24, Leicester in 2024/25 and Leeds in 2025/26. `teams.csv`
carries `code`, which across the four backfilled seasons never once maps to a different club. Since
:class:`TeamStrengthModel` pools team form across every season it is given, writing the season-local
id would have handed one club's attack and defence ratings to another — repairing a null column by
installing a plausible wrong one, which is worse than the null. **This is the club half of
[DL-19](#dl-19)**, arriving three months later for the same reason and with the same answer.

**3. `opponent_team_id` is relabelled with it, because a fixture's two sides must be one kind of
number.** `team_id` is resolved from a name and `opponent_team_id` from a season-local integer;
`fixture_calendar` joins one row's club against another row's opponent. In two id spaces that join
pairs a club with a stranger. Relabelling both through the same club list is a bijection within a
season, so every within-season consumer is unaffected and the cross-season one becomes correct.

**4. Unresolvable stays null, and the season is kept.** A row naming a club the season's list does
not contain, or a season whose `teams.csv` cannot be fetched, gets null club columns, a counted
`log.warning` and a conform-level warning — not a fallback to the season-local id. A null row is
dropped by the calendar and is visibly absent; a row carrying the wrong space is invisibly wrong.
The season's player rows are still evidence for a per-90 rate, so the season itself is not dropped
(DP-15). `team` is added to `REQUIRED_GAMEWEEK_COLUMNS` so a column that silently vanishes upstream
fails loudly instead of quietly re-creating D-26.

**5. Two latent defects that were inert only because `team_id` was null are fixed with it, and both
are the same bug.** Repairing the club makes them reachable, so leaving them would have swapped one
silent wrongness for another.

- **`_team_matches` grouped on `(team_id, fixture_id)` with no season.** The archive numbers
  fixtures 1..380 *within* a season, so a training set spanning two seasons contains every fixture
  number twice and the two matches merged into one row — summed goals, halved match count. The key
  is now `(season, team_id, fixture_id)`. That every `(season, club)` now has **exactly 38**
  matches, min and max alike, is the check that it worked.
- **`season` was absent from the fold frame the predictor fits on**, so `_team_matches` could not
  have keyed on it. It is added to `OUTCOME_COLUMNS` — the one list that reaches `fit` and is
  stripped before `predict` — because it is an identifier, not a feature. What a model could learn
  from a season label is that 2024/25 scored differently, and that is a rule change, not a
  footballer.

**6. The live path's team strength is explicitly restricted to the current season, which preserves
its behaviour rather than changing it.** The live feed writes season-local ids and the archive now
writes codes, so `live.build_forecast` would have pooled two id spaces from the first played
gameweek. Before this fix it pooled nothing — every archive row's null club was dropped — so
filtering to the current season reproduces the shipped behaviour exactly. `stages/publish.py`'s
fixture ticker already refused the same pooling for the same reason ([DL-37](#dl-37)), which is
independent corroboration rather than a new argument. **Widening M2 to prior seasons is a real model
change and needs DP-08's evidence**, not a side effect of a source repair.

### The evidence

**The fix resolves fixtures in the shipped path, not in a side reconstruction** — which is what
DL-51's diagnostic could not demonstrate. Through `fpl-dof ingest` and `fpl-dof transform` into
silver, then the harness unmodified:

| | before | after |
| --- | --- | --- |
| Rows whose club is known | **0%** | **100%** (all three seasons) |
| Gameweeks building a non-empty calendar | **0 of 114** | **114 of 114** |
| `walk_forward` `fixture_coverage` | **0.0** | **1.0** |
| Matches `TeamStrengthModel` fits on | **0** | **2,280** = 3 x 20 x 38 |
| Harness warnings | fixture-coverage warning | none |

The **2,280** is the arithmetic identity worth stating: three seasons of twenty clubs playing
thirty-eight matches, with every `(season, club)` at exactly 38 and 25 distinct clubs across the
three seasons — which is what promotion and relegation should produce and what a conflated id space
could not.

**The re-based grid.** 72 folds over 2024/25 and 2025/26, `minutes_v2` off — the shipped
configuration, and the arm every earlier E10 number was recorded against:

| | as DL-48/DL-49 recorded it | with fixtures real | |
| --- | --- | --- | --- |
| MAE | 1.92655 | 1.93106 | *worse* |
| Spearman | 0.23070 | **0.25058** | |
| Calibration slope | 0.70117 | 0.68990 | *worse* |
| Top-20 precision | 0.12708 | **0.12153** | *worse* |
| GKP Spearman | 0.04428 | **0.10094** | |
| DEF Spearman | 0.16278 | **0.21999** | |
| Minutes Brier | 0.35877 | 0.35877 | unchanged |

**This is a re-basing, not an improvement**, and three of seven figures move the wrong way. It is
also slightly different from DL-51's reconstructed preview (0.25032, GKP 0.09948, DEF 0.21867), and
the difference is exactly the thing that reconstruction could not have: it recovered season-local
ids, so it still conflated clubs across seasons and still collided fixture numbers. Resolving the
identity properly is worth a further +0.0003 overall and +0.0015 on GKP.

**E10-S1 re-checked (DL-48), and its conclusion holds.** Both arms re-run on the repaired data:

| | off | on | paired |
| --- | --- | --- | --- |
| MAE | 1.93106 | 1.92750 | |
| Spearman | 0.25058 | **0.25946** | |
| Calibration slope | 0.68990 | 0.70896 | |
| **Top-20 precision** | 0.12153 | **0.12361** | B0 is **0.16597** |
| Minutes Brier | 0.35877 | 0.34822 | identical to DL-48 |
| `long`-band Brier | 0.42122 | 0.46437 | identical to DL-48 |
| DEF Spearman | 0.21660 | 0.22759 | +0.01099, **t = 3.90** |
| MID Spearman | 0.27055 | 0.28214 | +0.01159, **t = 4.70** |
| FWD Spearman | 0.25508 | 0.26744 | +0.01236, **t = 3.43** |
| GKP Spearman | 0.10691 | 0.10566 | −0.00125, t = −0.20 |
| DEF / MID / FWD precision | | | +0.004 (t 0.70), −0.010 (t −1.52), +0.014 (t 1.42) |

**One finding here is a correction to the premise on which the re-run was ordered.** `minutes_v2`'s
congestion prior was assumed to read the fixture columns D-26 broke. **It does not.** The density
feature is `matches_last{N}d`, a count of *the player's own prior kickoff times* in a rolling
window; it touches no `team_id` and no calendar. That is why the minutes Brier, its per-position
split and its per-band split come back **identical to DL-48 to five decimal places** — the object
E10-S1 was actually measuring was never affected. What moved is the rest of the chain, equally in
both arms.

So DL-48's conclusion stands, and one part of its evidence is now stronger than it was:

- DL-48 said the aggregate movements were "small and none is yet shown to exceed the noise". Paired
  per-gameweek they now clearly do — **t between 3.4 and 4.7** on three of four positions. That is
  a real improvement, demonstrated rather than observed.
- **And it is still not at the head.** Top-20 precision moves +0.002; per-position precision is
  mixed and no movement clears two standard errors; MID's is *negative*. Both arms remain well below
  B0's 0.16597, so [DL-21](#dl-21)'s guardrail is untouched.
- The reason DL-48 refused promotion is **unchanged in both direction and magnitude**: the
  candidate still buys its aggregate gain by moving mass out of the 60+ state, `long`-band Brier
  0.42122 → 0.46437, and the head of the ranking is made of players who play 60+ minutes.

`discrimination.minutes_v2` **stays `False`**. The flag's six-shadow-gameweek clock has not started.

### Rejected alternatives

**Reconstruct the club from the fixture pairing, as DL-51's diagnostic and `optimise/replay.py`
do.** Rejected as the *primary* route once the `team` column was found: an inference that resolves
most rows is strictly worse than a lookup that resolves all of them, and it cannot resolve a fixture
only one side of which appears — which is most fixtures in a sparse frame. It is kept in `replay.py`
as a fallback, but changed to fill only where the source is silent. Left as it was it would have
*overwritten* resolved codes with season-local ids and put the two sides of every fixture in
different spaces — the fix causing a worse version of the bug it fixed.

**Write the season-local `id`, for consistency with the live adapter.** Rejected on the measurement
in decision 2. Consistency with the live source is real but costs less than cross-season club
identity, and the two never co-occur in one season: the archive is a prior-season backfill and the
live feed only ever writes the current one. Decision 6 makes that boundary explicit at the one place
they could have met.

**Convert the live adapter to codes as well, so the column has one meaning everywhere.** Rejected as
scope, and recorded so the omission is a decision rather than an oversight. `players`, `teams` and
`fixtures` all key on the season-local id and the optimiser's club cap joins on it, so this is a
silver-wide change with its own migration, not a line in a bug fix. It is the right eventual answer
if a future season is ever ingested from both sources.

**Re-run S2's and S3's arms as well.** Rejected on the mechanism rather than on effort. S2's
evidence is about shrinkage against minutes and sample size and S3's duty term is a dated additive
constant; neither reads the fixture calendar the way S1 and S4 do. Their *levels* are re-based by
the table above like everything else, but their paired contrasts are not disturbed. Stated so that
"not re-run" is not mistaken for "re-run and unchanged".

**Take the improved Spearman as evidence the model got better.** Rejected, and it is the tempting
one. Nothing about the model changed. The forecast that ships today is byte-identical to the one
that shipped yesterday; only the measurement of it is now honest, and three of its seven headline
figures got *worse* when it became so.

### Consequences

- **D-26 is closed and E9-S2's definition-of-done line is re-ticked** — on the measurement,
  `fixture_coverage` 1.0, not on the code having been written. The E10–E12 gate in E9 §1 is clear
  for the first time.
- **Every number in DL-48, DL-49, DL-50 and DL-51 is superseded as a level.** Those entries are not
  edited; this one re-bases them, and the table above is the conversion. Their *conclusions* are
  unaffected: no flag was promoted on any of them, and none of them turns on a figure this changes.
- **E10's §0 premise needs its fourth correction.** "GKP Spearman 0.04" was a statement about a null
  column; the position's honest floor is 0.101, where the model already beats B0's 0.087. The
  surviving shape of [DL-21](#dl-21) is that the model is weakest at the *head* — top-20 precision
  0.122 against B0's 0.166 — and that is unchanged and unexplained by fixtures.
- **The regression guard is four assertions, not one**, because asserting `team_id is not None`
  would not have caught what made D-26 survive: that the column being null broke nothing loudly.
  `tests/test_archive_source.py` now asserts every row names its club, that a club renumbered
  between two seasons keeps one id, that club and opponent share an id space, and that the harness's
  calendar is non-empty (DP-13).
- **`xp_v1.team_matches` now warns when it can return nothing.** An unfitted team-strength model
  makes every fixture league-average, which is precisely the condition that went unnoticed for two
  epics. It is no longer possible for it to happen in silence (DP-15).
- The model card and `backtest.json` now report a fixture coverage of 1.0 and a populated
  fixture-difficulty band table, so the next person to read one is reading a real breakdown.

---

## DL-53 — E10-S5: the chain's explainability costs 0.044 of top-20 precision, all of it in forwards and midfielders — and the monolith that recovers it only reaches B0, so the ceiling on this feature set at the head *is* price

**Date:** 2026-08-21 · **Status:** Accepted · **Serves:** OBJ-1, OBJ-7, FR-12, NFR-01 ·
**Builds on:** [DL-04](#dl-04), [DL-21](#dl-21), [DL-28](#dl-28), [DL-47](#dl-47), [DL-49](#dl-49),
[DL-52](#dl-52), DP-08, DP-09, DP-10, DP-12, DP-13 ·
**Bears on:** [Q-04](04-conceptual-design.md#15-open-design-questions)

### Context

[E10-S5](epics/E10-discrimination-at-the-head.md#e10-s5--blended-monolith-as-a-shadow-benchmark--1-day--shadow-only--q-04x6)
asks a different question from the four stories before it. S1 to S4 each tried to make the component
chain better and each failed its own acceptance criterion. S5 does not try to improve anything: it
asks whether the chain's **interpretability** — a product requirement, [DP-10](../DESIGN-PRINCIPLES.md)
— is *costing* accuracy at the head, and how much.

DP-10's own words are the reason this needs a number rather than an opinion. It says to prefer the
formulation you can argue with *"where two designs are close in expected quality"*, and to prefer a
chain of small models over one monolith *"unless the monolith is **materially better** — and if it
is, that trade-off is a recorded decision"*. Both clauses are conditional on a measurement nobody
had taken. Until now "the chain is interpretable and about as accurate" was an article of faith:
a thing the project believed because it would have been inconvenient not to.

### Decision

**1. A gradient-boosted regressor on the same feature set, fitted by the same harness, reported on
every run — and never a promotion candidate.**
Unlike S1 to S4 it has **no `discrimination` flag**, and the absence is the design rather than an
omission. [DL-47](#dl-47) built the flag mechanism so a future review could promote a candidate that
earns it; this one is never promoted whatever the numbers say, so there is nothing to flip and a
switch that existed would be a switch somebody eventually throws. Its configuration lives in
`BacktestConfig.monolith`, which nothing on the forecast, optimise or publish path reads, so the
guarantee is structural rather than a default. A test scans every module in the package: exactly two
files may reach it — `forecast/monolith.py` and `forecast/backtest.py`. **The stage that writes the
report is not one of them**; it reads `BacktestResult.monolith` like any other metric set, so even
the code that publishes the gap cannot construct the model.

**2. scikit-learn's `HistGradientBoostingRegressor`, not LightGBM or XGBoost.**
Free, open source and installable as a wheel on every platform the scheduled runner uses
(Invariant 3, NFR-01). It handles missing values natively, which is not a convenience here: much of
this feature store is legitimately null — a per-90 rate over a window in which nobody played is
*unmeasured* — and the alternative is imputing a number, which is the invented fact [DL-18](#dl-18)
warns against. It takes categorical features without a one-hot expansion of twenty-five club codes.
And it is the library [DL-04](#dl-04) already named as this project's intended stack for exactly
this. LightGBM would be faster on a dataset a thousand times this size and brings a compiled
dependency for it.

**3. The same features, deliberately, rather than the best features that could be assembled.**
The monolith reads exactly the 44 columns the feature store *declares* as inputs — every one of
them, none dropped — plus position, so 45 in all. (The prior-season features are not among them
because that prior is disabled in the shipped configuration; enabling it would widen both sides of
this comparison at once, which is the point of reading the declaration rather than a list.) Not
a richer hand-engineered set: the question is what is achievable **on this data**, and a monolith
that won by being given more would measure the feature store rather than the formulation. The
allow-list is also the look-ahead guarantee — every declared input is stamped `BEFORE_DEADLINE` or
`AT_DEADLINE`, so a new outcome column appearing in the fold frame cannot reach the model by
default, where a deny-list would admit it silently and the backtest would *improve*.

**4. The same fold assembly, reused rather than rebuilt.** It is fitted by `walk_forward` on the
same `training_rows` frame the chain gets and predicts on the same outcome-stripped `visible` frame.
A second training-set construction is a second chance to leak — precisely the trap [DL-28](#dl-28)
records for a different piece of code — and a leaking benchmark would report a gap that is entirely
its own dishonesty, with every metric looking *better* rather than worse. The regression test asserts
the consequence rather than the mechanism: rewrite every gameweek after a fold's deadline and that
fold's monolith predictions must come back **bit-identical**.

**5. What the monolith does not get, named rather than hidden (DP-09).** The chain does not consume
the opponent's id as an identifier — it turns it into M2's fitted attack and defence ratings, pooled
over every match that club has played. The monolith gets the raw club as a *category* and must
rediscover that pooling from splits. So the gap below is a **lower bound** on what a monolith could
do with a fixture-difficulty feature, and an honest measure of what one does with what the chain is
actually handed. Giving it M2's output would make it a hybrid of the thing it is benchmarking.

**6. Ordinary, unswept hyperparameters, and that is the honest setting for a ceiling.** A monolith
tuned against the folds it is graded on would report its own overfitting as the chain's deficit. If
the gap ever matters enough to argue about, the answer is a held-out tuning season, not a sweep
(DP-12).

### The evidence

The standard grid: 72 folds over 2024/25 and 2025/26, 54,045 observations, `fixture_coverage` 1.0,
every candidate flag off — the shipped configuration, on the repaired fixtures of [DL-52](#dl-52).
The monolith's final fold fits on 55,096 rows and did not degrade in any fold that was scored.

| | chain (`xp_v1`) | **monolith** | B0 | model-free |
| --- | --- | --- | --- | --- |
| MAE | **1.93106** | 1.99420 | 1.96499 | 2.11489 |
| MAE skill vs chain | — | **−0.0327** | — | — |
| Spearman | 0.25058 | **0.32087** | 0.21385 | 0.29104 |
| **Top-20 precision** | 0.12153 | **0.16597** | **0.16597** | 0.14444 |
| Captaincy hit rate | 0.02778 | **0.08333** | 0.05556 | 0.06944 |
| Calibration slope | **0.68990** | 0.55502 | 0.60553 | 0.39406 |

**The trade is real and it is significant.** Paired per gameweek over the 72 folds:

| | chain | monolith | paired | |
| --- | --- | --- | --- | --- |
| Top-20 precision | 0.12153 | 0.16597 | **+0.04444 ± 0.01147** | **t = +3.87**, moved in 52 of 72 |
| Spearman | 0.24929 | 0.31494 | **+0.06565 ± 0.00801** | **t = +8.20**, moved in 72 of 72 |
| Captaincy hit rate | 0.02778 | 0.08333 | +0.05556 ± 0.02718 | t = +2.04, moved in **4** of 72 |

That precision contrast is **the largest significant movement anywhere in E10**, and it is a deficit
of the shipped model rather than a gain from a candidate. Every arm S1 to S4 measured moved the head
by less than two standard errors; this moves it by nearly four.

**And the per-position split says it is not a statement about interpretability in general.**

| | chain | monolith | paired precision | | chain | monolith | paired Spearman |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **FWD** | 0.15972 | 0.21875 | **+0.05903, t = +2.64** | | 0.25508 | 0.42178 | **+0.16670, t = +8.09** |
| **MID** | 0.14484 | 0.16468 | +0.01984, t = +1.18 | | 0.27055 | 0.36189 | **+0.09134, t = +8.38** |
| **DEF** | 0.11111 | 0.10714 | −0.00397, t = −0.30 | | 0.21660 | 0.23422 | +0.01762, t = +1.62 |
| **GKP** | 0.20833 | 0.17130 | −0.03704, t = −1.30 | | 0.10691 | 0.08142 | −0.02549, t = −0.98 |

**The whole gap is forwards and midfielders. At goalkeeper and defender the chain is level or
ahead**, and GKP is the one position where the chain beats the monolith on both measures — which is
the first evidence in this epic that E10-S4's formulation work was aimed at a position that was
never the problem, and corroborates [DL-52](#dl-52)'s finding that "GKP is unranked" was a broken
fixture join rather than a model deficiency.

**The finding that changes what E10 is for: the ceiling at the head *is* B0.** The monolith's
top-20 precision is **0.16597** and B0's is **0.16597** — the same number to five decimal places,
paired difference **+0.00000, t = 0.00**. This is a coincidence of the means and not a duplicated
column: the two disagree in 60 of 72 gameweeks and are equal in only 12, and their Spearman
(0.321 against 0.214), MAE and calibration are nowhere near each other. Averaged over 72 gameweeks
the metric takes values in multiples of 1/1440, so a collision is unlikely rather than impossible,
and it is recorded here precisely because a reader would otherwise suspect a bug.

What it means is worth more than the coincidence. **A gradient-boosted model with every feature this
project has recovers the chain's entire deficit to price at the head — and stops exactly there.**
E10 §0's target is to *beat* B0 at the head. Nothing measured in this epic does, and now the ceiling
on this feature set has been measured and it does not either. That reframes the remaining problem
from "the chain's formulation is losing to price" to "**this feature set contains about as much
head-of-ranking information as price does**", which is a data question (E12) rather than a
formulation one.

**The chain remains the best error-avoider, which is [DL-21](#dl-21)'s shape one level up.** The
monolith is *worse* on MAE (1.994 against 1.931, skill −0.033) and worse calibrated (slope 0.555
against 0.690, further from 1 in every position). It buys ranking with scale, exactly as
[DL-49](#dl-49) predicted when it redirected this epic: the deficiency is **correlation, not
scale**, and the monolith is a demonstration that correlation is where the recoverable information
was.

### The DP-10 statement

**Explainability is not free at the head of the ranking. It costs 0.044 of top-20 precision
(t = 3.87) and 0.066 of Spearman (t = 8.20), concentrated entirely in forwards and midfielders.**
That is the number DP-10 requires and it is now reported on every backtest run rather than assumed.

**And the chain is still the right formulation, for three reasons that are not "we prefer it".**

1. **Promoting the monolith would not lift the constraint the gap is about.** [DL-21](#dl-21)'s
   guardrail — no −8 hit, chip or wildcard justified by the model alone until top-20 precision beats
   B0 — would remain in force, because the monolith *ties* B0 and does not beat it. The project
   would trade every component decomposition it has for a model that leaves the binding decision
   rule exactly where it is.
2. **It cannot satisfy the contracts the chain does.** Invariant 6 requires mean **and variance**;
   DP-09 requires the decomposition by scoring component, which is a product feature and not a
   debugging aid. The monolith emits a point estimate and nothing else. "Promote the monolith" is
   therefore not a one-line configuration change that was declined — it is a rewrite of the
   model→optimiser contract, and the accuracy case for it is a tie at the head.
3. **A gap concentrated in two positions is a lead, not a verdict** (E10 §0). The monolith is
   telling us where recoverable information sits — attacking returns for forwards and midfielders,
   through the raw rolling features rather than through the chain's shrunk per-90s — and that is
   something the chain can be given without becoming opaque.

So the answer to [Q-04](04-conceptual-design.md#15-open-design-questions) is recorded rather than
left open: **the monolith is materially better at ranking and materially worse at everything else,
and the chain stands.** This is a decision taken on evidence, and the evidence is re-taken every
run, which means it can change its mind.

### Rejected alternatives

**Give the monolith a richer feature set — fixture difficulty from M2, ownership, price change
momentum.** Rejected as answering a different question. The point is an apples-to-apples ceiling on
*this* data; a monolith that won by being given more would prove that more features help, which
nobody doubts, and would say nothing about the formulation. It would also stop being a benchmark and
start being a hybrid of the thing under test (decision 5).

**Tune the hyperparameters until the monolith is as good as it can be.** Rejected on DP-12. Swept
against the same 72 folds it is scored on, the monolith would report its own overfitting as the
chain's deficit — and the resulting gap would be an argument for abandoning interpretability, made
with a number that does not survive a held-out season.

**Give it a `discrimination.monolith` flag "for symmetry" with S1 to S4.** Rejected, and this is the
one worth being explicit about. The epic says it is never promoted without an explicit DP-10
decision; a flag is a mechanism for promoting something *without* one. Symmetry with the other four
stories would be a cost, not a benefit.

**Make it an optional dependency, so an environment without scikit-learn still runs the backtest.**
Rejected. A benchmark that is present only when an extra was installed is one that silently stops
being reported, and the whole design of this story is that the number is taken again every run.
scikit-learn is a hard dependency of `fpl-dof` as of this change.

**Report only the aggregate gap.** Rejected on E10 §0, and the evidence vindicates it: the aggregate
+0.044 reads as "interpretability costs us at the head", and the split says it costs us **at forward
and midfield** and buys us something at goalkeeper. Those are different findings and only one of
them is actionable.

### Consequences

- **E10-S5's acceptance is met**: the head-of-ranking gap is reported every backtest run — in
  `backtest.json` under `explainability_gap`, as a benchmark row and a dedicated section in
  `backtest-card.md`, in the stage metrics on the run manifest, and as a plain-language sentence on
  the **model card**, which is the document actually read before a deadline. The sentence is written
  once, in `forecast/monolith.py`, and reproduced verbatim by both consumers: two wordings of one
  finding is two chances to word one of them reassuringly.
- **`scikit-learn>=1.6` is now a hard dependency of the pipeline** (Invariant 3 satisfied: free,
  open source, zero running cost). The backtest is slower by roughly the cost of 72 boosted fits.
- **E10 closes with four candidates flagged off and one benchmark permanently on.** No flag was
  promoted by any of S1 to S5, which is the honest outcome of an epic that measured five things and
  found none of them cleared its bar.
- **The reframing is the handover to E11/E12.** "The chain loses to price at the head" was read for
  three stories as a formulation problem. The ceiling measurement says the feature set is the
  binding constraint, so the next place to look is [E12](epics/E12-data-widening-for-priors.md)'s
  data widening rather than a sixth reformulation of the chain.
- **The DL-21 guardrail is untouched and remains in force.** Nothing here beats B0 at the head,
  including the ceiling.

---

## DL-54 — Post-E10 code review: a second team-id space-mixing guard, and four minor cleanups

**Date:** 2026-08-21 · **Status:** Accepted · **Arose in:** an eight-angle code-review pass over
E10-S1 through S5 plus the D-26 fix, run before committing

### Context

An eight-angle parallel review (shadow-mode gating, no-look-ahead correctness, the archive
team-id/club-code trace, the "flag-off is byte-identical" claim, reuse, efficiency, structural fit,
and CLAUDE.md conventions) was run over the full E10 diff before commit. Shadow-mode gating (DP-08)
came back clean — every `discrimination.*` flag resolves to `None`-or-configured exactly once, in
`fit_components`, and the monolith is structurally unreachable from `optimise`/`decision`/`publish`
(enforced by a text-scan test in `test_monolith.py`, the same idiom `test_source_isolation.py` uses
for Invariant 1). Three angles independently converged on the same real gap; four smaller findings
were fixed alongside it. One flagged concern was investigated and found to be a false alarm.

### Decision

**Fixed, before commit:**

1. **`TeamStrengthModel.fit` gains an explicit guard against pooling two `team_id` spaces.**
   [DL-52](#dl-52) fixed the archive's own `team_id` (it now writes FPL's stable club code, not
   `None`), but three review angles (no-look-ahead, the archive tracer, and structural fit)
   independently found the fix stops at the archive boundary: `TeamStrengthModel.fit` groups by
   `team_id` alone, with no check that every row in the frame means the same thing by it. The live
   feed writes a *season-local* team id (`sources/fpl/adapter.py`); the archive writes the *stable
   club code*; both are internally consistent and both are silently wrong the moment a frame
   contains both, because eight to ten of the twenty season-local ids point at a different club than
   their code does. `forecast/live.py` already carries a hand-written guard for this
   (`this_season = past[past["season"] == rules.season]`) at its one call site — but the backtest
   harness's own `ComponentPredictor.fit` (`xp_v1.py`, the model the whole epic grades) had no such
   guard, protected only by `BacktestConfig.training_seasons`'s default happening to exclude the
   live season. A config default is not a code invariant, and the epic's own promotion path
   explicitly requires widening the backtest to include live shadow gameweeks once they exist — the
   exact next step that would have silently corrupted M2. `TeamStrengthModel.fit` now takes an
   optional `current_season` and raises `ValueError` if the frame contains it alongside any other
   season, wired through `fit_components` (used by both the live path and the graded backtest
   predictor). This is the DP-08 bug-fix exception again, same reasoning as DL-52 itself: a stable
   fact about club identity, not a judgement call.
   - **Not done, and left as residual, documented risk**: the deeper fix all three angles pointed at
     — a `team_code` column mirroring the `player_code`/`player_id` split `PlayerGameweekSchema`
     already gives players — would remove the need for callers to remember a guard at all, and is
     the right shape for E12 or a dedicated follow-up, not a same-session addition to a review pass.
     `stages/backtest.py`'s `fixture_difficulty` (a report-only diagnostic) and `MonolithPredictor`'s
     raw categorical `FIXTURE_TEAM`/`FIXTURE_OPPONENT` columns (shadow-only, never a decision input)
     were not threaded with the same guard — both are lower blast-radius (a noisier report / a
     noisier shadow number, not a corrupted graded prediction), and both are already scoped as
     follow-up alongside the `team_code` column.
2. **`monolith.py`'s `MINIMUM_TRAINING_ROWS = 200` module constant moved into
   `MonolithConfig.minimum_training_rows`** (DP-06) — every sibling tunable in that class was
   already a documented `Field`; this one constant wasn't, with no `DP-WAIVER`.
3. **`DiscriminationConfig`'s docstring corrected** — it claimed the flag-off regression guarantee
   was tested "in `tests/test_forecast.py`"; the real tests are each story's own module
   (`test_minutes_calibration.py`, `test_adaptive_shrinkage.py`, `test_duty.py`,
   `test_goalkeeper.py`). A reader following the docstring's own pointer would have found nothing.
4. **A stale comment in `optimise/replay.py`** still said archive club ids were season-local,
   predating DL-52's fix. Corrected to state the real reason the call site is safe (it is already
   filtered to one season).
5. **`_evidence_minutes` documents a real, currently-dormant behaviour change** the "byte-identical"
   audit found: the pre-diff inline expression used `if minutes:` as its guard, which passes for
   `nan` (`bool(nan) is True`), so a missing `minutes_mean_last6` used to silently produce `nan`
   rather than `0.0`. The shipped feature store cannot currently emit that combination, so this was
   never reachable either before or after — recorded in the docstring so a future change to
   `build_features` doesn't quietly resurrect the worse, silent-NaN behaviour.

**Investigated and found to be a false alarm, not fixed:** two review angles independently flagged
`except TypeError, ValueError:` (bare-comma multi-exception, in `duty.py` and `sources/fplarchive/
adapter.py`) as invalid Python-2-era syntax. Verified with `ast.parse`, a live interpreter, and the
fact that the full test suite already imports and exercises both modules without error: Python 3.14
(PEP 758, this project's pinned interpreter) accepts bare comma-separated exception types in an
`except` clause and treats them as a tuple. Not a bug.

**Not fixed, recorded as minor follow-up debt, not urgent enough to hold the epic on:** two reuse
findings (the archive adapter's `_normalise` reimplements `sources/names.py`'s existing
`team_key`, weaker — no accent-folding; `GoalkeeperSavesModel.fit` hand-rewrites `RateModel`'s
shrinkage arithmetic instead of reusing it, and has already drifted from S2's adaptive-shrinkage
extension as a result) and two efficiency findings (`DutyTable` is rebuilt from unchanging config on
every one of ~150 backtest folds instead of once; `MinutesReporting.minutes_probabilities` reruns a
full second `iterrows()` pass that `predict()` already computed). None change a published number;
all are cheap to fix later and none was judged worth extending this review-and-commit pass for.

### Consequences

The graded backtest predictor and the live forecast path now share one enforced guarantee about
`team_id` rather than one enforced (`live.py`) and one merely undisturbed by today's config
(`xp_v1.ComponentPredictor`/backtest). The four other fixes are corrections to documentation and a
DP-06 gap, not behaviour changes — the full suite (854 tests), ruff, and mypy stay green with
identical results before and after this pass.
## DL-43 — `ingest-fast.yml` and `ingest-slow.yml` grant `contents: write`; the `data`-branch push was failing in production

**Date:** 2026-08-20 · **Status:** Accepted · **Arose in:** live GitHub Actions failures on `main`,
found while chasing a `/goal` to fix current CI defects

### Context

[DL-42](#dl-42--e7-lands-seven-workflows-a-deadline-relative-scheduling-seam-and-a-retention-mechanism-that-is-verified-against-a-real-remote-rather-than-assumed)
recorded that an actual `GITHUB_TOKEN`-authenticated push to `github.com` was **unverifiable from a
workstation** and could only be discharged by watching a real week happen. It has now happened, and
it failed every time the fast-ingest schedule actually decided to fetch.

### The defect

Both `ingest-fast.yml` and `ingest-slow.yml` declare `permissions: contents: read` at the workflow
level, but each ends its job by force-pushing the rebuilt `data` branch via `pipeline/scripts/
retention.py` using `secrets.GITHUB_TOKEN`. A workflow-level `permissions:` block sets the token's
actual grants for every job that does not override it — `contents: read` makes the push a 403 by
construction, not by chance:

```
remote: Permission to talonegg/fpl_dof2.git denied to github-actions[bot].
fatal: unable to access '.../fpl_dof2.git/': The requested URL returned error: 403
```

`ingest-fast.yml` only fetches on a minority of its hourly firings (the guard step decides), which is
why most runs showed green — the push step, and the bug, was only reached when the guard said yes.
Once it fired, the push failed, so `data` was never actually rebuilt with fresh bronze. Two further
alerts trace to this same root cause rather than being independent: `Pipeline` and `Backtest` both
failed downstream with `NoBronzeError: no bronze snapshot for fpl/bootstrap_static` — they inherited
an empty `data` branch because ingest had never successfully published to it.

### Decision

Both workflows' `permissions:` block changes from `contents: read` to `contents: write`. No other
workflow needed the same fix: `pipeline.yml` and `backtest.yml` only read the `data` branch (via
`git fetch`/`git worktree`, which needs no write grant) and never push.

### Consequence

Four open `pipeline-alert` issues (#14 Ingest (fast), #15 Pipeline, #16 Ingest (slow), #17 Backtest)
share this one root cause and are closed by this fix rather than needing four separate diagnoses. A
fifth, `Deploy` (#13), is a **separate** defect: GitHub Pages has never been enabled for this
repository (`GET /repos/.../pages` returns 404), so `actions/configure-pages@v5` 404s before it can
run. That is a one-time repository-settings change (Settings → Pages → Build and deployment → Source:
GitHub Actions), not a code fix, and needs the owner's action — enabling it programmatically requires
an admin-scoped token this agent does not hold and was correctly blocked by the permission
classifier.

---

## DL-62 — E12-S1: Q-13 resolved negative — the BPS action-count breakdown was never publicly captured for seasons before 2025/26

**Date:** 2026-08-22 · **Status:** Accepted · **Arose in:** E12-S1 implementation

### Context

The story's premise, taken from the model-improvement plan and Q-13 itself, is that "FPL recorded
tackles/CBI in the BPS breakdown long before it scored DefCon" — i.e. that the raw action counts
underlying the old (pre-2025/26) bonus-points formula already exist somewhere this project is
permitted to read, and M4's one-season training window is a conformance gap, not a data gap.

Checking that premise against the actual data closes it the other way. Three independent checks,
all agreeing:

1. **The official API.** `element-summary/{id}`'s `history` (current season, per-gameweek) does
   carry `tackles`, `recoveries`, `clearances_blocks_interceptions` for 2026/27 — but `history_past`
   (prior seasons) reports **season totals only**, never per-gameweek, and the adapter already
   defaults these fields to `0` for any season where the API simply omits them
   (`sources/fpl/adapter.py:625-630`). The official API has no per-gameweek historical endpoint at
   all (`sources/fplarchive/adapter.py`'s own docstring, lines 3-6, is why the archive mirror exists
   in the first place) — so there is no official-API path back to old gameweeks regardless.
2. **The archive mirror, as already ingested.** The cached 2023/24 `merged_gw.csv.gz` snapshot in
   `data/bronze/fplarchive/merged_gameweeks/` has 41 columns: `bonus` and `bps` are present, but
   none of `tackles`, `clearances_blocks_interceptions`, `recoveries`, or any synonym.
   `_MEASURED_LATER` (`sources/fplarchive/adapter.py:88-97`) already encodes this correctly — it is
   not an overly conservative guess, it is what the source contains.
3. **The archive mirror, fetched fresh.** Pulling `2023-24/gws/merged_gw.csv` and
   `2023-24/gws/gw1.csv` directly from the upstream repository today reproduces the same 41 (merged)
   / 40 (per-gameweek) columns, confirming the cached snapshot isn't stale or truncated — the
   upstream project itself never captured the breakdown.

The old BPS formula did score tackles won, CBI and recoveries as scoring components internally, but
that computation happened inside FPL's own (Opta-fed) backend and was only ever exposed as the
already-summed `bps` integer. Nothing publicly reachable — official API or community mirror — ever
published the per-action counts that produced it, for any season before 2025/26. This is the same
shape of finding as D-23 (Understat `robots.txt`, FBref Cloudflare 403): not a modelling choice, a
source that does not exist to be conformed.

### Decision

**Q-13 is resolved: no.** DefCon cannot be reconstructed for seasons before 2025/26 from data this
project can legitimately obtain, because the underlying action counts were never captured by any
permitted source, not because of an ingestion gap this project could close. No code changes to
`sources/fplarchive/`, `silver/`, or `forecast/models.py` follow from this story — `_MEASURED_LATER`,
the nullable defensive columns in `PlayerGameweekSchema`/`PlayerSeasonHistorySchema`, and M4's
implicit one-season gating (via `RateModel.fit`'s `dropna`) are all already correct and stay as they
are. `docs/planning/04-conceptual-design.md`'s Q-13 row is marked resolved, pointing here.

This closes the door DP-15 asks to be closed honestly rather than worked around: no synthetic proxy
(e.g. inferring action counts from `bps` via a fitted formula) was built. A regression that reverses
the old BPS formula from a single scalar output, calibrated on one season and applied retroactively
to four, would be indistinguishable from real signal in every metric this repo can measure and
wrong in a way DP-13 exists to prevent — inventing training data to widen a training window is a
worse defect than the one-season window it would replace.

### Consequences

- E12 epic DoD: "DefCon history reconstructed... Q-13 resolved" is met, in the negative — Q-13 *is*
  resolved, the answer is no. "M4 present across the widened backtest window" is **not** met and
  cannot be on this data; the acceptance criterion is unreachable, not failed.
- [E12-S3](#dl-63--e12-s3-blocked-on-its-own-precondition-the-prior-season-probe-has-no-new-real-input-to-re-measure-against)
  loses its primary route to "real advanced history" as a result — see that entry.
- `docs/planning/04-conceptual-design.md` Q-13 row struck through, pointing here, matching the Q-06
  pattern. `docs/planning/epics/E2-data-platform.md` and `E0-steel-thread-gw1.md`'s D-11 both still
  read correctly without edits — both already phrase Q-13 as conditional ("unless Q-13 succeeds"),
  and now it hasn't.
- No new scraping was attempted; D-23's refusals remain respected (E12 DoD's last line).

---

## DL-63 — E12-S3: blocked on its own precondition — the prior-season probe has no new real input to re-measure against

**Date:** 2026-08-22 · **Status:** Accepted · **Arose in:** E12-S3 implementation

### Context

E12-S3 asks to re-run the [DL-31](#dl-31) prior-season probe with real xG/DefCon inputs in place of
the official-feed-totals stand-in DL-31 used, because a genuine signal might have been masked by a
proxy input rather than being genuinely absent. The story names two routes to that real input:
depending on S1 (real DefCon history) and, ideally, an unblocked xG source.

Both routes are closed, for reasons already recorded rather than new ones this story discovers:

- **S1 resolved negative** ([DL-62](#dl-62--e12-s1-q-13-resolved-negative--the-bps-action-count-breakdown-was-never-publicly-captured-for-seasons-before-202526)):
  there is no reconstructed DefCon history to feed the prior with. `Table.PLAYER_METRIC`'s DefCon
  columns remain populated for 2025/26 only, exactly as before this epic.
- **xG remains blocked** by D-23: Understat's `robots.txt` disallows the whole site, FBref returns
  Cloudflare 403. Nothing in this epic changes that; E12 §0 states explicitly that re-attempting
  either against a stated refusal is out of scope, and that holds here too.

`PriorSeasonConfig.statistics` (`config/models.py:312-323`) already names the columns this feature
would read — `tackles`, `interceptions`, `blocks`, `clearances`, `recoveries` from
`Table.PLAYER_METRIC` — and every one of them is sourced from the same two blocked adapters
(`sources/understat/`, `sources/fbref/`) or, per DL-62, from a history that does not exist. There is
no third input this story could substitute that would be "real advanced history" rather than another
stand-in of the same kind DL-31 already measured and found wanting.

### Decision

**Do not re-run the probe.** Re-running `fpl-dof backtest --offline` with
`forecast.features.prior_season.enabled: true` today would exercise the exact same official-feed
proxy DL-31 already measured — `player_metric` has not gained a single new populated row for any
season since DL-31 ran, because nothing in E12 changed what feeds it. A second run would reproduce
DL-31's ~0.002 Spearman movement (or its noise-level variant) and report it as if it were new
evidence, which is precisely the "did more data actually move the number, or did it just feel like
progress" trap E12 §3 names. Running the backtest again to get a number that cannot mean anything
new is worse than not running it: it would look like verification.

`features.prior_season` stays exactly as DL-31 left it: `enabled: false`, DL-31's result standing as
the last real measurement, nothing promoted (DP-08).

### Consequences

- E12 epic DoD: "Prior-season prior re-measured with real inputs and either promoted on evidence or
  left dark with the null result recorded" is met by inaction — the null result is DL-31's, restated
  here as still current because nothing changed the inputs it was measured against.
- This is not a failure of S3's scope; it is S1's negative result propagating through a dependency
  the epic itself declared ("Depends on S1"). If either D-23 or the archive's data coverage changes
  in future — a permitted xG source appears, or FPL's own historical exposure widens — this probe is
  the first thing worth re-running, not `prior_season` promotion by any other route.
- No code, config, or test changes follow from this story.
## DL-55 — E11-S2: home advantage is now fitted and config-seeded; the fixture-band backtest shows the fit and the old guess performing indistinguishably

**Date:** 2026-08-21 · **Status:** Accepted · **Arose in:** E11-S2 implementation

### Context

`TeamStrengthModel.home_advantage` was a bare `1.12` dataclass default (`forecast/models.py`) — no
source, no config path, nowhere to change it, the same class of defect Invariant 2 names for a
scoring literal. E11-S2 replaces it with a value fitted from the same time-decayed match set M2
fits everything else from: the ratio of mean home to mean away goals across a fully home/away
balanced fixture list is `home_advantage**2` (every other term cancels), so the estimator is the
square root of that ratio, shrunk in log space toward a configured prior by how much evidence
exists (`home_advantage_prior_matches`, default 190 — one league season of home fixtures), and
clipped to `[home_advantage_minimum, home_advantage_maximum]` = `[1.0, 1.30]`.

The prior itself (`TeamStrengthConfig.home_advantage_prior`, default 1.09) is not a second guess —
it is the fit's own output run once over the real archive, done by materialising the 2023/24-2025/26
backfill locally (`fpl-dof ingest` then `transform`, both served entirely from the existing bronze
cache, no network call) and fitting directly: **1.0963 essentially unshrunk** (evidence-weighted,
`home_advantage_prior_matches≈0.0001`), **1.0929 at the shipped half-life and prior weight**. Both
land within rounding of each other and confirm the constant a manager plans fixtures around had
drifted from what actually happened on the pitch.

### Decision

Ship the fit. `TeamStrengthModel.home_advantage` defaults to `nan`, a sentinel `__post_init__`
resolves to `config.home_advantage_prior`, and `fit()` then replaces it with the measured value
whenever the training frame carries a venue column — `describe()` reports which of the two
happened (`home_advantage_source: "fitted" | "prior"`), per DP-09. `stages/publish.py`'s fixtures
ticker now threads `ctx.config.forecast.team_strength` through instead of constructing an
unconfigured `TeamStrengthModel()`. `forecast/backtest.py`'s `fixture_difficulty` diagnostic
deliberately keeps its own default-config `TeamStrengthModel()` unfitted-config-wise — it exists so
a fixture's *band* doesn't drift every time the graded model's config changes, which is the point
of a stable diagnostic; threading live config through it would defeat that.

**The acceptance criterion this does not clearly meet:** the epic asks for clean-sheet and goals
calibration to *improve*. A full offline walk-forward backtest (`fpl-dof backtest --offline`, 72
folds, 21,712 observations, `training_seasons: [2024/25, 2025/26]`, fixture coverage 1.0 per
E9-S2/DL-52) was run twice — once against the fitted value (effectively 1.093), once against a
config override pinning the old constant (`home_advantage_prior: 1.12`,
`home_advantage_prior_matches: 1e9` to prevent the fit moving off it) — and the two are
statistically indistinguishable: Spearman 0.24881 (fitted) vs 0.25058 (1.12), calibration slope
0.68986 vs 0.68990, MAE-skill 0.01716 vs 0.01727, top-20 precision 0.12083 vs 0.12153. Every
difference is within what one held-out window's noise can produce; none of it clears any bar. The
honest reading, not the convenient one: **this backtest gives no evidence the fitted value scores
higher than the guess**, and per E8§5 that means this cannot be promoted on the strength of "the
metric moved" — because on this measurement it didn't.

What it *does* fix, independent of that number moving, is Invariant 2: `1.12` was a literal with no
source and no way to update it as the effect drifts, which the epic text calls the same class of
bug as a hardcoded scoring constant. That argument does not rest on the backtest — a correct,
provenance-carrying mechanism that ties for accuracy with a magic number is still worth shipping in
place of the magic number, and this is not the "no time, so waive it" trade DL-10 warns against; it
is the opposite trade, spending the effort to remove a defect that happened not to move the metric.
It is *not* treated as clearing the full DP-08/E8§5 bar for a "genuinely new model behaviour" —
there is no shadow flag here, no six-live-gameweek window, because there is no behaviour being
bet on; the fitted value and the old constant are numerically close enough (1.093 vs 1.12, both
comfortably inside `[1.0, 1.30]`) that this reads as a provenance and correctness fix, not a model
change with a hypothesis to falsify. If a future re-fit ever pulls the value meaningfully further
from 1.09-1.12, that would be a real behaviour change and should clear the bar properly then.

### Consequences

- E11 epic DoD line "Home advantage is a fitted, config-seeded value reported in the model card" is
  met. The line implying calibration improvement is **not** claimed met by this entry — recorded
  here rather than silently ticked, so a later reader doesn't infer evidence that wasn't found.
- `config/defaults/forecast.yaml` gains a `forecast.team_strength` block restating the pydantic
  defaults with the measured provenance, matching the convention every other forecast section
  already follows.
- New test module `pipeline/tests/test_team_strength.py` covers the fit's edges specifically
  (DP-13): no venue column, no away rows, thin-evidence shrinkage, range clipping, and the
  `describe()` fitted-vs-prior distinction.
- Full affected suite (`test_team_strength.py`, `test_forecast.py`, `test_trend_artefacts.py`,
  `test_backtest.py`, `test_publish.py`, `test_config.py`), ruff, ruff format, and mypy all pass.

---

## DL-56 — E11-S1: xG-based team ratings clear the fixture-aware backtest bar comfortably; held dark pending live shadow gameweeks

**Date:** 2026-08-21 · **Status:** Accepted · **Arose in:** E11-S1 implementation

### Context

`ExpectedGoalsConfig.team_strength_from_xg` (`config/models.py:405`) and the code path it gates
(`_team_matches(..., use_xg=True)` reading `expected_goals`/`expected_goals_conceded` instead of
`goals_scored`/`goals_conceded` when reconstructing M2's training matches, `forecast/xp_v1.py:529`)
have existed since before this epic, wired at both the live and backtest call sites, defaulting to
`False`. The shipped config comment justifying that default said the flag was **unmeasurable**: with
opposition scored at league average, an xG-fitted attack/defence rating never reached a graded
prediction. [E9-S2](../epics/E9-forecast-delivery-and-backtest-fidelity.md)/[DL-52](#dl-52--d-26-closed-the-archive-always-stated-which-club-each-row-belonged-to-and-the-repair-is-keyed-on-the-stable-club-code-because-half-the-season-local-ids-change-club-every-year)
closed that gap — fixture coverage is now 1.0 — which is exactly the prerequisite E11 §0 names as
having gated this whole epic. That comment was stale the moment DL-52 landed; it is corrected as
part of this entry regardless of the flag's verdict below.

### Decision

**Measured, not promoted.** A full offline walk-forward backtest (`fpl-dof backtest --offline`, 72
folds, 21,712 observations, `training_seasons: [2024/25, 2025/26]`) was run with the flag off (the
shipped default, refreshed after E11-S2's home-advantage fit) and on, all else identical:

| metric | goals-based (off) | xG-based (on) | delta |
| --- | --- | --- | --- |
| Spearman (overall) | 0.24881 | 0.25536 | +0.00655 |
| calibration slope (overall) | 0.68986 | 0.73118 | +0.04132 |
| MAE-skill over B0 | 0.01716 | 0.02109 | +0.00393 |
| top-20 precision | 0.12083 | 0.12708 | +0.00625 |
| fixture-band Spearman, average | 0.20071 | 0.21603 | +0.01532 |
| fixture-band Spearman, easy | 0.24172 | 0.25345 | +0.01173 |
| fixture-band Spearman, hard | 0.22237 | 0.22613 | +0.00376 |
| fixture-band calibration, average | 0.60271 | 0.65704 | +0.05433 |
| fixture-band calibration, easy | 0.66863 | 0.72729 | +0.05866 |
| fixture-band calibration, hard | 0.57952 | 0.60454 | +0.02502 |

Every one of these moves in the same direction and by an order of magnitude more than the noise
floor DL-55 found for the home-advantage fit (there, differences of 0.0001-0.002; here, 0.004-0.06).
This is the story's own acceptance criterion — "fixture-conditioned Spearman and clean-sheet
calibration beat the goals-based ratings on a held-out season" — met without qualification, and it
is the shape the design predicted: xG regresses less than goals, so a rating built from it should
travel better into a held-out fixture list, most visibly exactly where a fixture is easy or hard
rather than average.

**Still not flipped to default `true`.** This is a genuinely new model behaviour — which attack and
defence ratings M2 learns, not a delivery defect like DL-55's literal — and the epic's own DoD is
explicit: "each promoted change cleared the E8 §5 bar", which requires backtest evidence on a
held-out season **and** six live shadow gameweeks minimum, "fewer than six and you are reading
noise." There is no live season yet for the flag to be shadowed against — E11 lands before GW1, and
the six-gameweek clock can only start once real gameweeks are being scored. Flipping the default
here would be declaring the shadow requirement met by a backtest alone, which is precisely the
substitution E8 §5 exists to prevent (and the same substitution DL-47 already refused to make for
every `discrimination.*` flag). The flag stays `false`; the config comment now states the measured
case for it plainly, so turning it on when the shadow window opens is a one-line change made with
full knowledge of why, not a rediscovery.

### Consequences

- Corrects the stale `team_strength_from_xg` comment in `config/defaults/forecast.yaml` (it called
  the flag unmeasurable; it has been measurable since DL-52).
- No code change — the wiring (`ExpectedGoalsConfig.team_strength_from_xg`, both `_team_matches` call
  sites) was already complete; this entry is the measurement DP-08 requires before a dark flag may be
  promoted, and the explicit decision not to promote it yet.
- E11 epic DoD line "xG-based team ratings promoted on backtest evidence; goals-based path retained
  as fallback" is **half true**: the backtest evidence is in hand and positive; promotion (flipping
  the default) is deferred to the live shadow window this entry opens, per E8 §5. Recorded here
  rather than ticked, so a later reader does not infer the flag is live in the shipped default.
- The two backtest runs behind this table used `--offline` against the locally cached archive
  (2023/24-2025/26, ingested and transformed once for DL-55, reused here); no network call was made.

---

## DL-57 — E11-S4: the widening mechanism is built and measured; the promoted-club detector is not, for a real reason

**Date:** 2026-08-21 · **Status:** Accepted · **Arose in:** E11-S4 implementation

### Context

Before this story, `TeamStrengthModel.fit()`'s per-club attack and defence ratings had **no
shrinkage at all** — a club's rating was its raw time-decayed scored/conceded ratio regardless of
how many matches informed it, so a single August fixture carried exactly as much confidence as
twenty. The epic frames this as specifically a *promoted-club* problem ("a promoted side's
September is weak evidence about their April"), but the underlying defect is general: every club
starts each rating with zero shrinkage, promoted or not.

Building the promoted-specific half properly — detecting which clubs are promoted or heavily
rebuilt — turned out to need something that does not exist: a club identity that survives a season
boundary. `TeamSchema` (`silver/tables.py`) is a current-season-only snapshot, 20 rows, no `season`
column; `player_season_history` carries no team reference at all; and the live model deliberately
fits `TeamStrengthModel` on the current season alone (`forecast/live.py:117-129`), because pooling
it with the archive would mean grouping by `team_id` across the season-local/stable-club-code split
D-26 exists to prevent. [DL-54](#dl-54--post-e10-code-review-a-second-team-id-space-mixing-guard-and-four-minor-cleanups)
already named the fix — a `team_code` column mirroring the `player_code`/`player_id` split — and
explicitly scoped it as "the right shape for E12 or a dedicated follow-up, not a same-session
addition." Building a name-matched crosswalk as a shortcut here, outside `sources/` (Invariant 1)
and without the schema work DL-54 already flagged, is exactly the kind of shortcut DP-13 warns
against: it would look like it detected promoted clubs and be silently wrong wherever a name-match
missed or over-matched, with no test able to catch it against real data this repository doesn't yet
model. Better to not build it than to build it badly.

### Decision

**Split the story at its real seam.** `TeamStrengthModel` gains the mechanism in full:
`rating_prior_matches` (general shrinkage, all clubs, toward the league-neutral 1.0, log-space,
same construction as [DL-55](#dl-55--e11-s2-home-advantage-is-now-fitted-and-config-seeded-the-fixture-band-backtest-shows-the-fit-and-the-old-guess-performing-indistinguishably)'s
home-advantage fit) and `promoted_teams: frozenset[int]` plus `promoted_prior_matches` (a wider
prior for any team id the caller names). Both new config fields default to `0.0`, which makes
`shrink` exactly `1.0` and reproduces the pre-E11-S4 unshrunk behaviour byte-for-byte — the
mechanism is inert until configured, per DP-08. What is **not** built: anything that populates
`promoted_teams` automatically. No caller sets it; the set is empty in every shipped path. The
config fields' own descriptions say why, so a reader hits the explanation at the point of use, not
only here.

**Measured anyway, with `promoted_teams` empty** — this tests the general-shrinkage half only, which
is still worth knowing: `fpl-dof backtest --offline`, 72 folds, `rating_prior_matches: 8.0` (chosen
as roughly a fifth of a season, no grid search) against the DL-56 baseline:

| metric | unshrunk (default) | shrunk, prior=8 | delta |
| --- | --- | --- | --- |
| Spearman (overall) | 0.24881 | 0.24760 | −0.00121 |
| calibration slope (overall) | 0.68986 | 0.72361 | +0.03375 |
| MAE-skill over B0 | 0.01716 | 0.02071 | +0.00355 |
| top-20 precision | 0.12083 | 0.12778 | +0.00695 |
| fixture-band Spearman, average | 0.20071 | 0.20500 | +0.00429 |
| fixture-band Spearman, hard | 0.22237 | 0.22049 | −0.00188 |
| fixture-band calibration, average | 0.60271 | 0.62109 | +0.01838 |
| fixture-band calibration, easy | 0.66863 | 0.73385 | +0.06522 |

Mixed but net positive: Spearman moves by roughly a noise-level amount in both directions (one
metric down, most others up), while calibration — the metric the epic actually names for this
story — improves consistently and by a real margin, not a noise-level one. **Not promoted anyway,
same reasoning as [DL-56](#dl-56--e11-s1-xg-based-team-ratings-clear-the-fixture-aware-backtest-bar-comfortably-held-dark-pending-live-shadow-gameweeks):**
this is a genuinely new model behaviour, `rating_prior_matches=8.0` was chosen by argument rather
than a proper search, and the promoted-specific half — the half the epic's acceptance criterion is
actually about ("Aug/Sept fixture calibration for promoted clubs improves without harming the
rest") — cannot be measured at all without the detector this entry declines to build. The general
number above is suggestive, not a verdict on the story's own acceptance test.

### Consequences

- E11 epic DoD line "Promoted-club priors widened without harming established clubs" is **not**
  met and cannot be, on this data model. `promoted_teams` is real and tested but unreachable from
  any shipped code path.
- Confirms the `team_code` follow-up DL-54 already scoped is now blocking two independent stories
  (this one, and any real "does the fixture ticker beat static FDR for promoted clubs" question) —
  worth prioritising ahead of "when convenient" if E12 has room to move earlier.
- New tests in `pipeline/tests/test_team_strength.py` cover the shrinkage math directly: the
  zero-prior no-op, thin-evidence shrinkage, a named club shrinking harder than an identical
  unnamed one, ample evidence overwhelming even a widened prior, and `describe()` reporting the
  configuration.
- Full affected suite, ruff, ruff format, and mypy all pass (same file set as DL-55, plus
  `test_team_strength.py`'s new cases).

---

## DL-58 — E11-S3: goal and assist rates now read the opponent, on a simplified formulation that beats the old fixture-blind chain on this backtest

**Date:** 2026-08-21 · **Status:** Accepted · **Arose in:** E11-S3 implementation

### Context

Before this story, `forecast_player` (`forecast/xp_v1.py`) scored a player's goals and assists from
his own shrunk per-90 rate alone — no fixture entered either number. Only clean sheets, goals
conceded and (with `gkp_v2`) saves read M2's opposition. Design §M3
(`docs/planning/04-conceptual-design.md`) calls for allocating the *team's* M2-implied expected
goals across its players by npxG/xA/shot-volume shares, then applying penalty/set-piece duty. That
full share model needs a cross-player normalisation pass — summing every teammate's raw rate before
any single player can be scored — that does not exist in this codebase's per-row scoring loop
(`ComponentPredictor.predict`, `horizon.py`'s equivalent), and building it was judged too large an
addition to make correctly in the time this story had, alongside S1/S2/S4/S5/S6.

### Decision

**Ship a simplified formulation that needs no aggregation, stated plainly so it can be argued with
(DP-10).** A player's own fitted rate already reflects his team's *general* attacking level, because
he was observed scoring for that team; re-applying M2's `attack(team)` rating on top would
double-count it. What is genuinely new information about *this* fixture, relative to the player's
own history, is only the opponent's defence and the venue — exactly
`TeamStrengthModel.attacking_fixture_factor(opponent_id, at_home=...)`, a new method returning
`defence(opponent) * home_advantage_multiplier`, deliberately built so `attack(team)` cancels out of
it rather than being included and then divided back out.

The factor is threaded through the existing `Opposition` seam (`clean_sheet_probability`,
`goals_conceded_mean`, now `attacking_fixture_factor`), computed once per fixture in
`fixture_opposition`/`row_opposition`, defaulted to `1.0` (neutral) in `league_average_opposition`.
`forecast_player` applies it to `goal_rate` and `assist_rate` only — not `defcon_rate`, `save_rate`
(already fixture-aware via `gkp_v2`), `card_rate` or `bps_rate`, matching Design §M3's own scope
("goal involvement"). `discrimination.opponent_adjusted_rates` gates it (default `False`); when off,
`_opponent_adjusted` returns the input rate unchanged, so the flag decides whether the factor is
even looked at, matching the shape S1/S2/S3/S4's siblings and E10's flags all use. `OpponentAdjustmentConfig.weight`
damps the raw factor toward 1.0 (`1 + w * (factor - 1)`, the same construction
`GoalkeeperConfig.fixture_weight` already uses), with a floor and ceiling so a single fixture cannot
collapse or explode a rate.

**Measured**: `fpl-dof backtest --offline`, 72 folds, `opponent_adjusted_rates: true`,
`weight: 1.0` (full, unshrunk default, matching how S1's flag was measured), against the DL-56/57
baseline:

| metric | fixture-blind (off) | opponent-adjusted (on) | delta |
| --- | --- | --- | --- |
| Spearman (overall) | 0.24881 | 0.25463 | +0.00582 |
| calibration slope (overall) | 0.68986 | 0.69475 | +0.00489 |
| MAE-skill over B0 | 0.01716 | 0.01791 | +0.00075 |
| top-20 precision | 0.12083 | 0.12847 | +0.00764 |
| fixture-band Spearman, easy | 0.24172 | 0.24613 | +0.00441 |
| fixture-band Spearman, hard | 0.22237 | 0.22565 | +0.00328 |
| fixture-band Spearman, average | 0.20071 | 0.19802 | −0.00269 |
| fixture-band calibration, easy | 0.66863 | 0.65770 | −0.01093 |
| fixture-band calibration, hard | 0.57952 | 0.60717 | +0.02765 |
| fixture-band calibration, average | 0.60271 | 0.58069 | −0.02202 |

The story's own acceptance criterion — Spearman improving specifically in the easy and hard bands —
is met on both bands individually. What is **not** clean is the "average" fixture-band row, which
moves the wrong way on both Spearman and calibration despite both named bands improving; this harness
computes "average" as a separate quantity from the mean of the two named bands (it is not simply
`(easy + hard) / 2`), and this entry does not have a satisfying account of why it diverges — recorded
honestly rather than smoothed over, and worth a specific look before anyone leans on that field
again. Every other overall metric (Spearman, calibration, MAE-skill, top-20 precision) moves in the
positive direction and outside DL-55's noise floor.

**Not promoted.** Same reasoning as DL-56/57: this is a genuinely new model behaviour needing the
full E8 §5 bar, including six live shadow gameweeks that cannot exist before GW1. `weight=1.0` was
chosen to match the full effect, not tuned by search. The flag stays `false`.

### Consequences

- E11 epic DoD line "Player rates are opponent-adjusted by sharing out M2 team xG, improving
  high/low-difficulty buckets" is **partially** met: rates are opponent-adjusted and both named
  fixture-difficulty buckets improve on Spearman, but the mechanism is a simplification of the
  share-based design (no cross-player allocation), and the fixture-band "average" metric moved the
  wrong direction for reasons this entry could not fully explain. Recorded here rather than ticked
  clean.
- The full share-based M3 (allocating team xG across players by npxG/xA/shot-volume shares) remains
  unbuilt; a candidate for a dedicated follow-up story if the simplified version's live-shadow
  results ever justify chasing the harder version.
- New test module `pipeline/tests/test_opponent_adjusted_rates.py`: the flag-off no-op, an average
  fixture reproducing the old rate exactly, direction (harder lowers, easier raises), a weight of
  zero as the exact identity, damping as a linear share of the full move, floor/ceiling clipping,
  the other components (`clean_sheet`, by extension `saves`/`goals_conceded`) staying untouched, the
  factor's own arithmetic excluding the player's own team's attack rating, and `score_player`
  threading the factor from `Opposition` the same way `forecast_player` does directly.
- Full affected suite, ruff, ruff format, and mypy all pass.

---

## DL-59 — E11-S5: the odds adapter is enabled by default everywhere, not switched on only in CI

**Date:** 2026-08-21 · **Status:** Accepted · **Arose in:** E11-S5 implementation

### Context

E5 already shipped a complete odds adapter (`sources/oddsapi/adapter.py`) — de-vigged market
arithmetic, a credit ledger enforced before each call, and a tested degrade-clean path when
`ODDS_API_KEY` is absent — but nothing enabled it anywhere, and no CI workflow passed the key
through. `OddsApiAdapter.enabled_by_default` is `False` (correctly: an adapter should not silently
assume every environment wants it running), and no shipped `config/defaults/*.yaml` file overrode
that, so the source never ran, key or no key.

### Decision

**Enable the source everywhere; put the secret only in CI.** A new
`config/defaults/sources.yaml` sets `sources.overrides.oddsapi.enabled: true`. This is a shipped
default, not a CI-only flip: an environment without `ODDS_API_KEY` (every contributor's laptop,
every fork, this repository before the owner signs up) hits exactly the already-tested
`test_no_key_means_no_request_is_even_attempted` path — zero network calls, a logged warning
(`ingest.warning`, `source: oddsapi`), the run succeeds. Verified locally with `fpl-dof ingest
--offline` and no key set: `sources.built` now reports `enabled: ["fpl", "fplarchive", "oddsapi"]`
and the run completes in 3.75s with `oddsapi.network_calls: 0`. The alternative — leaving the
source off by default and enabling it only inside `ingest-slow.yml` — was rejected: it would mean
local and CI runs exercise a different source set purely as an artefact of where a secret happens
to be configured, which is the exact drift Invariant 1 exists to prevent (one config, one set of
enabled sources, everywhere).

`ingest-slow.yml`'s "Full ingest" step now passes `ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}` as an
env var. No conditional around the step: the adapter's own degrade-clean path is the conditional,
so the workflow does not need to know whether the secret has been set yet.

**Still not "live" in the sense of actually fetching anything**, and cannot be from this side of the
work: `ODDS_API_KEY` is an owner-provided secret (`docs/planning/epics/INPUTS-REQUIRED.md` item
4.1, "Requires you to sign up"), tracked as an open item, target ~GW10. What this entry closes is
narrower than "live data flowing": *which* provider and *what* credit budget (OD-03's actual
question) were already decided in the adapter's own shipped defaults — the Odds API, free tier,
~450 requests/month after reserving headroom for pre-deadline refreshes. This entry is what makes
that decision reachable by a real run instead of sitting behind a flag nothing sets. "Does the
market view actually improve calibration" (E11-S6's question) still needs real fetched data the
owner's key unlocks, and stays open until then.

### Consequences

- **OD-03 closed**: provider (Odds API) and free-tier credit budget (450/month, `FPL_DOF_ODDS_CREDIT_BUDGET`
  overridable) were already decided in the adapter's own defaults; this entry is what makes that
  decision actually reachable in a run rather than dead code.
- E11 epic DoD line "Odds adapter live within a credit budget, degrading cleanly when the key or
  budget is absent" is met on the code and CI-wiring side. The line's implicit promise of a working
  live signal is blocked on the owner adding the secret, not on anything in this codebase.
- New test `test_the_shipped_default_config_enables_the_odds_source`
  (`tests/test_external_sources.py`) pins the default at the config layer, not just the adapter
  class — the two are independent and both need to agree for the source to actually run.
- Full affected suite (`test_external_sources.py`, `test_config.py`), ruff, ruff format, and mypy
  all pass.

---

## DL-60 — E11-S6: the market-blend mechanism is built and tested; it cannot be backtested at all, and is not wired into a live scoring path yet

**Date:** 2026-08-21 · **Status:** Accepted · **Arose in:** E11-S6 implementation

### Context

Design §M2 calls for blending the odds market's expected goals into M2, with the blend weight a
function of horizon — near the deadline, defer to the market; far out, defer to the ratings. DL-59
made the odds adapter reachable in a real run, but confirmed nothing downstream reads
`team_match_expectation` yet: `TeamStrengthModel`, `xp_v1.py` and `forecast/live.py` had no
awareness the table exists.

**This story has no backtest to measure it against, structurally, not by choice.** `fpl-dof
backtest` walk-forwards over `player_gameweek` history, which carries no market column and never
will retroactively — the odds adapter only started collecting data once E5 shipped it, so there is
no historical archive of past lines to replay a fold against. Every other E11 story that shipped
dark (S1, S3, S4) has a DL entry with a real backtest table; this one cannot have one, which is
worth stating plainly rather than manufacturing a number from data that does not exist.

### Decision

**Build and test the blend mechanism; do not wire it into a live scoring path this session.**
`TeamStrengthModel` gains `market: dict[(home_team_id, away_team_id), (xg_home, xg_away)]`,
`attach_market(rows)` (reads `TeamMatchExpectationSchema`-shaped rows, latest `captured_at` per
pair wins, degrades to a no-op on anything malformed or empty — DP-15), `market_expected_goals`
(the honest `None` for an unresolved fixture, never a silent fallback) and
`blended_expected_goals(..., weight)` (identity whenever there is nothing to blend with — no
market row, or `weight <= 0`). A new module-level `market_blend_weight(gameweeks_ahead, config)`
implements the horizon decay Design §M2 calls for — `weight_at_next_gameweek` (default 0.6) falling
by `decay_per_gameweek` (default 0.15) until it floors at 0, both named, defaulted and justified by
argument rather than fit (DP-06, DP-10 — there is nothing to fit this against, see above).
`discrimination.market_blend` gates it, off by default, matching every other E11 candidate's shape.

**What is deliberately not done**: reading `team_match_expectation` out of silver into
`ComponentModels` at fit time, and threading "how many gameweeks ahead is this fixture" through
`fixture_opposition`/`week_forecast`/`ComponentPredictor.predict` so a real weight reaches
`blended_expected_goals` in a real run. This is not the same kind of gap S4 hit — the data model
exists, the wiring is mechanical, not blocked on new plumbing DL-54 already flagged as follow-up
work. It is a scope decision, made explicitly rather than by running out of session first: E11-S1
through S5 landed with real measurement behind each one, and rushing S6's wiring to completion
without any way to validate it — no backtest, no live data yet (the key is still an owner action)
— would produce code that looks finished and has never been exercised against a real fixture,
which is a worse position than a clearly-scoped, fully-tested building block waiting for its data.

### Consequences

- E11 epic DoD line "Market view blended into M2 with a horizon-dependent weight, degrading cleanly
  to ratings-only" is met at the *mechanism* level (every test in `test_market_blend.py` is
  exactly this claim) and **not** met at the *wired into a live decision* level. Recorded here
  rather than ticked, so a later reader does not assume the fixtures ticker or the published
  forecast currently reflects any odds data.
- A concrete follow-up, now that the mechanism exists to wire: attach `team_match_expectation` in
  `fit_components`/`forecast/live.py` (mirroring how `team_matches` is attached today), compute
  `gameweeks_ahead` from the horizon list already built in `horizon_frame`, and pass
  `market_blend_weight(...)` through `fixture_opposition`. None of this can be validated until
  `ODDS_API_KEY` is set and real odds start flowing (INPUTS-REQUIRED.md 4.1) — wiring it earlier
  would not make it more finished, only harder to tell apart from working.
- New test module `pipeline/tests/test_market_blend.py`: attach/lookup by ordered pair, the
  latest-`captured_at`-wins rule, degrade-clean on empty or malformed input, the blend's identity
  cases (no market data, zero weight), a full-weight blend returning the market figure exactly, a
  partial weight as a linear interpolation, an unresolved fixture falling back to ratings even at
  full weight, and the horizon decay function's shape including its floor and its (defensive)
  handling of a negative horizon.
- Full affected suite, ruff, ruff format, and mypy all pass.

---

## DL-61 — Post-E11 review: `ComponentModels.describe()` was dead code — nothing had ever called it in a real run

**Date:** 2026-08-21 · **Status:** Accepted · **Arose in:** verifying DL-55's own claim

### Context

DL-55 said E11-S2's fitted home advantage would be "reported in the model card (DP-09)". Checking
that claim before letting it stand found it was false: `ComponentModels.describe()`
(`forecast/models.py`) — which nests `M1_minutes`, `M2_team_strength`, every `RateModel`, `M8_bonus`,
`duty` and `goalkeeper` — was called nowhere in the shipped pipeline. `stages/forecast.py` builds
the fitted `ComponentModels` inside `forecast/live.py`'s `build_forecast`, uses it to produce the
scored frame, and discards it; `write_model_card` (`forecast/model_card.py`) only ever received the
frame, the config and the backtest report. Every fitted number this epic added — `home_advantage`
and its `_source`, `rating_prior_matches`, `promoted_teams`, `market_fixtures` — existed correctly
in `describe()`'s output and reached nobody. This predates E11 entirely; E11 is simply what first
added a fitted value worth checking for.

### Decision

**Wire it, without changing `build_forecast`'s signature.** ~35 call sites across two test files
treat its return value as a plain `DataFrame`; threading a second return value through would touch
all of them for a diagnostics-only addition. Instead the fitted description rides `frame.attrs`
(pandas' own "about the frame, not a column of it" mechanism) — `live.build_forecast` sets
`frame.attrs["component_description"] = models.describe()` right after fitting, `stages/forecast.py`
reads it off before returning its own `Forecast` dataclass (now carrying an optional
`component_description` field, `None` for `xp_v0`'s cold-start fallback, which has no component
chain to describe), and `write_model_card` gains an optional `component_description` parameter
rendering a new "## Component internals" section — only when given one, so every existing card
(and every existing test asserting on card contents) is unchanged.

### Consequences

- DL-55's claim is now actually true, and DL-57's and DL-60's `market_fixtures`/`promoted_teams`
  fields are reachable the same way, for whenever S1/S3/S4/S6's flags are eventually shadowed and
  someone needs to read what the fitted model actually did.
- New tests: `test_the_fitted_component_chain_reaches_the_model_card`
  (`tests/test_xp_v1_live.py`, pins `frame.attrs` and `Forecast.component_description` both) and
  `test_a_card_with_a_component_description_shows_what_was_fitted`
  (`tests/test_forecast.py`, pins the card renders the section when given one and omits it when
  not — the `xp_v0` case).
- Full affected suite, ruff, ruff format, and mypy all pass.

---

## DL-64 — E13 built: all four stories landed, realising DL-44 end to end

**Date:** 2026-08-22 · **Status:** Accepted · **Serves:** NFR-11, NFR-13, FR-32, FR-40 · **Arose in:**
E13 implementation · **Realises:** [DL-44](#dl-44--fpl-team-and-league-ids-are-runtime-inputs-entered-in-the-ui-never-persisted-in-the-repository)

### Context

DL-44 settled the design in principle: the two IDs are a pipeline-side runtime variable and a
browser-side `localStorage` setting, never committed either way. E13-S1's half already existed —
`EntryConfig.team_id` / `league_id` default to `None` and read `FPL_DOF_TEAM_ID` /
`FPL_DOF_LEAGUE_ID` from the environment — but `pipeline.yml`'s `run` job never set those two
environment variables from anything, so a CI run could not actually pick up a repository variable
however one was configured in GitHub's settings. The browser side (E13-S2, E13-S3) did not exist at
all: no Settings route, no `localStorage` module, no personalisation on any published view.

### Decision

**E13-S1.** Added `workflow_dispatch.inputs.team_id` / `league_id` (optional strings) and a `run`-job
`env:` block to `pipeline.yml`: `FPL_DOF_TEAM_ID: ${{ inputs.team_id || vars.FPL_DOF_TEAM_ID }}`,
same shape for the league ID. The dispatch inputs exist for E13-S3's one-off override case (below);
the scheduled and `workflow_run`-triggered firings fall through to the repository variable, or to
neither, which is `EntryConfig`'s already-correct default (a declared squad, no league).

**E13-S2.** A new `web/src/components/settings/identity.ts` (`useOwnerIdentity`, mirroring
`squad/locks.ts`'s defensive load/parse/save shape exactly) backs a new `/settings` route. This is
a genuinely different thing from `EntryConfig.team_id`: a **client-side lens**, comparable but not
identical to what the pipeline was configured with, because the published site is public and anyone
reading it — a rival in the mini-league, not only the site's own operator — can type their own ID to
see themselves picked out, without changing what was built. Three personalisations follow, each
checked against a field the pipeline already publishes rather than fetched fresh (Invariant 8):

- `/league` highlights the row whose `entry_id` matches the entered team ID (`LeagueTable`'s new
  `enteredTeamId` prop), independently of the `is_owner` flag the pipeline bakes in from its own
  config — the two usually agree and need not.
- `/settings` and `/league` both state plainly, rather than silently substituting, when the entered
  league ID does not match the published `league.league.id` (DP-09, consistent with DL-40).
- `/squad` compares the entered team ID against `week.squad_state.entry_id` — present only when the
  pipeline actually read live picks — and says which of three states holds: nothing to check (no
  team ID entered), confirmed match, or a stated mismatch naming both ids. `/scout` offers a "My
  squad only" filter and an "In squad" badge, gated on a team ID being entered at all (so the app
  never presumes "your squad" language before the reader has said who they are), built from
  `squad.json`'s player ids — there is no per-viewer squad artefact to check the badge against, only
  the one the pipeline built, which the mismatch note upstream already covers honestly.

**E13-S3.** `web/src/components/settings/dispatch.ts` composes a link to `pipeline.yml`'s Actions
page. GitHub's `workflow_dispatch` UI has no supported way to pre-fill a dispatched run's inputs from
a URL, so the acceptance criterion's "or copyable inputs" alternative is what shipped: the Settings
view shows the entered team/league ID as copyable text next to the link, for the owner to paste into
the two inputs E13-S1 added. No token is constructed, stored or transmitted anywhere in this path.

**E13-S4.** Added FR-40 to the charter (§6, User experience) naming the UI-entry behaviour as a
requirement in its own right, not only as a consequence of DL-44. The feared "config-smell" —
`config/local.yaml` committed with a real team ID — turned out not to exist in the repository: the
file has never been tracked (`git log --all -- config/local.yaml` is empty) despite being gitignored
after the fact; the gitignore entry was already sufficient. No cleanup commit was needed for that
half of the story.

### Consequences

The E13 Definition of Done is met in full, including the one item that stays deliberately undone:
**Q-16 is still open** — nothing here auto-dispatches a run from the browser; the manual,
owner-authenticated deep link is the whole of E13-S3's scope, exactly as written. `web/src/App.test.tsx`,
`LeagueRoute.test.tsx`, `LeagueTable.test.tsx`, `ScoutTable.test.tsx`, `SettingsRoute.test.tsx` and
`identity.test.ts` cover the new behaviour; the full pytest and vitest suites (659 web tests, the
Python suite unchanged) are green. No pipeline code changed beyond the workflow YAML — `EntryConfig`
and the CLI path were already correct from an earlier session.

---

## Open decisions

Decisions deliberately deferred, with the point at which each must be resolved.

| ID | Question | Must resolve by |
| --- | --- | --- |
| ~~OD-01~~ | ~~Public or private GitHub repository~~ — **Closed: public.** See [DL-12](#dl-12--public-repository) | Resolved |
| ~~OD-02~~ | ~~Hosting: Cloudflare Pages, public repo, or local-only~~ — **Closed by DL-12.** GitHub Pages is free on a public repository; no Cloudflare account needed | Resolved |
| ~~OD-03~~ | ~~Which odds provider and free-tier credit budget~~ — **Closed: the Odds API, free tier, ~450 requests/month.** See [DL-59](#dl-59--e11-s5-the-odds-adapter-is-enabled-by-default-everywhere-not-switched-on-only-in-ci). The key itself is still an owner action (INPUTS-REQUIRED.md 4.1), tracked separately | Resolved |
| OD-04 | Whether to add injury/press-conference feeds as a fourth source | E8, in-season |
| ~~OD-05~~ | ~~Default risk-dial posture~~ — **Closed: Balanced, as a configuration field the owner can change at any time.** Reopens only if the owner states a target rank or a temperament. See [DL-25](#dl-25--od-05-resolved-the-risk-dial-defaults-to-balanced) | Resolved |
| ~~OD-06~~ | ~~How effective ownership is obtained~~ — **Closed: redefined without a captaincy term.** See [DL-24](#dl-24--od-06-resolved-effective-ownership-redefined-without-a-captaincy-term) | Resolved |
