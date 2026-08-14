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

- [x] Three adapters live, each with a contract test — `sources/understat/adapter.py`,
      `sources/fbref/adapter.py`, `sources/oddsapi/adapter.py`, each with fixture-backed contract
      tests in `tests/test_external_sources.py` (no live network call during tests, per §0 below).
      **Read with one correction (D-23):** the two scraped adapters' fixtures are *hand-constructed*
      pages matching the shape the adapter assumes, not pages recorded from the live sites, so they
      test the parser against its own assumptions. The live Understat page has since stopped
      carrying the script the parser looks for and neither adapter would notice until a run
      degraded — which is what a recorded-page contract test is supposed to prevent
- [x] Entity resolution with override file; unmatched rate gated — `sources/resolve.py`,
      `sources/entity_overrides.yaml`, gate in `quality/rules.py`; `tests/test_entity_resolution.py`
      covers all three tiers plus both hard-failure guardrails (cross-source ID conflict, stale
      override)
- [x] Field precedence configured, not coded — `sources/precedence.py` plus a `PrecedenceConfig`
      section in `config/models.py`; `tests/test_field_precedence.py`
- [x] Fault injection proves graceful degradation for every non-FPL source —
      `tests/test_source_degradation.py`, one test per source for both "raises while fetching" and
      "returns nothing", plus a combined test that losing all three at once still produces a squad
      (stronger than the DoD asks for)
- [ ] **Backtest metrics measurably improve** — **still not met, and the reason has changed again.**
      The consumer D-22 named now exists: the feature store joins `player_metric` on `player_code`
      and feeds prior-season, position-relative ratios into the priors of M3 and M4, with the
      season-label knowability boundary property-tested at both ends
      (`tests/test_prior_season_features.py`, [DL-31](../00-decision-log.md#dl-31)). **D-22 is
      closed and this item still cannot be ticked, for a blunter reason: there is no data.**
      Enabling both scraped sources and running ingest for real returns nothing from either —
      Understat's `robots.txt` now disallows the entire site, and FBref answers every request,
      `robots.txt` included, with a Cloudflare 403. Both refusals are respected rather than worked
      around (NFR-10). A mechanism probe using the official feed's own prior-season totals in place
      of the missing ones moves the model by ~0.001 Spearman, so there is no evidence the *design*
      is where the value was either. Opened as **D-23**; the odds half of D-20 remains an external
      blocker for want of an `ODDS_API_KEY`
- [x] **Adapter abstraction verified: nothing outside `sources/`, config and tests changed** —
      checked via `git diff --name-only HEAD -- pipeline/src/fpl_dof | grep -Ev '/(sources|config)/|/tests/'`
      against the pre-E4/E5 tree; the only hits are `silver/tables.py` (new canonical tables the
      schemas must live in per Invariant 1/9 — conformance is in `sources/`, canonical shape is in
      `silver/` by design) and `quality/rules.py` (the unmatched-rate gate). No source name
      (`understat`, `fbref`, `oddsapi`) appears anywhere outside `sources/`
- [x] Attribution visible in the UI — `attribution` field on each adapter, carried through the
      provenance pattern already used by `squad.schema.json`
- [ ] D-07 closed — **still not closed.** Entity resolution exists, is tested, and is now correct
      across seasons: a real defect was fixed in this pass, where every crosswalk row was stamped
      with the *current* season whatever season its reference described, which both prevented a
      backfilled advanced row from ever joining an identity and would have failed any multi-season
      backfill on the duplicate-claim guard. But D-07's own text ("harmless now — one source.
      Becomes critical the moment E5 lands") is only retired once the forecast actually consumes a
      second source's data, and no second source can currently be fetched. Left open, narrowed
      again: the remainder is **D-23**, not D-22
