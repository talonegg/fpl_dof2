# E6 — Web Application

**Objective:** OBJ-5 · **Target:** ~GW14 · **Estimate:** 7–10 days
**Depends on:** E3 (forecasts worth exploring), E4 (plans worth showing)

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

### E6-S1 — App shell and data layer · 1 day · FR-34
Routing, layout, theming, responsive frame, data loading with caching. Light and dark themes via
tokens. **The app reads published static artefacts only — never an external API.**

### E6-S2 — Scout view · 2 days · FR-27 · the centrepiece
Searchable, filterable, sortable table over every Premier League player: position, club, price,
minutes, ownership, form, expected points, underlying stats, fixture run. Saved filter presets.
Multi-select into comparison.

**Virtualisation is mandatory** — ~700 players with many columns cannot render naively within the
NFR-04 budget. Assess DuckDB-WASM over published Parquet for client-side querying (T2 interactivity)
versus pre-aggregated JSON; this is open question Q-06 and should be settled by measurement on a
phone, not by preference.

### E6-S3 — Player detail · 1.5 days · FR-23, FR-29
Expected-points decomposition by component, minutes probability, upcoming fixtures with model-derived
difficulty, trend charts, price and ownership history, set-piece role, injury status.

### E6-S4 — Comparison view · 1 day · FR-28
Two to four players side by side across stats, expected points, trend overlays and fixture runs, with
a plain-language verdict on the difference.

### E6-S5 — Trend charts · 1 day · FR-29
Points, xG/xA versus actual returns, minutes, defensive contributions, price, ownership over time.

**Uncertainty must be visible on every forecast chart.** A predicted 5.2 points that could plausibly
be anything from 0 to 15 must not render as though it were a measurement.

### E6-S6 — Dashboard · 1 day · FR-26
Current squad and its expected points, the recommended action with marginal gain, deadline countdown
in **both UK and local time**, price-change alerts, availability alerts, and the roll option always
visible alongside.

### E6-S7 — Squad builder and transfer planner · 1.5 days · FR-31
Optimised squad with formation view, manual editing with live legality checking, lock and ban, and
client-side re-optimisation around locks (T2). Multi-gameweek plan and chip calendar.

### E6-S8 — Fixture ticker · 0.5 day · FR-30
Team-by-gameweek difficulty grid using model expectations rather than FPL's static ratings, sortable
by run quality, with doubles and blanks marked.

### E6-S9 — PWA, accessibility and performance · 1 day · FR-34, NFR-04, NFR-14
Installable, offline access to last-published data. Keyboard navigation, contrast, charts legible
without relying on colour alone. Performance budgets verified: p95 first contentful paint under 2.5s
on mobile 4G, initial payload at or under 3MB.

### E6-S10 — Mini-league view · 0.5 day · FR-32 · could-have
Standings, squad overlap, differentials held by each side, captain divergence.

## 3. Definition of done

- [ ] All must-have views working on laptop and phone
- [ ] Scout table handles the full player set within the interaction budget
- [ ] Every forecast displays its uncertainty
- [ ] Every interaction assigned a tier (T1/T2/T3); nothing on the deadline path is T3
- [ ] Performance and accessibility budgets met and measured
- [ ] Installable as a PWA with offline access to last-published data
- [ ] Deadline shown in both timezones throughout

## 4. Success test

**Do you reach for this instead of the official FPL site?** If not, it has not delivered OBJ-5,
regardless of feature completeness.
