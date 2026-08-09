# FPL DOF

Fantasy Premier League decision-support platform for the 2026/27 season. Scheduled Python pipeline
ingests data, forecasts expected points, solves a multi-gameweek MILP, and publishes static
artefacts; a React SPA reads them. No server, no database, no runtime backend.

Planning documents are in `docs/planning/`. Read `docs/planning/README.md` first when you need
context beyond this file. AI tooling design is in `docs/planning/ai/README.md`.

**The build plan of record is `docs/planning/epics/`** — a steel thread to the GW1 deadline, then
eight incremental epics. `docs/planning/02-project-plan-and-blueprint.md` still contains an older
phase plan (P0–P6); its §3, §4 and §8 are superseded and marked as such. Do not plan work from them.

## Design principles — binding

**`docs/DESIGN-PRINCIPLES.md` holds fifteen binding design principles (DP-01…DP-15).** Read them
before designing a module, adding a data source, adding or changing a model, changing the optimiser
formulation, altering a contract, or deciding how something is tested. The invariants below are the
short always-loaded subset; that document is the full reasoned set and is authoritative.

- Violating code is a **defect**. Fix it, or record a waiver: an inline
  `DP-WAIVER(DP-nn): <reason> — see DL-nn` marker at the code site **plus** a decision-log entry.
  Both, never one alone. Find live waivers with `rg "DP-WAIVER"`.
- **When a principle conflicts with a deadline, the principle holds and scope gets cut** (DL-10).
  "No time" is a scope decision, not a waiver reason.
- **That file is amendment-controlled and must never be edited by an agent** — a `PreToolUse` hook
  blocks it. If a principle is wrong or obstructive, say so and stop; propose the wording to the
  owner. Never work around or disable the hook (DL-16).

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

- `pipeline/` — Python. Everything before the web data contract. *(not yet created)*
- `web/` — TypeScript/React. Everything after it. *(not yet created)*
- `contracts/` — shared JSON Schema. The single definition of the boundary between the two. *(not yet created)*
- `docs/planning/` — charter, plan, architecture, conceptual design, AI tooling plan.
- `data/` — local working data. Gitignored. Never commit it.

## Invariants

These are not style preferences. Breaking one causes silent, expensive wrongness.

1. **Only `pipeline/src/fpl_dof/sources/` may know a data source exists.** No module outside it may
   import, name or branch on a specific source. Everything downstream consumes the conformed silver
   model. Enforced by import-lint in CI (from Phase 1 onward).
2. **Never hardcode FPL scoring, price or squad values.** They live in config, seeded from the API's
   game settings where exposed. A literal `4` for a forward goal is a bug even when the number is
   right. See the `fpl-rules` skill for authoritative values.
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
8. **The browser never calls an external API.** The web app reads published static artefacts and
   nothing else. There is no request path from the client to any code this project operates (DL-03).
9. **Invariant 2 does not stop at the language boundary.** The TypeScript legality validator is
   generated from `rules.json` in the web contract, which comes from the same config the Python rules
   module reads (DL-14). A hardcoded `3` for the club limit in a `.tsx` file is the same bug as a
   hardcoded `4` for a forward goal in a `.py` file.
10. **This repository is public.** No secret reaches it, ever — not in a commit, not in a test
    fixture, not in a client bundle. API keys live only in GitHub Actions secrets (NFR-13, DL-12).

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
