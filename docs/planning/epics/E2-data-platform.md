# E2 — Data Platform Hardening

**Objective:** OBJ-1, NFR-06, NFR-07 · **Target:** ~GW6 · **Estimate:** 4–6 days
**Depends on:** E0 · **Repays debt:** D-06

---

## 1. Why

The steel thread's data layer works but is not yet trustworthy. It has schema validation and nothing
else — no freshness checks, no volume anomaly detection, no history for training, and only one
contract test. E2 turns "it produced output" into "the output can be relied on", which is the
precondition for every model improvement that follows.

## 2. Stories

### E2-S1 — Complete the FPL adapter · 1 day
Remaining endpoints: `event/{gw}/live/` (per-gameweek actuals including BPS), `set-piece-notes/`,
`leagues-classic/{id}/standings/`. Extends FR-01 to full coverage.

**Acceptance:** every endpoint in the `fpl-api` skill catalogue is ingested or explicitly recorded as
out of scope.

### E2-S2 — Full quality gate framework · 1.5 days · FR-08
Four assertion classes, per [Design §3.4](../04-conceptual-design.md#34-quality-gates-fr-08):
schema, range, referential integrity, and freshness-and-volume. Severity model — `error` blocks
publication, `warn` publishes and surfaces, `info` records. Each gate names the requirement it protects.

**Acceptance:** injected bad data demonstrably blocks publication; the last good artefact stays live;
gate results land in the manifest. **Testing the gate itself is the story, not an extra.**

### E2-S3 — Historical backfill · 1 day · FR-06
Prior seasons of per-gameweek data for model training and backtesting — the input E3 cannot start
without. Ingest once, snapshot, treat as static.

**Acceptance:** at least three prior seasons available as validated silver tables, with the
scoring-regime caveats from the `fpl-rules` skill recorded alongside them.

### E2-S4 — Contract tests for every endpoint · 0.5 day · R-02
Recorded-response tests so upstream schema drift is caught in CI rather than at a deadline.

### E2-S5 — Price and ownership history · 0.5 day · FR-09
Daily price and ownership tracking, so price-change exposure and effective ownership become
computable. Feeds E1 alerts and E4's risk objective.

### E2-S6 — Run manifest and lineage · 1 day · NFR-06/07
Complete the manifest from [Design §12.2](../04-conceptual-design.md#122-run-manifest): per-source
status, row counts and deltas, gate results, model versions, solver status, output checksums. Append
metrics to a history table so drift becomes visible.

**Acceptance:** any published output is traceable to the exact snapshots, commit and config that
produced it (NFR-06).

## 3. Definition of done

- [ ] All FPL endpoints ingested, each with a contract test
- [ ] Quality gates across all four classes, with blocking behaviour proven by test
- [ ] Three-plus prior seasons backfilled and validated
- [ ] Price and ownership history accumulating daily
- [ ] Manifest complete; reproducibility demonstrated by replaying a past run
