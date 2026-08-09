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
| Monthly | Retrain on accumulated current-season data; re-run backtest regression |
| **GW4** | **Decision point:** is the model beating your intuition? If not, E3 takes priority over E6 |
| **GW8** | **Decision point:** is manual operation sustainable? If not, E7 jumps immediately |
| GW10–12 | First honest read on live out-of-sample accuracy |
| **GW15** | Chip calendar for set 1 must exist |
| **GW19 deadline** | **Chip set 1 expires — 13:30 GMT, 2 Jan 2027.** Unused chips are lost |
| January | Re-plan chips for the run-in; second set opens |
| Feb–Apr | Blanks and doubles dominate; fixture-structure modelling matters most |
| **~GW30** | **Stop building. Operate only.** Remaining gameweeks no longer repay build time |
| End of season | Retrospective against charter §5; decide whether 2027/28 is worth it |

## 5. Anti-patterns to watch for

| Pattern | Why it is dangerous | Response |
| --- | --- | --- |
| Overriding the model every week | Either the model is bad or you are not letting it work. Both need addressing | Log overrides; review the pattern after four weeks |
| Never overriding the model | The model has no injury news, no press conferences, no judgement | Deliberately question one recommendation per week |
| Overriding a blocked quality gate | Normalises publishing data you know is suspect | Stop. Fix the gate or the data |
| Chasing last week's points | The classic FPL error, and a model does not immunise you | Trust the horizon, not the last result |
| Building instead of playing | Late-season build time has almost no payoff | Honour the GW30 stop |

## 6. Definition of done

The season ends with:

- [ ] 38 gameweeks played, every deadline met
- [ ] A decision log covering every gameweek
- [ ] An honest assessment against charter §5, including whether the model added edge
- [ ] Chips used within their sets, none expired unused
- [ ] A retrospective, and a decision on 2027/28
