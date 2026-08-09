# E5 — External Data Sources

**Objective:** OBJ-1 · **Target:** ~GW12 · **Estimate:** 4–6 days
**Depends on:** E2 · **Feeds:** E3 · **Repays debt:** D-07
**Needs from you:** odds provider API key — see [INPUTS-REQUIRED §4](INPUTS-REQUIRED.md#4-needed-for-e5-external-sources-around-gw10-12)

---

## 1. Why it sits here and not earlier

Richer data only helps if there is a model capable of exploiting it. Adding xG before the
expected-points chain exists means feeding better inputs into a cruder forecast — real cost, little
return. E5 therefore follows E3, and its true test is whether backtest metrics improve once the
extra signals are wired in.

**This epic is also the first real test of the adapter abstraction** (FR-04, DL-05). If adding these
three sources touches anything outside `sources/`, config and tests, the abstraction has leaked and
fixing that is part of the epic, not a follow-up.

## 2. Stories

### E5-S1 — Entity resolution · 1.5 days · FR-07 · repays D-07 · **highest risk in the epic**
The moment a second source arrives, players must be matched across sources. A mismatch silently
attributes one footballer's xG to another and **nothing visibly breaks** — the definition of an
expensive invisible bug (R-10).

Three tiers, per [Design §3.2](../04-conceptual-design.md#32-entity-resolution-fr-07-r-10):
deterministic on normalised name plus club plus position; fuzzy token-set similarity with a high
confidence threshold, accepted only when unambiguous within a club; then a committed, reviewed manual
override file.

**Guardrails:** unmatched rate above threshold fails the quality gate; one canonical ID mapping to two
IDs from the same source fails immediately; resolution re-runs from scratch each season because
transfers invalidate club-based matching.

### E5-S2 — Understat adapter · 1 day · FR-02
Shot-level xG, npxG, xA, shots and key passes. Data is embedded in page scripts rather than served as
an API, so extraction is inherently brittle — contract test against a recorded page, cache hard.

### E5-S3 — FBref adapter · 1 day · FR-02
Progressive actions, shot- and goal-creating actions, box touches, and — most importantly — the
**defensive action counts that model M4 depends on**. Strict crawl delay, `robots.txt` respected,
weekly cadence at most, attributed in the UI (NFR-10). Prefer a wrapper library that already handles
polite access over bespoke scraping.

### E5-S4 — Odds adapter · 1 day · FR-03
Match result and totals markets, de-vigged and converted to team goal expectations feeding M2.

**Credit budget is enforced in the adapter, not by scheduling discipline** (CON-7, R-08). Fixed weekly
schedule plus one pre-deadline refresh; degrade cleanly to the xG-based model when exhausted.

### E5-S5 — Field precedence and degradation · 0.5 day · NFR-15
Per-field source precedence as configuration — minutes and prices always FPL, xG prefers Understat
falling back to FBref. Fault-injection test per adapter proving that killing any non-FPL source
degrades the model without breaking the pipeline.

## 3. Definition of done

- [ ] Three adapters live, each with a contract test
- [ ] Entity resolution with override file; unmatched rate gated
- [ ] Field precedence configured, not coded
- [ ] Fault injection proves graceful degradation for every non-FPL source
- [ ] **Backtest metrics measurably improve** — otherwise the epic has not delivered its purpose
- [ ] **Adapter abstraction verified: nothing outside `sources/`, config and tests changed**
- [ ] Attribution visible in the UI
- [ ] D-07 closed
