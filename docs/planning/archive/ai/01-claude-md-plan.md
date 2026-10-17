# CLAUDE.md and Project Rules Plan

**Part of:** [AI Tooling Plan](README.md)

Covers the always-loaded instruction layer: one root `CLAUDE.md`, and seven path-scoped files under
`.claude/rules/` that load only when the relevant layer is touched.

---

## 1. How the mechanism actually behaves

Facts that shape the design, from the Claude Code memory documentation:

| Behaviour | Consequence for this plan |
| --- | --- |
| `CLAUDE.md` may live at `./CLAUDE.md` **or** `./.claude/CLAUDE.md` | Use `./CLAUDE.md` — visible at the repo root, and obvious to a human reading the project |
| Loaded into context at the start of **every** session | Every line has a permanent cost. Target under 200 lines; this plan targets ~130 |
| It is **context, not enforced configuration** | Anything that must not fail goes in a hook or CI as well — see [04](04-hooks-and-settings-plan.md) |
| `@path` imports load at launch too | Imports organise, they do **not** save context. No point importing the planning docs |
| Files in subdirectories load on demand when Claude reads files there | Nested `CLAUDE.md` is an alternative to path-scoped rules; rules are cleaner because the glob is explicit |
| `.claude/rules/*.md` **without** `paths:` load at launch, same priority as `.claude/CLAUDE.md` | Every rule file in this plan **must** carry `paths:`, or it defeats the purpose |
| Path-scoped rules trigger when Claude *reads a matching file* | A rule cannot guide work on a file that has not been opened yet. Keep genuinely universal things in `CLAUDE.md` |
| Root `CLAUDE.md` survives `/compact`; **nested files and path-scoped rules do not re-inject** | Long sessions lose layer rules after compaction. Another reason the critical invariants live in the root file |
| Block-level HTML comments are stripped before loading | Use them for maintainer notes that should not cost tokens |

---

## 2. Root `CLAUDE.md` — draft

Create at `./CLAUDE.md`. The commands section is a stub until Phase 0 fills it in; everything else is
knowable today.

<!-- Sections marked TODO are filled in at the end of Phase 0. -->

````markdown
# FPL DOF

Fantasy Premier League decision-support platform for the 2026/27 season. Scheduled Python pipeline
ingests data, forecasts expected points, solves a multi-gameweek MILP, and publishes static
artefacts; a React SPA reads them. No server, no database, no runtime backend.

Planning documents are in `docs/planning/`. Read `docs/planning/README.md` first when you need
context beyond this file.

## Commands

<!-- TODO Phase 0: fill in once the toolchain exists. -->
| Task | Command |
| --- | --- |
| Full local pipeline run | `TODO` |
| Single pipeline stage | `TODO` |
| Python tests | `TODO` |
| Lint + type check | `TODO` |
| Web dev server (LAN-accessible for mobile testing) | `TODO` |
| Web tests | `TODO` |

## Layout

- `pipeline/` — Python. Everything before the web data contract.
- `web/` — TypeScript/React. Everything after it.
- `contracts/` — shared JSON Schema. The single definition of the boundary between the two.
- `docs/planning/` — charter, plan, architecture, conceptual design.
- `data/` — local working data. Gitignored. Never commit it.

## Invariants

These are not style preferences. Breaking one causes silent, expensive wrongness.

1. **Only `pipeline/src/fpl_dof/sources/` may know a data source exists.** No module outside it may
   import, name or branch on a specific source. Everything downstream consumes the conformed silver
   model. Enforced by import-lint in CI.
2. **Never hardcode FPL scoring, price or squad values.** They live in config, seeded from the API's
   game settings where exposed. A literal `4` for a forward goal is a bug even when the number is
   right. See the `fpl-rules` skill for the authoritative values.
3. **Never introduce a paid service, tier or dependency.** Zero running cost is a hard requirement
   (NFR-01), not a preference. If a task seems to need one, stop and say so.
4. **Never collect, store or transmit FPL credentials.** Public endpoints only. There is no auth in
   this project and there never will be (NFR-11).
5. **No look-ahead in features or backtests.** Every feature carries the gameweek at which it becomes
   knowable, and the backtester enforces it. This is the single easiest way to produce a model that
   looks excellent and is worthless.
6. **Expected-points outputs always carry variance, not just a mean.** The optimiser contract depends
   on it even where the current solver only approximates its use.
7. **A failing quality gate blocks publication.** Never work around a gate to get a run to complete.
   Stale and honest beats fresh and wrong.

## Conventions

- Name the requirement IDs a change implements in the commit message — `FR-12`, `NFR-08`. The
  numbered requirements are in `docs/planning/01-project-charter.md` §6.
- Record any significant decision in `docs/planning/00-decision-log.md` **before** implementing it.
  Append a new entry; never edit an accepted one — supersede it.
- Update the relevant `docs/planning/` document in the same change as the code, not afterwards.
- British English in documentation, UI copy and comments. Currency is £.
- The definition of done is charter §13. It applies to every increment.

## Working style

- The season is the clock. Gameweek deadlines are immovable; check
  `docs/planning/02-project-plan-and-blueprint.md` §5 before assuming there is time.
- Prefer boring and testable. This codebase is maintained by one person at intermittent hours.
- When a model or optimiser change is proposed, ask what would falsify it before writing it.
````

**Target: ~130 lines.** If it grows past 200, move the newest material into a path-scoped rule.

### What deliberately stays out

| Excluded | Where it goes instead | Why |
| --- | --- | --- |
| The FPL scoring table and BPS matrix | `fpl-rules` skill | Long, and only needed when touching scoring code |
| FPL API endpoint catalogue | `fpl-api` skill | Same |
| Adapter interface details | `.claude/rules/sources.md` | Only relevant inside `sources/` |
| MILP formulation | `milp-patterns` skill | Long reference, rarely needed |
| Architecture prose | `docs/planning/03-*` | Claude can read it when relevant; importing it would cost context every session |
| Directory listings and dependency lists | Nowhere | Derivable from the codebase. `/doctor` actively recommends trimming these |
| The weekly operating loop | `gameweek-review` skill | A procedure, not a fact |

---

## 3. Path-scoped rules

All seven carry a `paths:` glob, so each costs nothing until its layer is touched. Create each one
**with the layer it describes**, not before.

### `.claude/rules/sources.md` — Phase 1

```yaml
paths:
  - "pipeline/src/fpl_dof/sources/**/*.py"
  - "pipeline/tests/sources/**/*.py"
```

- The adapter interface and what each member must and must not do — `fetch` never parses, `parse`
  never conforms, `to_canonical` never applies business logic.
- Never reimplement rate limiting, retry, caching, snapshotting or user-agent handling in an adapter;
  the base class owns all of it.
- Every adapter needs a contract test against recorded responses before it is considered done.
- Field precedence between sources is configuration, never code.
- Politeness obligations per source: `robots.txt`, crawl delay, credit budget, personal-use terms.
- Failure of a non-FPL source must degrade, never break (NFR-15).

### `.claude/rules/rules-engine.md` — Phase 2

```yaml
paths:
  - "pipeline/src/fpl_dof/rules/**/*.py"
  - "pipeline/tests/rules/**/*.py"
```

- Pure functions only. No I/O, no config loading inside them, no globals.
- 100% test coverage is required here, not aspirational (NFR-08).
- Values come from config. Point at the `fpl-rules` skill for authoritative numbers.
- Any change must keep the conformance test green — historical gameweek points recomputed from raw
  stats must still reconcile to FPL's published totals.

### `.claude/rules/models.md` — Phase 2

```yaml
paths:
  - "pipeline/src/fpl_dof/models/**/*.py"
  - "pipeline/src/fpl_dof/features/**/*.py"
  - "pipeline/src/fpl_dof/backtest/**/*.py"
```

- Every feature declares the gameweek at which it becomes knowable. No exceptions.
- Every model emits mean **and** variance.
- Components register with both the aggregator and the explanation decomposition — a component that
  scores points but cannot be explained is not finished.
- New or changed models run in shadow mode first, and are promoted only on backtest evidence.
- Prior seasons come from different scoring regimes. The 25/26 BPS revision and the introduction of
  Defensive Contribution mean older training data needs explicit handling.
- Never tune against the held-out season.

### `.claude/rules/optimise.md` — Phase 3

```yaml
paths:
  - "pipeline/src/fpl_dof/optimise/**/*.py"
  - "pipeline/tests/optimise/**/*.py"
```

- Every constraint gets a property-based test asserting it holds for arbitrary inputs.
- The optimiser consumes model *outputs*; it must never import a model.
- Respect the solve-time budget. Candidate pruning, time limits, warm starts, greedy fallback.
- Bilinear terms are linearised with the standard three-inequality pattern; see `milp-patterns`.
- A returned squad that violates any FPL rule is a critical bug, not a tuning issue.

### `.claude/rules/contracts.md` — Phase 4

```yaml
paths:
  - "contracts/**"
  - "pipeline/src/fpl_dof/publish/**/*.py"
  - "web/src/types/**"
```

- The schema in `contracts/` is the single source of truth. Both the Pandera schemas and the
  TypeScript types are generated from it; neither is hand-written.
- A breaking change bumps the contract version and publishes both versions during transition. A
  stale cached client must never break.
- Respect the payload budget: initial load ≤ 3 MB, detail lazy-loaded (NFR-04).

### `.claude/rules/web.md` — Phase 4

```yaml
paths:
  - "web/**/*.{ts,tsx,css}"
```

- The app never calls an external API. It reads published static artefacts only.
- Assign every new interaction to a tier — T1 precomputed, T2 client-side, T3 job-triggered — and say
  which in the PR. Nothing on the deadline path may be T3.
- Uncertainty is always visible. A forecast rendered as a bare number is a defect.
- Tables over the full player set must be virtualised.
- Theme tokens for colour; must read correctly in light and dark, and without relying on colour alone.
- Keyboard navigable; run the accessibility audit on new views.

### `.claude/rules/workflows.md` — Phase 5

```yaml
paths:
  - ".github/workflows/**"
```

- Nothing scheduled inside 45 minutes of a gameweek deadline. Scheduled runs are best-effort and
  can be delayed; the deadline is not.
- Every workflow is manually dispatchable.
- Stages are idempotent and independently resumable.
- Concurrency groups prevent a stale run overwriting a fresher publication.
- Secrets come from Actions secrets only, and never reach the client bundle.

---

## 4. Personal, uncommitted instructions

`CLAUDE.local.md` at the repo root, gitignored, for anything machine-specific — local paths, a
personal team ID for testing, preferred scratch locations. Keep project standards out of it; if a
rule matters to the project it belongs in the committed files.

---

## 5. Maintenance

| Trigger | Action |
| --- | --- |
| The same correction typed twice | Add it — to `CLAUDE.md` if universal, to a rule if layer-specific |
| `CLAUDE.md` passes 200 lines | Move the least universal section to a path-scoped rule |
| A section becomes a procedure rather than a fact | Move it to a skill |
| An instruction is repeatedly ignored | It is probably too vague, or it needs to be a hook |
| Phase exit | Review whether that phase's rule file matches what was actually built |

Verify what is loading with `/context` (lists memory files) and `/memory` (browse and edit).
