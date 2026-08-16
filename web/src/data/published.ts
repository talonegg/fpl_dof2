import { DATA_BASE, fetchMeta, fetchPlan, fetchPlayers, fetchRules, fetchSquad, fetchWeek } from "./api";
import { warmPublishedCache } from "./offline";
import type { Meta, Plan, Players, Rules, Squad, Week } from "../contract/types";

/**
 * Everything the published contract carries, loaded as one unit.
 *
 * All six artefacts are small and are wanted by more than one view, so they are fetched together
 * once rather than per route (DL-35). `week` and `plan` are nullable because their absence before
 * the first scored gameweek is a normal state, not a failure (DL-20, DP-15).
 */
export interface PublishedData {
  meta: Meta;
  rules: Rules;
  players: Players;
  squad: Squad;
  week: Week | null;
  plan: Plan | null;
}

/**
 * The in-memory cache. Holding the *promise* rather than the result means concurrent callers share
 * one set of requests, and navigating between routes never re-fetches — a route change is a render,
 * not a network event.
 */
let cache: Promise<PublishedData> | null = null;

/**
 * Load the published artefacts, returning the cached load if one is already in flight or complete.
 *
 * This is the single seam E6-S9 will warm from a service worker: cache the six files under
 * `data/v1/` and this function is satisfied offline with no change here.
 */
export function loadPublishedData(): Promise<PublishedData> {
  if (!cache) {
    cache = Promise.all([
      fetchMeta(),
      fetchRules(),
      fetchPlayers(),
      fetchSquad(),
      fetchWeek(),
      fetchPlan(),
    ])
      .then(([meta, rules, players, squad, week, plan]) => {
        // Fire-and-forget, deliberately after the data has resolved and never awaited: warming the
        // offline cache must not delay the first paint, and a failure to warm it must not turn a
        // successful load into an error (DP-15). See `offline.ts` for why the page does this rather
        // than leaving it to the service worker.
        void warmPublishedCache({ dataBase: DATA_BASE });
        return { meta, rules, players, squad, week, plan };
      })
      .catch((error: unknown) => {
        // A failed load must not be cached, or the retry button would replay the failure for ever.
        cache = null;
        throw error;
      });
  }
  return cache;
}

/** Drop the cache so the next load hits the network. Used by the retry path, and by tests. */
export function resetPublishedDataCache(): void {
  cache = null;
}
