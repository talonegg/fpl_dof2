# E1 — Weekly Operating Loop

**Objective:** OBJ-3, minimum viable — a defensible transfer recommendation before every deadline
**Target:** GW2 deadline, ~28 Aug 2026 · **Estimate:** 3.5–4.5 days
**Depends on:** E0

---

## 0. Build outcome — 2026-08-11

**E1-S1 through E1-S5 are built.** `fpl-dof week` runs as a pipeline stage and writes one artefact
that answers the whole question; the web app renders it as a "This week" panel.

**The API gap was total, not partial.** E1-S1 anticipated a manual override "when confidence is
low". Probing the live endpoints showed that before GW1 is scored there is *no* reconstructible
state at all — `picks` 404s, `bank` and `value` are null, `transfers` is empty. So a declared squad
is a first-class input rather than a degraded mode, and the service reports provenance
(`from_picks` / `reconstructed` / `declared`) instead of hiding it. Recorded as
[DL-20](../00-decision-log.md#dl-20).

**Purchase prices are not public.** Only the authenticated `my-team` endpoint carries them, and this
project will never authenticate (Invariant 4). They are reconstructed from the transfer log plus
per-gameweek prices, and where neither is available the run says so rather than quietly using the
current price — which would overstate what the squad can raise for anyone who has risen.

**What the plan got right.** Extending the MILP was indeed a modest change. Solving each transfer
count as a separate model — rather than penalising transfers inside one — cost a few extra solves
and produced the thing the weekly output actually needed: a ranked list where every option carries
its own number, including the roll.

**What was harder than it looked.** The free-transfer count is path-dependent and a wildcard week
does not consume the allowance; reading it off the transfer count alone concludes the manager is
deep in the red and then refuses every sensible hit for weeks. The timezone work is also not a
display concern: the UK and Australian clock changes do not coincide, so the offset moves from +9
to +11 for several weeks and any code reasoning in local time is wrong exactly then.

---

## 1. Why this is next

The moment GW1 is submitted, the problem changes. Building stops being the risk; *operating* becomes
the risk. There is a deadline every week for 37 more weeks, and most of them fall between 02:30 and
05:00 AEST.

E1 is small because E0 did the hard part. Extending the optimiser from *choose 15 from scratch* to
*given my squad, what is the best single transfer?* is a modest change to an existing model. What E1
really delivers is **the ability to answer "what should I do this week?" in ten minutes instead of two
hours** — which is what makes the remaining 37 weeks sustainable.

## 2. Scope

### In scope

- Load the owner's actual squad, bank, free transfers and chips used, for a configured team ID
- Reconstruct pre-deadline squad state from public endpoints, with a manual override path
- Single-gameweek transfer optimiser: 0, 1 or 2 transfers, with correct hit arithmetic
- Starting XI, captain, vice-captain and bench order recommendation
- Availability and price-change alerts for owned players
- A refresh command that updates everything in one go
- Deadline countdown in **both UK and local time**

### Out of scope

Multi-gameweek planning, chips, the risk dial, free-transfer rollover beyond a simple count — all E4.
Automation — E7. Any new data source — E5.

## 3. Stories

### E1-S1 — Squad state service
**1.5 days · implements FR-25**

The awkward one, because of the API gap documented in the `fpl-api` skill.

- Load `entry/{team_id}/`, `/history/`, `/event/{gw}/picks/`, `/transfers/`
- **Reconstruct current squad before a deadline**: last finished gameweek's picks, overlaid with
  transfers made since, with bank and value derived from price history
- Recompute free transfers available from transfer history rather than assuming a count
- Track purchase prices so selling values are correct (the 50% sell-on fee from E0-S4)
- Report reconstruction confidence, and accept a manual squad override when it is low

**Acceptance**
- Squad, bank, free transfers and chips used all load for a configured team ID
- Pre-deadline reconstruction verified against a known state
- Low-confidence reconstruction warns loudly rather than guessing silently
- Manual override path works and is documented

---

### E1-S2 — Transfer optimiser
**1 day · implements FR-18 partially, FR-24**

- Extend the E0 MILP with transfer-in and transfer-out variables against the current squad
- Correct budget arithmetic using selling prices, not purchase prices
- Hit arithmetic: transfers beyond those free cost −4 each
- Evaluate 0, 1 and 2 transfers and rank them
- **Always present "no transfer, roll it" as a first-class option** (FR-24)

**Acceptance**
- Recommends a transfer, or explicitly recommends none, with the expected gain for each
- Never recommends a hit whose expected gain is below the 4-point cost
- Resulting squad is legal, verified by the E0-S4 validator
- Property tests extended to cover transfer scenarios

---

### E1-S3 — Team selection
**0.5 day · implements FR-19**

- Optimal starting XI and formation from the 15
- Captain and vice-captain
- Bench order by `P(plays) × xP` — a heuristic, adequate until E3 provides a real minutes model

**Acceptance**
- Legal formation, correct captain, sensible bench ordering
- Selection re-runs instantly when the squad changes

---

### E1-S4 — Weekly refresh and alerts
**0.5–1 day**

- One command that refreshes data, recomputes forecasts, and produces the recommendation
- Alerts for owned players: injury and status changes, price rise and fall risk
- Deadline countdown in **both UK and local time** — see the timezone finding in
  [INPUTS-REQUIRED §7](INPUTS-REQUIRED.md#7-a-finding-that-needs-your-decision-timezone)
- Extend the E0 web view with a "this week" panel

**Acceptance**
- `fpl-dof week` produces a complete recommendation from cold in under five minutes
- Availability changes on owned players are surfaced without being looked for
- Deadline shown in both zones, with an explicit "decide by" time in local evening

---

### E1-S5 — Post-deadline reconciliation
**0.5 day · closes the loop that lineage only promises**

[Design §12.4](../04-conceptual-design.md#124-lineage) sets the practical test for lineage: *"for any
recommendation the system ever made, it must be possible to reconstruct exactly what it knew at the
time and why it advised that."* That records what was **advised**. Nothing yet records what was
actually **played** — and the two diverge, because the human overrules (correctly, per ASM-6), and
occasionally because of a mis-click at 03:00 local.

Without this, [E8](E8-in-season-operations.md)'s decision log grades the model against a memory of
what you did, which is rationalisation rather than evidence.

- After each deadline passes, fetch `entry/{team_id}/event/{gw}/picks/` — now public — and diff it
  against the recommendation plus the recorded overrides
- Classify every difference: **intentional override** (with its logged reason), or **unexplained**
- Persist the diff to gold alongside the recommendation, so the season-long comparison of
  model-versus-intuition has a real dataset behind it

**Acceptance**
- Every gameweek has a stored triple: what was advised, what was played, why they differ
- An unexplained divergence is surfaced, not silently absorbed — it usually means a submission error,
  which is worth catching in GW3 rather than in May

## 4. Definition of done

- [ ] **Your real squad loads correctly from your team ID** — *yours to confirm.* The loader and
      its reconstruction are built and tested, but no entry has published picks yet, so this cannot
      be verified against your team until GW1 is scored (DL-20)
- [x] A transfer recommendation, with alternatives and the roll option
- [x] Recommended squad is legal, verified programmatically against the E0-S4 validator
- [x] Hit arithmetic correct and never recommended below break-even
- [x] One command produces the full weekly recommendation (`fpl-dof week`, inside `run`)
- [x] Deadline visible in both UK and local time, with a decide-by time
- [x] Advised-versus-played reconciliation, ready to run from the first scored gameweek
- [ ] **The whole loop takes under 15 minutes of your attention** — measurable only in use

## 5. The real success test

**Can you get from "it is Thursday evening" to "I know what I am doing this week and why" in under
fifteen minutes?** If yes, the season is operable and every later epic is an improvement on a working
system. If no, fix that before building anything else.
