# Releases and epics — the plan of record

Work is delivered in releases numbered `Rx.y.z`. **R1.0** was the first build: epics E0–E14,
archived in [`../archive/R1.0/`](../archive/README.md) — all but E8, which stays live here as the
ongoing in-season monitoring epic. **R1.1.0**, the data pipeline uplift, is closed and archived in
[`../archive/R1.1.0/`](../archive/README.md), and **R1.1.1** verified it on `main`. **R1.2.0**, the
first slice of the modular platform, is tagged; R1.2.1 is a hotfix and **R1.2.2**, the second slice, is tagged; **R1.3.0** is open, not started. Each release and epic records its outcome in its Status line and the decisions it took in [`docs/decisions/`](../../decisions/README.md).

## Register

| Release | Plan | Status |
| --- | --- | --- |
| **R1.2.0** — the registry slice | [Modular platform backlog](R1.2.0-modular-platform-backlog.md) §2, first drop: MOD-01 started, MOD-03, MOD-02, MOD-04, MOD-07; design in [05](../05-target-architecture.md), set by [DL-86](../../decisions/DL-86.md) and [DL-87](../../decisions/DL-87.md) | Tagged 2026-10-23 ([DL-87](../../decisions/DL-87.md)) |
| **R1.2.1** — hotfix | The prospective job's scoring step creates `raw/` before the frozen `score.py` writes into it ([DL-88](../../decisions/DL-88.md)) | Hotfix from `main` |
| **R1.2.2** — five models live | The same backlog §2, second drop: the archive and football-data.co.uk live, MOD-05, MOD-08, MOD-09, MOD-06; MOD-01 closed | Tagged 2026-10-23: all five strategies live, the frozen harness retired (switch GW8), F1 shipped ([DL-90](../../decisions/DL-90.md)), F3 rejected ([DL-91](../../decisions/DL-91.md)) |
| **R1.2.3** — hotfix | Purchase prices are what was paid; an unknown one never overstates the budget ([DL-92](../../decisions/DL-92.md)) | Tagged 2026-10-23 |
| **R1.2.4** — hotfix | Training rows refresh once a gameweek is checked; a warning gate for lagging rows; dependencies pinned in `pipeline/requirements.lock` ([DL-93](../../decisions/DL-93.md)) | Tagged 2026-10-23 |
| **R1.3.0** — gameweek orchestration | [R1.3.0 gameweek orchestration](R1.3.0-gameweek-orchestration.md): ORC-01 … ORC-10 and WEB-02, in two drops ([DL-94](../../decisions/DL-94.md)) | Open on `dev/R1.3.0`; planned, not started |
| **R1.4.0** — independent web | [R1.4.0 independent web](R1.4.0-independent-web.md): WEB-01 … WEB-06 | Planned after R1.3.0; plan drafted 2026-10-23, awaiting the owner's answers |
| Ongoing, every season | [E8 — ongoing in-season monitoring](E8-ongoing-in-season-monitoring.md): the season state and decision points (rewritten each gameweek), the weekly loop, the bar for changing the model mid-season | Live, GW1 → 30 May 2027; updated weekly |

**Planning a release.** Write `Rx.y.z-<slug>.md` here — its stories, acceptance boxes and Status
line — add its row, and record the decision to build it in a DL entry. When it closes, fill its
Status line, `git mv` it and any epics it owns into `../archive/Rx.y.z/`, add them to the archive
index, and run `python scripts/docs.py check` to find the links to re-point
([documentation rules](../../agents/documentation.md)).

## Branching and releases

[DL-80](../../decisions/DL-80.md), [DL-82](../../decisions/DL-82.md). The step-by-step procedure, with commands, is the
`release` skill (`.claude/skills/release/SKILL.md`).

```
feature/<description> ──merge──► dev/Rx.y.z ──PR──► pre-release ──PR──► main ──► tag Rx.y.z
 (kept until the tag)            (the release)      (main + promotion;  (production; merge deploys;
                                                     CI + site smoke)    tag publishes the Release)
hotfix: feature/<fix> from main ──PR──► pre-release ──PR──► main ──► tag Rx.y.(z+1) ──► merge main into dev/Rx.y.z
```

| Branch | Role |
| --- | --- |
| `main` | Production: scheduled workflows run its code and every merge deploys. Pull requests from `pre-release` only; one annotated tag per release |
| `pre-release` | `main` plus the promotion under test; brought level with `main` before each promotion. CI and `pre-release.yml`'s smoke test run on it |
| `dev/Rx.y.z` | The open release (now `dev/R1.3.0`), cut from `main` when the release starts; deleted after its tag exists |
| `feature/<description>` | One feature or fix, from the open `dev/Rx.y.z`, merged into it directly after the local checks pass; deleted once the release is tagged. A hotfix branches from `main` and goes by pull request into `pre-release` |

`main` and `pre-release` accept changes only by pull request with passing checks. A release's number
is chosen when its dev branch is cut: `y` for a planned release, `z` for a hotfix, `x` for a change of
direction.

## Choosing what to build next

Ask, before starting each piece of work:

> **"What is the biggest regret I would have at the next deadline?"**

Then pick the smallest piece of work that removes it. When the answer is not obvious, score it:

| Factor | Scale | Meaning |
| --- | --- | --- |
| **Deadline regret** | 0–5 | Cost of not having this at the *next* deadline |
| **Season leverage** | 0–5 | How much it compounds across the remaining gameweeks |
| **Confidence** | 0–5 | How sure you are it delivers the value claimed |
| **Cost** | days | Focused build days |

```
priority = (2 × deadline_regret + season_leverage × (gameweeks_left / 38) × 3 + confidence) / cost
```

The `gameweeks_left / 38` term does the important work: early in the season compounding improvements
(a better model, more data) outrank convenience; late on, only what affects the next few deadlines
is worth starting. **After roughly GW30, stop building and just play.**

### Re-rank immediately when

| Trigger | Effect |
| --- | --- |
| A deadline was missed, or nearly missed | Automation and scheduling jump to the top |
| Data went stale or an adapter broke | Quality gates and the adapter jump |
| The model made a visibly bad call twice running | The forecast jumps; trust it less meanwhile |
| GW15 arrives with chips from set 1 unused | Chip planning is urgent — set 1 expires at the GW19 deadline |
| A blank or double gameweek is announced | Fixture-structure handling jumps |
| More than 30 minutes went on manual research | Whatever would have automated it jumps |
| A quality gate blocked publication and was overridden | Stop. Fix the gate or the data — never normalise the override |

### Dated decision points

The season's dated decision points (chip set 1 by GW15 and its GW19 expiry, the mid-season
investment, the ~GW30 stop) and their outcomes live in
[E8's season state](E8-ongoing-in-season-monitoring.md#decision-points), updated as each one passes.

Every model change, whatever its rank, clears the
[E8 §5 bar](E8-ongoing-in-season-monitoring.md#5-the-bar-for-changing-the-model-mid-season) before it is
promoted ([DP-08](../../guiding-principles.md#dp-08--new-behaviour-ships-dark-and-is-promoted-on-evidence)).
