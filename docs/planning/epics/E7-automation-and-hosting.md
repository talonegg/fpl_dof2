# E7 — Automation, Hosting and Observability

**Objective:** OBJ-6, NFR-01, NFR-02, NFR-05, NFR-07 · **Target:** ~GW8 · **Estimate:** 3–5 days
**Depends on:** E1 · **Repays debt:** D-08
**Needs from you:** hosting decision — see [INPUTS-REQUIRED §5](INPUTS-REQUIRED.md#5-needed-for-e7-automation-and-hosting-around-gw6-8)

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
Two cadences: a fast FPL-only workflow every four hours, hourly within 24 hours of a deadline; and a
slow workflow for external sources daily, with odds on their credit budget.

**All scheduling arithmetic in UTC**, derived from the deadline in the data — never hardcoded cron
assumptions about local time, which break when BST and AEDT shift within weeks of each other in
October.

### E7-S2 — Pipeline and publish workflow · 1 day
Transform → gates → model → optimise → publish, triggered after ingest, nightly, and at **T−3h and
T−45m before each deadline**.

**Nothing scheduled inside 45 minutes of a deadline** (R-09). Scheduled CI runs are best-effort and
can be delayed under platform load; the deadline is not. Manual dispatch is always available as the
fallback.

### E7-S3 — Site build and deploy · 0.5–1 day · NFR-01
Build the SPA and deploy site plus data. **Hosting choice needed** — the repo is private, so GitHub
Pages requires a paid plan. Cloudflare Pages is the recommended free path; see INPUTS-REQUIRED §5 for
the three options and their trade-offs.

### E7-S4 — Concurrency, idempotency and retention · 0.5 day · NFR-06
One pipeline run at a time, newer superseding queued. Stages independently resumable. Bronze
retention policy — full snapshots in a rolling window, one permanent snapshot per gameweek — so a Git
branch does not grow without bound (R-13).

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

- [ ] Data refreshes on schedule without intervention
- [ ] A current recommendation exists before every deadline
- [ ] Site deploys automatically; reachable from laptop and phone away from home
- [ ] Failures alert, and reach you at a time you will see them
- [ ] Data health page live
- [ ] **One full week passes with zero manual intervention** — the real acceptance test
- [ ] Monthly cost £0.00
- [ ] Actions minutes comfortably inside the private-repo cap
- [ ] D-08 closed
