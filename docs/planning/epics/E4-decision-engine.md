# E4 — Decision Engine

**Objective:** OBJ-3 (full), OBJ-4 · **Target:** ~GW15 · **Estimate:** 6–9 days
**Depends on:** E3 · **Repays debt:** D-03, D-04
**Hard constraint:** chip set 1 expires at the **GW19 deadline, 13:30 GMT Sat 2 Jan 2027**

---

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

**Acceptance:** produces a coherent multi-week plan; property tests extended across the horizon;
solves inside the time budget.

### E4-S3 — Chip modelling · 2 days · FR-20 · repays D-04
Wildcard, Free Hit, Triple Captain, Bench Boost as decision variables within the horizon, plus a
longer-range **chip calendar** projecting likely windows across the season.

- Wildcard relaxes hit costs; Free Hit needs a parallel squad variable set for one gameweek only
- Triple Captain linearised as `z ≤ k`, `z ≤ tc`, `z ≥ k + tc − 1`
- Set 1 variables forced to zero after GW19
- Calendar accounts for double and blank gameweeks, which reshape everything in the second half

**Acceptance:** a chip calendar exists and updates weekly; set-1 expiry is enforced, not advisory.

### E4-S4 — Risk dial and ownership · 1.5 days · FR-21, FR-16 · DL-07
Effective ownership modelled as an entity. A signed ownership-deviation term in the objective, from
template-safe through differential-aggressive.

**The UI obligation matters more than the dial itself:** every recommendation must state the bet
plainly — "you are 18% underweight on the most-captained player; you gain if he blanks and lose
roughly 4 points of rank-equivalent if he hauls." Making the bet explicit is what lets you apply
judgement the model does not have.

**Honest limitation to document:** a MILP cannot represent portfolio variance, which is quadratic,
and players in the same match are strongly correlated — two defenders from one club share a clean
sheet. The risk term is a linear proxy. The correct treatment is the stochastic layer deferred in
DL-06.

### E4-S5 — Constraint overrides · 0.5 day · FR-22
Locks, bans, budget caps, forced formations, club exclusions, and forcing or forbidding a chip in a
given gameweek. Infeasible combinations must explain *why*.

### E4-S6 — Explanation layer · 1 day · FR-23, FR-24
Decomposition, marginal gain over doing nothing, runner-up options and why they lost, ownership bet,
price exposure, and the assumptions — "this assumes he starts, which the model puts at 71%".

**"Roll the transfer" remains a first-class candidate, always shown.**

## 3. Definition of done

- [ ] Multi-gameweek plan over a rolling horizon, with correct free-transfer and hit arithmetic
- [ ] Chip calendar live, with set-1 expiry enforced
- [ ] Risk dial functional; ownership bet surfaced on every recommendation
- [ ] Overrides working, with useful infeasibility messages
- [ ] Every recommendation explained with runner-ups and marginal gain
- [ ] Property tests cover the full constraint set including chips
- [ ] Solve time inside budget, with greedy fallback proven
- [ ] D-03 and D-04 closed
