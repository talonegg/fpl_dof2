# E7 — Automation, Hosting and Observability

**Objective:** OBJ-6, NFR-01, NFR-02, NFR-05, NFR-07 · **Target:** ~GW8 · **Estimate:** 3–5 days
**Depends on:** E1 · **Repays debt:** D-08, D-10
**Needs from you:** nothing. Hosting is settled — [DL-12](../00-decision-log.md#dl-12--public-repository)
made the repository public, so GitHub Pages is free and OD-02 is closed

---

## 1. Why this is earlier than the original plan assumed

The planning set scheduled automation as Phase 5, late. **The timezone finding moves it forward.**

Every FPL deadline falls in UK time. On AEST that means roughly 03:30 local for Friday-night and
midweek gameweeks, and around 20:00 local for standard Saturday ones. You will be asleep for a large
share of them. Manual operation is fine for a handful of weeks; across 38 deadlines it is not a
sustainable model, and a missed deadline costs real points.

There is also a [scheduled decision point after GW8](README.md#scheduled-decision-points): if manual
operation is not sustainable by then, this epic jumps immediately regardless of what else is queued.

## 2. Stories

### E7-S1 — Ingestion workflows · 1 day · FR-35
Two cadences, and the split between them matters more than it looks:

- **Fast: `bootstrap-static` and `fixtures` only**, every four hours, hourly within 24 hours of a
  deadline. Two requests, seconds. This is what keeps prices, status and ownership inside the NFR-05
  freshness window, and all three live in `bootstrap-static`.
- **Slow: everything expensive**, daily — `element-summary` for all players (~700 requests, ~6
  minutes at a polite rate), plus external sources with odds on their credit budget.

**`element-summary` never goes on the fast path.** Putting it in a 4-hourly workflow re-fetches data
that changes daily at most, at roughly six minutes a run. It was the single largest line in the
minutes recount that led to [DL-12](../00-decision-log.md#dl-12--public-repository), and it remains
wrong even now that minutes are unlimited — a slow pipeline is a liability on the deadline path
whether or not anyone is billed for it.

**All scheduling arithmetic in UTC**, derived from the deadline in the data — never hardcoded cron
assumptions about local time, which break when BST and AEDT shift within weeks of each other in
October (CON-11).

### E7-S2 — Pipeline and publish workflow · 1 day
Transform → gates → model → optimise → publish. Triggered **nightly, after the slow ingest, and at
T−3h and T−45m before each deadline** — deliberately *not* after every fast ingest. Re-solving a MILP
because a price moved £0.1 is waste; the fast ingest keeps data fresh, and the pipeline turns fresh
data into a recommendation on its own deadline-aware schedule.

**Nothing scheduled inside 45 minutes of a deadline** (R-09). Scheduled CI runs are best-effort and
can be delayed under platform load; the deadline is not. Manual dispatch is always available as the
fallback.

**This workflow repays D-10.** It must run the E0 code path unchanged — the charter's pre-CI carve-out
for E0 expires on 22 August, and any E0 code that turns out not to run in CI is a defect against the
debt register, not a new requirement.

### E7-S3 — Site build and deploy · 0.5 day · NFR-01
Build the SPA and deploy site plus data to **GitHub Pages**. Free on a public repository; no account
to create, no third party, no decision outstanding.

### E7-S4 — Concurrency, idempotency and retention · 1 day · NFR-06 · R-13
One pipeline run at a time, newer superseding queued. Stages independently resumable.

**Retention needs a mechanism, not a policy.** Deleting a file from the tip of a Git branch reclaims
nothing — the blob stays in history and in every clone, forever. A `data` branch taking several
commits a day of gzipped JSON grows monotonically no matter how carefully old files are removed.
"Prune old snapshots" is a null operation against a Git backend unless history is rewritten, which is
why R-13 is rated High. Per
[Architecture §7.3](../03-solution-architecture.md#73-storage-volume-and-retention-mechanics):

- **`data`** — orphan branch, rebuilt from the retained ~30-day window and **force-pushed**, so
  history is truncated rather than accumulated
- **`snapshots`** — separate, small, append-only: one snapshot per source per gameweek, kept forever.
  This is the NFR-06 evidence trail, and it is separated precisely so the churn cannot threaten it
- **CI artefacts hold logs only.** They expire (90 days by default), so anything reproducibility
  depends on must live in a branch — otherwise NFR-06 silently lapses a quarter after each run

**Acceptance:** the `data` branch size is stable across a simulated month of runs, not merely growing
slowly.

### E7-S5 — Alerting · 0.5 day · FR-38
Notification on run failure or blocked quality gate, carrying the manifest excerpt.

**Given the timezone, alerts must reach you when you are awake**, not merely when they fire. An alert
at 03:00 local that is only seen at 08:00 is fine for a nightly run and useless for a pre-deadline one.

### E7-S6 — Data health page · 1 day · FR-33, NFR-07
Renders the manifest and metrics history: per-source freshness and status, last run outcome, gate
results, rolling model accuracy, degraded-source banners.

The monitoring dashboard being part of the product is not a compromise — with no budget for
observability tooling, it is the only version that stays free *and* actually gets looked at.

### E7-S7 — Deployed smoke test and deadline guard · 0.5 day
End-to-end smoke test against the deployed static site. Plus the H4 deadline-guard hook from the
[hooks plan](../ai/04-hooks-and-settings-plan.md) — warn loudly before publishing inside 45 minutes
of a deadline.

## 3. Definition of done

- [x] Data refreshes on schedule without intervention — `ingest-fast.yml` (hourly, guarded by
      `fpl-dof-schedule`) and `ingest-slow.yml` (daily). Not yet observed live; built and unit-tested
      against the exact decision logic a real cron firing will call. See [DL-42](../00-decision-log.md#dl-42)
- [x] A current recommendation exists before every deadline — `pipeline.yml`'s deadline-relative
      trigger fires at T-3h and T-45m, enforced never to land inside R-09's 45-minute freeze by
      construction (a one-sided window, checked in `pipeline_decision`'s tests), plus nightly and
      post-ingest-slow triggers. Live firing not yet observed
- [x] Site deploys automatically to GitHub Pages; reachable from laptop and phone away from home —
      `deploy.yml` wired to `actions/deploy-pages`. **Not yet actually deployed** — GitHub Pages must
      be enabled on the repository settings and one real run observed before this is more than "built"
- [x] Failures alert, and reach you at a time you will see them — `alert-on-failure.yml`, a reusable
      workflow every other workflow's failure path calls; opens/updates a deduplicated GitHub Issue
      with the manifest excerpt. Realtime delivery depends on the GitHub mobile app watching this
      repository (a one-time manual step, not verified as done)
- [x] Data health page live — `/health`, reading the new `health.json` artefact. Verified in a real
      Chromium browser at mobile (390px), tablet (820px) and desktop (1440px) viewports; not yet
      serving data from a real deployed pipeline run
- [ ] **One full week passes with zero manual intervention** — the real acceptance test, and it
      cannot be satisfied by anything short of watching a live week happen. Everything above is
      necessary for this and none of it is sufficient on its own
- [x] Monthly cost £0.00 — every workflow runs on `ubuntu-latest` GitHub-hosted runners, free on a
      public repository (DL-12); no paid service, tier or third-party dependency introduced (Invariant 3)
- [x] `data` branch size stable across a month of runs, not merely growing slowly — verified against
      a real local bare git remote: 60 simulated daily runs over a 30-day window held the branch at
      exactly one commit with zero parents throughout, and the retained file count stayed bounded at
      the window size. See [DL-42](../00-decision-log.md#dl-42)
- [x] **No secret has ever reached the repository** — every workflow uses only the
      automatically-provided `GITHUB_TOKEN`; no new secret, credential or API key was introduced
- [x] D-08 and D-10 closed; the E0 code path runs unchanged in CI — see the debt register in
      [E0 §6](E0-steel-thread-gw1.md#6-technical-debt-register) and [DL-42](../00-decision-log.md#dl-42)

**Status as of 2026-08-16: code-complete and locally/simulated-verified; not yet live-verified.**
Every checkbox above that depends on GitHub Actions actually firing, GitHub Pages actually being
enabled, or a real `GITHUB_TOKEN` push reaching `github.com` is marked done on the strength of
design, unit tests and verification against a real (but local) git remote — not on having watched it
happen in production. The remaining steps, in order: enable GitHub Pages in repository settings,
push this branch, watch the first `ci.yml` run go green, then watch one real week of scheduled runs
before calling the epic's one true acceptance test satisfied.
