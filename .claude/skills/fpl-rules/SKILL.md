---
name: fpl-rules
description: Authoritative Fantasy Premier League 2026/27 rules — scoring values, the revised Bonus Points System, Defensive Contribution thresholds, squad composition, budget, transfer and price mechanics, and chip rules with expiry dates. Load before writing or reviewing any code that computes points, prices, selling values, transfer costs, squad legality or chip eligibility, and before answering any question about how FPL scoring works.
user-invokable: true
---

# FPL 2026/27 rules — reference

**This skill is a reference for what belongs in `pipeline/src/fpl_dof/rules/` config, not a licence
to hardcode.** Every value below must live in configuration in the codebase, seeded from the API's
own game settings where exposed (see `fpl-api`). If code and this skill ever disagree, neither wins
automatically — re-check against the official rules and the conformance test before changing either.

**Confidence levels used below:**
- ✅ **Verified** — stable, long-standing FPL mechanics, or explicitly confirmed by the Premier
  League's own 2026/27 announcement. Safe to encode directly.
- ⚠️ **Community-inferred** — the exact number is not officially published by FPL; it comes from
  reverse-engineering by the FPL analytics community. Treat as a strong prior, not ground truth.
  **The rules-engine conformance test (recomputing historical gameweek points from raw stats and
  reconciling against FPL's published totals) is the actual source of truth — not this file.**

Last verified: 2026-08-09. Season: 2026/27 (starts 21 Aug 2026).

---

## Scoring table ✅ verified

Stable across many seasons; not part of the 2026/27 changes.

| Event | GK | DEF | MID | FWD |
| --- | --- | --- | --- | --- |
| Playing 1–59 minutes | 1 | 1 | 1 | 1 |
| Playing 60+ minutes | 2 | 2 | 2 | 2 |
| Goal scored | 6 | 6 | 5 | 4 |
| Assist | 3 | 3 | 3 | 3 |
| Clean sheet (60+ min) | 4 | 4 | 1 | 0 |
| Every 3 saves | 1 | — | — | — |
| Penalty save | 5 | — | — | — |
| Penalty miss | −2 | −2 | −2 | −2 |
| Every 2 goals conceded | −1 | −1 | — | — |
| Yellow card | −1 | −1 | −1 | −1 |
| Red card | −3 | −3 | −3 | −3 |
| Own goal | −2 | −2 | −2 | −2 |
| Bonus | 3 / 2 / 1 to the top three BPS in that match | | | |

## Defensive Contribution ✅ verified

Introduced 2025/26, unchanged in 2026/27.

| Position | Threshold | Points |
| --- | --- | --- |
| Defender | 10+ combined clearances, blocks, interceptions, tackles (**CBIT**) in a match | 2 |
| Midfielder | 12+ combined clearances, blocks, interceptions, tackles, **and ball recoveries** (**CBIRT**) in a match | 2 |
| Forward | Same as midfielder — 12+ CBIRT | 2 |
| Goalkeeper | Not eligible | — |

Capped at 2 points per match — reaching double the threshold does not score 4.

## Bonus Points System — 2026/27 changes ✅ verified

Officially confirmed changes, made "to reduce overlap with Defensive Contribution points and improve
the bonus-point prospects of goalkeepers, full-backs and attacking players":

- **Tackle penalty removed.** Players previously lost BPS for being tackled; this metric no longer
  exists. Benefits dribble-heavy attackers.
- **Clearances, blocks and interceptions devalued.** Changed from 1 BPS per 2 actions to **1 BPS per
  3 actions**.
- **Goalkeeper saves restructured.** The separate "saves outside the box" metric is removed. Saves
  now score more simply, with an additional bonus for "big chance" saves.
- **Penalty save BPS reduced** from 8 to 7.

Top 3 BPS scorers in a match receive bonus: 3 / 2 / 1. Standard FPL tie-break rules apply (a tie for
1st awards 3/3/1; a tie for 2nd awards 3/2/2; a tie for 3rd awards 3/2/1/1).

### Full BPS matrix ⚠️ community-inferred — do not hardcode without verification

FPL has never officially published a complete BPS weighting table for any season. The figures below
are the community's best current reconstruction (Fantasy Football Scout and similar sources) and are
**plausible but not confirmed**. Before encoding any of these into `rules/` config, verify against
observed BPS output for real 2026/27 matches — the conformance test is what actually matters here,
not this list.

| Action | Approx. BPS (unverified) |
| --- | --- |
| Playing 1–60 min / 60+ min | 3 / 6 |
| Goal — GK or DEF | 12 |
| Goal — MID | 18 |
| Goal — FWD | 24 |
| Assist | 9 |
| Clean sheet — GK/DEF | 12 |
| Penalty save | 7 *(confirmed change from 8)* |
| Every 3 clearances/blocks/interceptions | 1 *(confirmed change from every 2)* |
| Yellow card | −3 |
| Red card | −9 |
| Own goal | −6 |
| Missed penalty | −6 |

Because bonus points are a *ranking* within a match rather than a direct score, the expected-points
model (Design §5, model M8) treats bonus as a probabilistic estimate over the match's player set
rather than a deterministic function of these weights — which is precisely why exact BPS constants
matter less than getting the *ranking behaviour* right. See `references/bps-matrix.md` for more
detail and open questions.

## Squad rules ✅ verified

| Rule | Value |
| --- | --- |
| Squad size | 15 — exactly 2 GK, 5 DEF, 5 MID, 3 FWD |
| Initial budget | £100.0m |
| Players per club | Maximum 3 |
| Starting XI | 11 — exactly 1 GK; 3–5 DEF; 2–5 MID; 1–3 FWD |
| Captain / vice-captain | Captain scores double; vice substitutes if captain does not play |
| Bench | Ordered 1–3 for outfield players; substitute GK is automatic |

## Transfers and prices ✅ verified

| Rule | Value |
| --- | --- |
| Free transfers | 1 per gameweek, accumulating to a maximum of **5** |
| Extra transfers | −4 points each |
| Price movement | ±£0.1, driven by net transfers, evaluated daily at midnight UK time |
| Selling price | Purchase price + 50% of any profit, rounded down to £0.1 (the "sell-on fee") |
| AFCON allowance | None this season — no extra free transfers (AFCON is June/July 2027, outside season) |

## Chips ✅ verified

| Rule | Value |
| --- | --- |
| Chip sets | Two sets of four: Wildcard, Free Hit, Triple Captain, Bench Boost |
| Usage | One chip per gameweek maximum |
| **Set 1 expiry** | **GW19 deadline — 13:30 GMT, Saturday 2 January 2027.** Unused chips in set 1 are lost |
| Set 2 | Same four chips, available from GW19+ through the end of the season |

## Season dates ✅ verified

| Date | Event |
| --- | --- |
| Fri 21 Aug 2026, 18:30 BST | GW1 deadline |
| Fri 21 Aug 2026 | Season starts (Arsenal v Coventry City) |
| Sat 2 Jan 2027, 13:30 GMT | GW19 deadline — chip set 1 expires |
| Sun 30 May 2027 | Final match round |
| — | Gameweek "lockdown" (scores final) is 09:00 UK time the day **after** the last match of the gameweek — changed from one hour post-whistle |

## The trap in historical training data ⚠️ important

Defensive Contribution was introduced in 2025/26. The BPS matrix was revised for 2026/27. **Any
season before 2025/26 has neither DefCon points nor the current BPS weighting**, and 2025/26 itself
used the *pre-revision* BPS matrix. Training or backtesting on pre-2025/26 data without accounting
for this will silently misprice bonus and defensive-contribution-heavy players — full-backs and
defensive midfielders especially. See `references/changes-2026-27.md` and Design §5 model M8 and
Design §15 Q-05.

## Sources

- [premierleague.com — 2026/27 season dates](https://www.premierleague.com/en/news/4468487/dates-for-202627-premier-league-season-confirmed)
- [premierleague.com — FPL 2026/27 changes](https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627)
- [premierleague.com — BPS changes explained](https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system)
- [Fantasy Football Scout — 2026/27 rule changes](https://www.fantasyfootballscout.co.uk/2026/07/20/fpl-2026-27-5-rule-changes-new-features-announced)
- [Fantasy Football Scout — BPS explainer](https://www.fantasyfootballscout.co.uk/2026/07/20/what-are-fpl-bonus-points-2)
