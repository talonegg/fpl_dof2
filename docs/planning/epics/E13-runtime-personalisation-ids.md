# E13 — Runtime Personalisation: Team and League IDs

**Objective:** OBJ-5 · **Target:** independent of the model programme · **Estimate:** 2–3 days
**Depends on:** E6 (web surface), E7 (workflows) · **Implements:**
[Model Improvement Plan §7](../05-model-improvement-plan.md) · **Realises:** [DL-44](../00-decision-log.md#dl-44)
· **Bears on:** Q-16
**Status:** Complete — all four stories landed ([DL-64](../00-decision-log.md#dl-64--e13-built-all-four-stories-landed-realising-dl-44-end-to-end)). Q-16 stays open by design.

---

## 0. Why this is its own epic

The owner asked that the FPL team ID and mini-league ID be **enterable through the UI** and **never
persisted in the repository**. [DL-44](../00-decision-log.md#dl-44) settled the design; this epic
builds it. It is separate from the model-improvement epics (E9–E12) because it shares none of their
dependencies and gates none of their work — it can be built at any point after E6 and E7 exist, which
they do.

The plan (§7) originally proposed folding this into E6 and E7 as stories. Since **E6 has already
shipped**, reopening it is more disruptive than collecting the work here; this epic *realises* those
proposed E6/E7 stories in one place and cross-references both.

## 0.1 The constraint that shapes every story

[**Invariant 8** — the browser never calls an external API.](../../CLAUDE.md) The SPA reads published
static artefacts and nothing else; it cannot fetch the owner's picks or a league's standings itself,
and the FPL API sends no permissive CORS headers even if it were allowed to. So "enter the ID and see
your data" **cannot** mean "the browser fetches it", and [DL-03](../00-decision-log.md#dl-03) forbids
adding a backend that could. The two IDs are therefore treated as two genuinely different things that
normally coincide for a single user: a **build-time input to CI**, and **local personalisation plus a
dispatch convenience**.

## 1. Stories

### E13-S1 — Pipeline reads the IDs from repository variables · 0.5 day · NFR-11, NFR-13 · realises the E7 note
The pipeline reads `FPL_DOF_TEAM_ID` / `FPL_DOF_LEAGUE_ID` from the environment via the overrides
already declared on `EntryConfig`. In CI these come from GitHub Actions repository **variables** — the
correct home for a non-secret identifier (Invariant 10: variables, not secrets, and never committed).

- `config/local.yaml` remains the local-dev path and stays gitignored. **Nothing about the owner's
  identity enters git.**
- The workflows are documented to source the IDs from repository variables; INPUTS-REQUIRED §8 already
  names them.

**Acceptance:** a CI run picks up the IDs from repository variables with no committed value anywhere;
the local path still works from gitignored config.

### E13-S2 — Settings view backed by `localStorage` · 1 day · FR-32 · realises the E6 story
A new Settings screen lets the owner type their team ID and league ID; the values live in browser
`localStorage` only — never transmitted, never committed.

- Because of Invariant 8 the setting **personalises already-published artefacts**: highlights the
  owner's row in the league table, badges the owned squad, filters the scout to owned players.
- It can only personalise what the pipeline already published. When the published league artefact was
  built for a **different** league than the one entered, the view says so plainly (DP-09/DP-15),
  consistent with [DL-40](../00-decision-log.md#dl-40)'s treatment of the absent league — it does not
  silently show the wrong data or a blank.

**Acceptance:** entering an ID personalises the published views; a mismatch between the entered ID and
the published artefact is stated explicitly, not hidden.

### E13-S3 — Owner-triggered run: `workflow_dispatch` deep link · 0.5 day · bears on Q-16
The Settings view composes a `workflow_dispatch` deep link (or copyable inputs) so the repo owner can
dispatch a pipeline run with the entered IDs. **No token ever reaches the client** (Invariant 10,
NFR-13) — the owner authenticates to GitHub themselves.

- [Q-16](../05-model-improvement-plan.md#9-new-open-questions-raised-by-this-plan) is explicitly left
  **open and out of scope**: whether the browser may ever *auto*-dispatch a run. That needs either a
  client-held token (forbidden) or an owner-mediated flow, and is an owner-and-security decision, not
  a default. This story ships the manual deep link only.

**Acceptance:** the deep link dispatches a run when the owner is authenticated to GitHub; no
credential or token is present anywhere in the client bundle (verified against the secret-scan hook).

### E13-S4 — Charter requirement + config-smell cleanup · 0.5 day · NFR-11
Name the UI-entry-of-IDs behaviour as a charter requirement (per DL-44's consequences), and remove the
single-user assumption baked into `config/local.yaml`'s committed scaffold so the committed default
carries no personal identifier.

**Acceptance:** the charter names the requirement; no committed file carries a real team or league ID.

## 2. Definition of done

- [x] Pipeline sources the IDs from repository variables in CI and gitignored config locally; nothing
      personal is committed
- [x] Settings view stores team/league IDs in `localStorage` and personalises published artefacts
- [x] Mismatch between entered ID and published artefact is surfaced plainly (DP-09/DP-15)
- [x] `workflow_dispatch` deep link dispatches an owner-authenticated run with **no token in the client**
- [x] Charter requirement recorded (FR-40); committed config carries no personal identifier
- [x] **Q-16 left open** — no auto-dispatch shipped; the manual, owner-mediated path only

See [DL-64](../00-decision-log.md#dl-64--e13-built-all-four-stories-landed-realising-dl-44-end-to-end)
for what shipped against each story, and where the acceptance criteria's "or copyable inputs"
alternative was the one that actually applied.

## 3. The honest question

**"Could someone clone this public repo and learn who the owner is from it?"** The whole point of
DL-44 is that the answer stays *no* while the owner still gets UI entry. Every story is checked against
that: the IDs are public identifiers, but their presence in the repo is a persistence smell the owner
asked to remove — and this epic removes it without a backend and without the browser ever calling out.
