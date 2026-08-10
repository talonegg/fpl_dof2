# E4 — Decision Engine

**Objective:** OBJ-3 (full), OBJ-4 · **Target:** ~GW15 · **Estimate:** 7–10 days
**Depends on:** E3 · **Repays debt:** D-03, D-04 · **Resolves:** OD-06
**Hard constraint:** chip set 1 expires at the **GW19 deadline, 13:30 GMT Sat 2 Jan 2027**
**Insurance if this slips:** [E2-S7](E2-data-platform.md#e2-s7--chip-expiry-tracker--05-day--obj-4)
shipped a blunt chip-expiry tracker at ~GW6, precisely so that a dated irreversible loss never
depends on this epic landing on time

---

## 0. Gate carried in from E3 — read before starting

**[DL-21](../00-decision-log.md#dl-21--the-v1-forecast-beats-price-and-loses-to-recent-form-reported-not-tuned)
found the forecast loses to a model-free benchmark on top-20 precision (0.00 vs 0.05) — the exact
part of the ranking this epic's decisions act on. That finding opened debt
[D-13](E0-steel-thread-gw1.md#6-technical-debt-register), and its consequence is a hard constraint on
this epic, not a footnote:**

> No −8 hit, chip, or wildcard may be justified by `xp_v1` alone until top-20 precision beats B0.

**What this means concretely for the stories below:** E4-S2's MILP and E4-S3's chip modelling may be
built and tested against the current forecast — the machinery does not need to wait — but **the
squad/transfer engine must expose that its recommendations are running on an unvalidated-at-the-head
forecast**, and any UI or explanation surfacing a hit/chip/wildcard call (E4-S6) must carry that
caveat rather than present the recommendation as settled. Closing D-13 is not part of this epic's
scope; not silently proceeding as though it were already closed is.

## 1. Why, and why the timing is not negotiable

E1 gave a single-gameweek transfer recommendation. That is structurally short-sighted: it churns
transfers and, critically, has no view on chips. Four chips must be used by GW19 or they are lost.

**This epic must be usable by GW15 at the latest.** That is not a preference — a chip calendar built
in December for a January deadline has no room to be wrong. The dependency on E3 is therefore a
scheduling risk worth watching: if E3 slips past GW12, start E4's chip planning in parallel using
whatever forecast exists.

## 2. Stories

### E4-S1 — Candidate pruning · 0.5 day
Reduce ~700 players to a tractable 200–250 without bias. Must include all currently owned, top N per
position by xP, top N by xP per cost, **all viable cheap enablers** (a pure xP ranking drops them,
and they are structurally necessary to afford premiums), and anything user-locked.

**Acceptance:** periodically re-solve on the full set offline and confirm the pruned solution matches.

### E4-S2 — Multi-gameweek MILP · 2.5 days · FR-18 · repays D-03
Extend to a rolling 5–8 gameweek horizon per
[Design §6.2](../04-conceptual-design.md#62-milp-formulation): squad continuity across gameweeks,
free-transfer accrual with the **five-transfer rollover cap**, hit arithmetic, discounted objective.

Linearisation needed for the `min` in free-transfer accrual and the bilinear captain terms.

**Solver: HiGHS, not CBC** ([DL-15](../00-decision-log.md#dl-15--chip-timing-by-scenario-enumeration-highs-as-the-solver-from-e4)).
E0 validated CBC against the single-gameweek problem, which is a far easier one. This model is
roughly 10–20k binaries with a weak relaxation, and R-07 is rated **High** accordingly. Budget time
for tuning, not just building.

**Three property tests that must exist, because each failure is silent:**

| Test | The bug it catches |
| --- | --- |
| **Chips do not consume free transfers** (constraint C15) | The easy half of the rule — a Wildcard costs no *hit* — is obvious. The half that gets missed is that a Wildcard or Free Hit also does not *spend* the free-transfer balance. Without it the model thinks a Wildcard burns up to five banked transfers, and plays chips too late or never |
| **Free-transfer accrual caps at 5 and never goes negative** | Off-by-one in the `min` linearisation, over an 8-week horizon, compounds into a plan built on transfers that do not exist |
| **Squad legality holds at every gameweek of the horizon**, not just the first | E1's property tests only ever saw one gameweek |

**Acceptance:** produces a coherent multi-week plan; the three tests above pass across randomised
inputs; solves inside the time budget with the greedy fallback proven.

### E4-S3 — Chip modelling · 2 days · FR-20 · repays D-04
Wildcard, Free Hit, Triple Captain, Bench Boost, plus a longer-range **chip calendar** projecting
likely windows across the season. Supersedes — does not delete — the blunt
[E2-S7 tracker](E2-data-platform.md#e2-s7--chip-expiry-tracker--05-day--obj-4).

**Approach: enumeration over chip scenarios, not MILP decision variables**
([DL-15](../00-decision-log.md#dl-15--chip-timing-by-scenario-enumeration-highs-as-the-solver-from-e4),
[Design §6.3](../04-conceptual-design.md#63-chip-strategy--enumeration-not-decision-variables)).
Enumerate the plausible `(chip, gameweek)` assignments in the horizon — a small set after pruning —
solve the ordinary transfer MILP conditional on each, take the best and keep the runners-up.

- Far more tractable: Free Hit stops needing a parallel squad variable set inside one model
- Trivially parallel, which suits CI
- **Explainable**, which matters more than it sounds. "Free Hit in GW18 beats GW17 by 4.1 points and
  beats not playing it by 9.3" is a sentence you can argue with; a chip binary flipping inside a
  solver is not, and chip timing is the recommendation most likely to be challenged

Set 1 variables forced to zero after GW19. The calendar accounts for double and blank gameweeks,
which reshape everything in the second half.

**Acceptance:** a chip calendar exists and updates weekly; set-1 expiry is enforced, not advisory;
every chip recommendation carries its runner-up timing and the margin between them.

### E4-S4 — Risk dial and ownership · 1.5 days · FR-21, FR-16 · DL-07 · resolves OD-06

**Start by deciding where effective ownership comes from — it is not a given.** `EO = selected_by% +
captained_by%` is standard and correct, and **not computable from public FPL data**: captaincy share
is exposed by no endpoint (CON-12). Worse, `selected_by_percent` is ownership across all ~11m
managers, while the charter's target is top-100k, whose template differs materially.

Three routes are set out in [Design §7.1](../04-conceptual-design.md#71-effective-ownership-is-not-directly-observable-con-12-od-06):
estimate it, sample it post-deadline from large public leagues, or redefine EO without the captaincy
term. Pick one, record it as OD-06's resolution, and **state in the UI which one is in use**. A risk
dial driven by an estimated quantity presented as a measured one is worse than no risk dial.

Then: a signed ownership-deviation term in the objective, from template-safe through
differential-aggressive.

**The UI obligation matters more than the dial itself:** every recommendation must state the bet
plainly — "you are 18% underweight on the most-captained player; you gain if he blanks and lose
roughly 4 points of rank-equivalent if he hauls." Making the bet explicit is what lets you apply
judgement the model does not have.

**Honest limitation to document:** a MILP cannot represent portfolio variance, which is quadratic,
and players in the same match are strongly correlated — two defenders from one club share a clean
sheet. The risk term is a linear proxy. The correct treatment is the stochastic layer deferred in
DL-06. Two things narrow the gap without waiting for it — E4-S4a below, and constraint C16.

**C16 — cap the starting XI at 2 players per club.** One linear constraint per club, aimed squarely
at the dominant correlation, no change to the objective. Not a substitute for modelling covariance;
it is the part a linear model can actually express. Relaxable per club through E4-S5 overrides, and
[Q-12](../04-conceptual-design.md#15-open-design-questions) asks whether 2 or 3 is the better default.

### E4-S4a — Simulation re-rank · 1 day · **most of the stochastic layer, none of the solver work**

Sits between "linear proxy" and the deferred DL-06 stochastic optimiser, and needs no solver change:

1. Take the **top-k solutions** — the chip enumeration in E4-S3 produces a pool naturally
2. **Simulate** each: sample player outcomes many times, with draws **correlated within a match**, so
   a clean sheet is shared and a thrashing is shared
3. **Re-rank** on what the dial actually asks for — expected points at the safe end, upside
   percentiles at the aggressive end

This matters most exactly where the MILP is weakest. **Bench Boost and Triple Captain are variance
plays**, and an expectation-maximiser mistimes them systematically: it cannot distinguish a Triple
Captain on a 6.0-xP explosive forward from one on a 6.0-xP metronomic midfielder. Those are not the
same bet, and the difference is the entire point of the chip.

**Acceptance:** the re-rank changes at least one chip recommendation somewhere in the backtest, and
the direction of the change is explicable. If it never changes anything, either the simulation is not
correlating within matches or the top-k pool is degenerate — both are bugs.

### E4-S5 — Constraint overrides · 0.5 day · FR-22
Locks, bans, budget caps, forced formations, club exclusions, and forcing or forbidding a chip in a
given gameweek. Infeasible combinations must explain *why*.

### E4-S6 — Explanation layer · 1 day · FR-23, FR-24
Decomposition, marginal gain over doing nothing, runner-up options and why they lost, ownership bet,
price exposure, and the assumptions — "this assumes he starts, which the model puts at 71%".

**"Roll the transfer" remains a first-class candidate, always shown.**

## 3. Definition of done

- [ ] Multi-gameweek plan over a rolling horizon, with correct free-transfer and hit arithmetic
- [ ] **Chips do not consume free transfers** — property-tested, not assumed (C15)
- [ ] Chip calendar live, with set-1 expiry enforced; E2-S7's tracker superseded, not deleted
- [ ] **OD-06 resolved** — the EO source chosen, recorded, and named in the UI
- [ ] Risk dial functional; ownership bet surfaced on every recommendation
- [ ] Same-club XI cap in force and relaxable per club
- [ ] Simulation re-rank running, and demonstrably affecting at least one chip decision in backtest
- [ ] **Incumbency tie-break in the objective** — the same inputs produce the same squad twice running
      (R-16), and a transfer must clear a margin rather than merely tie
- [ ] Overrides working, with useful infeasibility messages
- [ ] Every recommendation explained with runner-ups and marginal gain
- [ ] Property tests cover the full constraint set including chips and the full horizon
- [ ] Solve time inside budget on HiGHS, with greedy fallback proven
- [ ] D-03 and D-04 closed
- [ ] **D-13's caveat is visible wherever a hit, chip or wildcard is recommended** — not resolved by
      this epic, but not silently dropped either (see §0)
