# FPL DOF

Fantasy Premier League decision-support platform for the 2026/27 season. Scheduled Python pipeline
ingests data, forecasts expected points, solves a multi-gameweek MILP, and publishes static
artefacts; a React SPA reads them. No server, no database, no runtime backend.

Planning documents are in `docs/planning/`. Read `docs/planning/README.md` first when you need
context beyond this file. AI tooling design is in `docs/planning/ai/README.md`.

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
