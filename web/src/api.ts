import type { Meta, Plan, Players, Rules, Squad, Week } from "./contract/types";

/** Base for published data files. Never points outside this origin (Invariant 8). */
const DATA_BASE = `${import.meta.env.BASE_URL}data/v1`;

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
