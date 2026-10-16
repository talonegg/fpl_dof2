# E14 — Weekly Recommendation Review and Hindsight Oracle

**Objective:** OBJ-1, OBJ-3, OBJ-7 · **Target:** In-season (live from GW7) · **Estimate:** 2–3 days
**Depends on:** E1 (weekly operating loop), E4 (decision engine), E6 (web application), E8 (in-season operations)
**Implements:** FR-41, FR-42 · **Realises:** [DL-72](../00-decision-log.md#dl-72)
**Status:** Proposed

---

## 0. Why this is its own epic

[E8](E8-in-season-operations.md) established the weekly discipline: *"What did the model recommend, and what actually happened?"* [DL-69](../00-decision-log.md#dl-69) delivered the persistence for this by adding the advice ledger (`data/ledger/advice/gwNN.json`) and publishing `log.json` to show played vs advised reconciliation.

However, the current reconciliation only answers whether the human **followed** the primary engine's advice. It has two blindspots:

1. **It does not grade what the advice actually scored.** When an advised player blanks or an unadvised bench option hauls, the system records `followed: false` without measuring the point consequence. It also does not compare candidate models (e.g. the `xp_v1` component engine vs the `C1` boosted xG shadow vs `B0` price-position baseline vs trailing form) on the owner's actual squad.
2. **It lacks a benchmark ceiling (the hindsight oracle).** After a gameweek finishes, the owner cannot see what the *mathematically optimal* legal transfer and starting lineup was given their pre-deadline budget and squad state, nor can they see how each model evaluated those optimal moves *before* kickoff. Without this, post-deadline analysis is pure impression: managers either over-index on fluky 18-point outliers or excuse systematic model blindspots.

This epic builds the automated weekly measurement and review loop directly into the `week` and `publish` stages.

---

## 0.1 Constraints that shape every story

1. [**Invariant 5** — No look-ahead in features, models or backtests.](../../CLAUDE.md) Models must be graded strictly on what they predicted *before* the deadline. Pre-deadline advice and expected points are frozen in the ledger and are never recomputed with hindsight.
2. [**Invariant 8** — The browser never calls an external API.](../../CLAUDE.md) All scoring, MILP hindsight solving, and diagnostics run in the Python pipeline. Precomputed static results are published into `log.json` for the client to render.
3. [**Invariant 2** — Scoring rules, price and hit values live in configuration and rules as data.](../../CLAUDE.md) Transfer hit penalties (-4 pts), auto-sub formation bounds (minimum 3 DEF, 1 GKP), and captaincy rules are sourced from `GameRules`, never hardcoded.
4. **Least new code (Ponytail principle):** The hindsight oracle reuses the existing transfer MILP ([recommend_transfers](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/optimise/transfer.py#L250)) with actual points as input; scoring advice reuses pure FPL scoring logic from the prospective harness.
5. **Pre-Registration Firewall ([PREREG_C1_vs_C3.md](file:///c:/JHH/source/fpl_dof2/prospective/PREREG_C1_vs_C3.md)):** Retrospective replays for GW1–6 (including `A_odds` backfill) are strictly quarantined to the web UI / Hindsight section and must never enter the confirmatory statistical evaluation sample (GW7–GW38).
6. **Raw Odds Persistence ([DP-11](file:///c:/JHH/source/fpl_dof2/docs/DESIGN-PRINCIPLES.md#dp-11--every-run-is-reproducible-from-its-recorded-inputs)):** Raw pre-deadline `fixtures.csv` odds feeds are permanently archived to `data/bronze/fdcouk/` on the `ledger` branch for every prospective gameweek.

---

## 1. Stories

### E14-S1 — Pre-deadline multi-model advice persistence · 0.5 day · FR-41
Before each deadline, the `week` stage evaluates transfer and lineup recommendations across candidate models for the owner's current squad state and stores them in the advice ledger ([gwNN.json](file:///c:/JHH/source/fpl_dof2/data/ledger/advice/gw06.json)):
* **Candidate models:**
  * `xp_v1`: Primary component chain (minutes mixture, team ratings, per-90 rates, bonus).
  * `c1`: Challenger shadow model (per-position boosted xG + minutes head).
  * `a`: Component model A.
  * `a_odds`: Model A with odds-driven team layer.
  * `b0`: Price and position linear regression baseline.
  * `model_free`: Trailing form baseline (trailing 6-gameweek average points per match).
* For each model, record: recommended transfers, starting XI, captain, vice-captain, and pre-deadline expected points.

**Acceptance:** `data/ledger/advice/gwNN.json` contains a `models` mapping with pre-deadline advice for all candidate models alongside the primary recommendation.

---

### E14-S2 — Realized recommendation scoring and weekly model ranking · 0.5 day · FR-41
A pure evaluation module (`pipeline/src/fpl_dof/week/score_advice.py`) scores each candidate model's stored recommendation against finished gameweek actual points:
* **FPL rule accuracy:**
  * Handles 0-minute starters via prioritized bench auto-substitutions respecting formation constraints (min 3 DEF, 1 GKP, etc.).
  * Doubles captain points; falls back to vice-captain if the captain played 0 minutes.
  * Subtracts transfer hits: $\max(0, \text{transfers} - \text{free\_transfers}) \times 4$.
* **Metrics emitted per model:**
  * Net actual points, gross points, hit points deducted, captain points scored.
  * Gain over the do-nothing roll option.
  * Prediction delta: $\text{Net Actual} - \text{Expected Points}$.
* **Model ranking:** Ranked table of all models plus the owner's played team and the do-nothing roll option.

**Acceptance:** Unit tests verify correct autosub priority, vice-captain promotion, and hit penalties; models are ranked deterministically against silver `player_gameweek.parquet`.

---

### E14-S3 — Hindsight oracle transfer and lineup solver · 0.5 day · FR-42
Implement `solve_hindsight_optimal` in `pipeline/src/fpl_dof/week/oracle.py`:
* Solves the exact MILP formulation in [recommend_transfers](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/optimise/transfer.py#L250) using the owner's pre-deadline `SquadState` (bank, free transfers, player selling values) and the finished gameweek's actual points.
* Bypasses the start-probability floor (since appearances are known facts) while enforcing all FPL squad budget, club, and formation constraints.
* Solves across transfer counts ($k \in \{0, 1, 2, ...\}$) to identify the optimal single transfer, optimal 2-transfer combination, and the overall unconstrained ceiling.

**Acceptance:** Produces the mathematically optimal legal transfers, starting XI, and captain choice for the owner's team in under 5 seconds of solve time.

---

### E14-S4 — Oracle vs. model review ("Oracle Gap" diagnostics) · 0.5 day · FR-42
Compare the hindsight-optimal solution against each model's pre-deadline beliefs:
* For each player in the optimal moves (optimal IN, optimal OUT, and optimal Captain):
  * Extract each model's pre-deadline expected points and rank.
  * Calculate the gap: $\text{Actual Points} - \text{Model xP}$.
* Classify the diagnostic reason for divergence:
  * **Model Blindspot:** Player had high minutes/underlying data and was affordable, but was discounted by the model (e.g. Dewsbury-Hall in GW6).
  * **High-Variance Outlier:** Player had near-zero form and was discounted across all models and market baselines (e.g. Henderson in GW6).
  * **Captaincy Trap:** Model preferred a lower-scoring asset over a reliable baseline captain (e.g. Fernandes over Haaland in GW6).

**Acceptance:** Emits a structured diagnostic breakdown mapping the winning actions to what each model knew beforehand.

---

### E14-S5 — Web contract publication and "Hindsight" sub-section on Models tab · 0.5–1 day · OBJ-5
* **Contract:** Add optional `model_rankings` and `hindsight_optimal` objects to `$defs/log_gameweek` in [log.schema.json](file:///c:/JHH/source/fpl_dof2/contracts/v1/log.schema.json) (or as part of `models.schema.json`).
* **Publisher:** [season_log.py](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/publish/season_log.py) writes the new sections into `data/web/v1/log.json` (or `models.json`).
* **Web UI (Models Page — `/models`):**
  * Add a dedicated **"Hindsight"** entry to `SECTIONS` in [ModelsPage.tsx](file:///c:/JHH/source/fpl_dof2/web/src/components/models/ModelsPage.tsx), anchoring at `#models-hindsight` and navigable via `#/models?section=hindsight`.
  * **Prior Week Selector:** An interactive gameweek selector (dropdown or pill bar) allowing the user to select any completed prior gameweek of the current season (e.g., GW1 through GW6).
  * **Multi-Model Recommendation Leaderboard:** For the selected gameweek, ranks the realized score of each model's pre-deadline advice (Owner vs Engine `xp_v1` vs Challenger `C1` vs Model `A` vs `A_odds` vs `B0` baseline vs `Model-Free` trailing form) against actual match points, showing transfers made, captain choice, and net points.
  * **Optimal Hindsight Transfers & Team Selection (Oracle):** Displays the mathematically optimal legal transfers and starting lineup calculated by the hindsight MILP solver, showing the point ceiling achievable for the owner's squad within budget.
  * **Pre-Deadline Model Diagnostics ("Oracle Gap"):** Side-by-side review of how each model scored the oracle's players and transfers prior to the deadline, isolating genuine model blindspots from high-variance outliers.

**Acceptance:** `src/contract/types.ts` regenerated; web tests and schema validation pass; the Models tab includes the "Hindsight" section with a working prior-week selector; UI renders cleanly on mobile and desktop without breaking when review data is absent.

---

### E14-S6 — Weekly raw odds feed archiving (Recommendation #1) · 0.25 day · DP-11
Ensure that for every prospective gameweek (GW7+), the raw bookmaker odds snapshot is captured and permanently archived into the data platform:
* **CI Ingest:** When `prospective_ci.py plan` fetches `fixtures.csv` during the pre-deadline decision window (`T-14h` to `T-45m`), persist the raw file to `data/bronze/fdcouk/GW{gw}_fixtures.csv`.
* **Ledger Persistence:** Add `data/bronze/fdcouk` to `RECORD` in `prospective_ci.py` so raw odds snapshots are bundled into `prospective.tgz` and committed to the `ledger` branch.
* **Benefits:** Provides uncorrupted ground-truth historical market data for future model calibration and walk-forward backtests.

**Acceptance:** CI pack/unpack roundtrip tests verify `data/bronze/fdcouk/GW{gw}_fixtures.csv` is preserved in the ledger tarball; live odds flow directly to `A_odds`.

---

### E14-S7 — Retrospective GW1–6 odds backfill for A+odds (Recommendation #2) · 0.5 day · FR-42
Backfill historical odds for the first 6 gameweeks of 2026/27 to allow full 5-model hindsight analysis and season replay:
* **Data Sourcing:** Conforming match opening/closing odds for GW1–6 as a historical proxy.
* **Replay Execution:** Run the frozen `comp_ot` model over GW1–6 using historical odds, generating squad selections, captaincy, and net points.
* **Artefact Update:** Populate `scripts/models_history/data/replay_2627.csv` and regenerate `web/public/static/models_history_2627_replay.json`.
* **Firewall Rule:** Strictly quarantined from prospective confirmatory evaluations ([PREREG_C1_vs_C3.md](file:///c:/JHH/source/fpl_dof2/prospective/PREREG_C1_vs_C3.md)); labelled with clear provenance in the replay document (`"GW1-6 replay uses closing odds proxy; descriptive only"`).

**Acceptance:** `models_history_2627_replay.json` includes `a_odds` across GW1–6; Hindsight Oracle prior-week selector displays `A_odds` alongside all other models; prospective hypothesis test suite remains untouched.

---

## 2. Definition of done

- [x] `data/ledger/advice/gwNN.json` stores pre-deadline advice for all candidate models
- [x] Pure scorer in `pipeline/src/fpl_dof/week/score_advice.py` correctly calculates realized points with FPL autosubs, vice-captain promotion, and hit penalties
- [x] `solve_hindsight_optimal` finds the legal hindsight-optimal transfer and lineup within pre-deadline budget
- [x] Diagnostic review identifies model blindspots vs high-variance outliers
- [x] Additive updates to contracts (`log.schema.json` / `models.schema.json`) pass schema validation
- [x] Static artefacts publish the ranking and hindsight review for completed gameweeks
- [x] Web application displays the feature under `/models` in the **Hindsight** sub-section (`#models-hindsight`) with an interactive prior-week selector
- [x] Weekly pre-deadline odds snapshots are archived into `data/bronze/fdcouk/` and committed to the `ledger` branch (E14-S6)
- [x] GW1–6 replay data includes `A_odds` with provenance metadata, quarantined from confirmatory testing (E14-S7)
- [x] 100% test coverage on new pure scoring, oracle, and diagnosis logic

---

## 3. The honest question

**"Does this make the model better, or are we beating ourselves up over unpredictable 18-point outliers?"**

The danger of hindsight analysis in FPL is result-oriented thinking: concluding the model is broken because an obscure £4.9m midfielder with 0.4 PPG scored 18 points. 

The purpose of E14 is the exact opposite: **to separate variance from model defects**. When an optimal move was missed by *every* model and baseline (like Henderson in GW6), the diagnosis proves it was noise and stops the owner from making panicked adjustments. When a candidate model like `C1` or `B0` correctly ranked an asset or avoided a captaincy error that `xp_v1` fell into (like Dewsbury-Hall or Haaland in GW6), the diagnosis provides actionable evidence to refine model weights.
