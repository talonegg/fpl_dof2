import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ARTEFACTS } from "../contract/types";
import type { ArtefactKey, ArtefactMap, Health, Meta, Models, Plan, Players, Rules, Squad, Week } from "../contract/types";
import { buildRegistry, normaliseAccuracy, normaliseHistory, normaliseModels } from "./registry";
import type { Registry } from "./registry";
import { DATA_DIR, WARMED_ARTEFACTS, warmPublishedCache } from "./offline";
import { checkMajor } from "./compat";
import type { WarmOptions, WarmResult } from "./offline";

export type { ArtefactKey, ArtefactMap };

/** Base for published data files. Never points outside this origin (Invariant 8). */
export const DATA_BASE = `${import.meta.env.BASE_URL}${DATA_DIR}`;

/**
 * What loading one artefact came to — the one spelling of each state (WEB-04).
 *
 * **Absent is a state, not a failure** (DP-15): `league.json` and `log.json` are absent by default,
 * and a bundle deployed against an older published directory 404s on anything newer. `malformed`
 * is a file that parses and is not this artefact, which TypeScript cannot see coming off the
 * network: handed on, it would crash the view on its first missing field.
 */
export type Loaded<T> =
  | { status: "ready"; data: T }
  | { status: "absent" }
  | { status: "malformed" }
  | { status: "error"; message: string };

export type ArtefactState<T> = { status: "loading" } | Loaded<T>;

/** Why a settled artefact is not ready, in a sentence (`absent` is the caller's), or null. */
export function unready(state: ArtefactState<unknown>, absent: string): string | null {
  if (state.status === "loading" || state.status === "ready") return null;
  if (state.status === "absent") return absent;
  return state.status === "error" ? state.message : "the published file is malformed.";
}

/**
 * Everything the published contract carries, loaded as one unit.
 */
export interface PublishedData {
  meta: Meta;
  rules: Rules;
  players: Players;
  /** As published; `useData` gives the effective squad of the chosen strategy (`withModel`). */
  squad: Squad;
  /** The champion's week and plan. */
  week: Week | null;
  plan: Plan | null;
  models: Models | null;
  publishedSquad: Squad;
  registry: Registry;
  /** Each published strategy's week and plan, by registry id, for those that publish one. */
  weeks: Record<string, Week>;
  plans: Record<string, Plan>;
}

const isObject = (body: unknown): body is Record<string, unknown> => typeof body === "object" && body !== null;
const hasArrays = (...keys: string[]) => (body: unknown) => isObject(body) && keys.every((k) => Array.isArray(body[k]));
const hasDeadline = (body: unknown) => isObject(body) && "deadline" in body;

/**
 * The minimum shape the health page renders from: the run excerpt, a source list, and the gate slot.
 *
 * A floor, not a full validation: the publisher validates against the JSON Schema before writing
 * (DP-04), so a payload that fails *this* is a different or truncated file, not schema drift.
 */
export function looksLikeHealth(value: unknown): value is Health {
  if (!isObject(value)) return false;
  const candidate = value as Partial<Health>;
  return (
    typeof candidate.generated_at === "string" &&
    isObject(candidate.run) &&
    Array.isArray(candidate.run.stages) &&
    Array.isArray(candidate.sources) &&
    // `gates: null` is the documented "no report" case, so the key must exist, not be truthy.
    "gates" in candidate
  );
}

/** Each artefact's shape floor; the rest need only be an object. */
const GUARDS: Partial<Record<ArtefactKey, (body: unknown) => boolean>> = {
  week: hasDeadline,
  plan: hasDeadline,
  strategies: hasArrays("strategies"),
  models: hasArrays("gameweeks"),
  models_history: hasArrays("summary", "gameweeks"),
  as_if_played: hasArrays("summary", "gameweeks"),
  xp_accuracy: hasArrays("seasons"),
  health: looksLikeHealth,
  live: hasArrays("fixtures", "teams"),
};

/** Artefacts keyed by strategy id, mapped onto the registry's ids as they load. */
const NORMALISE: Partial<Record<ArtefactKey, (registry: Registry, body: never) => unknown>> = {
  models: normaliseModels,
  models_history: normaliseHistory,
  as_if_played: normaliseHistory,
  xp_accuracy: normaliseAccuracy,
};

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

/**
 * One published file. A 404, or a single-page host's HTML fallback for a missing path, is absent
 * (DL-37); a body that fails its guard is malformed. Never rejects.
 */
async function load<T>(
  path: string,
  looksRight: (body: unknown) => boolean = isObject,
  revalidate = false,
): Promise<Loaded<T>> {
  try {
    // A read made after a refresh asks the origin whether the file changed (`no-cache` revalidates, and
    // answers 304 when it did not): GitHub Pages serves `max-age=600`, so a plain fetch could hand back
    // the copy the HTTP cache already held for up to ten minutes. First loads are plain fetches.
    const res = await fetch(`${DATA_BASE}/${path}`, revalidate ? { cache: "no-cache" } : undefined);
    if (res.status === 404) return { status: "absent" };
    if (!res.ok) return { status: "error", message: `Failed to load ${path}: ${res.status} ${res.statusText}` };
    const contentType = res.headers.get("content-type") ?? "";
    if (contentType && !contentType.includes("json")) return { status: "absent" };
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      return { status: "malformed" };
    }
    return looksRight(body) ? { status: "ready", data: body as T } : { status: "malformed" };
  } catch (error) {
    return { status: "error", message: message(error) };
  }
}

/** The data, or null for an artefact the app can do without. */
const optional = <T,>(loaded: Loaded<T>): T | null => (loaded.status === "ready" ? loaded.data : null);

/** The data, or a thrown error for one the app cannot render without. */
function need<T>(key: ArtefactKey, loaded: Loaded<T>): T {
  if (loaded.status === "ready") return loaded.data;
  throw new Error(loaded.status === "error" ? loaded.message : `Failed to load ${key}.json: ${loaded.status}`);
}

class DataStore {
  private cache = new Map<ArtefactKey, Promise<Loaded<unknown>>>();
  private files = new Map<string, Promise<Loaded<unknown>>>();
  private publishedPromise: Promise<PublishedData> | null = null;
  private registryPromise: Promise<Registry> | null = null;
  private generationCount = 0;
  /** True from the first `refresh` until a hard `reset`: reads made then revalidate with the origin. */
  private revalidating = false;
  private listeners = new Set<() => void>();

  /** One artefact. Only a ready one is kept; anything else is asked for again next time. */
  get<K extends ArtefactKey>(key: K): Promise<Loaded<ArtefactMap[K]>> {
    let promise = this.cache.get(key);
    if (!promise) {
      const fetched = this.fetchArtefact(key);
      promise = fetched;
      this.cache.set(key, fetched);
      void fetched.then((loaded) => {
        if (loaded.status !== "ready" && this.cache.get(key) === fetched) this.cache.delete(key);
      });
    }
    return promise as Promise<Loaded<ArtefactMap[K]>>;
  }

  /** The strategy registry; a deployment without `strategies.json` gets the champion alone. */
  registry(): Promise<Registry> {
    this.registryPromise ??= this.get("strategies").then((loaded) => buildRegistry(optional(loaded)));
    return this.registryPromise;
  }

  /**
   * One strategy's week or plan, at the path the registry publishes for it and nowhere else. A
   * strategy that publishes none, or whose file is missing or unreadable, has none (DP-15).
   */
  async strategyFile<K extends "week" | "plan">(
    kind: K,
    id: string,
  ): Promise<(K extends "week" ? Week : Plan) | null> {
    const entry = (await this.registry()).entries.find((e) => e.id === id);
    const path = entry?.artefacts[kind];
    if (!path) return null;
    const key = `${kind}:${path}`;
    let promise = this.files.get(key);
    if (!promise) {
      promise = load(path, GUARDS[kind], this.revalidating);
      this.files.set(key, promise);
    }
    return optional(await promise) as (K extends "week" ? Week : Plan) | null;
  }

  loadPublished(): Promise<PublishedData> {
    if (!this.publishedPromise) {
      // Every other published strategy's week and plan start as soon as the registry resolves, in
      // parallel with the fixed artefacts; one that fails to load simply has none.
      const others = this.registry().then(async (registry) => {
        const weeks: Record<string, Week> = {};
        const plans: Record<string, Plan> = {};
        await Promise.all(
          registry.entries
            .filter((e) => e.published && e.id !== registry.champion)
            .map(async (e) => {
              const [w, p] = await Promise.all([this.strategyFile("week", e.id), this.strategyFile("plan", e.id)]);
              if (w) weeks[e.id] = w;
              if (p) plans[e.id] = p;
            }),
        );
        return { weeks, plans };
      });
      this.publishedPromise = Promise.all([
        this.registry(),
        this.get("meta"),
        this.get("rules"),
        this.get("players"),
        this.get("squad"),
        this.get("week"),
        this.get("plan"),
        this.get("models"),
        others,
      ])
        .then(([registry, meta, rules, players, squad, week, plan, models, other]) => {
          const published = {
            meta: checkMajor(need("meta", meta)),
            rules: need("rules", rules),
            players: need("players", players),
            squad: need("squad", squad),
          };
          // A week or plan that failed to load is an error; one not published yet is none (DL-20).
          if (week.status === "error") throw new Error(week.message);
          if (plan.status === "error") throw new Error(plan.message);
          const weeks: Record<string, Week> = { ...other.weeks };
          const plans: Record<string, Plan> = { ...other.plans };
          const championWeek = optional(week);
          const championPlan = optional(plan);
          if (championWeek) weeks[registry.champion] = championWeek;
          if (championPlan) plans[registry.champion] = championPlan;
          void this.warm();
          return {
            ...published,
            week: championWeek,
            plan: championPlan,
            models: optional(models),
            publishedSquad: published.squad,
            registry,
            weeks,
            plans,
          };
        })
        .catch((error: unknown) => {
          this.publishedPromise = null;
          throw error;
        });
    }
    return this.publishedPromise;
  }

  reset(): void {
    this.revalidating = false;
    this.cache.clear();
    this.files.clear();
    this.publishedPromise = null;
    this.registryPromise = null;
  }

  resetKey(key: ArtefactKey): void {
    this.cache.delete(key);
  }

  /**
   * Drop everything loaded so the next read asks the network again, and tell the views that read
   * the store (LIVE-06). Unlike a hard `reset`, this is for an app that is already showing data:
   * the views keep what they have until the new files arrive, so a refresh updates in place and
   * never blanks the screen. The reads that follow revalidate rather than trust the HTTP cache.
   */
  refresh(): void {
    this.reset();
    this.revalidating = true;
    this.generationCount += 1;
    for (const listener of [...this.listeners]) listener();
  }

  /** How many times `refresh` has run: a view's cue to read again. */
  generation(): number {
    return this.generationCount;
  }

  /** Be told after each `refresh`; returns the unsubscribe. The shape `useSyncExternalStore` takes. */
  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Warm the offline cache with the registry's warmed artefacts and every file each strategy publishes. */
  async warm(options?: Partial<WarmOptions>): Promise<WarmResult> {
    const registry = await this.registry();
    const published = registry.entries.flatMap((e) => (e.published ? [e.artefacts.week, e.artefacts.plan] : []));
    const names = [...WARMED_ARTEFACTS, ...published.filter((p): p is string => !!p).map((p) => p.replace(/\.json$/, ""))];
    return warmPublishedCache({ dataBase: DATA_BASE, names, ...options });
  }

  private async fetchArtefact(key: ArtefactKey): Promise<Loaded<unknown>> {
    if (key === "week" || key === "plan") {
      // The champion's, at the path the registry publishes; nothing is published without one.
      const registry = await this.registry();
      const path = registry.entries.find((e) => e.id === registry.champion)?.artefacts[key];
      return path ? load(path, GUARDS[key], this.revalidating) : { status: "absent" };
    }
    const loaded = await load(ARTEFACTS[key].path, GUARDS[key], this.revalidating);
    const fix = NORMALISE[key] as ((registry: Registry, body: unknown) => unknown) | undefined;
    if (loaded.status !== "ready" || !fix) return loaded;
    try {
      return { status: "ready", data: fix(await this.registry(), loaded.data) };
    } catch {
      return { status: "malformed" };
    }
  }
}

export const dataStore = new DataStore();

export function loadPublishedData(): Promise<PublishedData> {
  return dataStore.loadPublished();
}

export function resetPublishedDataCache(): void {
  dataStore.reset();
}

/** Re-read every published file; the views that read the store update in place (LIVE-06). */
export function refreshPublishedData(): void {
  dataStore.refresh();
}

const subscribeToRefresh = (onChange: () => void) => dataStore.subscribe(onChange);
const currentGeneration = () => dataStore.generation();

/** The store's refresh count, as state: a view that loads files reads again when it changes. */
export function useRefreshGeneration(): number {
  return useSyncExternalStore(subscribeToRefresh, currentGeneration);
}

/**
 * The one loading hook (WEB-04): any artefact by its registry key, as `loading`, `ready`, `absent`,
 * `malformed` or `error`. The promise is cached in the store, so remounting costs a render and
 * not a request; `retry` asks again.
 *
 * When the store refreshes (the app became visible again, LIVE-06) the hook reads again **without
 * going back to `loading`**: the view keeps what it shows until the new file arrives, and a refresh
 * that fails keeps it too, since stale and honest beats a blank screen. A file that has since gone
 * absent, or turned malformed, replaces it.
 */
export function useArtefact<K extends ArtefactKey>(key: K): { state: ArtefactState<ArtefactMap[K]>; retry: () => void } {
  const [state, setState] = useState<ArtefactState<ArtefactMap[K]>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const generation = useRefreshGeneration();
  const shown = useRef<{ key: K; attempt: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refreshing = shown.current?.key === key && shown.current.attempt === attempt;
    shown.current = { key, attempt };
    if (!refreshing) setState({ status: "loading" });
    void dataStore.get(key).then((loaded) => {
      // A view unmounted mid-flight must not be written to.
      if (cancelled) return;
      setState((previous) => (refreshing && loaded.status === "error" && previous.status === "ready" ? previous : loaded));
    });
    return () => {
      cancelled = true;
    };
  }, [key, attempt, generation]);

  const retry = useCallback(() => {
    dataStore.resetKey(key);
    setAttempt((n) => n + 1);
  }, [key]);

  return { state, retry };
}
