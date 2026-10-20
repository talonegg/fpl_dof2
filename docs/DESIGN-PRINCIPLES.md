# Design Principles — FPL DOF

> **Amendment-controlled.** No agent edits this file without the owner's explicit approval, in the
> current conversation, of the specific change. If a principle is wrong, obstructive or missing, say
> so and stop: propose the wording. A `PreToolUse` hook enforces this; never route around it.
> Procedure: [§4](#4-amendment-procedure).

**Status:** Binding · **Version:** 2.0 · **Adopted:** 2026-08-10 ([DL-16](decisions/DL-16.md)) ·
**Amended:** 2026-10-17 ([DL-75](decisions/DL-75.md)) · **Applies to:** all code, configuration,
contracts and schemas in this repository, in every language.

---

## 1. How to use this document

These ten principles are **binding constraints**. They keep the codebase modular, safe to change,
open to extension, and cheap for an agent to work in. Code that violates one is a defect: fix it, or
record a waiver (§3). Read this file before designing a module, adding a data source, adding or
changing a model, changing the optimiser formulation, altering a contract, or deciding how something
is tested.

The invariants in `CLAUDE.md` are the always-loaded short form. This is the reasoned set, and is
authoritative where the two overlap.

**When a principle conflicts with a deadline, the principle holds and scope is cut**
([DL-10](decisions/DL-10.md)). These properties are cheap to build in and expensive to retrofit; a
deadline is a reason to ship less, never a reason to ship it badly wired.

**Product, modelling and delivery guidance lives in [`guiding-principles.md`](guiding-principles.md)**
— how numbers are presented, how a formulation is chosen, how a model is promoted and measured, how
work is sliced. It is editable, and departing from it is a decision rather than a defect. Its IDs
(DP-07, DP-08, DP-09, DP-10, DP-12) were kept when it moved out in v2.0, so citations still resolve.
IDs are never reused or renumbered.

### The ten, in brief

| | Structure — how the system is divided | | Trust — how it stays right as it changes |
| --- | --- | --- | --- |
| **DP-01** | Sources are plugins; the core never names one | **DP-11** | Every run is reproducible from its recorded inputs |
| **DP-02** | Prediction and decision are separate concerns | **DP-13** | Test hardest where being wrong is invisible |
| **DP-03** | Pure core, effectful edge | **DP-14** | Every artefact traces to its reason; every fact has one home |
| **DP-04** | Every seam is a versioned, typed contract | **DP-15** | Degrade, never break |
| **DP-05** | Business rules are configuration, in every language | | |
| **DP-06** | Every tunable is named, defaulted and justified | | |

---

## 2. The principles

### Structure — how the system is divided

#### DP-01 — Sources are plugins; the core never names one

**Only the source layer may know that a particular data provider exists.** No module outside
`pipeline/src/fpl_dof/sources/` may import, name, or branch on a specific source. Everything
downstream consumes the conformed model.

**Why here.** [DL-05](decisions/DL-05.md) records the owner's requirement for easy onboarding of
future sources, and more are anticipated (OD-04). A source name leaking into a model turns "add an
adapter" into "audit the whole pipeline".

**In practice**
- Adding a source touches exactly one new adapter module, one config entry, and its tests.
- Cross-cutting behaviour (rate limiting, retry, caching, snapshotting, user-agent, credit budgeting)
  lives in the adapter base class and is never reimplemented per source.
- Where two sources supply the same field, precedence is **configuration, not code**.
- `fetch` never parses; `parse` never conforms; `to_canonical` never applies business logic.

**Violated when** a model imports `understat`; a transform branches on `if source == "fbref"`; an
adapter computes a derived metric; precedence is expressed as an `if` chain.

**Verified by** `pipeline/tests/test_source_isolation.py` in CI, and by the acceptance test in
[Design §14.1](planning/04-conceptual-design.md#141-adding-a-data-source): if onboarding a source
touched anything else, the abstraction has leaked and that is the defect.

#### DP-02 — Prediction and decision are separate concerns

**The model answers "what is this player worth?" The optimiser answers "given those values, what
should I do?" They are separate packages communicating through a typed contract.** The optimiser
never imports a model; the model never knows a squad exists.

**Why here.** [Blueprint B5](planning/02-project-plan-and-blueprint.md). It is what lets the
deterministic MILP be replaced by a stochastic layer, or a simulation re-rank sit between the two as
a new stage, without touching either side ([DL-06](decisions/DL-06.md)).

**In practice**
- The contract carries **mean and variance**, even while the solver only approximates its use of
  variance (CLAUDE.md Invariant 6).
- A change to how points are forecast requires no optimiser change, and vice versa.
- Both sides are independently testable with fixtures, and are.

**Violated when** the optimiser recomputes an expected value; a model reasons about budget or squad
legality; the two are tuned together against a single end-to-end metric.

#### DP-03 — Pure core, effectful edge

**Rules, constraint construction, scoring arithmetic, price mechanics and transfer accounting are
pure functions.** No I/O, no clock reads, no global state, no config loading inside them —
configuration arrives as an argument.

**Why here.** These are the modules where a bug is silent and total: an off-by-one in selling-price
arithmetic misprices every transfer for a season. Purity is what makes the 100% coverage requirement
in NFR-08 achievable and property-based testing possible at all.

**In practice**
- I/O happens at the boundary: adapters read, publishers write, `stages/` wires them; everything
  between is a transformation.
- Anything time-dependent takes the time as a parameter, which is also what makes deadline logic
  testable across the BST/AEDT transition ([DL-11](decisions/DL-11.md)).
- Randomness takes an explicit seed.

**Violated when** a rules function calls `datetime.now()`, reads an environment variable, or hits the
network; a test needs a fixture directory to check an arithmetic result.

#### DP-04 — Every seam is a versioned, typed contract

**Where two components meet — especially across a language or process boundary — the interface is
explicit, versioned, and generated from a single definition rather than written twice.**

**Why here.** [DL-04](decisions/DL-04.md) creates a two-language monorepo, and
[DL-14](decisions/DL-14.md) shows the failure mode: without a shared definition, FPL's squad rules
get implemented twice and drift.

**In practice**
- `contracts/` holds the single schema definition; Python validators and TypeScript types are both
  **generated** from it. Neither is hand-written.
- The published web contract is versioned (`/data/v1/...`). Breaking changes bump the version and
  publish both during transition, so a stale cached client never breaks.
- Behaviour implemented in both languages is pinned by one fixture corpus in
  `contracts/conformance/`, read by both test suites and never copied ([DL-39](decisions/DL-39.md)).
- The model→optimiser contract (DP-02) is a typed interface, not a shared dataframe convention.

**Violated when** a TypeScript type is hand-maintained alongside a Python schema; a field is added to
a published artefact without a version consideration; two components agree by convention rather than
by contract.

#### DP-05 — Business rules are configuration, in every language

**No FPL rule value appears as a literal in code, in any language.** Scoring values, squad
composition, budget, club limits, formation legality, transfer costs, rollover caps, price and
selling-value mechanics, chip definitions and expiries all live in configuration, seeded from the
API's own game settings where exposed.

**Why here.** CLAUDE.md Invariants 2 and 9. FPL changes rules most seasons. A rule change must be a
configuration edit plus a conformance test, not an archaeology exercise. **A literal `4` for a
forward goal is a bug even when the number is right**, because next season it will be wrong and
nobody will know where to look.

**In practice**
- The `fpl-rules` skill is the reference for *what the values should be*; config is where they live.
- Values carry a verification date and a source, and are labelled where inferred rather than
  officially published.
- The rules configuration is published as `rules.json` so the browser validator is parameterised
  from the same source ([DL-14](decisions/DL-14.md)).
- Historical data from a different scoring regime is handled explicitly, never assumed comparable.

**Violated when** a `3` for the club limit appears in a `.tsx` file; a scoring value is duplicated
between config and a docstring that then drifts; a test asserts a hardcoded points total that would
silently pass under changed rules.

#### DP-06 — Every tunable is named, defaulted and justified

**A number that could reasonably be different is a parameter, not a literal — and every parameter
carries a name, a default, a valid range, what it trades off, and how it was last set.**

**Why here.** The planning horizon, discount factor, bench weight, shrinkage strength, risk dial and
candidate-pool size are the knobs the season is spent turning (open questions in
[Design §15](planning/04-conceptual-design.md#15-open-design-questions)). A magic number buried in a
function is a knob nobody can find.

**In practice**
- Parameters are declared in configuration with their documentation alongside, not scattered as
  defaults in function signatures.
- Each records **why the current value**: measured, assumed, or inherited — and if measured, from what.
- "Tune this later" is a parameter plus an open question ID, never a `# TODO` on a literal.
- Changing a parameter never requires a code change.

**Violated when** `0.85` appears inline in an objective function; a constant is chosen in a notebook
and copied into code with no record of why; two modules independently define what should be one
parameter.

### Trust — how it stays right as it changes

#### DP-11 — Every run is reproducible from its recorded inputs

**For any output the system ever produced, it must be possible to reconstruct exactly what it knew at
the time and why it advised what it did.**

**Why here.** NFR-06 as amended by [DL-13](decisions/DL-13.md). It is what makes the weekly
retrospective honest rather than a rationalisation, and what lets a regression be bisected instead of
guessed at.

**In practice**
- Immutable bronze snapshots, a `run_id` threaded through every stage, pinned dependencies, and the
  effective resolved configuration recorded in the manifest.
- **Logical, not byte-for-byte, reproducibility** (DL-13): byte-identical silver, identical objective
  within tolerance, identical published decisions, backed by a **deterministic tie-break** in the
  optimiser.
- Determinism where it is affordable — explicit seeds, stable sort orders, fixed tie-breaks.

**Violated when** an output cannot be tied to the inputs that produced it; a run depends on ambient
state; two identical inputs produce different published decisions with no tie-break to explain it.

#### DP-13 — Test hardest where being wrong is invisible

**Testing effort follows the probability that a defect is silent, not code volume or uniform coverage
targets.**

**Why here.** [Design §10](planning/04-conceptual-design.md#10-testing). This project's dangerous bugs
do not throw: a mismatched player attributes one footballer's xG to another (R-10); a leaked feature
makes the model look better (R-04); an off-by-one in free-transfer accrual builds a plan on transfers
that do not exist. Nothing goes red; the output just becomes quietly wrong.

**In practice**
- **Property-based tests** for optimiser legality: for *any* generated input, the returned squad
  satisfies every FPL rule at *every* gameweek of the horizon.
- **Conformance tests** as ground truth: recompute historical gameweek points from raw stats and
  reconcile against FPL's published totals.
- **Contract tests** against recorded responses, so upstream schema drift surfaces in CI and not at a
  deadline.
- **The safety mechanisms are themselves tested** — inject bad data and prove the quality gate blocks.
- Fault injection per source, proving degradation (DP-15).
- 100% coverage on rules and constraint modules; elsewhere, coverage follows risk.

**Violated when** a quality gate has never been shown to block; a constraint has an example test but
no property test; effort goes to raising a coverage percentage rather than to the modules where
wrongness is silent.

#### DP-14 — Every artefact traces to its reason; every fact has one home

**Code, tests, gates and decisions name what they exist for, and each fact is written in exactly one
place that everything else links to.** The chain requirement → decision → commit → test → gate is
walkable in both directions.

**Why here.** It is what lets scope be cut under deadline pressure without cutting something
load-bearing, and what lets a later session or a different agent find *why* something exists before
changing it — by opening one cited file rather than reading the whole history. A fact kept in two
places drifts, and an agent that finds both has to pay to work out which is true.

**In practice**
- Commits name the requirement IDs they implement (`FR-nn`, `NFR-nn`).
- A significant decision is recorded as `docs/decisions/DL-nn.md` **before** implementation, and is
  superseded rather than edited.
- Code and documents **cite** (`DL-nn`, `FR-nn`, `DP-nn`) rather than restate the reasoning.
- Each fact's home is listed in [`docs/README.md`](README.md); a change updates that home in the same
  commit, rewritten to the new truth ([documentation rules](agents/documentation.md)).
- Quality gates name the requirement they protect; tests for a requirement are discoverable from it.

**Violated when** a change lands with no requirement or decision reference; a comment narrates a
decision's history instead of citing it; the same fact is maintained in two documents; a document is
left describing behaviour the code no longer has.

**Verified by** `python scripts/docs.py check` in CI (decision index, links, `DL-nn` citations).

#### DP-15 — Degrade, never break

**Loss of any non-essential input reduces quality; it never stops the system.**

**Why here.** NFR-15. Scraped and credit-capped sources *will* fail — layout changes break scrapers
(R-06), odds credits run out (R-08). The system must still produce a recommendation before the
deadline, because a slightly worse recommendation beats none.

**In practice**
- Each source declares which fields it contributes; losing it removes those and nothing else.
- Degraded state is **visible, not silent** — the manifest records it and the UI shows it. Silent
  degradation is worse than failure, because the output looks normal.
- The optimiser has a greedy fallback when the solver does not converge; the result is flagged as
  fallback-quality (R-07).
- **Correctness never degrades quietly**: a failing quality gate blocks publication and the last good
  artefact stays live (CLAUDE.md Invariant 7). Stale and honest beats fresh and wrong.

**Violated when** a scraper failure aborts the pipeline; a missing source silently substitutes a
default that looks like real data; a fallback result is presented indistinguishably from a full solve.

---

## 3. Waivers

A principle may be knowingly broken. It may not be *quietly* broken.

1. **Add an inline marker** at the code site:

   ```
   DP-WAIVER(DP-06): candidate pool size fixed at 220 pending Q-01 measurement — see DL-nn
   ```

2. **Record a decision** as `docs/decisions/DL-nn.md` ([format](decisions/README.md)): which
   principle, why, what it costs, and what would let it be removed.

3. **Cite the decision in the marker.** A waiver without one is a violation with a comment attached.

`rg "DP-WAIVER"` returns every live waiver; review them at each release boundary. A waiver is a debt,
not an amendment. **Deadline pressure is not a waiver reason** (DL-10): a waiver justified only by
"no time" is a scope decision in disguise. If the same waiver recurs three times, propose an
amendment instead.

Guiding principles (DP-07, 08, 09, 10, 12) take no waiver marker: departing from one is recorded as
a decision.

---

## 4. Amendment procedure

1. **The owner approves the specific change in conversation**, having seen the proposed wording.
2. Record a decision describing the amendment and its rationale.
3. The owner edits the file, or lifts the hook (`.claude/settings.json`) and authorises an agent to
   edit it in that conversation, then restores the hook.
4. Bump the version and the `Amended` date in the header, and in the same change update the table in
   [§1](#the-ten-in-brief), `.claude/rules/design-principles.md`, and the count in `CLAUDE.md`.

**Principles may be added, clarified, retired, or moved to the guiding principles. They may not be
silently weakened.** Retiring or moving one states what now prevents the failure it existed to
prevent. At each release boundary, ask whether any principle obstructed without benefit.

---

## 5. Provenance

v1.0 (2026-08-10, [DL-16](decisions/DL-16.md)) set fifteen principles, derived from the
[charter](planning/01-project-charter.md), [plan and blueprint](planning/02-project-plan-and-blueprint.md),
[architecture](planning/03-solution-architecture.md), [conceptual design](planning/04-conceptual-design.md),
decisions DL-01 to DL-15, and the invariants in `CLAUDE.md`. v2.0 (2026-10-17,
[DL-75](decisions/DL-75.md)) kept the ten that make the codebase sound, modular, extensible and cheap
to work in, widened DP-14 to one home per fact, and moved five to
[`guiding-principles.md`](guiding-principles.md).
