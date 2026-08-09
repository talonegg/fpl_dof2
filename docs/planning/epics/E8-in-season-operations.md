# E8 — In-Season Operations

**Objective:** OBJ-1 · **Runs:** GW1 → 30 May 2027 · **Estimate:** ~0.5 day per week
**Depends on:** E1 minimum

---

## 1. What this is

Not a build epic. This is the discipline that turns a working system into a good season — the weekly
ritual, the learning loop, and the judgement about when to stop building.

It starts the moment GW1 is submitted and runs alongside every other epic.

## 2. The weekly loop

Target: **under 30 minutes**, excluding any build work.

| Step | Question | Output |
| --- | --- | --- |
| 1. Review | What did the model recommend, and what actually happened? | Logged decision and outcome |
| 2. Drift check | Are rolling accuracy metrics holding? | Investigate significant drops |
| 3. Data health | Fresh? Gates passing? Adapters alive? | Fix or accept, explicitly |
| 4. Improve | What is the biggest regret I would have at the next deadline? | **One** improvement. One, not three |
| 5. Decide | Review, override where you know something the model does not, submit | Team in before the deadline |

**Step 4 is where solo projects die.** Three improvements a week sounds like progress and produces a
half-finished system by December. One improvement a week, finished, compounds.

**Step 5 timing, given AEST:** decide the evening before, local time. Most deadlines land while you
are asleep.

## 3. The decision log

Every week, record: what was recommended, what you did, why you differed, and what happened. This is
the single most valuable dataset the project produces about *itself* — it is how you eventually
answer whether the model or your intuition is better, with evidence rather than impression.

Lineage (Design §12.4) exists to make this honest: for any recommendation, it must be possible to
reconstruct exactly what the system knew at the time. Without that, a retrospective becomes
rationalisation.

## 4. Periodic activities

| When | Activity |
| --- | --- |
| Monthly | Re-run the backtest regression. Retrain **into shadow mode**, never straight into production — promotion needs the three conditions in §5 |
| **GW4** | **Decision point:** is the model beating your intuition? If not, E3 takes priority over E6 |
| **GW8** | **Decision point:** is manual operation sustainable? If not, E7 jumps immediately |
| GW10–12 | First honest read on live out-of-sample accuracy |
| **GW15** | Chip calendar for set 1 must exist |
| **GW19 deadline** | **Chip set 1 expires — 13:30 GMT, 2 Jan 2027.** Unused chips are lost |
| January | Re-plan chips for the run-in; second set opens |
| Feb–Apr | Blanks and doubles dominate; fixture-structure modelling matters most |
| **~GW30** | **Stop building. Operate only.** Remaining gameweeks no longer repay build time |
| End of season | Retrospective against charter §5; decide whether 2027/28 is worth it |

## 5. The bar for changing the model mid-season

"Retrain monthly on accumulated current-season data" sounds like diligence. By GW10 that is **ten
gameweeks** of the noisiest target in the project, and fitting to it is how a working system quietly
gets worse. R-17.

The mechanism already exists — **shadow mode** ([Design §13](../04-conceptual-design.md#13-configuration-and-feature-flags)),
which publishes a candidate model's predictions for comparison without letting them influence
anything. What was missing is the bar for coming out of it. Three conditions, all of them:

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
are improvements in intent rather than corrections in fact — and the distinction is usually obvious,
so if it is being argued about, it is a model change.

## 6. Anti-patterns to watch for

| Pattern | Why it is dangerous | Response |
| --- | --- | --- |
| Overriding the model every week | Either the model is bad or you are not letting it work. Both need addressing | Log overrides; review the pattern after four weeks |
| Never overriding the model | The model has no injury news, no press conferences, no judgement | Deliberately question one recommendation per week |
| Overriding a blocked quality gate | Normalises publishing data you know is suspect | Stop. Fix the gate or the data |
| Chasing last week's points | The classic FPL error, and a model does not immunise you | Trust the horizon, not the last result |
| Building instead of playing | Late-season build time has almost no payoff | Honour the GW30 stop |
| Retuning the model after a bad gameweek | One gameweek is noise. This is chasing last week's points wearing a lab coat | Shadow mode and the six-gameweek bar in §5 |
| Reacting to the captaincy hit rate in-season | n = 38 over a whole season, so the standard error on a 50% rate is ~8 points. 45% and 55% are indistinguishable | Backtest gate only. Charter §5 now says so |

## 7. Definition of done

The season ends with:

- [ ] 38 gameweeks played, every deadline met
- [ ] A decision log covering every gameweek, with **advised-versus-played reconciled** (E1-S5)
- [ ] An honest assessment against charter §5, including whether the model added edge over B0 and
      over the model-free benchmark
- [ ] Chips used within their sets, none expired unused
- [ ] A retrospective, and a decision on 2027/28
