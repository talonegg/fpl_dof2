# E8 — Ongoing in-season monitoring, 2026/27

**Status:** Live — **updated every gameweek until the season ends** · **Objective:** OBJ-1 ·
**Runs:** GW1 → 30 May 2027 · **Effort:** ~0.5 day per week · **Last reviewed:** see the season state
below

This is the one epic that never closes mid-season. It is not a build plan: it is the weekly
monitoring loop, the record of where the season stands, and the bar any model change must clear. It
runs alongside whichever release is open (R1.1.0 now). It is archived to `../archive/R1.0/` with a
filled Status line only after GW38, when §7 is ticked.

**Keeping it current.** At step 5 of each weekly loop, rewrite the season state in place — do not
append a diary. The per-gameweek history already has a home: the `ledger` branch and `/log`
([DL-69](../../decisions/DL-69.md)). Sections 2–6 are the standing method; change them only by
decision.

---

## Season state — rewrite each gameweek

| Field | Now | Where the evidence lives |
| --- | --- | --- |
| Last gameweek reviewed | *(set at each loop)* | `/log`, `log.json` |
| Next deadline | *(set at each loop)* | `/` (week panel), `week.json` |
| Data health | *(fresh / degraded — which sources)* | `/health`, `health.json`. Understat and FBref are blocked upstream (D-23); stopping their ingress is R1.1.0 PIPE-09 |
| Model verdict | *(model card headline)* | `model-card.md` beside the published artefacts ([DL-21](../../decisions/DL-21.md)) |
| Overrides this season, and why | *(count; reasons pattern)* | Reasons are a manual note until a reasons file feeds `reconcile(overrides=...)` (§3) |
| Chips | *(used / remaining; set 1 expires GW19)* | `/log`, squad state in `week.json` |
| Candidates in shadow | `minutes_v2` on in the shipped config; `adaptive_shrinkage`, `duty_term`, `gkp_v2` off, each measured and not clearing the bar (DL-49, DL-50, DL-51) | `forecast.discrimination` in `config/defaults/forecast.yaml`; the model card |
| Next decision point | *(from §4)* | §4 |

### Decision points

| Gameweek | Question | Outcome |
| --- | --- | --- |
| GW4 | Is the model beating your intuition? If not, the forecast takes priority over everything else | **Intuition is ahead** (owner, 17 Oct). R1.1.0 keeps its order: the pipeline is what a better forecast is built from ([DL-79](../../decisions/DL-79.md)) |
| GW8 | Is weekly operation sustainable? If not, automation and alerting jump to the top | *(record)* |
| GW10–12 | First honest read on live out-of-sample accuracy | *(record)* |
| Before GW15 | A chip calendar for set 1 exists | *(record)* |
| GW19 deadline | **Chip set 1 expires — 18:30 GMT, Fri 1 Jan 2027** (per the API, 17 Oct 2026; re-check, FPL moves deadlines). Unused chips are lost | *(record)* |
| Mid-season break | One larger investment: the stochastic layer or another source. Choose one | *(record)* |
| ~GW30 | **Stop building. Operate only** | *(record)* |
| End of season | Retrospective against charter §5; decide whether 2027/28 is worth it | *(record)* |

---

## 1. What this is

The discipline that turns a working system into a good season — the weekly ritual, the learning
loop, and the judgement about when to stop building. What to build is chosen by the
[release register](README.md#choosing-what-to-build-next); this page says when the season's
evidence should change that choice.

## 2. The weekly loop

Target: **under 30 minutes**, excluding any build work.

| Step | Question | Output |
| --- | --- | --- |
| 1. Review | What did the model recommend, and what actually happened? | `/log` row reconciled |
| 2. Drift check | Are rolling accuracy metrics holding? | Investigate significant drops |
| 3. Data health | Fresh? Gates passing? Adapters alive? | Fix or accept, explicitly |
| 4. Improve | What is the biggest regret I would have at the next deadline? | **One** improvement. One, not three |
| 5. Decide | Review, override where you know something the model does not, submit; rewrite the season state above | Team in before the deadline |

**Step 4 is where solo projects die.** Three improvements a week sounds like progress and produces a
half-finished system by December. One improvement a week, finished, compounds.

**Step 5 timing, given AEST:** decide the evening before, local time. Most deadlines land while you
are asleep.

## 3. The decision log

Every week, record: what was recommended, what you did, why you differed, and what happened. This is
the single most valuable dataset the project produces about *itself* — it is how you eventually
answer whether the model or your intuition is better, with evidence rather than impression.

Lineage ([Design §12.4](../04-conceptual-design.md#124-lineage)) exists to make this honest: for any
recommendation, it must be possible to reconstruct exactly what the system knew at the time.

**Where it lives ([DL-69](../../decisions/DL-69.md)).** The pipeline writes each week's advice to the
`ledger` branch before the deadline, judges each finished gameweek once into `evaluation/entry-<id>/gwNN.json`
(ORC-05), and publishes `log.json` from those judgements — played, scored, advised, reconciled, per
evaluated gameweek — rendered at `/log`. GW1 to GW4 were decided without the tool and appear there with
picks and points and *no advice recorded*; nothing is reconstructed after the event. The owner's
*reason* for an override is not yet held there; it stays a manual note until a reasons file is wired
into `reconcile(overrides=...)`.

## 4. Periodic activities

| When | Activity |
| --- | --- |
| Weekly | The loop in §2, ending with the season state rewritten |
| Monthly | Re-run the backtest regression. Retrain **into shadow mode**, never straight into production — promotion needs the three conditions in §5 |
| At each dated decision point | Answer it and record the outcome in the decision-points table |
| January | Re-plan chips for the run-in; second set opens |
| Feb–Apr | Blanks and doubles dominate; fixture-structure modelling matters most |
| After the first double gameweek, blank gameweek and Free Hit are played | Add their entries to the realised-points corpus with `python scripts/realised_corpus.py` (see `contracts/conformance/README.md`) and run `tests/test_rules_realised.py`: the one scorer must reproduce FPL's points, or the failing rule is a defect (ORC-04, [DL-39](../../decisions/DL-39.md)) |

## 5. The bar for changing the model mid-season

"Retrain monthly on accumulated current-season data" sounds like diligence. By GW10 that is **ten
gameweeks** of the noisiest target in the project, and fitting to it is how a working system quietly
gets worse. R-17.

The mechanism is **shadow mode** ([Design §13](../04-conceptual-design.md#13-configuration-and-feature-flags)),
which publishes a candidate model's predictions for comparison without letting them influence
anything. Coming out of it needs three conditions, all of them:

| # | Condition |
| --- | --- |
| 1 | **Backtest regression improves** on the held-out season — not just on the current one |
| 2 | **Live rolling accuracy does not degrade** over a minimum of **six** shadow gameweeks. Fewer than six and you are reading noise |
| 3 | The change is **explicable** — you can say why it should work, in advance. A change that only improves the metric is a change that found a pattern in this season's noise |

**Prefer shrinkage to refitting.** Blending the preseason model toward current-season evidence in
proportion to how much evidence there is will beat a fresh fit on ten gameweeks nearly every time,
and it degrades gracefully rather than lurching.

**One exception, deliberately:** a *bug fix* is not a model change and does not wait for six
gameweeks. A miscomputed clean-sheet probability gets fixed on discovery. The bar is for changes that
are improvements in intent rather than corrections in fact — and if it is being argued about, it is a
model change.

## 6. Anti-patterns to watch for

| Pattern | Why it is dangerous | Response |
| --- | --- | --- |
| Overriding the model every week | Either the model is bad or you are not letting it work. Both need addressing | Log overrides; review the pattern after four weeks |
| Never overriding the model | The model has no injury news, no press conferences, no judgement | Deliberately question one recommendation per week |
| Overriding a blocked quality gate | Normalises publishing data you know is suspect | Stop. Fix the gate or the data |
| Chasing last week's points | The classic FPL error, and a model does not immunise you | Trust the horizon, not the last result |
| Building instead of playing | Late-season build time has almost no payoff | Honour the GW30 stop |
| Retuning the model after a bad gameweek | One gameweek is noise. This is chasing last week's points wearing a lab coat | Shadow mode and the six-gameweek bar in §5 |
| Reacting to the captaincy hit rate in-season | n = 38 over a whole season, so the standard error on a 50% rate is ~8 points. 45% and 55% are indistinguishable | Backtest gate only |
| Letting the season state go stale | A monitoring page nobody updated is a confident record of last month | Rewrite it at step 5, every week |

## 7. Definition of done

The season ends — and this epic closes — with:

- [ ] 38 gameweeks played, every deadline met
- [ ] A decision log covering every gameweek, with **advised-versus-played reconciled**
- [ ] An honest assessment against charter §5, including whether the model added edge over B0 and
      over the model-free benchmark
- [ ] Chips used within their sets, none expired unused
- [ ] A retrospective, and a decision on 2027/28
