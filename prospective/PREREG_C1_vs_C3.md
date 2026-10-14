# Pre-registration: C1 vs C3, 2026/27 prospective run

**Registered:** 2026-10-14 (AEDT), before the GW7 deadline (Sat 17 Oct 2026 21:00 AEDT = 10:00 UTC),
which is the first gameweek any frozen model's picks are recorded before a deadline. This file is
committed on its own so its commit time is the registration time. It must not be edited after GW7's
deadline; any change is a new, dated addendum below the line and does not replace the plan.

## What is being compared
- **Models:** the five frozen at tag `frozen-2026-10-13` (79e080c): engine, C3 (champion), C1
  (challenger), A, A_odds. Config hashes are fixed in `prospective/bundle/manifest.json` and
  checked by `pipeline/tests/test_frozen_configs_unchanged.py`. No model is changed during the run.
- **Primary comparison:** **C1 vs C3** (challenger vs champion), as in round 3.
- **A_odds:** labelled **currently duplicating A**. Until odds rows flow into its team layer its xP and
  picks equal A's, so A_odds results are reported but are not evidence about the odds layer.

## Data
- Gameweeks: GW7 onward of 2026/27, prospective only (decisions recorded before each deadline by the
  CI `prospective` job, write-once). The GW1-6 replay is retrospective and is **excluded** from every
  test here; it is shown on the site as replay only.
- xP: each model's full-pool `xp_{model}.parquet`, sha256-hashed into `decisions/GW{n}.json` and kept
  under `data/gold/xp/GW{n}/`. A file whose hash does not match is not scored.
- Actuals: FPL `event/{gw}/live` `total_points` (double gameweeks summed) and minutes, once the
  gameweek is `finished` and `data_checked`.

## Primary metric
**All-player MAE per GW** of next-GW xP vs actual points, on the paired population: every player-GW
that all five models priced and FPL listed at the deadline. Zero-minute players stay in.
Test: paired per-GW difference (C1 − C3), two-sided sign-flip test over GWs (20,000 draws, seed 0),
α = 0.05. Negative = C1 better.

## Secondary metric
**XI points after auto-subs** (final XI, armband with vice fallback, minus hits) from the frozen
`score.py` (`scores.csv`), C1 − C3 paired per GW, same sign-flip test. Reported with the primary;
it is the decision criterion for any model change but, at one season, is expected to be underpowered.

Further diagnostics, no claims, Holm-corrected within their family where tested
(`xp_scores_paired.csv`): engine vs C3, A vs C1, A_odds vs C1 on MAE; RMSE, Spearman within
GW×position, MAE on the union of each model's top-50 by xP, `avail_prior` subset, calibration by xP
bucket, zero-minute mean xP.

## Horizon and looks
- **Fixed horizon. No look before GW10.** "Look" means computing or reading any C1-vs-C3 comparison
  statistic (difference, p-value, CI) for the purpose of a decision. The CI job writes the per-GW
  files automatically; nobody interprets them as a comparison before GW10 has been scored.
- **Interim look:** once, after GW10 is scored (4 prospective GWs). Descriptive only: no model
  switch is made on it.
- **Final analysis:** after GW38 is scored, on all prospective GWs (GW7-GW38). This is the
  confirmatory result.
- No stopping early for success. A model may be stopped early only for a fault (failed freshness
  checks, harness bug), which is logged and its GWs reported as missing, not imputed.

## Missing data
A GW where a model was unavailable (fail-closed status) or its xP file failed the hash check is
dropped for that pair and counted; it is never filled in.

## Known caveats (declared now)
- The 2025/26 illustrative run (research/fpl-xp-accuracy-scoring.md) is in-sample for config
  selection; C1 is unseeded. The 2026/27 GW1-6 replay already showed C3 ahead of C1 on all-player
  MAE (1.029 vs 1.206) — another reason it is excluded from the test.
- All-player MAE is about 60% zero-minute rows, so it is partly an availability score.

---
*Addenda (dated, append-only) go below this line.*
