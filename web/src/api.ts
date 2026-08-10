import type { Meta, Players, Rules, Squad } from "./contract/types";

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
