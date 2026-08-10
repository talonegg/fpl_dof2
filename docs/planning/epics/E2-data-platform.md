# E2 — Data Platform Hardening

**Objective:** OBJ-1, OBJ-4, NFR-06, NFR-07 · **Target:** ~GW6 · **Estimate:** 4.5–6.5 days
**Depends on:** E0 · **Repays debt:** D-06, D-11

---

## 0. Build outcome — 2026-08-11

All seven stories are built. Three findings changed the work.

**The endpoint catalogue was wrong in two places.** `set-piece-notes/` 404s; the endpoint lives at
`team/set-piece-notes/`. `element-status/` no longer exists at all. Both are now asserted by live
contract tests, including one that fails if the *old* path ever starts working again.

**E2-S3's premise no longer held.** It assumed it would extend an archive ingested in E0-S3, which
[DL-18](../00-decision-log.md#dl-18) had removed. Re-checking against the API produced a worse
answer than expected: **the official API publishes no per-gameweek data for any prior season at
all.** E3 cannot start without it, so a second source adapter was admitted —
[DL-19](../00-decision-log.md#dl-19).

**The gates caught a real inconsistency in our own test fixture** on their first run: an eight-club
recorded league whose fixture list still referenced twenty clubs. That is the sort of thing the
referential class exists for, and it found it immediately.

**A fifth element type.** 2024/25 carried Managers as `element_type` 5 for the Assistant Manager
chip; 2026/27 publishes four types. Managers are dropped from the backfill rather than mapped onto
a position — they have no minutes and would pollute every per-90 rate.

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

### E2-S3 — Historical backfill · 1 day · FR-06 · repays D-11
Prior seasons of per-gameweek data for model training and backtesting — the input E3 cannot start
without. Extends the 2025/26 archive already ingested in E0-S3. Ingest once, snapshot, treat as static.

**Three seasons is fewer than it sounds, and the plan must say which components each one can train.**
Defensive Contribution arrived in 2025/26 and the BPS matrix was revised for 2026/27, so:

| Component | Usable training seasons | Why |
| --- | --- | --- |
| Minutes, goals, assists, clean sheets, saves, cards | **All available seasons** | Regime-invariant. These are the same events they always were |
| Defensive Contribution (M4) | **2025/26 only** — unless [Q-13](../04-conceptual-design.md#15-open-design-questions) succeeds | The component did not exist before. Q-13 asks whether the underlying action counts can be reconstructed from BPS records for earlier seasons, which would widen this from one season to several |
| Bonus (M8) | **None, directly** | *No* season used the 2026/27 BPS matrix. This is why M8 is modelled structurally — expected BPS computed from expected actions — rather than learned from historical bonus. Training M8 on past bonus would bake in a scoring regime that no longer exists |

Backfilling three seasons is still worth doing: it is most of the model. It just is not three seasons
of *everything*, and a backtest that quietly assumes otherwise will overstate its own evidence.

**Acceptance:** at least three prior seasons available as validated silver tables; the per-component
usability table above recorded alongside them; the scoring-regime caveats from the `fpl-rules` skill
carried into the model cards, not just the data docs.

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
produced it. Replay reproduces a **byte-identical silver layer, the same objective value within
tolerance, and the same published decisions** — the logical-reproducibility form of NFR-06, not the
byte-for-byte claim the charter carried at v1.0.

### E2-S7 — Chip expiry tracker · 0.5 day · OBJ-4

Not an optimiser. A **deliberately dumb insurance policy** against a dated, irreversible loss.

Chip set 1 expires at the **GW19 deadline, 13:30 GMT Sat 2 Jan 2027**, and unused chips are simply
gone. The real chip planner is [E4-S3](E4-decision-engine.md#e4-s3--chip-modelling--2-days--fr-20--repays-d-04),
which sits last in the epic sequence and depends on E3. If either slips — and
[ASM-8](../01-project-charter.md#8-assumptions) has no slack — the thing that gets lost is four chips.

So the tracker ships here, months early, and costs half a day:

- Which chips remain in set 1, and how many gameweeks until expiry
- A blunt rule-of-thumb calendar: known double and blank gameweeks, congestion windows, and a
  "latest sensible week to play each remaining chip" derived from fixture structure alone
- **An escalating warning on the dashboard and in the weekly output** from GW12, becoming
  unmissable from GW16

**Acceptance:** it is impossible to reach the GW19 deadline with an unused set-1 chip without having
been told, repeatedly, in the weekly output. Superseded — not deleted — by E4-S3 when that lands.

## 3. Definition of done

- [x] All FPL endpoints ingested, each with a contract test (`pytest --network`)
- [x] Quality gates across all four classes, with blocking behaviour proven by test — injected
      corruption of each kind is shown to stop publication
- [x] Prior seasons backfilled and validated, with per-component usability recorded
- [x] Price and ownership history accumulating — appended, never rebuilt
- [x] Manifest records per-source status, row counts, gate results and output checksums
- [ ] **Logical reproducibility demonstrated by replaying a past run** — the manifest carries
      everything needed; the replay itself is not yet automated
- [x] Chip expiry tracker live, reading expiry from the API rather than assuming GW19
- [x] **D-11 re-scoped, not closed.** The archive widens minutes, goals, assists, clean sheets,
      saves and cards to four seasons. Defensive Contribution still exists in 2025/26 alone
