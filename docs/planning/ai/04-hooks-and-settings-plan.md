# Hooks and Settings Plan

**Part of:** [AI Tooling Plan](README.md)

The enforcement layer. Everything in documents 01–03 is *context* — read and usually followed, but
never guaranteed. This document covers the small set of things that must hold every time, and
therefore cannot live in an instruction file.

---

## 1. The distinction that matters

The Claude Code documentation is unambiguous: `CLAUDE.md` and rules are context, not enforced
configuration. Hooks execute as shell commands at fixed lifecycle events regardless of what the model
decides.

So the question for every project invariant is: **what happens if it is missed once?**

| If missed once… | Mechanism |
| --- | --- |
| Mildly annoying, obvious in review | Instruction file |
| Silently wrong, invisible in review, expensive later | **Hook or CI gate** |

Three of this project's seven invariants fall in the second category:

| Invariant | Why context is insufficient |
| --- | --- |
| Source isolation (`sources/` dependency rule) | A stray import compiles, passes tests, and quietly destroys the extensibility guarantee the whole architecture rests on. Nobody notices until the fourth data source is painful to add |
| No secrets in the repo or client bundle | A leaked key in a private repo is still a leaked key, and git history is forever |
| No look-ahead in features | Produces a model that looks better, so there is no error signal pulling anyone towards catching it |

The third cannot be reliably automated — hence the `leakage-auditor` subagent — but the first two can.

---

## 2. Recommended hooks

Four. Configured in `.claude/settings.json` (committed) via the `update-config` skill rather than by
hand-editing, so the schema stays valid.

### H1 — Format on write · Phase 0

**Event:** `PostToolUse` on `Edit`/`Write`
**Action:** run the Python formatter on changed `.py` files, the JS/TS formatter on changed
`web/**` files.

Removes an entire category of pointless diff noise and review comments. The cheapest hook to add and
the one with the highest nuisance-reduction per line of config.

### H2 — Import-lint gate · Phase 1 · **the important one**

**Event:** `PostToolUse` on `Edit`/`Write` matching `pipeline/src/fpl_dof/**/*.py`
**Action:** run the import-contract check; on violation, return the failure so it surfaces immediately.

This is the structural enforcement of [Invariant 1](01-claude-md-plan.md#2-root-claudemd--draft) and
of FR-04. The contract to enforce:

| Layer | May not import |
| --- | --- |
| `transform/`, `features/`, `models/`, `optimise/`, `publish/` | `sources/` — anything at all |
| `optimise/` | `models/` — consumes typed outputs only |
| `rules/` | Everything except the standard library and config types — it must stay pure |

The same check runs in CI, so the hook is a fast local signal rather than the only line of defence.
The hook catches it in seconds; CI catches it if the hook is bypassed.

### H3 — Secret scan before commit · Phase 0

**Event:** `PreToolUse` on `Bash` matching `git commit`
**Action:** scan staged content for key patterns and known secret shapes; block on a hit.

NFR-13. Cheap insurance, and the failure it prevents is unrecoverable — history rewriting after a
push is never clean.

### H4 — Deadline guard · Phase 5

**Event:** `PreToolUse` on `Bash` matching the publish or deploy command
**Action:** if the next gameweek deadline is inside 45 minutes, warn loudly and require explicit
confirmation.

Encodes the "never last-minute" rule from [Design §9](../04-conceptual-design.md#9-orchestration) at
the one moment it is most likely to be forgotten — when someone is rushing before a deadline, which
is precisely when a bad publish is most damaging.

### Deliberately not hooks

| Considered | Why not |
| --- | --- |
| Run the full test suite on every edit | Too slow; kills the working rhythm. CI's job |
| Block edits to `docs/planning/` | The docs are meant to evolve with the code |
| Auto-commit | Removes the review step that catches the things hooks cannot |
| Enforce requirement IDs in commit messages | Mechanical compliance would follow; useful traceability would not. Leave it as a convention |

---

## 3. Settings

### `.claude/settings.json` — committed

Hooks, plus a permissions allowlist for the routine read-only commands this project runs constantly.
The point is to cut prompt fatigue on safe operations so that a prompt actually means something when
it appears.

Candidates for `permissions.allow`, once the toolchain is fixed in Phase 0:

- Test, lint and type-check invocations
- Read-only `git` — `status`, `diff`, `log`, `branch`
- The pipeline's own read-only stages, run locally
- The web dev server and build

Everything that writes outside the repo, publishes, deploys, or touches the network beyond the
declared data sources stays prompting.

Build this with the `fewer-permission-prompts` skill after a few weeks of real use rather than
guessing up front — it derives the allowlist from what has actually been run.

### `.claude/settings.local.json` — gitignored

Machine-specific paths and any personal overrides. Already covered by the `.gitignore` pattern for
`*.local`.

### Environment

`.env` is gitignored. API keys — currently only the odds provider — live in the environment locally
and in GitHub Actions secrets in CI, never in a settings file and never in the repo (NFR-13).

---

## 4. What enforcement does *not* cover

Worth stating plainly, so the hooks are not mistaken for a safety net they are not:

- **Model correctness.** No hook can tell whether an expected-points forecast is any good. That is
  what the backtest and `backtest-analyst` are for.
- **Look-ahead leakage.** Partially detectable by convention checks, not reliably. Hence a dedicated
  auditor agent and the knowability-stamp discipline.
- **Whether a recommendation is sensible.** The human at the deadline is the last check, by design
  (ASM-6).
- **Scope discipline.** Nothing stops a session adding scope. The weekly "one improvement, not three"
  rule is cultural, and it will hold or fail on judgement alone.

---

## 5. Setup order

| Phase | Add |
| --- | --- |
| **P0** | H1 format-on-write · H3 secret scan · initial permissions allowlist |
| **P1** | H2 import-lint gate, alongside the import contract in CI |
| **P5** | H4 deadline guard |
| **Ongoing** | Re-run `fewer-permission-prompts` when prompt fatigue returns |

Add hooks one at a time and confirm each behaves before adding the next. A misconfigured
`PreToolUse` hook that blocks the wrong thing is disproportionately disruptive, and the debugging
loop for hooks is slower than for anything else in this setup.
