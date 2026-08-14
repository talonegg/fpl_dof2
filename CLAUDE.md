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
Python lives in `.venv` at the repo root, created with `uv`. `uv` is installed as a module, so it is
`python -m uv`, not `uv`.

| Task | Command |
| --- | --- |
| First-time setup | `python -m uv venv .venv --python 3.14` then `python -m uv pip install --python .venv\Scripts\python.exe -e "pipeline[dev]"` |
| Full local pipeline run | `.venv\Scripts\fpl-dof run` |
| Single pipeline stage | `.venv\Scripts\fpl-dof ingest\|transform\|quality\|forecast\|optimise\|week\|publish` |
| This week's decision only | `.venv\Scripts\fpl-dof week` |
| Walk-forward backtest — **not** part of `run` | `.venv\Scripts\fpl-dof backtest`. Needs the archive source enabled and `sources.backfill_seasons` set in `config/local.yaml` |
| Re-run ignoring caches | `.venv\Scripts\fpl-dof run --force-refresh` |
| Python tests | `cd pipeline && ..\.venv\Scripts\python -m pytest -q` |
| Live-API drift tests | `cd pipeline && ..\.venv\Scripts\python -m pytest -q --network` |
| Slow tests — the historical chip replay (D-18/DL-28), ~16 min | `cd pipeline && ..\.venv\Scripts\python -m pytest -q --slow tests/test_chip_replay.py`. Needs the archive backfill in silver; writes its finding to `data/gold/chip-replay.json` |
| Rules coverage gate (must be 100%) | `cd pipeline && ..\.venv\Scripts\python -m pytest --cov=fpl_dof.rules --cov-fail-under=100 tests/test_rules_build.py tests/test_rules_scoring.py tests/test_rules_legality.py` |
| Lint + format + type check | `cd pipeline && ..\.venv\Scripts\python -m ruff check . && ..\.venv\Scripts\python -m ruff format --check . && ..\.venv\Scripts\python -m mypy` |
| Web dev server (LAN-accessible for mobile testing) | `cd web && npm run dev` — `vite.config.ts` sets `host: true` |
| Web tests | `cd web && npm run test -- --run` |
| Web type check + build | `cd web && npm run typecheck && npm run build` |
| Browser verification (3 viewports) | Serve a build, then `cd web && npm run verify:browser -- http://127.0.0.1:4173` — see `web/verify/README.md` |

Reading the current squad without the web app: `data/gold/season=2026-27/squad.json`, this week's
decision at `week.json`, the gate report at `quality.json`, and the model card next to them at
`model-card.md`. **The model card carries the backtest verdict** — read it before acting on a
ranking (DL-21).

## Layout

- `pipeline/` — Python. Everything before the web data contract.
  - `sources/` — the only package allowed to know a data source exists (Invariant 1).
  - `silver/` — the conformed canonical model and its Pandera schemas.
  - `rules/` — the game's rules as data, seeded from the API (Invariant 2), plus scoring and the
    squad legality validator.
  - `forecast/` — expected points, the feature store, the component models, the backtest harness
    and the model card. Prediction only.
  - `optimise/` — the squad MILP and the weekly transfer MILP. Decision only (DP-02).
  - `squad/` — the owner's squad: what it is now, and how to set it up this week. Pure core.
  - `week/` — deadlines in both zones, alerts, and advised-versus-played reconciliation.
  - `quality/` — the data quality gates. A blocking failure stops the run before anything is built
    on the data, which is how Invariant 7 is enforced by ordering rather than by remembering.
  - `publish/` — the web contract writer and the TypeScript generator.
  - `stages/` — the five pipeline stages; the effectful edge (DP-03).
- `web/` — TypeScript/React. Everything after it. `src/contract/types.ts` is **generated** — never
  edit it by hand; `fpl-dof publish` rewrites it from the JSON Schemas.
- `contracts/` — shared JSON Schema. The single definition of the boundary between the two.
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
   Stale and honest beats fresh and wrong. Thresholds are configuration; loosening one so a run
   passes is working around the gate.
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
