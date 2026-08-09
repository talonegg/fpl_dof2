# Skills Plan

**Part of:** [AI Tooling Plan](README.md)

Fourteen candidate skills, derived from the recurring procedures and reference bodies in the
[conceptual design](../04-conceptual-design.md). Three are worth building now; the rest are specified
here and built with the code they describe.

---

## 1. Mechanics that shape the design

| Fact | Design consequence |
| --- | --- |
| Location is `.claude/skills/<name>/SKILL.md`; the **directory name** becomes `/command` | Directory names are the user-facing API. Name them as verbs where they are procedures |
| The body loads **only when invoked** | Long reference material is nearly free. This is why the FPL rules belong in a skill, not `CLAUDE.md` |
| `description` (+ optional `when_to_use`) is always in context, truncated at 1,536 chars combined | Descriptions must be short and trigger-rich. This is the only part that costs context permanently |
| Supporting files load on demand when referenced | Split large references into `references/*.md` and point at them from `SKILL.md` |
| Keep `SKILL.md` under 500 lines | Anything longer is a reference file, not a skill body |
| `disable-model-invocation: true` → user-invoked only, description not in context | Right for side-effecting or timing-critical workflows |
| `user-invocable: false` → model-invoked only, hidden from the `/` menu | Right for pure background knowledge |
| `paths:` limits automatic activation to matching files | Ties a skill to its layer without a rule file |
| `context: fork` runs the skill in a subagent | Right for long, output-heavy work like a backtest |
| Invoked content persists for the session; the file is not re-read | Write standing instructions, not one-time steps |
| `allowed-tools` pre-approves tools for that turn only | Use sparingly, and only with narrowly scoped Bash patterns |

---

## 2. The catalogue

Ordered by the phase in which each should be created.

| # | Skill | Type | Invocation | Phase |
| --- | --- | --- | --- | --- |
| 1 | `fpl-rules` | Reference | Model | **Now** |
| 2 | `fpl-api` | Reference | Model | **Now** |
| 3 | `add-data-source` | Procedure | Both | P1 |
| 4 | `pipeline-triage` | Procedure | Both | P1 |
| 5 | `add-quality-gate` | Procedure | Both | P1 |
| 6 | `add-model-component` | Procedure | Both | P2 |
| 7 | `run-backtest` | Procedure | Both, forked | P2 |
| 8 | `milp-patterns` | Reference | Model | P3 |
| 9 | `add-optimiser-constraint` | Procedure | Both | P3 |
| 10 | `change-data-contract` | Procedure | Both | P4 |
| 11 | `new-app-view` | Procedure | Both | P4 |
| 12 | `deadline-run` | Operational | **User only** | P5 |
| 13 | `gameweek-review` | Operational | **User only** | P6 |
| 14 | `season-retro` | Operational | **User only** | P6 |

---

## 3. Build now

### 3.1 `fpl-rules` — the highest-value skill in the project

The authoritative 2026/27 FPL rules. This exists because **a hallucinated scoring value corrupts
every number downstream and nothing visibly breaks.** It is the one place where being confidently
wrong is worst, and it is knowable today without any code.

```yaml
---
name: fpl-rules
description: Authoritative Fantasy Premier League 2026/27 rules — scoring values, the revised Bonus Points System, Defensive Contribution thresholds, squad composition, budget, transfer and price mechanics, and chip rules with expiry dates. Load before writing or reviewing any code that computes points, prices, selling values, transfer costs, squad legality or chip eligibility, and before answering any question about how FPL scoring works.
user-invocable: true
---
```

**Body outline** (~150 lines):
- A prominent statement that config is the source of truth in code, and this skill is the reference
  for *what the config values should be* — never a licence to hardcode.
- Scoring table by position, including Defensive Contribution thresholds (DEF 10+ CBIT; MID/FWD
  12+ CBIRT).
- Squad composition, budget, club limit, legal formations.
- Transfer mechanics: one free per gameweek, rollover capped at five, −4 per extra.
- Price and selling-value mechanics, including the 50% sell-on fee and its rounding.
- Chips: two sets of four, one per gameweek, **set 1 expires at the GW19 deadline, 13:30 GMT,
  2 January 2027**.
- Key 2026/27 changes and the trap they create: the BPS revision means prior-season bonus data comes
  from a different scoring regime.
- Season dates and the deadline pattern.

**Supporting files:**
- `references/bps-matrix.md` — the full Bonus Points System table. Long, rarely needed, verified
  against the official rules at creation time.
- `references/changes-2026-27.md` — what changed this season and what it invalidates in historical data.

**Verification discipline:** every value carries the date it was verified and the source. The skill
instructs that if code and skill disagree, neither wins automatically — check the official rules.

### 3.2 `fpl-api` — endpoint reference

Prevents guessing at endpoint paths and response shapes, and encodes the awkward parts that are not
obvious from any documentation because there is none.

```yaml
---
name: fpl-api
description: Reference for the official Fantasy Premier League API — endpoint catalogue, response shapes, field meanings, rate-limiting expectations, and known quirks including the pre-deadline squad visibility gap. Load when writing or debugging FPL ingestion code, or when deciding which endpoint provides a given field.
user-invocable: true
---
```

**Body outline** (~120 lines):
- Endpoint catalogue with what each provides and its natural refresh cadence.
- The important quirks, which is the real value here:
  - `entry/{id}/event/{gw}/picks/` is only public **after** the deadline — the current squad must be
    reconstructed before it (CON-10). This is the single most likely thing for an agent to get wrong.
  - Which fields are authoritative for prices and ownership, and the daily price-change timing.
  - Status and chance-of-playing semantics, including their unreliability close to kickoff.
  - Where the API contradicts itself between endpoints.
- Politeness expectations: honest user agent, conservative rate limiting, cache first.
- A standing instruction that this API is undocumented and unversioned, so the recorded contract
  tests — not this file — are the real check.

**Supporting files:**
- `references/response-shapes.md` — annotated example payloads.

### 3.3 Why not a third one yet

Every other candidate describes code that does not exist. Writing `add-data-source` before the
adapter base class exists means inventing an interface and then either following the invention or
having a skill that lies. Both are worse than waiting.

---

## 4. Specified, built later

### `add-data-source` — P1 · the flagship procedure

Implements [Design §14.1](../04-conceptual-design.md#141-adding-a-data-source), and is how the
extensibility requirement (FR-04, DL-05) actually gets honoured rather than merely designed.

```yaml
---
name: add-data-source
description: Onboard a new external data source as a pluggable adapter — adapter module, canonical field declarations, recorded contract test, config entry and field precedence. Use when adding any new data provider or feed to the pipeline.
argument-hint: [source-name]
paths: ["pipeline/src/fpl_dof/sources/**"]
---
```

Body: the five-step procedure, with an explicit acceptance check — **if the change touches anything
outside `sources/`, config and tests, stop; the abstraction has leaked and that is a defect to fix,
not a step to take.** Bundles `templates/adapter.py` and `templates/contract_test.py`.

### `pipeline-triage` — P1

The runbook from [Design §11](../04-conceptual-design.md#11-documentation). Given a failed run or a
blocked quality gate: read the manifest, locate the failing stage, check per-source status codes and
freshness, decide between transient failure, upstream schema drift, and a genuine data problem. Ends
with the decision of whether to publish, hold, or roll back — never "retry until green".

### `add-quality-gate` — P1

Gate authoring: pick the class (schema / range / referential / freshness-and-volume), pick the
severity, name the requirement it protects, and — the step that gets skipped — write the test that
injects bad data and proves the gate blocks.

### `add-model-component` — P2

[Design §14.2](../04-conceptual-design.md#142-adding-a-model-component). Implement behind the model
interface emitting mean and variance; register with the aggregator **and** the explanation
decomposition; add backtest metrics; run in shadow mode; promote only on evidence. Includes the
leakage checklist and a reminder about scoring-regime changes in historical training data.

### `run-backtest` — P2

```yaml
---
name: run-backtest
description: Run the walk-forward backtest harness and report results honestly against the charter's tier-2 thresholds — rank correlation, MAE, calibration, captaincy hit rate, and simulated season score versus benchmarks.
context: fork
agent: backtest-analyst
---
```

Forked because a backtest produces far more output than anyone will re-read. The body's most
important instruction is about interpretation, not execution: **report the numbers as they came out.
If the model does not beat the naive benchmark, that is the finding.** Produces or updates a model card.

### `milp-patterns` — P3

Reference for the formulation in [Design §6.2](../04-conceptual-design.md#62-milp-formulation):
the full variable and constraint set, linearisation recipes for the bilinear captain × triple-captain
term and the free-transfer `min` accrual, Free Hit's parallel squad handling, candidate-pruning
rationale, and solve-time management. Model-invoked, `paths:` scoped to `optimise/`.

### `add-optimiser-constraint` — P3

[Design §14.3](../04-conceptual-design.md#143-adding-an-optimiser-constraint). Constraint builder,
property test, config exposure. Standing instruction: express it linearly or say explicitly that it
cannot be, and never weaken an existing FPL legality constraint to make a new one feasible.

### `change-data-contract` — P4

The two-language boundary — the riskiest routine change in the codebase because a mistake breaks the
app for a cached client with no server-side error to notice. Procedure: edit the JSON Schema,
regenerate both sides, decide breaking versus additive, bump and dual-publish if breaking, check the
payload budget, update the fixture data the web tests use.

### `new-app-view` — P4

Frontend screen conventions from [Design §8](../04-conceptual-design.md#8-user-experience): assign
the interaction tier, wire data loading, virtualise if the full player set is involved, render
uncertainty, handle the degraded-source and stale-data states, accessibility pass, check both
viewports and both themes.

### `deadline-run` — P5 · user-invoked only

```yaml
---
name: deadline-run
description: Pre-deadline procedure — refresh data, verify freshness, review the recommendation and its explanation, apply human overrides, confirm the final team.
disable-model-invocation: true
argument-hint: [gameweek]
---
```

`disable-model-invocation` because this is timing-critical and side-effecting; Claude should never
decide on its own that it is deadline time. The body ends where it must: **the human submits the
team. The system never does.**

### `gameweek-review` — P6 · user-invoked only

The weekly loop from [Plan §3, Phase 6](../02-project-plan-and-blueprint.md#phase-6--in-season-operations--continuous-to-30-may-2027):
post-gameweek review of recommendation versus outcome, drift check, data health check, then **one**
improvement — the body should say "one, not three" explicitly, because scope creep across 38
gameweeks is how solo projects die.

### `season-retro` — P6 · user-invoked only

End-of-season assessment against [charter §5](../01-project-charter.md#5-success-criteria), including
the honest question of whether the model added edge over intuition, and whether 2027/28 is worth it.

---

## 5. Rejected candidates

Worth recording so they are not proposed again.

| Candidate | Why not |
| --- | --- |
| `commit` / `push` / `pr` workflow skills | Generic git workflow, no project-specific procedure. Claude Code handles this well already |
| `write-test` | Testing conventions are layer-specific and belong in the `.claude/rules/` files |
| `explain-recommendation` | This is a product feature to build, not an agent procedure |
| `update-decision-log` | Two sentences. Belongs in `CLAUDE.md` conventions, and it is there |
| `scrape-understat` / `scrape-fbref` | Per-source skills would duplicate `add-data-source` and undermine the abstraction it exists to protect. Source specifics belong in the adapter and its contract test |
| `optimise-squad` | Running the optimiser is a command, not a procedure |
| `setup-project` | One-time. A plan document already covers it |

---

## 6. Conventions for writing these skills

1. **The description is the interface.** It is the only permanently loaded part, so lead with the
   trigger case and use the vocabulary that will actually appear in a prompt.
2. **Body under 500 lines**; anything longer becomes `references/`.
3. **Write standing instructions, not steps**, where guidance should apply for the rest of the task —
   invoked content persists but is not re-read.
4. **Every procedure skill ends with an acceptance check**, not just steps. The `add-data-source`
   check ("did this touch anything outside `sources/`?") is the model for the rest.
5. **State the failure mode.** Each skill should say what going wrong looks like, because that is what
   makes it possible to notice.
6. **Date and source every external fact**, so staleness is visible rather than assumed.
7. **`disable-model-invocation: true` for anything with side effects or deadline timing.**
