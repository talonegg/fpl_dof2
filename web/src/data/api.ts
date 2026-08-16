import type {
  Fixtures,
  Health,
  History,
  League,
  Meta,
  Plan,
  Players,
  Rules,
  Squad,
  Week,
} from "../contract/types";

/** Base for published data files. Never points outside this origin (Invariant 8). */
export const DATA_BASE = `${import.meta.env.BASE_URL}data/v1`;

async function fetchJson<T>(name: string): Promise<T> {
  const res = await fetch(`${DATA_BASE}/${name}.json`);
  if (!res.ok) {
    throw new Error(`Failed to load ${name}.json: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export function fetchMeta(): Promise<Meta> {
  return fetchJson<Meta>("meta");
}

export function fetchRules(): Promise<Rules> {
  return fetchJson<Rules>("rules");
}

export function fetchPlayers(): Promise<Players> {
  return fetchJson<Players>("players");
}

export function fetchSquad(): Promise<Squad> {
  return fetchJson<Squad>("squad");
}

/**
 * This week's decision, when there is one.
 *
 * Returns null on 404 rather than throwing. Before the first gameweek is scored there is no squad
 * to advise on (DL-20), so its absence is a normal state — and a missing weekly panel must not take
 * the whole page down with it (DP-15).
 */
export async function fetchWeek(): Promise<Week | null> {
  const res = await fetch(`${DATA_BASE}/week.json`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to load week.json: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as Week;
}

/**
 * The multi-gameweek plan and the chip calendar, when there is one.
 *
 * Returns null on 404 for the same reason `fetchWeek` does: before the first gameweek is scored
 * there is no squad to plan around (DL-20), and a missing plan panel must not take the page down
 * with it (DP-15).
 */
export async function fetchPlan(): Promise<Plan | null> {
  const res = await fetch(`${DATA_BASE}/plan.json`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to load plan.json: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as Plan;
}

// --- the trend artefacts (DL-37) ---------------------------------------------------------------
//
// Deliberately NOT part of `loadPublishedData`'s eager `Promise.all`. DL-35 loads the six original
// artefacts as one unit because they are small and wanted by more than one view; `history.json` is
// neither — fully populated it is larger than the other six combined, and only the trend-bearing
// views (`/player/:id`, and the charts of E6-S5) ever read it. Putting it in the shell's eager load
// would spend the NFR-04 3 MB initial-payload budget on data the dashboard never opens.
//
// Each has its own module-scope promise cache, for the same reason `loadPublishedData` holds a
// promise rather than a result: a route mounted, unmounted and mounted again is a render, not a
// network event, and two components asking at once share one request.

let historyCache: Promise<History | null> | null = null;
let fixturesCache: Promise<Fixtures | null> | null = null;
let leagueCache: Promise<League | null> | null = null;
let healthCache: Promise<Health | null> | null = null;

async function fetchLazy<T>(name: string): Promise<T | null> {
  const res = await fetch(`${DATA_BASE}/${name}.json`);
  // Null on 404, as `fetchWeek` and `fetchPlan` do. These artefacts arrived after the first six, so
  // a bundle deployed against an older published data directory would 404 on them — and a missing
  // trend chart must degrade to "no data" rather than take the player page down with it (DP-15).
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to load ${name}.json: ${res.status} ${res.statusText}`);
  }
  // **A 200 is not proof the file exists.** A single-page host answers a missing path with
  // `index.html` and a 200 rather than a 404 — `vite dev` and `vite preview` both do, and so does
  // any static host configured with an SPA fallback. Parsing that as JSON throws, and the route
  // would report a broken page for what is actually an absent artefact.
  //
  // This is not hypothetical and not only a dev-server quirk: `league.json` is absent whenever no
  // mini-league is configured, which is the default, so the fallback is what local development
  // hits every time. Content type is the honest discriminator — the server said HTML, so there is
  // no artefact here (DP-15).
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType && !contentType.includes("json")) return null;
  return (await res.json()) as T;
}

/**
 * Per-player trend series for the current season — E6-S3's price and ownership history, and the
 * data behind E6-S5's charts.
 *
 * **Empty is a normal answer.** Before the first gameweek is scored, every player's `gameweeks`
 * array is empty and `gameweeks_played` is 0 (DL-20, DL-37); the `prices` series is populated from
 * the first day the pipeline observed a price, so it has rows in preseason when `gameweeks` does
 * not. Check `gameweeks_played` rather than inferring emptiness from an array length.
 *
 * Returns null only when the artefact is absent from the published data entirely.
 */
export function fetchHistory(): Promise<History | null> {
  historyCache ??= fetchLazy<History>("history").catch((error: unknown) => {
    historyCache = null; // A failed load must not be cached, or a retry replays the failure.
    throw error;
  });
  return historyCache;
}

/**
 * The team-by-gameweek fixture difficulty grid — E6-S8's ticker, and the fixture run on E6-S3.
 *
 * Difficulty is model-derived, not FPL's static FDR: read `scale` for what the numbers mean and
 * `model.teams_rated` for whether the model has any ratings at all. **When `teams_rated` is 0 the
 * model has not seen a match this season** and every fixture scores close to neutral, separated
 * only by home advantage — say so rather than presenting it as a rated grid (DP-09).
 */
export function fetchFixtures(): Promise<Fixtures | null> {
  fixturesCache ??= fetchLazy<Fixtures>("fixtures").catch((error: unknown) => {
    fixturesCache = null;
    throw error;
  });
  return fixturesCache;
}

/**
 * The configured mini-league's table and the squads in it — E6-S10's comparison view.
 *
 * **Null is the ordinary answer, not a degraded one.** Unlike `history` and `fixtures`, which every
 * run publishes, this artefact exists only when a `league_id` is configured, and none is by
 * default. A 404 here therefore means "no mini-league is set up" rather than "something is
 * missing", and the view says so in those terms.
 */
export function fetchLeague(): Promise<League | null> {
  leagueCache ??= fetchLazy<League>("league").catch((error: unknown) => {
    leagueCache = null;
    throw error;
  });
  return leagueCache;
}

/**
 * How the pipeline itself is doing — E7-S6's data health page (FR-33, NFR-07, DL-41).
 *
 * Lazy for the opposite reason to the others. `history.json` is lazy because it is large; this one
 * is small, and is lazy because of *when* it is wanted: it is the page you open when something
 * looks wrong, and the shell's eager load is the path every other page waits behind.
 *
 * **A null here is itself a health signal.** Every run that publishes anything publishes this too,
 * so its absence means either a bundle deployed against older published data, or a run that could
 * not read its own manifest. The view says which of those it cannot tell apart, rather than showing
 * a blank page (DP-15).
 */
export function fetchHealth(): Promise<Health | null> {
  healthCache ??= fetchLazy<Health>("health").catch((error: unknown) => {
    healthCache = null;
    throw error;
  });
  return healthCache;
}

/** Drop the lazy caches so the next call hits the network. Used by the retry path, and by tests. */
export function resetTrendCaches(): void {
  historyCache = null;
  fixturesCache = null;
  leagueCache = null;
  healthCache = null;
}
