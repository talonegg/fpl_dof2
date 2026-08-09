# Subagents and AGENTS.md Plan

**Part of:** [AI Tooling Plan](README.md)

Covers two things the phrase "agent.md files" can mean, because both matter here:

1. **Subagent definitions** — `.claude/agents/*.md`, specialised workers Claude delegates to.
2. **`AGENTS.md`** — the cross-tool instruction file convention. Settled in §4.

---

## 1. When a subagent is actually the right answer

A subagent runs in its own context window and returns only a summary. That is the entire value
proposition, and it is also the entire cost: every spawn starts cold and re-derives context the main
session already has.

**A subagent earns its place when all three hold:**

| Test | Meaning |
| --- | --- |
| **Volume** | The work produces output — logs, search results, file contents — that would flood the main context and that nobody will re-read |
| **Separability** | The task has a clean input and a clean summarisable output, with no need to interleave with the main thread |
| **Repetition or constraint** | It recurs often enough to be worth defining, or it needs restricted tools to be trustworthy |

Most of what looks like a subagent candidate in this project is really a skill. A procedure that
should shape how *the main session* works is a skill; a job whose *output* is all that matters is a
subagent.

**Three qualify.** Everything else is covered by the built-in `Explore` and `general-purpose` agents,
which need no definition.

---

## 2. The three

### 2.1 `backtest-analyst` — Phase 2

The reason this one exists is not context volume, though a backtest produces plenty. It is
**independence of judgement**. The person who built a model is the worst person to assess it, and
the same applies to a session that has spent an hour tuning one. A separate context that has not
watched the model being built reports what the numbers say rather than what the effort deserves.

```yaml
---
name: backtest-analyst
description: Runs the walk-forward backtest harness and reports model quality honestly against the charter's tier-2 thresholds. Use after any change to features, models or the expected-points aggregator, and whenever asked how good the forecast currently is.
model: opus
effort: high
skills: [fpl-rules]
memory: project
color: blue
---
```

**System prompt shape:**
- Run the harness; never modify model code — this agent measures, it does not fix.
- Report against charter §5 tier 2: rank correlation, MAE, calibration slope, captaincy hit rate,
  simulated season versus the template, overall-average and naive-strategy benchmarks.
- Break results down by position, price tier and minutes band. Aggregates hide the failures that matter.
- **Standing instruction: if the model does not beat the naive benchmark, say so plainly in the first
  sentence.** Do not lead with what improved.
- Actively look for signs of look-ahead leakage: results that are too good, or accuracy that does not
  degrade with horizon.
- Produce or update the model card.

`memory: project` lets it accumulate a genuinely useful thing across the season — what the metrics
looked like before, so "improvement" is measured rather than asserted.

### 2.2 `pipeline-triage` — Phase 1

Classic context-isolation case. Diagnosing a failed run means reading the manifest, structured logs,
per-source status codes, gate results and possibly bronze snapshots — a large fan-out where only the
conclusion matters.

```yaml
---
name: pipeline-triage
description: Diagnoses failed pipeline runs and blocked quality gates by reading run manifests, structured logs and raw snapshots. Use when a scheduled run fails, a gate blocks publication, or published data looks wrong.
tools: Read, Grep, Glob, Bash, WebFetch
model: sonnet
memory: project
color: orange
---
```

**Read-only by design** — no `Edit` or `Write`. A triage agent that can also apply fixes will apply
fixes, and a hurried fix to a data pipeline the day before a deadline is exactly the failure mode
this project should avoid. It reports; the main session decides.

**System prompt shape:** start from the manifest, not the logs. Classify the failure as transient,
upstream schema drift, or genuine data problem — the three have completely different responses. End
with an explicit recommendation among publish / hold / roll back. Never recommend retrying until green.

`memory: project` accumulates the recurring failure signatures, which for scraped sources will
repeat (R-06).

### 2.3 `leakage-auditor` — Phase 2

The narrowest and, per unit of effort, probably the most valuable. Look-ahead leakage is the project's
highest-likelihood serious risk (R-04): it produces a model that looks excellent and is worthless,
and it is nearly invisible to the person who wrote the feature.

```yaml
---
name: leakage-auditor
description: Audits feature engineering, model training and backtest code for look-ahead bias and data leakage. Use before promoting any model change out of shadow mode, and whenever backtest results look surprisingly good.
tools: Read, Grep, Glob
model: opus
effort: high
color: red
---
```

**System prompt shape:** one mandate only — establish, for every feature involved, whether it could
have been known before the deadline it is used to predict. Check knowability stamps, rolling-window
boundaries, joins against post-match data, target encoding, normalisation fitted on the full dataset,
and any use of the held-out season. Report findings ranked by severity with the concrete scenario in
which each one leaks. Say plainly when nothing is found — a clean audit is a useful result, and an
auditor that always finds something is not an auditor.

Read-only, and deliberately given no other responsibilities.

---

## 3. Rejected candidates

| Candidate | Why not |
| --- | --- |
| `adapter-builder` | Building an adapter should happen in the main session where the result gets reviewed. The procedure belongs in the `add-data-source` skill |
| `fpl-rules-auditor` | Verifying rules against official sources is occasional and small. The conformance test is the real check |
| `frontend-builder` | UI work is iterative and visual; delegating it to a context that cannot show its work is worse than doing it inline |
| `data-explorer` | The built-in `Explore` agent already does this |
| `optimiser-tuner` | Tuning needs tight iteration with the main session; isolation would slow it down |
| `doc-writer` | Documentation should be written by whoever made the change, in the same change |
| A general `code-reviewer` | The bundled `/code-review` skill covers this and is better maintained than a bespoke one would be |

---

## 4. The `AGENTS.md` decision

**Recommendation: do not create `AGENTS.md`.**

Reasoning:

- **Claude Code reads `CLAUDE.md`, not `AGENTS.md`.** Creating one would produce a file that the only
  agent working on this project ignores.
- This is a solo project with a single agent. `AGENTS.md` exists to share instructions across tools —
  there is nothing to share with.
- Two instruction files with overlapping content is the specific failure the Claude Code
  documentation warns about: conflicting instructions get resolved arbitrarily.

**If a second coding agent is ever adopted** — Codex, Cursor, Copilot — the migration is small and
should be done in this order:

1. Move the tool-neutral content out of `CLAUDE.md` into `AGENTS.md` — commands, layout, invariants,
   conventions. That is most of it.
2. Replace the top of `CLAUDE.md` with `@AGENTS.md`, then keep only Claude-specific additions below it.
3. Leave `.claude/rules/`, skills and subagents where they are; they are Claude Code mechanisms with
   no cross-tool equivalent.

```markdown
@AGENTS.md

## Claude Code specifics

Layer conventions live in `.claude/rules/`. Domain references are skills — see `/fpl-rules`.
```

A symlink also works, but **not on Windows without Administrator rights or Developer Mode**, so on
this machine use the import.

Note also that `/init` can read an existing `AGENTS.md` and other tools' rule files when generating
`CLAUDE.md`, and `/import` can pull another agent's configuration in wholesale — so adopting a second
tool later costs very little. There is no benefit to pre-empting it now.

---

## 5. Conventions for these definitions

1. **Read-only unless writing is the point.** `pipeline-triage` and `leakage-auditor` are auditors;
   giving them `Edit` would change what they are for.
2. **`memory: project`** for agents whose value compounds across the season — recurring failure
   signatures, historical metric baselines. Committed, so it survives machine changes.
3. **Preload domain skills** with `skills:` rather than hoping the agent finds them. `backtest-analyst`
   needs `fpl-rules` in context to interpret anything.
4. **One mandate per agent.** `leakage-auditor` is effective because it does one thing. An agent asked
   to audit leakage *and* suggest improvements will do the second and skim the first.
5. **Model and effort matched to the job.** Opus at high effort for judgement work; Sonnet for
   mechanical log reading.
6. **Instruct honest reporting explicitly.** Both audit agents carry a standing instruction to lead
   with bad news. Without it, summaries drift towards the reassuring.
