# What changed for 2026/27 — and what it invalidates in historical data

Supporting reference for the [`fpl-rules` skill](../SKILL.md). Load this when working on model
training, backtesting, or anything that consumes data from prior seasons.

## The changes

| Change | What it was | What it is now |
| --- | --- | --- |
| Defensive Contribution | Did not exist before 2025/26 | 2 points at DEF 10+ CBIT or MID/FWD 12+ CBIRT per match, introduced 2025/26, unchanged in 2026/27 |
| BPS — tackle penalty | Being tackled cost BPS | Removed entirely |
| BPS — CBI rate | 1 BPS per 2 clearances/blocks/interceptions | 1 BPS per 3 |
| BPS — goalkeeper saves | Separate metric for saves outside the box | Restructured; simpler save scoring plus a "big chance" save bonus |
| BPS — penalty save | 8 BPS | 7 BPS |
| Gameweek lockdown | 1 hour after the final whistle | 09:00 UK time the day after the final match of the gameweek |
| Chip rollover cap | Historically lower in some past seasons | 5 free transfers, confirmed stable for 2026/27 |
| AFCON free transfers | Extra free transfers granted in seasons overlapping AFCON | None in 2026/27 — AFCON falls in June/July 2027, outside the season |

## Why this matters for training data

**Every season before 2025/26 has zero Defensive Contribution signal.** A model naively trained on
combined 2019–2025 data will systematically underweight defensive volume for defenders and
defensive midfielders, because five-plus seasons of that training set contain no such points at all.

**2025/26 itself used the pre-2026/27 BPS matrix.** Bonus points awarded in 2025/26 reflect the old
CBI rate (1 per 2, not 1 per 3) and the old goalkeeper save scoring. A model trained to predict bonus
points using 2025/26 outcomes as ground truth, then applied to 2026/27, is training against a
different function than the one it will be scored against.

## What this means concretely for the pipeline

- **Feature engineering** (Design §3.5): rolling defensive-action rates are safe to compute from any
  season, since the underlying actions (tackles, interceptions, etc.) are recorded regardless of how
  FPL scored them at the time. It is the *scoring* of those actions, not the actions themselves, that
  changed.
- **Target variables** (actual FPL points, actual bonus points) are **not** comparable across the
  regime change. Recompute what *should* have been awarded under 2026/27 rules from raw match stats
  where feasible, rather than using the points FPL actually awarded historically — the rules engine
  and its conformance test exist partly to make this recomputation possible.
- **Model M8 (bonus)** should be trained primarily on the current season's own accumulating data
  once it exists, with pre-2025/26 seasons weighted down or excluded, and 2025/26 treated as
  informative for goal/assist/clean-sheet patterns but suspect for BPS-derived bonus specifically.
- This is tracked as open design question **Q-05** in
  `docs/planning/04-conceptual-design.md` §15 — resolve deliberately during Phase 2 model design, not
  by default.

## Re-verify this file every season

FPL rules change most seasons, sometimes substantially. This file should be reviewed and updated (or
a fresh dated version created) at the start of every future season, not silently assumed to still
apply.
