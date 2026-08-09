# BPS matrix — detail and open questions

Supporting reference for the [`fpl-rules` skill](../SKILL.md). Load this only when working directly
on BPS estimation (model M8) or the rules-engine conformance test.

## Why this file exists

The Bonus Points System converts a wide range of in-match actions into a per-player score; the top
three in each match receive bonus FPL points. FPL has never published an official, complete numeric
table for any season — every "BPS matrix" in circulation, including the one in `SKILL.md`, is
reverse-engineered by the analytics community from observed outputs. This file records what is known,
what changed for 2026/27, and how the project should treat the uncertainty.

## What is officially confirmed for 2026/27

Per the Premier League's own announcement (see `SKILL.md` sources):

1. The BPS penalty for being tackled is removed entirely.
2. Clearances, blocks and interceptions (CBI) move from 1 BPS per 2 actions to 1 BPS per 3.
3. Goalkeeper saves are restructured: the separate "save from outside the box" metric is gone;
   saves are scored more simply, with an added bonus for saving a "big chance".
4. Penalty save BPS drops from 8 to 7.

Stated intent: reduce overlap between BPS and Defensive Contribution, and improve bonus prospects for
goalkeepers, full-backs and attacking players specifically.

## What is not officially confirmed

Everything else in the widely-circulated "full matrix" — exact BPS values for goals by position,
assists, clean sheets, key passes, pass-completion tiers, cards, and so on. These values are
plausible (internally consistent with historical patterns) but should not be treated as certain.

## How the project should handle this

- **Do not hardcode unverified BPS weights into `rules/` config as if they were confirmed values.**
  Mark them clearly as estimates in code comments and config documentation, mirroring the confidence
  labelling in `SKILL.md`.
- **The conformance test is the real check** (Design §10, "Conformance" row): recompute historical
  gameweek points, including bonus, from raw match stats using the assumed BPS weights, and reconcile
  against FPL's actually published bonus point awards. Where the reconciliation fails, that is
  evidence the assumed weights are wrong — adjust and re-test, rather than trusting the matrix as-is.
- **Model M8 (bonus points) treats this as inherently probabilistic**, not deterministic — it
  estimates the probability of finishing top-3 in BPS within a match, rather than computing an exact
  BPS score and looking up a table. This is a deliberate hedge against matrix uncertainty: getting
  the *relative ranking* behaviour right matters more than getting each constant exactly right.
- **Re-verify at the start of every season**, not just 2026/27 — the BPS matrix has been tweaked most
  seasons in FPL's history, usually without a full public specification of the new values.

## Where to look when actual verification is needed

- FPL's own bonus-points explainer pages (checked at skill-creation time; re-check each season).
- Match-by-match BPS breakdowns published in-app and on the official site after each fixture — the
  single best source of ground truth, since it shows the *result* of the matrix even without the
  matrix itself.
- Community reverse-engineering write-ups (Fantasy Football Scout and similar), used as a starting
  hypothesis only.
