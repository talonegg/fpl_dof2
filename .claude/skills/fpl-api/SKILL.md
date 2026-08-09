---
name: fpl-api
description: Reference for the official Fantasy Premier League API — endpoint catalogue, response shapes, field meanings, rate-limiting expectations, and known quirks including the pre-deadline squad visibility gap. Load when writing or debugging FPL ingestion code, or when deciding which endpoint provides a given field.
user-invocable: true
---

# FPL API — reference

**The FPL API is undocumented and unversioned by FPL itself** (CON-5). Everything below is
community reverse-engineered knowledge, stable for many years but never officially guaranteed. **The
adapter's recorded contract tests, not this file, are the actual defence against this API changing
shape** (Design §10, Testing — Contract row). Update this file whenever a contract test fails due to
a genuine upstream change, not just when convenient.

Base URL: `https://fantasy.premierleague.com/api/`. All endpoints below are relative to it. All are
public JSON, no authentication required, unless noted.

## Endpoint catalogue

| Endpoint | Provides | Natural cadence |
| --- | --- | --- |
| `bootstrap-static/` | Every player (price, ownership, form, status, chance-of-playing, season totals), every team (with strength ratings), positions (`element_types`), gameweek/event list, game settings (`game_settings` — includes some scoring parameters) | Every 4h; hourly near a deadline |
| `fixtures/` | Full fixture list: kickoff times, FPL's own difficulty rating, scores once played | Every 4h |
| `fixtures/?event={gw}` | Fixtures for one gameweek only | On demand |
| `element-summary/{player_id}/` | One player's full gameweek-by-gameweek history for the current season, prior-season history, and upcoming fixtures | Daily; on demand for player detail views |
| `event/{gw}/live/` | Per-player stats and points for a specific gameweek, including the BPS breakdown | Hourly during and shortly after a gameweek |
| `entry/{team_id}/` | One manager's team summary — overall points, rank, value, bank | Post-deadline / post-gameweek |
| `entry/{team_id}/history/` | That manager's gameweek-by-gameweek history, past seasons, chip usage | Same |
| `entry/{team_id}/event/{gw}/picks/` | That manager's 15-man picks, captain, chip played, for one gameweek | **See the visibility gap below — this is the important quirk** |
| `entry/{team_id}/transfers/` | That manager's full transfer history | Post-deadline / post-gameweek |
| `leagues-classic/{league_id}/standings/` | Mini-league standings, paginated | Weekly |
| `set-piece-notes/` | Penalty, free-kick and corner taker notes per club, as maintained by FPL's own team | Weekly |
| `dream-team/{gw}/` | FPL's own "team of the week" | Informational only, low priority |

## The critical quirk: pre-deadline squad visibility (CON-10)

**`entry/{team_id}/event/{gw}/picks/` for the *current, not-yet-played* gameweek only becomes public
after that gameweek's deadline has passed.** Before the deadline, this endpoint either 404s or
returns the previous gameweek's picks, depending on timing — do not assume it reflects transfers made
since the last deadline.

**Consequence for the squad-state service (Design §4.2):** the "current" squad before a deadline must
be *reconstructed*, not fetched directly:

1. Start from `entry/{team_id}/event/{last_finished_gw}/picks/` — the last confirmed public state.
2. Overlay `entry/{team_id}/transfers/`, filtering to transfers made since that gameweek.
3. Derive bank and squad value from the price history and the transfer overlay.
4. Recompute free transfers available from transfer history, not by assuming a count — it is easy to
   get wrong (see FR-25, Design §4.2).
5. Fall back to a manual override when reconstruction confidence is low.

This is a known, permanent gap in the API, not a bug to work around cleverly. Treat any code that
assumes `picks/` is live pre-deadline as incorrect.

## Field notes

- **`chance_of_playing_next_round`** (in `bootstrap-static`) is FPL's own percentage estimate of a
  player's chance of playing the next gameweek. It is manually curated by FPL's team and can lag real
  news, especially close to kickoff — treat it as one signal for the availability model (M1), not
  ground truth.
- **`status`** is a single-letter code (`a` available, `d` doubtful, `i` injured, `s` suspended,
  `u` unavailable, `n` not in squad or similar) — check `bootstrap-static`'s own `element_types` and
  status legend at ingestion time rather than assuming the code set is fixed, since it has changed
  historically.
- **Prices** in the raw API are tenths of a million (e.g. `105` means £10.5m). Convert consistently
  at the ingestion boundary, not scattered through downstream code.
- **`now_cost`** vs **`cost_change_start`/`cost_change_event`** — the latter give the price delta,
  useful for the price-history table (Design §3.1) without having to diff snapshots yourself.
- **Ownership** (`selected_by_percent`) is a same-day aggregate across the whole player base and does
  not distinguish captaincy — combine with the separate captaincy data where needed for effective
  ownership (Design §7).
- **`game_settings`** inside `bootstrap-static` exposes some rule parameters directly (e.g. squad
  size limits). Prefer reading these over hardcoding where the field exists — see `fpl-rules` for
  what is and is not exposed this way.

## Politeness and access (NFR-10)

- Honest, identifiable user agent on every request.
- Conservative rate limiting — this is a shared public service with no published rate-limit contract,
  so the burden is on the client to be conservative, not on FPL to tell you when you've gone too far.
- Cache aggressively; a snapshot to bronze happens on every fetch regardless (Design §2.2).
- No authenticated endpoints are in scope for this project (DL-08) — `my-team/` and login-gated
  endpoints are deliberately excluded.

## Sources

Community-maintained references, not official FPL documentation (none exists):

- Widely-used community API references (e.g. the various `fpl-api-docs` community write-ups) —
  cross-check against actual responses at implementation time, since these drift.
- The adapter's own recorded contract tests are the authoritative, currently-verified source once
  Phase 1 ingestion exists — trust those over any external write-up, including this file.
