# E0 — Steel Thread: GW1 Squad

**Objective:** OBJ-2 — produce an optimal, rule-legal 15-player squad for GW1 within £100.0m
**Hard deadline:** Fri 21 Aug 2026 18:30 BST = **Sat 22 Aug 03:30 AEST**
**Practical cut-off:** Friday evening 21 Aug, local time
**Estimate:** 9.5–11.5 focused days · **Available:** 12 days · **Buffer:** 1 day

---

## 0. Build outcome — as at 2026-08-10

**E0-S1 to E0-S7 are built, tested and verified.** [E0-S8](#e0-s8--human-verification-gate), the
human review gate, is the only remaining story and is yours, not the pipeline's.

The full pipeline runs end to end in **~16 seconds**: `fpl-dof run` → ingest, transform, forecast,
optimise, publish. 260 Python tests, 6 web unit tests, `ruff`, `mypy --strict` and a real-Chromium
browser check at three viewports all pass.

**The squad it currently produces:** 3-5-2, **exactly £100.0m**, solved optimally in 0.5s.
B.Fernandes captain, Watkins vice. Verified legal by the E0-S4 validator, not by inspection.

### What the plan got right

- The MILP was never the risk. It solves in half a second.
- The R-15 diagnostic was worth its hour: **R² of xP on (price, position) = 0.494**, verdict
  *informative*. The forecast is addin    g real information beyond FPL's own prices. Had it come back
  above 0.9 the squad would still exist, but it would have been a budget-allocation exercise, and
  the review gate would need to know that. It is in the model card either way.
- The start-probability floor earns its place. 423 of 573 players fall below it; without it the
  optimiser fills the XI with cheap players who will never take the pitch.

### What the plan got wrong, and what changed

| Finding | Consequence |
| --- | --- |
| **`history_past` carries `defensive_contribution`** | E0-S3 route 1 works. The 2025/26 community archive and its half-day are not needed ([DL-18](../00-decision-log.md#dl-18--the-202526-community-archive-is-not-needed-e0-s3-took-route-1)). Debt D-11 stands: DefCon still rests on one season |
| **`game_config.scoring` publishes the whole scoring table** | Invariant 2 is satisfied by reading the rules, not transcribing them ([DL-17](../00-decision-log.md#dl-17--game-rules-are-read-from-the-api-not-transcribed)) |
| **A goalkeeper goal is worth 10, not 6** | The `fpl-rules` skill said 6. Transcribing it would have mispriced every goalkeeper silently. The skill is corrected and now points at the API |
| **Defensive Contribution now includes forwards** | Another 2026/27 change the skill missed |
| **Preseason team strength fields are all zero** | Fixture difficulty comes from the fixture's own 1–5 rating, not from team strength |
| **Fields absent in a past season read as zero, not null** | DefCon before 2025/26 and `starts` before 2022/23. Read naively this says "did no defending". Both are now restricted to the seasons in which they were measured |

### Debts confirmed against the register in §6

D-01 through D-10 and D-12 all stand as written. D-11 stands but for a better reason than expected:
not because the archive was cut, but because 2025/26 is genuinely the only season in which DefCon
was recorded.

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
- A second, static source — the 2025/26 per-gameweek archive — purely to obtain Defensive
  Contribution rates, which `history_past` does not carry. See [E0-S3](#e0-s3--minimal-silver-layer-and-the-202526-archive)
- Minimal conformed silver layer: players, teams, fixtures, prior-season history
- Config-driven rules module with a squad legality validator
- Cold-start expected-points model (v0) with explicit, wide uncertainty
- Single-shot squad MILP: budget, composition, club limit, formation, captain, locks and bans
- Versioned JSON web contract
- Minimal React view: squad formation, sortable player table, xP decomposition
- Mandatory human verification gate before submission

### Deliberately out of scope

Everything else. Named explicitly so it is a decision, not an oversight: no Understat, FBref or odds;
**no entity resolution** — the 2025/26 archive is keyed on FPL element IDs, so both sources already
share a key, which is precisely why that second source is safe to admit here when no other would be;
no minutes model; no multi-gameweek horizon; no transfers; no chips; no risk dial; no backtesting;
no automation; no CI; no quality gates beyond schema validation; no data health page.

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

### E0-S3 — Minimal silver layer, and the 2025/26 archive
**Target: Thu 13 Aug · 1.5 days**

- Conform bronze into four canonical tables: `player`, `team`, `fixture`, `player_season_history`
- Parquet output, partitioned by season
- Pandera schemas asserting types, ranges and referential integrity
- Prices converted from tenths at the ingestion boundary, once, never downstream

#### The Defensive Contribution problem — why this story grew by half a day

The cold-start model (E0-S5) is built on `element-summary/{id}/history_past`, which gives **season
totals**: minutes, goals, assists, clean sheets, saves, bonus, BPS. Per-90 rates come out of that
fine, so goals and assists are covered.

**Defensive Contribution is not in there** — and the design calls DefCon *"the best signal-to-noise
ratio in the whole model, and the place where a model most easily beats intuition, because most
managers still price players as if the component did not exist"*
([Design §5 M4](../04-conceptual-design.md#m4--defensive-contribution)). A GW1 squad built without it
prices defenders and defensive midfielders in exactly the way the design says is wrong. For a squad
that is 5 defenders and 5 midfielders out of 15, that is not a rounding error.

**Route, in order — take the first that works:**

1. **Check `history_past` for a season-total DefCon field.** FPL added `defensive_contribution` to
   per-gameweek element data in 25/26; if it also reached the season-totals shape, this is free.
2. **Otherwise ingest the 2025/26 per-gameweek community archive** as a second source: a static,
   already-published CSV set keyed on **FPL element IDs**, so it needs no entity resolution (which is
   why it is safe to admit into E0 when nothing else is). Snapshot it to bronze once, conform to a
   `player_gameweek_history` silver table, treat as static thereafter.
3. **Otherwise fall back** to a role-based positional prior with deliberately wide uncertainty, say so
   loudly in the model card, and tell the E0-S8 review gate to weight defender selection on judgement.

This is a genuine bonus beyond the DefCon fix: it is **the first real test of the adapter registry**
(a second source, four days into the build), and it is [E2-S3](E2-data-platform.md) work brought
forward rather than throwaway effort.

**Acceptance**
- `fpl-dof transform` produces validated Parquet tables; schema violations fail the run rather than
  passing bad data through
- Row counts logged to the manifest
- **A per-90 Defensive Contribution rate exists for every player with 2025/26 minutes, or route 3 is
  taken and recorded as a debt item**
- **The second source went in through the registry, and nothing outside `sources/` changed** — if it
  did, the abstraction has already leaked and fixing it is part of this story

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
2. **Per-90 Defensive Contribution rate** from the 2025/26 archive ingested in E0-S3. Rate-driven and
   far more stable week to week than goal involvement, so it earns high weight despite one season of
   evidence
3. **FPL's own initial price** as a market-implied prior on role and expected value. This is a
   genuinely strong signal: FPL prices players on expected returns
4. **Position and price-tier baselines** for players with no top-flight history — new signings from
   abroad, promoted-club players
5. **Availability haircut** from `status` and `chance_of_playing_next_round`
6. **Fixture difficulty** over GW1–6, from team strength ratings in `bootstrap-static`

Method: compute per-90 rates, shrink toward the position-and-price-tier prior in inverse proportion
to prior-season minutes, scale by expected minutes and fixture difficulty, convert to expected points
via the rules module.

**Output:** expected points per player for GW1 and summed over GW1–6, plus a **deliberately wide
uncertainty band** (Invariant 6) and a per-player confidence tier reflecting how much real evidence
sits behind it.

#### The diagnostic that decides whether any of this is worth anything

Signal 3 is FPL's own price. The optimiser then maximises expected points *subject to a budget*. If
expected points turns out to be largely a function of price, the objective is nearly flat across every
affordable squad and the solver is selecting on residual noise — **an expensive random number
generator with a budget constraint**. This is R-15, and it costs an hour to check:

> Regress xP on `(price, position)`. **Report the R² and the within-price-tier spread of xP in the
> model card, and read them before submitting.**

Interpretation, decided now rather than in the moment:

| R² | Meaning | Response |
| --- | --- | --- |
| < 0.7 | The model is adding real information beyond price | Proceed |
| 0.7 – 0.9 | Thin, but there is signal in the residuals | Proceed, and weight the E0-S8 review more heavily |
| **> 0.9** | The forecast is a repricing of FPL's prices | **Say so.** The squad is then a budget-allocation exercise, not a forecast, and should be reviewed as one. This is a finding to report, not a number to tune until it looks better |

**Acceptance**
- xP table for every player, with decomposition by scoring component **including Defensive Contribution**
- Every value carries an uncertainty estimate and a confidence tier
- Method documented in a model card, including its known weaknesses
- **R² of xP on `(price, position)` reported in the model card, with the response above applied**
- Sanity check: the top 20 by xP are recognisably plausible premium players
- Newly promoted and newly signed players are not systematically absurd in either direction
- **No player enters the starting XI with a modelled start probability below 60% unless explicitly
  overridden.** With no minutes model (D-02) and preseason `status` flags almost universally `a`, the
  availability haircut does almost nothing — a crude starts-per-appearance prior from last season is
  the only thing standing between the optimiser and a bench full of players who will never play

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
| Thu 13 Aug + ½ Fri | E0-S3 | Silver layer **+ 2025/26 archive** (1.5 d) |
| ½ Fri 14 – ½ Sat 15 Aug | E0-S4 | Rules + validator |
| ½ Sat 15 – Sun 16 Aug | E0-S5 | **xP v0 — the risk story** |
| Mon 17 – Tue 18 Aug | E0-S6 | Optimiser |
| Wed 19 Aug | E0-S7 | Publish + web view |
| Thu 20 Aug | E0-S8 | **Review gate** |
| Fri 21 Aug | Buffer | Final data refresh, re-run, submit |
| **Sat 22 Aug 03:30** | **DEADLINE** | Team must be in before this |

The 2025/26 archive added half a day to E0-S3, taken from the front of the buffer rather than from
E0-S5 or E0-S8 — the two stories that must not be compressed. **One full buffer day remains**, which
is still deliberate: preseason FPL data changes right up to the deadline (price changes, injury news,
late transfers), so a final refresh and re-run on Friday is expected, not exceptional. If E0-S3 runs
long, the archive is the first thing to cut — see below.

## 5. Emergency cut

If the schedule slips, drop in this order. Each step below is survivable; the ones above the line
are not.

| Priority | Item | If dropped |
| --- | --- | --- |
| 1st to drop | **E0-S7 web view** | Read the squad from console output or a CSV. The squad is the deliverable; the UI is not |
| 2nd | **Contract test in E0-S2** | Accept the risk for one run; add it in E1 |
| 3rd | **The 2025/26 archive in E0-S3** | Fall back to route 3 — a role-based positional DefCon prior with wide uncertainty. Defender and defensive-midfielder pricing gets materially worse, so tell the E0-S8 gate to scrutinise those ten squad places by hand. Recoverable, and E2-S3 repays it |
| 4th | **Fixture-difficulty adjustment in E0-S5** | Use GW1 only rather than a GW1–6 horizon. Weaker, but not wrong |
| 5th | **Bench optimisation** | Fill the bench with the cheapest legal playing options |
| ——— | ——— | ——— |
| **Never drop** | **E0-S4 rules + validator** | Without it you cannot know the squad is legal |
| **Never drop** | **The R² diagnostic in E0-S5** | One hour. It is the only thing that tells you whether the forecast is a forecast or a repricing of FPL's prices |
| **Never drop** | **E0-S8 review gate** | This is the only validation the model gets |

## 6. Technical debt register

Every shortcut, with the epic that repays it. Reviewed at the end of E0 and again after GW4.

| # | Debt | Consequence | Repaid by |
| --- | --- | --- | --- |
| D-01 | ~~No backtesting — B7 knowingly breached~~ **Closed by E3.** Replaced by D-13 | The forecast is now measured, not merely unvalidated — and measurement is unflattering | **E3** — first deliverable |
| D-02 | No minutes model; availability is a crude haircut | Rotation risk and injury returns mispriced | E3 (M1) — **see D-14**: the calibration half of this acceptance criterion is still unmet |
| D-03 | ~~Single-gameweek objective with a fixed horizon weight~~ **Closed by E4-S2.** A rolling 5-8 gameweek MILP with free-transfer accrual, the five-transfer rollover cap and hit arithmetic | Transfer planning and rollover logic now exist and are property-tested | **E4** - closed |
| D-04 | ~~No chips modelled~~ **Closed by E4-S3.** All four chips modelled by scenario enumeration, plus a season-long chip calendar; set-1 expiry read from the game's own chip windows and enforced rather than advised | The GW19 loss is now planned against rather than only warned about. E2-S7's blunt tracker is superseded, not deleted, and still runs | **E4** - closed |
| D-05 | FPL's own team strength used for fixture difficulty | Weaker than an xG-based model | E3 (M2) |
| D-06 | Quality gates limited to schema validation | Bad data could pass silently | E2 |
| D-07 | ~~No entity resolution~~ **Mechanism closed by E5-S1** — three-tier resolution (deterministic/fuzzy/override), a hard failure on cross-source ID conflict, and an unmatched-rate quality gate all exist and are tested. **Still not fully closed, and the reason has moved again** ([DL-31](../00-decision-log.md#dl-31)). The consumer D-22 asked for now exists, and a real resolution defect underneath it is fixed — every crosswalk row was stamped with the *current* season regardless of which season the reference described, so a backfilled advanced row could never join an identity and any multi-season backfill would have tripped the duplicate-claim guard on what is not a conflict. What is left is not code: **no external source is reachable to resolve against** (D-23) | The invisible-mismatch risk is mitigated for live runs and the cross-season path is now correct and tested; it remains unexercised against real external data, because there is none | **D-23** — closes when a second source's data actually reaches the forecast |
| D-08 | No automation; every run is manual | Not viable across 38 deadlines, especially given AEST timings | E7 |
| D-09 | Uncertainty is a heuristic band, not a modelled variance | The eventual risk dial needs real variance | E3 |
| D-10 | **No CI.** E0 runs entirely locally, so charter §13.3 is knowingly unmet | Nothing proves the code runs anywhere but this machine. Covered by the dated carve-out in [charter §13](../01-project-charter.md#the-one-dated-exception--e0), which expires 22 Aug | E7 — the first workflow must run the E0 code path unchanged |
| D-11 | **Defensive Contribution rests on one season** (2025/26), or on a positional prior if the archive was cut | The highest signal-to-noise component has the thinnest evidence behind it. See [Q-13](../04-conceptual-design.md#15-open-design-questions) — whether earlier seasons can be reconstructed from action counts | E2-S3 backfill, then E3-S5 |
| D-12 | **Start probability is a crude prior, not a model** | Related to D-02 but distinct: D-02 is about rotation and injury *risk*; this is about whether a player is a starter at all. In preseason the FPL status flags say almost nothing, so ~£17–20m of cheap squad places rest on a heuristic | E3 (M1) |
| D-13 | **The forecast does not beat the model-free benchmark at the head of the ranking** (top-20 precision 0.00 vs 0.05) — replaces D-01. See [E3 build outcome](E3-expected-points-engine.md#0-build-outcome--2026-08-11--the-model-does-not-clear-the-bar) and [DL-21](../00-decision-log.md#dl-21) | No −8 hit, chip or wildcard may be justified on xp_v1 alone until this closes | E4 must gate on it; a dedicated model-improvement pass may be needed before E4 starts |
| D-14 | **Minutes-model calibration is unmeasured** — `minutes_brier` is always null because the backtest harness never passes minutes probabilities through the (already-built) Brier-score function. Found in the post-E3 audit, not by E3 itself — E3-S3's DoD checkbox was ticked without this acceptance criterion actually being checked | E3-S3's own stated acceptance criterion ("calibration curves and Brier score reported") is not met; the minutes model's reliability is unknown, not just crude | E3 follow-up, before E4 leans on start-probability output for anything expensive |
| D-15 | **The most-captained player is not carried through to the decision layer.** `bootstrap-static` publishes `most_captained` as a single element id on each event, but the silver `gameweek` table does not carry the column, so E4's ownership callout always renders as "not available" | [DL-24](../00-decision-log.md#dl-24) makes the most-captained callout the *replacement* for the captaincy term the risk dial cannot model. Without the column, the one thing the redefinition promised to surface is absent | A source/silver change: add `most_captained` to the gameweek adapter and schema, then pass it to `build_plan` in `stages/decision.py`, which already accepts it |
| D-16 | **The chip captain multiplier is seeded from configuration, not read from the game.** `decision.chips.captain_multiplier_by_chip` defaults to `{"3xc": 3}`. The API publishes it as `overrides.pick_multiplier` on each chip, and the silver `chip` table does not carry that field | A transcribed rule, which is what Invariant 2 exists to prevent. It is in configuration rather than in code, so it is one line to correct and it is visible - but it is still a number this project asserted rather than read | Add `pick_multiplier` to the chip adapter and schema, then seed the config default from it (the same shape as the E0-S4 rules seeding) |
| D-17 | **The candidate-pruning rule is validated by a helper, not by a scheduled check.** `optimise.candidates.pruning_matches_full_pool` exists and is unit-tested, but nothing runs it against the full ~700-player pool on a schedule | E4-S1's acceptance criterion is "periodically re-solve on the full set offline and confirm the pruned solution matches". The mechanism exists; the *periodically* does not, so pruning bias would go unnoticed | E7, as a scheduled offline job alongside the backtest - both are slow, both produce findings rather than artefacts |
| D-18 | ~~**The simulation re-rank is not exercised by the backtest.**~~ **Closed.** `optimise/replay.py` runs `build_plan` twice — re-rank on and off — at a bounded sample of real historical deadlines, refitting through the walk-forward harness's own `fold_rows`/`training_rows`, and scores each chip week against what those players actually scored. It changed the recommendation at **8 of 8** deadlines; see [DL-28](../00-decision-log.md#dl-28) | The criterion is met on real data rather than on a constructed tie. It is **not** evidence that the re-rank improves timing — 5 changes better, 3 worse, on eight observations — and the systematic direction is now **D-21** | **Closed** by `tests/test_chip_replay.py` (gated `--slow`) |
| D-19 | **Multi-gameweek solve time is measured only preseason, and only locally.** A full local run solved 20 scenarios over a 5-gameweek horizon on a 159-player pool in 92.7s, inside the 600s budget ([DL-26](../00-decision-log.md#dl-26)). That run had no double or blank gameweeks in the fixture list and ran on a developer machine, not a CI runner | R-07 stays High. The budget is met on the easy half of the season, on the faster of the two machines that matter. The greedy fallback and the scenario budget are the mitigations, and both are exercised | E7, when CI runs the real path on a schedule; re-check after the first double gameweek |
| D-20 | **Re-diagnosed and narrowed, not closed** ([DL-29](../00-decision-log.md#dl-29)). The premise was wrong: Understat and FBref *did* already backfill via `request.seasons`, and ingest and transform already passed `sources.backfill_seasons` into it — the path was untested, not absent. It is now covered by `tests/test_source_backfill.py` against recorded historical pages, and a real defect underneath it is fixed (a configured backfill used to **replace** the current season rather than add to it). What remains is the odds half | The odds provider publishes no historical archive on its free tier and there is no `ODDS_API_KEY` to test one with. **This half is an external blocker**, not code: it needs the owner obtaining a key per INPUTS-REQUIRED §4.1 | Owner action for the key. The larger remainder moved to **D-22**, now closed; what stands between E5 and its acceptance test is **D-23**, and it is a provenance decision rather than code |
| D-21 | **The re-rank concentrates chip timing at the front of the horizon, and the mechanism is unidentified.** At the default Balanced dial it moved Bench Boost to the *first* horizon gameweek at 8 of 8 replayed deadlines ([DL-28](../00-decision-log.md#dl-28)). A three-dial probe shows this is **not** a fixed artefact — the safe dial declined to move the chip at all at one deadline and the aggressive dial chose a different week at another — so the percentile is doing real work. But the front-loading at the two dials a user is most likely to run is a strong regularity that nothing yet explains | The re-rank is proven to *move* chip timing and to *respond to the dial*; it is not proven to *time* chips well. A pull toward playing a chip immediately is the opposite of what a chip planner is for, and until the cause is known the timing carries less weight than its precision suggests | Identify the mechanism — the interaction between the per-gameweek discount applied in `plan._draws` and ranking a *percentile* of a discounted sum is the first place to look, since the discount shrinks later weeks' contribution to the tail as well as to the mean. Reproduce with `optimise/replay.py` at all three dials |
| D-22 | ~~**Nothing consumes the conformed advanced metrics.**~~ **Closed** ([DL-31](../00-decision-log.md#dl-31)). `forecast/features.py` now joins `player_metric` on `player_code` and emits prior-season, position-relative per-90 ratios; `RateModel` uses them to move the position prior a component is shrunk toward; the knowability boundary is the **season label**, so a total is invisible at every deadline inside its own season and visible from the first deadline of the next, property-tested across all 38 gameweeks at both ends (`tests/test_prior_season_features.py`). Ships dark per DP-08 | The consumer exists and is safe. It changed no metric, because there is nothing for it to consume: **no external source is reachable** (D-23), and a mechanism probe on the data the project does hold moved the backtest by ~0.001 Spearman | **Closed**; the measurement it was meant to enable now waits on **D-23** |
| D-23 | **Neither scraped source can be fetched at all.** Understat's `robots.txt` now reads `User-agent: * / Disallow: /` — the whole site — and FBref returns a Cloudflare 403 to every request including `robots.txt` itself. Found by enabling both and running ingest for real ([DL-31](../00-decision-log.md#dl-31)). Underneath it, a posture defect: the **Understat adapter never checked `robots.txt`** — only FBref did — so the source was fetching pages the site disallows. Fixed: the check is now a shared `sources/robots.py` used by both, and Understat correctly fetches nothing. Separately, the live Understat league page no longer embeds the `playersData` script the adapter parses, and E5's "recorded page" contract fixtures are hand-constructed rather than recorded, so neither adapter has ever been exercised against a real page | **E5's acceptance test cannot be run.** Not for want of a consumer, a backfill or a key — the data cannot be obtained politely. Working around either block would mean ignoring a site's stated rules or defeating an access control, which NFR-10 and [DL-27](../00-decision-log.md#dl-27) forbid | Owner decision, not code. Options: a licensed or freely-published alternative provider; FBref's own bulk exports if any exist under terms that permit this; or accepting that the official feed's `expected_goals`/`expected_assists`/action counts are the only advanced data this project will have, and closing E5's remaining scope on that basis |
| D-24 | ~~**The component models never fitted in the backtest.**~~ **Closed by [DL-32](../00-decision-log.md#dl-32).** `fold_rows` handed `fit_components` a frame carrying only features, the target and minutes, so `RateModel.fit` found none of the raw statistic columns it fits on: every position prior was empty, every scoring rate was shrunk toward **zero** rather than toward a fitted prior, team strength was never estimated and the bonus model kept its defaults. Found while investigating why the D-22 feature moved nothing — it was multiplying a prior that was identically zero | **[DL-21](../00-decision-log.md#dl-21)'s table describes a model that was not the one it claims to describe.** Correcting it makes the forecast slightly *worse* (Spearman 0.2444 → 0.2255): shrinking to zero was accidental regularisation. D-13 is unchanged and better evidenced | **Closed** by widening `OUTCOME_COLUMNS` — the fold frame now carries the outcome statistics for fitting and `walk_forward` strips all of them before predicting, asserted by `test_no_outcome_column_of_any_kind_reaches_a_prediction` |

**Rule:** a debt item may be deferred but never deleted. Deleting one requires a decision-log entry
saying why it stopped mattering.

## 7. Definition of done

- [x] A legal 15-player squad exists, verified by the validator, within £100.0m — 3-5-2, exactly £100.0m
- [x] The full pipeline runs end-to-end from a clean checkout with one command — `fpl-dof run`, ~16s
- [x] Squad and player table viewable on laptop and phone — verified in Chromium at 390/820/1440 px
- [x] Rules module at 100% coverage; optimiser legality property tests pass — 100% statement *and* branch
- [x] No source-specific code outside `sources/` — enforced by `tests/test_source_isolation.py`
- [x] No FPL constant hardcoded outside config — and most are read from the API (DL-17)
- [x] Every xP value carries an uncertainty estimate — enforced by the contract schema
- [x] Model card written, including known weaknesses **and the R² of xP on `(price, position)`** — 0.494, *informative*
- [x] Defensive Contribution is in the xP decomposition — modelled as a Poisson threshold event
- [x] Debt register complete and committed — see §0
- [ ] E0-S8 review completed and overrides recorded — **yours to do**
- [ ] **Team submitted before Sat 22 Aug 03:30 AEST** — **yours to do**

## 8. Success criteria beyond the deadline

E0 has succeeded if, on 22 August, all three hold:

1. A considered squad was submitted on time.
2. The codebase is a genuine foundation — E1 extends it rather than working around it.
3. You know which parts of the recommendation you trusted and which you overrode, and why.

The third matters most. It is the baseline against which every later model improvement gets measured.
