# E6 — Web Application

**Objective:** OBJ-5 · **Target:** ~GW16 · **Estimate:** 7–10 days
**Depends on:** E3 (forecasts worth exploring), E4 (plans worth showing)

> **Target moved from GW14 to GW16.** E6 was previously targeted *before* E4, one of its own stated
> dependencies. Everything except E6-S7 depends only on E3, so those stories can start once E3 lands;
> the planner half genuinely needs E4. If E4 slips, ship E6 without E6-S7 rather than blocking the
> whole epic — the scout experience is the objective here, and it needs nothing from the optimiser.

---

## 1. Why here

E0 shipped a minimal view; E1 added a weekly panel. E6 is the product surface proper — the scouting
experience of OBJ-5, which is the one objective with **standalone value regardless of whether the
model turns out to have edge**. If E3 concludes the forecast is no better than intuition, a good
scout UI is still worth having; the reverse is not true.

Note the [scheduled decision point after GW4](README.md#scheduled-decision-points): if the model is
not beating your intuition, E3 takes priority over this epic. A polished interface on a poor forecast
is worse than no interface, because it lends unearned authority.

## 2. Stories

### E6-S1 — App shell and data layer · 1 day · FR-34 · **delivered**
Routing, layout, theming, responsive frame, data loading with caching. Light and dark themes via
tokens. **The app reads published static artefacts only — never an external API.**

What the remaining stories plug into, decided in
[DL-35](../00-decision-log.md#dl-35--the-web-app-routes-on-the-hash-and-published-data-is-loaded-once-into-a-react-context):

- **Routes** are declared in `web/src/App.tsx` (`AppRoutes`) with the nav model in
  `web/src/routes/nav.ts`. `/scout`, `/player/:id`, `/compare`, `/squad` and `/fixtures` exist and
  render, each naming the story that fills it out. Hash routing, because GitHub Pages cannot rewrite
  unknown paths onto `index.html`.
- **Data** is fetched once into a React context. A view calls `useData()` from
  `web/src/data/DataProvider.tsx` and gets the published artefacts non-nullable; `web/src/data/` is
  the only package permitted to call `fetch`, which is where Invariant 8 is enforced structurally.
- **Colour lives only in `web/src/tokens.css`**, with a light and a dark value for every token. A
  literal in a component stylesheet is a defect — it is right in one theme and wrong in the other.

### E6-S2 — Scout view · 2 days · FR-27 · the centrepiece · **delivered**
Searchable, filterable, sortable table over every Premier League player: position, club, price,
minutes, ownership, form, expected points, underlying stats, fixture run. Saved filter presets.
Multi-select into comparison.

What landed, and what the remaining stories can rely on
([DL-36](../00-decision-log.md#dl-36--the-scout-table-virtualises-on-tanstackreact-virtual-and-hands-a-comparison-selection-over-in-the-url)):

- **`web/src/components/scout/`** holds the view. `columns.tsx` is the column set *as data* — sort
  accessor, renderer, width, group, default visibility — so E6-S3 and E6-S4 reuse the accessors
  rather than restating how a component is rendered. `filters.ts` is pure and DOM-free.
- **Virtualised** on `@tanstack/react-virtual`. Verified in real Chromium at all three viewports:
  587 published players, 15–29 rows in the DOM. **Q-06 stands as scoped** — plain JSON and a
  client-side `filter`/`sort`, no DuckDB on this path. Confirming it on a *real phone on a throttled
  connection* is still open in the definition of done below; a desktop Chromium run is not that.
- **Two layouts, not one shrunk.** Below 640px the rows become cards and sorting moves from the
  column header into a control, because a header that scrolls sideways off a 390px screen is worse
  than no header. The breakpoint is expressed twice — `scout.css` and `PHONE_QUERY` in
  `useMediaQuery.ts` — because the virtualiser needs the row height in pixels; change them together.
- **The comparison selection is a URL**: `#/compare?compare=1,2,3`, parsed and built by
  `web/src/data/comparison.ts`. That is the seam E6-S4 reads.
- **Not columns yet:** `minutes`, `form` and the fixture run named above are not in `players.json`.
  `start_probability` stands in for minutes and is labelled as the forecast it is; the other two
  wait on `history.json` and `fixtures.json`, and are one column definition each when those land.

**Virtualisation is mandatory** — ~700 players with many columns cannot render naively within the
NFR-04 budget.

**No DuckDB here.** [Q-06 is provisionally resolved by scoping](../04-conceptual-design.md#15-open-design-questions):
the scout dataset is ~700 rows, which plain JSON plus client-side filtering handles faster and far
smaller than a multi-megabyte WASM download would — and that download would land on the first-paint
path, against a 3 MB budget. DuckDB-WASM is lazy-loaded and route-scoped to the *history* views
(E6-S5), where the data is genuinely large enough to justify a query engine. **Confirm by measurement
on a phone**, not by preference — and if the measurement contradicts this, that is a finding worth
recording, not a reason to be embarrassed.

### E6-S3 — Player detail · 1.5 days · FR-23, FR-29
Expected-points decomposition by component, minutes probability, upcoming fixtures with model-derived
difficulty, trend charts, price and ownership history, set-piece role, injury status.

### E6-S4 — Comparison view · 1 day · FR-28
Two to four players side by side across stats, expected points, trend overlays and fixture runs, with
a plain-language verdict on the difference.

### E6-S5 — Trend charts · 1 day · FR-29 · **delivered**
Points, xG/xA versus actual returns, minutes, defensive contributions, price, ownership over time.

**Uncertainty must be visible on every forecast chart.** A predicted 5.2 points that could plausibly
be anything from 0 to 15 must not render as though it were a measurement.

What landed, on top of the shared `web/src/components/charts/` module E6-S3 built:

- **`/player/:id` already covered the measured series** — points, minutes, expected-versus-actual
  goals and assists, defensive contribution, price and ownership. Verified rather than assumed; no
  change was needed there.
- **`/compare` gained the overlay slot E6-S4 marked out.** `compare/overlays.ts` is pure and DOM-free
  and makes two to four players commensurable: cumulative points, minutes and defensive
  contributions on a gameweek axis, and price on a **shared, unioned observation-date axis** with
  each player's value carried forward. Cumulative rather than per gameweek because four crossing
  weekly spikes answer no question. The alignment is where this fails silently, so that is what the
  tests are for — no back-filling before a player's first observation, no zero for an unobserved
  date, doubles summed, unmeasured values dropped rather than counted as nil.
- **The uncertainty clause was vacuously satisfied and is now actually satisfied.** An audit of
  `xp_next`/`xp_horizon` across `web/src/components/` found every forecast rendered as *text* —
  `formatXpRange`, `XpCell`, the verdict — and **no chart anywhere plotted a forecast quantity**, so
  nothing could have broken the rule. Rather than leave it untested, `charts/IntervalChart.tsx` now
  charts the compared players' `xp_next` and `xp_horizon` with the **±2σ band as the mark and the
  mean as a tick inside it**. Overlapping bands make the verdict's "too close to call" visible
  instead of merely stated. `geometry.uncertaintyBand` returns **null** for an unpublished standard
  deviation rather than a zero-width band, because a zero-width band renders as a bare tick and a
  bare tick is visually a measurement — the exact failure this clause names.
- **No forward xP-over-gameweeks chart, deliberately.** The contract publishes `xp_next` for one
  gameweek and `xp_horizon` as an aggregate, with no per-gameweek forecast path between them.
  Spreading the horizon across its gameweeks to draw a line would invent a derivation the pipeline
  never made (DP-09). When a per-gameweek forecast series is published, `compare/CompareTrends.tsx`
  is where it goes.
- **Four series variants, not three** — `/compare` allows four players and each needs a line. The
  fourth borrows `--warn-border`; the role mismatch is noted at the code site and is the same trade
  the first three already make.
- Verified in real Chromium at 390/820/1440px against the current preseason publication
  (`gameweeks_played: 0`): zero horizontal overflow, no console errors, no external request
  (Invariant 8). Preseason renders as the normal state it is — the performance charts say no
  gameweek has been scored, and the price overlay still draws, because prices are observed before
  the season starts (DL-20, DP-15).

### E6-S6 — Dashboard · 1 day · FR-26
Current squad and its expected points, the recommended action with marginal gain, deadline countdown
in **both UK and local time**, price-change alerts, availability alerts, and the roll option always
visible alongside.

### E6-S7 — Squad builder and transfer planner · 1.5 days · FR-31 · *the only story needing E4* · **delivered**
Optimised squad with formation view, manual editing with live legality checking, lock and ban, and
client-side re-optimisation around locks (T2). Multi-gameweek plan and chip calendar.

What landed, in `web/src/components/squad/`:

- **`legality.ts` is a deliberate mirror of `pipeline/src/fpl_dof/rules/legality.py`** — the same
  violation codes, the same `detail` keys, every violation returned rather than the first, and the
  budget compared in tenths. Every threshold is read from `rules.squad`; the file names no rule
  value. Its test suite changes the *rules* and requires the answers to change with them, which is
  the check a hardcoded club limit would fail.
- **The cross-language conformance test is built, and it found a real disagreement**
  ([DL-39](../00-decision-log.md#dl-39--behaviour-implemented-twice-is-pinned-by-one-corpus-in-contractsconformance-read-by-both-toolchains)).
  `contracts/conformance/legality-corpus.json` holds twenty-six cases — a ruleset, a squad, and the
  exact ordered list of `(code, detail)` pairs both validators must return — read by
  `pipeline/tests/test_legality_conformance.py` and `legality.conformance.test.ts`. **One file, two
  readers**, outside both `pipeline/` and `web/`, because a corpus copied into two test directories
  drifts with the implementations and catches nothing. Twenty-five cases agreed on the first run;
  the twenty-sixth did not, and the TypeScript side changed to match the Python authority. Both
  suites also assert that every violation code the validator can emit appears in the corpus, so a
  thirteenth code fails on both sides until it is covered.
- **Legality is derived, never remembered.** `draft.ts` holds fifteen ids and whichever are
  starting; the members, price, formation, captaincy, bench order and violations are recomputed every
  render, so the panel cannot drift from the squad. Controls never refuse a click — a reader passing
  through an illegal shape reads what is wrong rather than wondering why nothing happened.
- **Re-optimisation is a heuristic and says so on the page.** A greedy build on points per pound with
  a cheapest-remaining reservation, a bounded club-slot repair for the dead end greedy filling
  reaches, then a one-for-one hill climb within each position. It maximises squad-total `xp_horizon`,
  makes no two-player moves and ignores transfer cost entirely; the panel states all three next to
  the button. The result is put through `validateSquad` before it is returned, so an illegal squad is
  reported as infeasible rather than handed back.
- **Prices are current prices, and the page says so.** `sellingPrice` mirrors the Python arithmetic
  and is tested, but is unused: the contract carries no per-player purchase price. The builder spends
  against `week.squad_state.budget`, which nets the fee off in aggregate, so budget legality is real
  while any single sale is approximate to within the fee on that player's rise.
- **Locks and bans persist in `localStorage`**, following the scout-preset pattern — defensively
  parsed, capped, and degrading to "no marks" on every storage failure. A player is never both.
- **`PlanTimeline.tsx` is not a second `PlanPanel`.** That panel makes the argument; this shows the
  mechanics — named transfers per gameweek, the alternatives the solver also ranked with the roll
  among them, and a chip clock whose expiry gameweek comes from the published calendar and is tested
  by changing it.

**Live legality checking reads `rules.json` from the web contract**
([DL-14](../00-decision-log.md#dl-14--the-web-data-contract-carries-the-rules-configuration)). The
TypeScript validator is parameterised from the same configuration the Python rules module uses, and a
cross-language conformance test fails the build if the two ever disagree. Hand-writing the squad
rules in TypeScript is not an option available here: a hardcoded `3` for the club limit in a `.tsx`
file is the same bug as a hardcoded `4` for a forward goal in a `.py` file, and Invariant 2 does not
stop at the language boundary.

### E6-S8 — Fixture ticker · 0.5 day · FR-30 · **delivered**
Team-by-gameweek difficulty grid using model expectations rather than FPL's static ratings, sortable
by run quality, with doubles and blanks marked.

What landed, reading `fixtures.json` (DL-37) lazily on the route rather than through the shell's
eager load:

- **`web/src/components/fixtures/`**. `ticker.ts` is pure and DOM-free — banding, per-club run
  summaries and the sort orders — with the view and its stylesheet alongside it, the same shape
  `scout/` and `dashboard/` use.
- **The scale is explained on the page, not assumed.** These are continuous model-derived scores,
  not the integer 1–5 FDR a reader arrives expecting, so the grid ships with a legend giving each
  band's numeric range, the scale's own published description, and the model, its league mean and
  its home advantage. Every chip carries its score and its band name as text, so colour is never
  the only carrier. When `model.teams_rated` is 0 the panel says the grid is unrated rather than
  presenting neutral scores as ratings.
- **Bands are derived from the published scale**, measured outwards from `neutral` — never from a
  literal 3. The two band edges are the only new tunables and they are presentation-only: they
  decide how much of the grid shades strongly and nothing downstream reads them.
- **A blank cannot hide behind a good mean.** A blank contributes nothing to a run's mean, exactly
  as the published `mean_difficulty` does, so every row shows its fixture, double and blank counts
  next to the mean and a blank cell is labelled rather than left empty. Trimming the window to the
  next three recomputes the means rather than reusing the full-window figure.
- **Attack and defence are selectable**, because a high-scoring game is a good fixture for forwards
  and a bad one for defenders and one number cannot say both.

### E6-S9 — PWA, accessibility and performance · 1 day · FR-34, NFR-04, NFR-14 · **delivered**
Installable, offline access to last-published data. Keyboard navigation, contrast, charts legible
without relying on colour alone. Performance budgets verified: p95 first contentful paint under 2.5s
on mobile 4G, initial payload at or under 3MB.

What landed, and what it found ([DL-38](../00-decision-log.md#dl-38--q-06-confirmed-by-measurement-and-the-app-caches-its-shell-and-its-data-under-opposite-rules)):

- **Installable and genuinely offline.** `vite-plugin-pwa` generates the manifest and worker; icons
  are generated by `web/scripts/make-icons.mjs` from `tokens.css` rather than committed as opaque
  binaries. **The shell is precached and the published data is network-first, never the reverse** —
  precaching a stable URL like `data/v1/players.json` would pin one publication for the life of the
  bundle. Offline is verified by switching the network off in Chromium and requiring the app to open
  and render eleven starters, not merely to load.
- **A first visit would not have worked, and the measurement is what caught it.** A worker does not
  control the page that registered it until after that page's fetches, so nothing reached the runtime
  cache on a cold visit. `web/src/data/offline.ts` warms it from the page — the seam
  `published.ts` was written to expect.
- **Two real contrast failures, both invisible to inspection.** `--border` bounded the scout search
  box and the builder's inputs at 1.43:1 against a 3:1 obligation; `--fdr-blank-fg` missed AA by
  0.09. Fixed by adding `--border-strong` and darkening the blank cell. The audit is now
  `web/src/theme/contrast.ts` plus tests — both palettes, every rendered pairing, and the checker
  tested by being made to fail (DP-13). It also found that nothing had ever required the two copies
  of the dark palette to agree.
- **Keyboard operability is checked by pressing keys**, not by inspecting ARIA: every control tabbed
  to, focus rings confirmed present on each, and filters, sort headers, the theme toggle and the
  builder all operated with Enter. No `outline: none` anywhere, and no positive `tabindex`.
- **Charts were already legible without colour and this verified rather than assumed it** — series
  carry dash pattern and marker shape as well as hue, every chart has an accessible name and a
  written summary, and every fixture cell prints its score with the band ranges in an on-page legend.
- **Budgets cleared with room**: p95 FCP **1044 ms** against 2500 ms, initial payload **155 KiB**
  against 3 MB. Nothing needed code-splitting; adding it would have been optimisation against a
  budget already met twentyfold.

### E6-S10 — Mini-league view · 0.5 day · FR-32 · could-have · **delivered**
Standings, squad overlap, differentials held by each side, captain divergence.

What landed, at `/league`, decided in
[DL-40](../00-decision-log.md#dl-40--the-mini-league-is-an-optional-artefact-that-is-absent-by-default-and-its-comparison-is-anchored-on-the-squad-actually-fielded):

- **The feature had ingestion support and no data.** `fetch_league_standings` has existed since E0,
  declared and drift-tested against the live API, wired to a `request.league_id` that **nothing ever
  set** — no configuration field existed, so the resource had never been fetched in a real run.
  `entry.league_id` is that field, optional and unset, with `FPL_DOF_LEAGUE_ID` as the override
  [INPUTS-REQUIRED §8](INPUTS-REQUIRED.md#8-environment-variables) had already promised and nobody
  had wired. **Unset is the tested state**, because it is the state the repository is in.
- **Absent, not empty.** With no league configured, no `league.json` is written at all — not an
  empty one, and not a `skipped`-flagged one as `week.json` and `plan.json` use. Those two model a
  *run* that was skipped; this is a configuration field nobody filled in, which does not change week
  to week, and a file whose only content is "you have not configured me" is a weaker statement than
  no file. `/league` renders a first-class page naming the setting, where to find the ID, and the
  four things configuring it would show.
- **A 200 is not proof a file exists, and this is the artefact that proves it.** An SPA host answers
  a missing path with `index.html` and a 200 — `vite dev` and `vite preview` both do — so the absent
  path parsed HTML as JSON and reported a *broken page* for a perfectly working one. Since this
  artefact is absent by default, that was the response local development would hit every time.
  `fetchLazy` now reads the content type, which fixes the same latent bug for `history.json` and
  `fixtures.json`. Found by serving a real build, not by a test — and now covered by both.
- **The comparison is anchored on the squad actually fielded, never on `squad.json`.** The
  recommended squad was the cheap anchor and is usually not what the owner owns; measuring against
  it would report players the owner does not hold as their differentials — plausible-looking and
  wrong (DP-13). With no owner row, or no squad on it, the comparison is **refused rather than
  approximated**, and the page prints which of the three reasons applies.
- **Two differential directions, never summed.** Players only the rival holds are exposure; players
  only the owner holds are a bet. One count cannot say both. Overlap is expandable to the names.
- **Unmeasured never renders as measured.** A rival outside the fetch budget shows "squad not
  published", not a zero overlap; an unpublished captain shows "not published" and a divergence of
  `null` rather than `false`. Those two are the assertions most worth having, and both are tested.
- **The cost is a named budget**: `entry.league_rival_limit` (default 20) squads, one request each,
  over one page of standings rather than a crawl of a league that can hold hundreds of thousands.
  Rivals' picks land in a new `league_pick` silver table rather than in `entry_pick`, so no
  downstream consumer's correctness depends on remembering an `entry_id` filter.
- Verified against a real `fpl-dof run` with no league configured — the run succeeds, publishes no
  `league.json`, and reports `league_entries: 0` — and in real Chromium at 390/820/1440 px: the
  unconfigured page renders, no horizontal overflow, no console errors, no external request
  (Invariant 8).
- **Scoped out deliberately:** no historical league data and no rank projection. Only the latest
  scored gameweek's squads are read; a season of every rival's picks is 20 × 38 requests for a view
  nobody asked for. Nothing here reaches a model or the optimiser — rival ownership as a *feature*
  is a modelling decision belonging with the risk dial, and would need its own evidence (DP-08).

## 3. Definition of done

- [x] All must-have views working on laptop and phone — verified at 390/820/1440 px and on an
      emulated Pixel 5 (`web/verify/browser-check.mjs`)
- [x] Scout table handles the full player set within the interaction budget — 587 players, 31 ms
      search and 77 ms sort against 150 ms, on throttled emulated phone hardware
- [x] Q-06 **confirmed by measurement** on an emulated phone over throttled mobile 4G with a 4× CPU
      throttle ([DL-38](../00-decision-log.md#dl-38--q-06-confirmed-by-measurement-and-the-app-caches-its-shell-and-its-data-under-opposite-rules)).
      **No physical handset was used** — none was available, and NFR-04 states its budget against
      *simulated* mobile 4G, so this is the sanctioned instrument. The margin is wide enough
      (5% of the payload budget, a fifth of the interaction budget) that a handset would have to
      disagree by an order of magnitude to change the answer. Worth one confirming run on a real
      phone when one is to hand; not worth blocking the epic on
- [x] Client legality checking generated from `rules.json`; cross-language conformance test green —
      26 cases in `contracts/conformance/legality-corpus.json`, one file read by both pytest and
      vitest, covering all 12 violation codes and asserting the exact ordered `(code, detail)` list
      each squad produces. Two rulesets, the second deliberately not FPL's, so a hardcoded `15` or
      `3` fails. It caught one genuine disagreement on its first run — a duplicated `bench_order`
      entry — fixed on the TypeScript side per Invariant 9
      ([DL-39](../00-decision-log.md#dl-39--behaviour-implemented-twice-is-pinned-by-one-corpus-in-contractsconformance-read-by-both-toolchains))
- [x] Every forecast displays its uncertainty — E6-S5, and asserted in the browser sweep on the
      pitch and on every scout row
- [x] Where effective ownership is displayed, the UI names how it was obtained (OD-06) — audited
      every render site of `selected_by_percent` (`scout/columns.tsx`, `player/PlayerDetail.tsx`,
      `player/TrendCharts.tsx`, `PlanPanel.tsx`'s ownership bet, `compare/verdict.ts` and
      `compare/rows.tsx`; the squad builder shows no ownership figure at all). Every one is labelled
      "selected by", never "effective ownership", and states its source next to the number (a column
      tooltip, a chart summary or an adjacent sentence), all citing DL-24. The wording is asserted by
      tests, not just present in source — `PlayerDetail.test.tsx`, `PlanPanel.test.tsx` and
      `verdict.test.ts` each fail if "effective ownership" appears or "selected by" does not. No gap
      found; no code change was needed
- [x] Every interaction assigned a tier (T1/T2/T3); nothing on the deadline path is T3 — audited
      against the tier definitions in
      [03-solution-architecture.md §4](../03-solution-architecture.md#4-the-static-hosting-constraint-and-how-interactivity-survives-it)
      and [04-conceptual-design.md §8.5](../04-conceptual-design.md#85-interaction-tiers); table
      recorded in §5 below. Every interaction on the dashboard's deadline path (viewing the
      recommendation, the roll comparison, the plan and its caveats) is T1; the squad builder's
      re-optimise-around-locks, which a reader might also reach for near a deadline, is T2 exactly as
      designed. Nothing reachable before a deadline is T3
- [x] Performance and accessibility budgets met and measured — p95 FCP 1044 ms against 2500 ms,
      initial payload 155 KiB against 3 MB, WCAG AA on every rendered token pairing in both themes,
      keyboard operability driven from the keyboard
- [x] Installable as a PWA with offline access to last-published data — verified by loading the app
      with the network switched off and requiring it to render the published squad
- [x] Deadline shown in both timezones throughout

## 5. Interaction tier audit

Tiers are defined in
[03-solution-architecture.md §4](../03-solution-architecture.md#4-the-static-hosting-constraint-and-how-interactivity-survives-it):
**T1 — precomputed** (pipeline writes a file, the app reads it, instant), **T2 — client-side compute**
(runs in the browser — filtering, aggregation, a small solver or heuristic, tens of ms to a few
seconds) and **T3 — job-triggered** (a CI `workflow_dispatch` run, minutes, results land as a new
artefact later). The binding rule: anything wanted *at the deadline, under time pressure* must be T1
or T2; T3 is for exploration and is never on the critical path.

The **deadline path** is the dashboard's core flow: viewing the recommended action and its marginal
gain, understanding the roll comparison, reading the plan's caveats and ownership bet, and acting
before the gameweek deadline.

| View | Interaction | Tier | Notes |
| --- | --- | --- | --- |
| Dashboard | View squad, xP, recommended action, marginal gain | T1 | Reads `week.json` / `squad.json` as published |
| Dashboard | Roll comparison, plan caveats, ownership bet | T1 | Reads `plan.json` as published |
| Dashboard | Deadline countdown (both timezones), price/availability alerts | T1 | Rendered from a published timestamp; no compute |
| Scout | Search / filter / sort ~700 players | T2 | Plain client-side JS, not DuckDB (Q-06) — 31 ms search, 77 ms sort measured, well inside T2's range |
| Scout | Saved filter presets, column visibility | T1 | `localStorage` read/write only, no compute |
| Scout | Multi-select into comparison | T1 | Builds a URL; no compute |
| Player detail | Navigate to a player, view decomposition, trend charts, fixture run | T1 | Reads `players.json` / lazily-loaded `history.json` / `fixtures.json` as published |
| Compare | Select 2–4 players | T1 | URL state, no compute |
| Compare | Verdict (plain-language difference) | T2 | Assembled client-side from published figures by a fixed rule set (`compare/verdict.ts`); not precomputed by the pipeline, but sub-millisecond in practice |
| Compare | Trend overlays, uncertainty band chart | T1 | Plotted directly from published series |
| Squad builder | View optimised squad, formation | T1 | Reads `squad.json` / `week.json` as published |
| Squad builder | Manual edit, live legality/budget check | T2 | `legality.ts` recomputes on every render, parameterised from `rules.json` (DL-14) |
| Squad builder | Lock / ban a player | T1 | `localStorage` marks only; no compute |
| Squad builder | Re-optimise around locks | T2 | Explicitly designed as T2 (E6-S7) — greedy heuristic + hill climb, entirely in-browser, no network round trip |
| Transfer planner | View multi-gameweek plan, chip calendar, alternatives | T1 | Reads `plan.json` as published |
| Fixtures | View difficulty grid, legend | T1 | Reads `fixtures.json` as published |
| Fixtures | Sort by run quality, trim window (next-N recompute) | T2 | Client-side sort and mean recomputation over ~20 teams; negligible latency but the mechanism is client compute, not a precomputed file |
| Fixtures | Toggle attack / defence | T1 | Re-renders already-loaded data; no compute |
| *(not built)* | Full multi-gameweek re-optimisation under bespoke constraints, wildcard drafting | T3 | Named in architecture §4 as the T3 case; no E6 story implements a UI for it, so nothing on any shipped path reaches it |

**Finding:** nothing on the deadline path is T2 or T3 — the dashboard's entire core flow is T1,
reading published artefacts with no client compute at all. The only T2 interaction a reader might
plausibly reach for *near* a deadline (last-minute squad builder edits and re-optimise-around-locks)
is T2 by design, matching architecture §4's own classification of that exact feature, and runs
entirely in-browser with no network round trip — so even that path never touches T3. No genuine T3
leakage onto a time-pressured path was found.

## 6. Success test

**Do you reach for this instead of the official FPL site?** If not, it has not delivered OBJ-5,
regardless of feature completeness.
