# E0 — Steel Thread: GW1 Squad

**Objective:** OBJ-2 — produce an optimal, rule-legal 15-player squad for GW1 within £100.0m
**Hard deadline:** Fri 21 Aug 2026 18:30 BST = **Sat 22 Aug 03:30 AEST**
**Practical cut-off:** Friday evening 21 Aug, local time
**Estimate:** 9–11 focused days · **Available:** 12 days

---

## 1. What this epic is

A complete, working path through every architectural layer, carrying the minimum viable
implementation of each:

```
FPL API ──▶ bronze ──▶ silver ──▶ features ──▶ xP v0 ──▶ MILP ──▶ web contract ──▶ React view
  adapter   snapshot   conform    per-90       forecast  squad     versioned JSON   squad + table
```

Every layer is real. None is stubbed out or bypassed. What is thin is the *content* of each layer —
one data source, one crude forecast, one single-gameweek optimiser — not the structure.

**It runs entirely locally.** No GitHub Actions, no hosting, no secrets, no external accounts. That
removes OD-01, OD-02 and OD-03 from the critical path completely.

## 2. Scope

### In scope

- FPL API adapter behind the real adapter interface, with rate limiting, caching and bronze snapshots
- Minimal conformed silver layer: players, teams, fixtures, prior-season history
- Config-driven rules module with a squad legality validator
- Cold-start expected-points model (v0) with explicit, wide uncertainty
- Single-shot squad MILP: budget, composition, club limit, formation, captain, locks and bans
- Versioned JSON web contract
- Minimal React view: squad formation, sortable player table, xP decomposition
- Mandatory human verification gate before submission

### Deliberately out of scope

Everything else. Named explicitly so it is a decision, not an oversight: no Understat, FBref or odds;
no entity resolution (single source, so unnecessary); no minutes model; no multi-gameweek horizon;
no transfers; no chips; no risk dial; no backtesting; no automation; no quality gates beyond schema
validation; no data health page.

## 3. Stories

### E0-S1 — Project scaffolding
**Target: Mon 10 Aug · 1 day**

Python package, config layer, logging, CLI and data layout.

- `pipeline/` package `fpl_dof` with `pyproject.toml`, locked dependencies, ruff, mypy, pytest
- Layered config: committed YAML defaults → environment variables → gitignored local override
- Structured JSON logging with a `run_id` threaded through every stage
- Run manifest primitive: `run_id`, git SHA, timestamps, stage outcomes, output checksums
- `data/{bronze,silver,gold,web}` layout, gitignored
- CLI: `fpl-dof ingest | transform | forecast | optimise | publish | run`

**Acceptance**
- `fpl-dof --help` lists all stages on a clean checkout
- `pytest` and `ruff` pass; `mypy` clean
- A no-op `run` writes a valid manifest with a `run_id`

---

### E0-S2 — FPL source adapter
**Target: Tue 11 – Wed 12 Aug · 1.5 days**

The real adapter, not a fetch script. This is the layer most expensive to retrofit.

- Adapter base class owning rate limiting, retry with backoff and jitter, response caching, bronze
  snapshotting with checksums, honest User-Agent, and structured error taxonomy
- Adapter registry so a second source drops in without touching anything downstream
- FPL adapter covering `bootstrap-static/`, `fixtures/`, and `element-summary/{id}/` for all players
- One recorded-response contract test

**Acceptance**
- `fpl-dof ingest` writes gzipped bronze snapshots with checksums and a lineage sidecar
- Re-running within the cache window makes zero network calls
- Contract test passes against a recorded response
- **Invariant check: nothing outside `sources/` imports or names a source**

**Notes**
- `element-summary` needs ~700 requests. At a polite ~2/second that is ~6 minutes — acceptable, and
  cached thereafter. Do not parallelise it aggressively.
- `history_past` inside `element-summary` is the prior-season data the cold-start model needs.

---

### E0-S3 — Minimal silver layer
**Target: Thu 13 Aug · 1 day**

- Conform bronze into four canonical tables: `player`, `team`, `fixture`, `player_season_history`
- Parquet output, partitioned by season
- Pandera schemas asserting types, ranges and referential integrity
- Prices converted from tenths at the ingestion boundary, once, never downstream

**Acceptance**
- `fpl-dof transform` produces four validated Parquet tables
- Schema violations fail the run rather than passing bad data through
- Row counts logged to the manifest

---

### E0-S4 — Rules module and legality validator
**Target: Fri 14 Aug · 1 day**

Pure functions, config-driven. The foundation everything else trusts.

- Scoring values, squad composition, budget, club limit and legal formations, all in config
- `validate_squad()` — pure, exhaustive, returns every violation rather than the first
- Selling-price arithmetic including the 50% sell-on fee (unused in E0, needed from E1)
- Property-based tests: any legal squad validates; any perturbation of a legal squad fails

**Acceptance**
- 100% test coverage on the rules module (NFR-08 requires this here specifically)
- Property tests pass across randomised inputs
- **No FPL constant appears as a literal anywhere outside config** (Invariant 2)

**Reference:** the `fpl-rules` skill carries the verified 2026/27 values. Note its ⚠️ markers — the
full BPS matrix is community-inferred, not official, and E0 does not need it.

---

### E0-S5 — Expected points v0 (cold start)
**Target: Sat 15 – Sun 16 Aug · 2 days**

The hardest story, because it is judgement rather than mechanics. Preseason has **zero current-season
data**, so this is entirely a prior-construction problem.

Signal stack, in descending weight:

1. **Prior-season per-90 rates** from `history_past` — goals, assists, clean sheets, minutes — for
   players with Premier League history
2. **FPL's own initial price** as a market-implied prior on role and expected value. This is a
   genuinely strong signal: FPL prices players on expected returns
3. **Position and price-tier baselines** for players with no top-flight history — new signings from
   abroad, promoted-club players
4. **Availability haircut** from `status` and `chance_of_playing_next_round`
5. **Fixture difficulty** over GW1–6, from team strength ratings in `bootstrap-static`

Method: compute per-90 rates, shrink toward the position-and-price-tier prior in inverse proportion
to prior-season minutes, scale by expected minutes and fixture difficulty, convert to expected points
via the rules module.

**Output:** expected points per player for GW1 and summed over GW1–6, plus a **deliberately wide
uncertainty band** (Invariant 6) and a per-player confidence tier reflecting how much real evidence
sits behind it.

**Acceptance**
- xP table for every player, with decomposition by scoring component
- Every value carries an uncertainty estimate and a confidence tier
- Method documented in a model card, including its known weaknesses
- Sanity check: the top 20 by xP are recognisably plausible premium players
- Newly promoted and newly signed players are not systematically absurd in either direction

**This is the story most likely to overrun.** If it does, ship the crude version and spend the saved
time on E0-S8 review instead. A cruder forecast reviewed carefully beats a better forecast trusted blindly.

---

### E0-S6 — Squad optimiser
**Target: Mon 17 – Tue 18 Aug · 1.5 days**

Single-shot MILP. **De-risked already:** PuLP with its bundled CBC solver has been verified against
an FPL-shaped problem (15 from 200 candidates, budget, position and club constraints) and returns
optimal in seconds. No external solver needed.

- Constraints: exactly 15 (2 GK / 5 DEF / 5 MID / 3 FWD), £100.0m budget, max 3 per club, legal
  starting XI formation, one captain
- Objective: maximise xP over the GW1–6 horizon, with a small bench weight and a discount factor
- User overrides: lock a player in, ban a player, exclude a club
- Solve-time guard and a greedy fallback

**Acceptance**
- Returns a legal squad — verified by the E0-S4 validator, not by inspection
- **Property test: for arbitrary randomised inputs, the returned squad never violates any FPL rule**
- Solves in under 60 seconds
- Locks and bans are honoured, and infeasible combinations report *why*

---

### E0-S7 — Publish and minimal web view
**Target: Wed 19 Aug · 1 day**

- Gold → versioned web contract at `data/web/v1/`: `squad.json`, `players.json`, `meta.json`
- Shared JSON Schema in `contracts/`, with TypeScript types generated from it
- Vite + React + TypeScript: squad formation view, sortable and filterable player table, xP
  decomposition on selection
- Runs via `vite --host` for phone access on the local network

**Acceptance**
- Squad and player table render on a laptop and on a phone over LAN
- Table sorts and filters without a page reload
- Data loads from static JSON only — no API calls from the browser (Invariant, architecture §4)

---

### E0-S8 — Human verification gate
**Target: Thu 20 Aug · 0.5 day · MANDATORY**

Not a formality. The model behind this squad has never been validated against anything, and this
story is the only thing standing between an unvalidated forecast and a submitted team.

**Checklist**
1. Compare the squad against public consensus and the emerging template. Note every difference.
2. For each difference, ask: *does the model know something, or does it not know something?* The
   second is far more likely in a v0 forecast.
3. Check every player's actual availability — injuries, suspensions, preseason minutes, transfer
   rumours. The model sees only the FPL status flag, which lags.
4. Check the cheap enablers are genuinely playable, not just cheap. This is where a naive xP
   optimiser most reliably goes wrong.
5. Verify budget is efficiently used and the bench is not accidentally load-bearing.
6. Sanity-check captain choice against fixture and form.
7. Apply overrides via locks and bans, and **re-run** — do not hand-edit the output.
8. Record every override and its reasoning.

**Acceptance**
- Squad reviewed against consensus, differences explained
- Overrides applied through the optimiser, not by hand
- Reasoning recorded for the post-GW1 retrospective
- **Team submitted to FPL before the deadline** — by you, manually, per ASM-6 and DL-08

---

## 4. Schedule

| Date (AEST) | Story | Notes |
| --- | --- | --- |
| Sun 9 Aug | — | Planning complete |
| Mon 10 Aug | E0-S1 | Scaffolding |
| Tue 11 – Wed 12 Aug | E0-S2 | FPL adapter |
| Thu 13 Aug | E0-S3 | Silver layer |
| Fri 14 Aug | E0-S4 | Rules + validator |
| Sat 15 – Sun 16 Aug | E0-S5 | **xP v0 — the risk story** |
| Mon 17 – Tue 18 Aug | E0-S6 | Optimiser |
| Wed 19 Aug | E0-S7 | Publish + web view |
| Thu 20 Aug | E0-S8 | **Review gate** |
| Fri 21 Aug | Buffer | Final data refresh, re-run, submit |
| **Sat 22 Aug 03:30** | **DEADLINE** | Team must be in before this |

Two full buffer days are deliberate. Preseason FPL data changes right up to the deadline — price
changes, injury news, late transfers — so a final refresh and re-run on Friday is expected, not
exceptional.

## 5. Emergency cut

If the schedule slips, drop in this order. Each step below is survivable; the ones above the line
are not.

| Priority | Item | If dropped |
| --- | --- | --- |
| 1st to drop | **E0-S7 web view** | Read the squad from console output or a CSV. The squad is the deliverable; the UI is not |
| 2nd | **Contract test in E0-S2** | Accept the risk for one run; add it in E1 |
| 3rd | **Fixture-difficulty adjustment in E0-S5** | Use GW1 only rather than a GW1–6 horizon. Weaker, but not wrong |
| 4th | **Bench optimisation** | Fill the bench with the cheapest legal playing options |
| ——— | ——— | ——— |
| **Never drop** | **E0-S4 rules + validator** | Without it you cannot know the squad is legal |
| **Never drop** | **E0-S8 review gate** | This is the only validation the model gets |

## 6. Technical debt register

Every shortcut, with the epic that repays it. Reviewed at the end of E0 and again after GW4.

| # | Debt | Consequence | Repaid by |
| --- | --- | --- | --- |
| D-01 | **No backtesting — B7 knowingly breached** | The forecast is unvalidated. Do not trust it for expensive decisions (hits, chips) until repaid | **E3** — first deliverable |
| D-02 | No minutes model; availability is a crude haircut | Rotation risk and injury returns mispriced | E3 (M1) |
| D-03 | Single-gameweek objective with a fixed horizon weight | No transfer planning, no rollover logic | E1, then E4 |
| D-04 | No chips modelled | Chip set 1 expires at the GW19 deadline | E4 |
| D-05 | FPL's own team strength used for fixture difficulty | Weaker than an xG-based model | E3 (M2) |
| D-06 | Quality gates limited to schema validation | Bad data could pass silently | E2 |
| D-07 | No entity resolution | Harmless now — one source. Becomes critical the moment E5 lands | E5 |
| D-08 | No automation; every run is manual | Not viable across 38 deadlines, especially given AEST timings | E7 |
| D-09 | Uncertainty is a heuristic band, not a modelled variance | The eventual risk dial needs real variance | E3 |

**Rule:** a debt item may be deferred but never deleted. Deleting one requires a decision-log entry
saying why it stopped mattering.

## 7. Definition of done

- [ ] A legal 15-player squad exists, verified by the validator, within £100.0m
- [ ] The full pipeline runs end-to-end from a clean checkout with one command
- [ ] Squad and player table viewable on laptop and phone
- [ ] Rules module at 100% coverage; optimiser legality property tests pass
- [ ] No source-specific code outside `sources/`
- [ ] No FPL constant hardcoded outside config
- [ ] Every xP value carries an uncertainty estimate
- [ ] Model card written, including known weaknesses
- [ ] Debt register complete and committed
- [ ] E0-S8 review completed and overrides recorded
- [ ] **Team submitted before Sat 22 Aug 03:30 AEST**

## 8. Success criteria beyond the deadline

E0 has succeeded if, on 22 August, all three hold:

1. A considered squad was submitted on time.
2. The codebase is a genuine foundation — E1 extends it rather than working around it.
3. You know which parts of the recommendation you trusted and which you overrode, and why.

The third matters most. It is the baseline against which every later model improvement gets measured.
