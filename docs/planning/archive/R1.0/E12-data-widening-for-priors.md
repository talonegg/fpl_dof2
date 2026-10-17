# E12 — Data Widening for Priors

**Objective:** OBJ-1 · **Target:** feeds E10/E11, low urgency · **Estimate:** 3–4 days
**Depends on:** E9-S2 (fixtures in the backtest) · **Implements:**
[Model Improvement Plan §3 D2, D4, D5](../05-model-improvement-plan.md) · **Resolves:** Q-13
**Status:** Complete. S2 (the duty reference table) landed early to unblock
[E10-S3](E10-discrimination-at-the-head.md). S1 investigated and resolved Q-13 negative — the BPS
action-count breakdown was never publicly captured before 2025/26 ([DL-62](../00-decision-log.md#dl-62--e12-s1-q-13-resolved-negative--the-bps-action-count-breakdown-was-never-publicly-captured-for-seasons-before-202526)).
S3 is consequently blocked on its own precondition and stays dark, DL-31's null result standing
([DL-63](../00-decision-log.md#dl-63--e12-s3-blocked-on-its-own-precondition-the-prior-season-probe-has-no-new-real-input-to-re-measure-against)).

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

**Outcome — 2026-08-22 · resolved negative.** [DL-62](../00-decision-log.md#dl-62--e12-s1-q-13-resolved-negative--the-bps-action-count-breakdown-was-never-publicly-captured-for-seasons-before-202526).
Checked three independent ways — the official API's `history_past` (season totals only, no
per-gameweek historical endpoint exists at all), the cached archive snapshot already in
`data/bronze/`, and a fresh fetch of the same upstream files today — and all three agree: no
per-action breakdown (tackles, CBI, recoveries) was ever publicly captured for any season before
2025/26. The old BPS formula did score these actions internally, but FPL exposed only the
already-summed `bps` integer, never the components. `sources/fplarchive/adapter.py`'s
`_MEASURED_LATER` handling was already correct, not overly conservative. **Q-13 is resolved: no.**
No source code changed — there was nothing to reconstruct from and inventing a proxy (e.g. inverting
`bps` back into action counts) would be exactly the DP-13 failure mode this repo tests hardest
against: wrong in a way no metric here would catch.

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

**Outcome — 2026-08-21 · met.** [DL-50](../00-decision-log.md#dl-50).
`pipeline/src/fpl_dof/config/defaults/duty.yaml` holds 40 spells of penalty duty behind
`forecast.duty`, validated by `DutyConfig`, read only by `forecast/duty.py`, and consumed only by
E10-S3's term. Every entry carries a `basis` naming the snapshot it was seeded from, a confidence
tier that **scales** the term rather than gating it, and `known_from`/`known_until` dates — the
last of these being the half of the design that matters, because a table written today and applied
to a 2024 gameweek is Invariant 5 broken by a config file rather than by a feature.

**Nothing in the file was written from recollection.** The historical spells are FPL's own
`penalties_order` as it stood at the *end of the previous season*, so every one was knowable before
the season it is applied to; the 2026/27 spells are FPL's own pre-season `penalties_order` and are
tiered `likely` rather than `confirmed` because the field is carried forward and is stale for
promoted clubs and new signings by construction.

**Set pieces are recorded as a schema and deliberately left unseeded.** `direct_free_kicks` and
`corners` validate and no entries exist: nothing in silver carries set-piece volume, so a
corner-taker assist uplift would be an invented number (DP-09), and shipping it beside the penalty
term would make one experiment measure two changes ([DL-49](../00-decision-log.md#dl-49)).

**A finding for this epic rather than for E10:** the official `bootstrap-static` feed *already
publishes* `penalties_order`, `direct_freekicks_order` and `corners_and_indirect_freekicks_order`
for all twenty clubs, and the archive's season-end snapshots carry them too. Conforming that field
through the source layer into silver would make most of this file redundant and is squarely E12's
own scope (Invariant 1) — it is **not** in this story, and the file is the seam until it happens.
The `set_piece_notes` endpoint is separately ingested already and is unusable as a duty signal: it
is free prose, and at the 2026/27 season start every one of the twenty rows reads *"Check back for
additional notes soon"*.

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

**Outcome — 2026-08-22 · blocked on its own precondition.** [DL-63](../00-decision-log.md#dl-63--e12-s3-blocked-on-its-own-precondition-the-prior-season-probe-has-no-new-real-input-to-re-measure-against).
Both routes to "real advanced history" this story named are closed: S1 resolved negative (above),
and D-23 still blocks both xG sources — nothing in this epic changed that, and E12 §0 rules out
re-attempting it. `PriorSeasonConfig.statistics` names exactly the columns DL-31 already found
absent; nothing new populates them. Re-running the backtest today would reproduce DL-31's
measurement against the identical proxy input and report it as new evidence, which is the trap E12
§3 exists to name. **Not re-run.** `features.prior_season.enabled` stays `false`; DL-31's ~0.002
Spearman null result stands as the last real measurement.

## 2. Definition of done

- [x] DefCon history reconstructed from the BPS breakdown under the 2026/27 regime — **Q-13
      resolved**: no, it cannot be — the breakdown was never publicly captured for these seasons.
      [DL-62](../00-decision-log.md#dl-62--e12-s1-q-13-resolved-negative--the-bps-action-count-breakdown-was-never-publicly-captured-for-seasons-before-202526)
- [ ] M4 present across the widened backtest window, with DEF/DM Spearman improvement reported —
      **unreachable on this data**, not failed; see DL-62. M4 stays a one-season component.
- [x] Penalty/set-piece duty reference table committed, documented, owner-maintained (**D4**) —
      `config/defaults/duty.yaml`, 40 penalty spells, every entry carrying its provenance and the
      dates that keep a backtest honest. [DL-50](../00-decision-log.md#dl-50)
- [x] Prior-season prior re-measured with real inputs and either promoted on evidence or left dark
      with the null result recorded (DP-08) — **blocked on its own precondition, not re-run**; DL-31's
      null result stands as current because no new real input exists to measure against.
      [DL-63](../00-decision-log.md#dl-63--e12-s3-blocked-on-its-own-precondition-the-prior-season-probe-has-no-new-real-input-to-re-measure-against)
- [x] No new scraping introduced; D-23's refusals remain respected

## 3. The honest question

**"Did more data actually move the number, or did it just feel like progress?"** The DL-31 probe is
the cautionary tale in this repo: a plausible signal moved Spearman by a rounding error. Every story
here is gated on a measured gain precisely so that "we added data" is never mistaken for "the forecast
got better".

**Closing answer, 2026-08-22:** in the end there was no more data to widen with. S1's investigation
found the widening this epic was named for — DefCon history before 2025/26 — does not exist to be
recovered, on any source this project may use; S3's re-measurement inherited that absence rather than
adding a second, independent finding. The honest result of "did more data move the number" this time
is "there was no more data, and saying otherwise would have been the easier, wrong answer."
