# E12 — Data Widening for Priors

**Objective:** OBJ-1 · **Target:** feeds E10/E11, low urgency · **Estimate:** 3–4 days
**Depends on:** E9-S2 (fixtures in the backtest) · **Implements:**
[Model Improvement Plan §3 D2, D4, D5](../05-model-improvement-plan.md) · **Resolves:** Q-13
**Status:** Planned

---

## 0. Why a separate epic for data

The forecast is **signal-starved, not under-modelled.** The official feed's own `expected_goals` /
`expected_assists` are the only advanced signals reaching the model; every scraped or purchased source
is blocked ([D-23](E0-steel-thread-gw1.md#6-technical-debt-register): Understat `robots.txt` disallows
scraping, FBref returns Cloudflare 403). This epic recovers most of the lost modelling intent **from
sources already permitted** — no new scraping, no `robots.txt` fight.

It is kept separate from the modelling epics because its work is a different kind: reconstruction and
reference-data curation, whose value shows up only once E10 and E11 consume it. It is low-urgency by
design — a widened training window compounds over a season, so it earns its place in leverage terms
but never blocks a deadline.

**What is deliberately not pursued.** Re-attempting Understat/FBref against an explicit
`robots.txt`/Cloudflare refusal (NFR-10, D-23). The refusals are respected, not worked around; the
value is re-tested only if a polite, permitted path appears.

## 0.1 Gate

The backtest-graded stories (S1, S3) require [E9-S2](E9-forecast-delivery-and-backtest-fidelity.md) —
a widened window is only demonstrably better on a harness that can grade it. S2 (the reference table)
has no such dependency and can be prepared at any time.

## 1. Stories

### E12-S1 — Reconstruct DefCon history from BPS action counts · 1.5 days · **resolves Q-13**
Defensive Contribution is the best signal-to-noise component in the design (M4), yet it exists for
**one season only** and is absent from ~half the current backtest window
([DL-21 caveat](../00-decision-log.md#dl-21)). FPL recorded tackles/CBI in the **BPS breakdown** long
before it scored DefCon — so the history can be reconstructed from data already in silver, with **no
new source**.

- Reconstruct per-player DefCon-equivalent counts from the historical BPS action breakdown, under the
  scoring-regime table in [E2-S3](E2-data-platform.md) (the 2026/27 rules applied to historical
  actions, not historical DefCon points that did not exist).
- This is the input D5 (S3) needs, and it strengthens M4 across the window E10 grades against.

**Acceptance:** DEF and DM Spearman improve with M4 present across the widened window rather than the
one season it currently covers.

### E12-S2 — Penalty and set-piece duty reference table · 0.5 day · **D4** · pairs with [E10-S3]
A small, **committed** config/reference file naming penalty and set-piece takers, hand-maintained.
Penalties are large, lumpy, highly identifiable points and a primary way the elite separate; they are
currently unmodelled (Design §M3).

- Because it is a committed reference file and not a data source, **no Invariant-1 or scraping
  question arises** — it is curated knowledge, like the rules seed, not an ingested feed.
- E12 owns the file and its maintenance discipline; [E10-S3](E10-discrimination-at-the-head.md) owns
  the model term that consumes it.

**Acceptance:** the file exists, is documented, has an owner-maintenance note, and is the single
source the E10 duty term reads.

### E12-S3 — Re-measure the prior-season prior with real advanced history · 1 day · promotes `prior_season`
`features.prior_season` is built but **dark**. The [DL-31](../00-decision-log.md#dl-31) probe moved
Spearman by ~0.001 — but it used official-feed *totals* as a stand-in, not xG/DefCon. S1 changes the
input, so the probe is worth repeating with real advanced history.

- Depends on S1 (real DefCon history) and ideally on an unblocked xG source; runs against the
  fixture-aware backtest.
- **Promoted only if it earns its place with the real inputs** (DP-08). A second ~0.001 result is a
  finding — the prior stays dark and that is recorded, not tuned around.

**Acceptance:** backtest, per DP-08 — the prior-season prior is promoted only on a measured
improvement with real xG/DefCon inputs; otherwise it stays dark with the null result recorded.

## 2. Definition of done

- [ ] DefCon history reconstructed from the BPS breakdown under the 2026/27 regime — **Q-13 resolved**
- [ ] M4 present across the widened backtest window, with DEF/DM Spearman improvement reported
- [ ] Penalty/set-piece duty reference table committed, documented, owner-maintained (**D4**)
- [ ] Prior-season prior re-measured with real inputs and either promoted on evidence or left dark
      with the null result recorded (DP-08)
- [ ] No new scraping introduced; D-23's refusals remain respected

## 3. The honest question

**"Did more data actually move the number, or did it just feel like progress?"** The DL-31 probe is
the cautionary tale in this repo: a plausible signal moved Spearman by a rounding error. Every story
here is gated on a measured gain precisely so that "we added data" is never mistaken for "the forecast
got better".
