# Guiding principles — product, modelling and delivery

How numbers are presented, how a formulation is chosen, how a model is promoted and measured, and how
work is sliced. These five moved out of [`DESIGN-PRINCIPLES.md`](DESIGN-PRINCIPLES.md) in v2.0
([DL-75](decisions/DL-75.md)) because they shape *what* is built rather than whether the codebase
stays sound, so they need not be amendment-controlled. Their IDs were kept so that the citations in
code still resolve.

**This page is editable.** Rewrite a principle to the new truth when the owner changes it, and record
the change as a decision. Departing from one in code is also a decision (`DL-nn`), not a defect, and
takes no `DP-WAIVER` marker. Where one restates an invariant in `CLAUDE.md` (Invariant 6, variance on
every forecast), the invariant still binds.

| | Principle |
| --- | --- |
| **DP-07** | Build vertical slices that each exit usable |
| **DP-08** | New behaviour ships dark, and is promoted on evidence |
| **DP-09** | Every number carries its derivation, its uncertainty and its provenance |
| **DP-10** | Prefer the formulation you can argue with |
| **DP-12** | Measure skill against a baseline, never in absolute terms |

---

## DP-07 — Build vertical slices that each exit usable

**Every increment is a thin path through all the layers it needs, ending in something that works.
Never a horizontal layer waiting on another layer to become useful.**

**Why.** [Blueprint B2](planning/02-project-plan-and-blueprint.md). The defence against R-05 — a solo
project stalling mid-build and leaving a half-connected system that is worse than none. A plan of
usable slices can be re-ordered; a plan of layers cannot.

- A release or epic that cannot be stopped after any of its stories and still leave a working system
  is mis-decomposed.
- Thin does not mean shortcut: the binding principles are present in the thinnest slice.

**Departed from when** a story delivers "the data layer" with no consumer; a refactor lands that
nothing uses yet; nothing is demonstrable until three stories have all landed.

## DP-08 — New behaviour ships dark, and is promoted on evidence

**Model and decision changes land behind a flag, off by default, run in shadow mode, and are promoted
only when evidence says they are better — never because they are finished.**

**Why.** R-17: retraining on ten gameweeks of the noisiest target in the project is how a working
system quietly gets worse, and mid-season is when every change gets proposed. The bar for promotion
is [E8 §5](planning/epics/E8-ongoing-in-season-monitoring.md#5-the-bar-for-changing-the-model-mid-season);
the flag mechanism is [Design §13](planning/04-conceptual-design.md#13-configuration-and-feature-flags).

- **Prefer shrinkage to refitting**: blending toward current-season evidence in proportion to how much
  exists degrades gracefully; a fresh fit lurches.
- **A bug fix is not a model change** and does not wait. If it is being argued about, it is a model
  change.

**Departed from when** a model is retrained and deployed in one step; a flag is added and immediately
defaulted on; a change is promoted after two good gameweeks.

## DP-09 — Every number carries its derivation, its uncertainty and its provenance

**A figure the system shows or acts on is traceable to its inputs, states how confident it is, and
says where it came from when that is not obvious.**

**Why.** [Blueprint B6](planning/02-project-plan-and-blueprint.md): the system exists to make the
owner a better manager, and a recommendation that cannot be explained will not be trusted or
followed. *A quantity estimated and presented as measured is worse than no quantity.*

- Expected points decompose by scoring component; the decomposition is a product feature.
- Every forecast shows an uncertainty range. **A predicted 5.2 that could be anything from 0 to 15
  never renders like a measurement** (Invariant 6).
- Estimated, assumed and measured quantities are distinguishable, and named as such; "not measured"
  never renders as zero.
- Every recommendation shows what it beat and by how much, with "do nothing" as a first-class option.

**Departed from when** a bare number appears with no interval; an estimate is displayed identically to
an observation; a recommendation is shown without its runner-up.

## DP-10 — Prefer the formulation you can argue with

**Where two designs are close in expected quality, choose the one whose output a human can
interrogate and challenge.**

**Why.** [DL-15](decisions/DL-15.md): chip timing is decided by enumerating scenarios, because
*"Free Hit in GW18 beats GW17 by 4.1 points"* is a sentence you can argue with and a chip binary
flipping inside a solver is not. An unarguable recommendation gets overridden on instinct or followed
on faith.

- Prefer enumeration over opaque search where the space is small enough.
- Prefer a chain of small models with observable intermediate outputs over one monolith, unless the
  monolith is *materially* better — and then the trade is a recorded decision (Q-04, DL-53).
- Keep runners-up and margins, not just winners.

**Departed from when** an approach is chosen on benchmark score alone; intermediate results are
discarded; the answer to "why did it pick that?" is "the solver decided".

## DP-12 — Measure skill against a baseline, never in absolute terms

**Every quality metric is expressed as improvement over a stated, dumb baseline. A threshold a
no-edge model could pass is not a threshold.**

**Why.** [DL-13](decisions/DL-13.md) amendment 1: the original `MAE ≤ 2.1` sat in the range a
constant predictor achieves, and would have certified a model with no edge.

- Every metric names its baseline — typically a `(position, price)` predictor, the template team, or
  the overall average. Backtests report against the naive strategy.
- Respect sample size: one season's captaincy hit rate is n=38. **Metrics too noisy to act on
  in-season are backtest gates only**, and say so.
- **"It improved" is not a finding. "It improved relative to X, by more than the noise in X" is.**

**Departed from when** a metric is quoted with no comparator; a change is accepted on an absolute
score; a movement within its own error bars triggers action.
