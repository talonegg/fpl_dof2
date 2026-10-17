# AI Tooling Plan — FPL DOF

How Claude Code (and any other coding agent) should be configured to build and operate this project.

**Companion to:** the [planning set](../README.md) · **Baselined:** 2026-08-09

---

## Why this exists

FPL DOF is a solo project with a hard weekly deadline, a two-language monorepo, and several
invariants where a quiet mistake is expensive and invisible — a hallucinated scoring value, a
look-ahead leak in a feature, an adapter that reaches into the model layer. Most of the build will be
AI-assisted, across many sessions, over ten months.

The purpose of this plan is to make the **project's invariants structural rather than remembered**.
An agent starting a fresh session in February should be unable to get the scoring table wrong, unable
to put source-specific code outside `sources/`, and unable to ship a model change without a
leakage check — without anyone having to remember to say so.

## The documents

| # | Document | Covers |
| --- | --- | --- |
| 01 | [CLAUDE.md and rules plan](01-claude-md-plan.md) | Root `CLAUDE.md` (full draft), the seven path-scoped `.claude/rules/` files, and what deliberately does *not* go in them |
| 02 | [Skills plan](02-skills-plan.md) | Fourteen candidate skills, specified and phased — with an honest cut down to the three worth creating before any code exists |
| 03 | [Subagents plan](03-agents-plan.md) | The three subagents that earn their cost, why the rest do not, and the `AGENTS.md` decision |
| 04 | [Hooks and settings plan](04-hooks-and-settings-plan.md) | The enforcement layer: what must be a hook because context alone will not hold it |

---

## Choosing the right mechanism

The four mechanisms differ mainly in **when they load** and **whether they are advisory or enforced**.
Choosing wrongly is the most common way these setups go bad: everything ends up in `CLAUDE.md`, the
file grows past 200 lines, adherence drops, and the rules that matter get lost among the ones that
do not.

| Mechanism | Loads | Enforced? | Right for |
| --- | --- | --- | --- |
| **`CLAUDE.md`** | Every session, always in context | No — advisory | Universal facts and non-negotiables that apply to *every* task: commands, layout, the handful of invariants |
| **`.claude/rules/*.md` with `paths:`** | When Claude reads a matching file | No — advisory | Conventions for one layer — adapters, models, optimiser, web. Costs nothing until that layer is touched |
| **`.claude/skills/<name>/SKILL.md`** | On demand, model- or user-invoked | No — advisory | Multi-step procedures and long reference bodies. The body is free until invoked |
| **`.claude/agents/*.md`** | When delegated a task | No — advisory, but tool access *is* enforced | Side quests that would flood the main context with output nobody will re-read |
| **Hooks in `settings.json`** | At fixed lifecycle events | **Yes — executed regardless** | Anything that must hold every time: formatting, lint gates, blocking a forbidden edit |

**The decision rule used throughout this plan:**

```
Is it a fact true in every session?              → CLAUDE.md
Is it a convention for one layer or file type?   → .claude/rules/ with paths:
Is it a procedure or a reference body?           → skill
Would doing it flood the main context?           → subagent
Must it hold even when the model forgets?        → hook
```

The last line is the important one. The Claude Code documentation is explicit that `CLAUDE.md` is
context, not configuration — Claude reads it and tries to follow it, with no guarantee. **Anything
that must not fail belongs in a hook or in CI, not in an instruction file.** That is why the
dependency rule (`sources/` isolation) appears in `CLAUDE.md` *and* as a rule *and* as an
import-lint gate — advisory where it teaches, enforced where it matters.

---

## Summary of recommendations

| Mechanism | Recommended | Notes |
| --- | --- | --- |
| Root `CLAUDE.md` | **1 file, ~130 lines** | Full draft in [01](01-claude-md-plan.md). Create now |
| `.claude/rules/` | **7 path-scoped files** | One per architectural layer. Create alongside each layer, not up front |
| Skills | **14 specified, 3 built now** | Two domain references plus one procedure. The other 11 wait for the code they describe |
| Subagents | **3** | `backtest-analyst`, `pipeline-triage`, `leakage-auditor`. Built-in `Explore` covers the rest |
| `AGENTS.md` | **Do not create** | Claude Code reads `CLAUDE.md`, not `AGENTS.md`. Single-agent project. Revisit only if a second tool joins — see [03](03-agents-plan.md) |
| Hooks | **4** | Format-on-write, import-lint gate, secret scan, deadline guard |

**The central judgement in this plan: build almost none of it yet.** A skill that documents a
procedure for code that does not exist is fiction, and fiction in an instruction file is worse than
silence — it will be followed. Only the two domain-reference skills are genuinely knowable today,
because they describe external realities (the FPL rules and the FPL API) rather than this codebase.

---

## Build sequence

Aligned to the [epic register](../epics/README.md#2-epic-register), which replaced the phase plan
under [DL-10](../00-decision-log.md#dl-10--build-a-steel-thread-to-gw1-rather-than-deferring-the-build).

| Epic | AI assets to create | Why then |
| --- | --- | --- |
| **Now (pre-code)** | `fpl-rules` skill · `fpl-api` skill · root `CLAUDE.md` (skeleton) · secret-scan hook | All describe external facts or fixed decisions; none depend on code existing. The secret-scan hook is brought forward because [DL-12](../00-decision-log.md#dl-12--public-repository) made the repository public — every push is world-readable from the first commit |
| **[E0](../epics/E0-steel-thread-gw1.md) Steel thread** | Complete `CLAUDE.md` commands section · `rules/sources.md` · format-on-write hook · permissions allowlist | Commands become real once there is something to run. `rules/sources.md` lands here rather than later because E0 ships **two** sources (FPL plus the 2025/26 archive), so the adapter pattern is already a pattern |
| **[E1](../epics/E1-weekly-operating-loop.md) Weekly loop** | `rules/rules-engine.md` · import-lint hook | The rules module is load-bearing from E0-S4 onward, and the dependency rule is worth enforcing before a third source arrives |
| **[E2](../epics/E2-data-platform.md) Data platform** | `add-data-source` skill · `pipeline-triage` agent | Onboarding a source is the first genuinely repeated procedure |
| **[E7](../epics/E7-automation-and-hosting.md) Automation** | `rules/workflows.md` · `deadline-run` skill · deadline guard hook | Operational skills need the operation to exist |
| **[E3](../epics/E3-expected-points-engine.md) Expected points** | `rules/models.md` · `add-model-component` skill · `run-backtest` skill · `backtest-analyst` agent · **`leakage-auditor` agent** | Leakage becomes possible the moment features exist — and E3-S2 builds the feature store, so the auditor must exist by then, not after |
| **[E4](../epics/E4-decision-engine.md) Decision engine** | `rules/optimise.md` · `milp-patterns` skill · `add-optimiser-constraint` skill | MILP conventions are worth writing down after the first constraint set works, not before |
| **[E6](../epics/E6-web-application.md) Web app** | `rules/web.md` · `rules/contracts.md` · `change-data-contract` skill · `new-app-view` skill | Frontend conventions emerge from the first two screens. `rules/contracts.md` must cover the **cross-language rules conformance test** ([DL-14](../00-decision-log.md#dl-14--the-web-data-contract-carries-the-rules-configuration)) — two validators, one definition |
| **[E8](../epics/E8-in-season-operations.md) In-season** | `gameweek-review` skill | The weekly ritual, written down once it has been done a few times |

**Rule of thumb applied throughout:** write the instruction the *second* time you find yourself
explaining something, not the first. The first time is an observation; the second is a pattern.

---

## What good looks like

- A fresh session can run the pipeline, find the docs and understand the invariants from
  `CLAUDE.md` alone, in under 130 lines.
- Working on an adapter automatically loads adapter conventions, and nothing else.
- Nobody has typed the FPL scoring table into a chat window since August.
- An import that breaks the dependency rule fails before it is committed, not in review.
- `/gameweek-review` runs the same weekly loop in May that it ran in September.
