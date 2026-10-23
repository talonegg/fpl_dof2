import { useCallback, useEffect, useState } from "react";
import type {
  Fixtures,
  Health,
  History,
  League,
  Log,
  Meta,
  Models,
  ModelsHistory,
  Plan,
  Players,
  Rules,
  Squad,
  Strategies,
  Week,
} from "../contract/types";
import { effectiveSquad } from "../components/squad/effective";
import type { XpAccuracy, XpAccuracySeason } from "../contract/types";
import { buildRegistry, normaliseAccuracy, normaliseHistory, normaliseModels } from "./registry";
import type { Registry } from "./registry";
import { DATA_DIR, WARMED_ARTEFACTS, warmPublishedCache } from "./offline";
import { checkMajor } from "./compat";
import type { WarmOptions, WarmResult } from "./offline";

/** Base for published data files. Never points outside this origin (Invariant 8). */
export const DATA_BASE = `${import.meta.env.BASE_URL}${DATA_DIR}`;

/** Per-GW all-player xP MAE for the 2025/26 backtest, a frozen-era record nothing rebuilds; WEB-04
 * moves it into the published data. The live season is published beside the contract as
 * `xp_accuracy.json` from the evaluations (ORC-05) and merged in by `mergeAccuracy`. */
export const XP_ACCURACY_URL = `${import.meta.env.BASE_URL}static/xp_accuracy.json`;

export interface ArtefactMap {
  meta: Meta;
  rules: Rules;
  players: Players;
  squad: Squad;
  week: Week | null;
  plan: Plan | null;
  strategies: Strategies | null;
  models: Models | null;
  history: History | null;
  fixtures: Fixtures | null;
  league: League | null;
  health: Health | null;
  log: Log | null;
  models_history: ModelsHistory | null;
  xp_accuracy: XpAccuracy | null;
}

export type ArtefactKey = keyof ArtefactMap;

/**
 * Everything the published contract carries, loaded as one unit.
 */
export interface PublishedData {
  meta: Meta;
  rules: Rules;
  players: Players;
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

export interface ArtefactState<T> {
  status: "loading" | "ready" | "error";
  data: T | null;
  value: T | null;
  error: string | null;
  retry: () => void;
}

async function fetchRequired<T>(file: string): Promise<T> {
  const res = await fetch(`${DATA_BASE}/${file}`);
  if (!res.ok) {
    throw new Error(`Failed to load ${file}: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

async function fetchNullable<T>(file: string): Promise<T | null> {
  const res = await fetch(`${DATA_BASE}/${file}`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to load ${file}: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

async function fetchLazy<T>(file: string): Promise<T | null> {
  const res = await fetch(`${DATA_BASE}/${file}`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to load ${file}: ${res.status} ${res.statusText}`);
  }
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType && !contentType.includes("json")) return null;
  return (await res.json()) as T;
}

async function fetchStaticSafe<T>(url: string, validator: (body: unknown) => body is T): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const contentType = res.headers.get("content-type") ?? "";
    if (contentType && !contentType.includes("json")) return null;
    const body: unknown = await res.json();
    return validator(body) ? body : null;
  } catch {
    return null;
  }
}

function isWeek(body: unknown): body is Week {
  return typeof body === "object" && body !== null && "deadline" in body;
}

function isPlan(body: unknown): body is Plan {
  return typeof body === "object" && body !== null && "deadline" in body;
}

function isStrategies(body: unknown): body is Strategies {
  return typeof body === "object" && body !== null && Array.isArray((body as Strategies).strategies);
}

function isModels(body: unknown): body is Models {
  return typeof body === "object" && body !== null && Array.isArray((body as Models).gameweeks);
}

function isModelsHistory(body: unknown): body is ModelsHistory {
  return (
    typeof body === "object" &&
    body !== null &&
    Array.isArray((body as ModelsHistory).summary) &&
    Array.isArray((body as ModelsHistory).gameweeks)
  );
}

/** The checked-in seasons and the live one the pipeline publishes from its evaluations (ORC-05).
 * A season the live file carries replaces a checked-in copy of the same season and kind. */
export function mergeAccuracy(checkedIn: XpAccuracy | null, live: XpAccuracy | null): XpAccuracy | null {
  if (!checkedIn || !live) return checkedIn ?? live;
  const key = (s: XpAccuracySeason) => `${s.season}|${s.kind}`;
  const fresh = new Set(live.seasons.map(key));
  return { ...checkedIn, seasons: [...checkedIn.seasons.filter((s) => !fresh.has(key(s))), ...live.seasons] };
}

function isXpAccuracy(body: unknown): body is XpAccuracy {
  return typeof body === "object" && body !== null && Array.isArray((body as XpAccuracy).seasons);
}

class DataStore {
  readonly DATA_BASE = DATA_BASE;
  readonly XP_ACCURACY_URL = XP_ACCURACY_URL;

  private cache = new Map<ArtefactKey, Promise<unknown>>();
  private files = new Map<string, Promise<unknown>>();
  private publishedPromise: Promise<PublishedData> | null = null;
  private registryPromise: Promise<Registry> | null = null;

  get<K extends ArtefactKey>(key: K): Promise<ArtefactMap[K]> {
    const existing = this.cache.get(key);
    if (existing) {
      return existing as Promise<ArtefactMap[K]>;
    }

    const promise = this.fetchArtefact(key);
    promise
      .then((val) => {
        if (val === null && this.cache.get(key) === promise) {
          this.cache.delete(key);
        }
      })
      .catch(() => {
        if (this.cache.get(key) === promise) {
          this.cache.delete(key);
        }
      });
    this.cache.set(key, promise);
    return promise as Promise<ArtefactMap[K]>;
  }

  /** The strategy registry; a deployment without `strategies.json` gets the champion alone. */
  registry(): Promise<Registry> {
    this.registryPromise ??= this.get("strategies").then(buildRegistry);
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
      promise = fetchStaticSafe(`${this.DATA_BASE}/${path}`, kind === "week" ? isWeek : isPlan);
      this.files.set(key, promise);
    }
    return (await promise) as (K extends "week" ? Week : Plan) | null;
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
        this.get("meta").then(checkMajor),
        this.get("rules"),
        this.get("players"),
        this.get("squad"),
        this.get("week"),
        this.get("plan"),
        this.get("models"),
        others,
      ])
        .then(([registry, meta, rules, players, squad, week, plan, models, other]) => {
          const weeks: Record<string, Week> = { ...other.weeks };
          const plans: Record<string, Plan> = { ...other.plans };
          if (week) weeks[registry.champion] = week;
          if (plan) plans[registry.champion] = plan;
          void this.warm();
          return {
            meta,
            rules,
            players,
            squad: effectiveSquad(squad, week, players),
            week,
            plan,
            models,
            publishedSquad: squad,
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
    this.cache.clear();
    this.files.clear();
    this.publishedPromise = null;
    this.registryPromise = null;
  }

  resetTrends(): void {
    const trends: ArtefactKey[] = [
      "history",
      "fixtures",
      "league",
      "health",
      "log",
      "models_history",
      "xp_accuracy",
    ];
    for (const key of trends) {
      this.cache.delete(key);
    }
  }

  resetKey(key: ArtefactKey): void {
    this.cache.delete(key);
  }

  /** Warm the offline cache with the fixed artefacts and every file the registry publishes. */
  async warm(options?: Partial<WarmOptions>): Promise<WarmResult> {
    const registry = await this.registry();
    const published = registry.entries.flatMap((e) => (e.published ? [e.artefacts.week, e.artefacts.plan] : []));
    const names = [...WARMED_ARTEFACTS, ...published.filter((p): p is string => !!p).map((p) => p.replace(/\.json$/, ""))];
    return warmPublishedCache({ dataBase: this.DATA_BASE, names, ...options });
  }

  private fetchArtefact(key: ArtefactKey): Promise<unknown> {
    switch (key) {
      case "meta":
      case "rules":
      case "players":
      case "squad":
        return fetchRequired(`${key}.json`);
      case "week":
      case "plan":
        // The champion's, at the path the registry publishes; nothing is published without one.
        return this.registry().then((r) => {
          const path = r.entries.find((e) => e.id === r.champion)?.artefacts[key];
          return path ? fetchNullable(path) : null;
        });
      case "strategies":
        return fetchStaticSafe(`${this.DATA_BASE}/strategies.json`, isStrategies);
      case "models":
        return this.normalised(fetchStaticSafe(`${this.DATA_BASE}/models.json`, isModels), normaliseModels);
      case "history":
      case "fixtures":
      case "league":
      case "health":
      case "log":
        return fetchLazy(`${key}.json`);
      case "models_history":
        // Published by the pipeline from the weekly backtest's record (ORC-06); absent until one ran.
        return this.normalised(fetchStaticSafe(`${this.DATA_BASE}/models_history.json`, isModelsHistory), normaliseHistory);
      case "xp_accuracy":
        return this.normalised<XpAccuracy>(
          Promise.all([
            fetchStaticSafe(this.XP_ACCURACY_URL, isXpAccuracy),
            fetchStaticSafe(`${this.DATA_BASE}/xp_accuracy.json`, isXpAccuracy),
          ]).then(([checkedIn, live]) => mergeAccuracy(checkedIn, live)),
          normaliseAccuracy,
        );
    }
  }

  private async normalised<T>(body: Promise<T | null>, fix: (registry: Registry, body: T) => T): Promise<T | null> {
    const [loaded, registry] = await Promise.all([body, this.registry()]);
    return loaded && fix(registry, loaded);
  }
}

export const dataStore = new DataStore();

export function loadPublishedData(): Promise<PublishedData> {
  return dataStore.loadPublished();
}

export function resetPublishedDataCache(): void {
  dataStore.reset();
}

export function useArtefact<K extends ArtefactKey>(key: K): ArtefactState<ArtefactMap[K]> {
  const [state, setState] = useState<ArtefactState<ArtefactMap[K]>>({
    status: "loading",
    data: null,
    value: null,
    error: null,
    retry: () => {},
  });
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    dataStore.resetKey(key);
    setAttempt((n) => n + 1);
  }, [key]);

  useEffect(() => {
    let cancelled = false;
    setState({
      status: "loading",
      data: null,
      value: null,
      error: null,
      retry,
    });

    dataStore
      .get(key)
      .then((data) => {
        if (cancelled) return;
        setState({
          status: "ready",
          data,
          value: data,
          error: null,
          retry,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          data: null,
          value: null,
          error: err instanceof Error ? err.message : String(err),
          retry,
        });
      });

    return () => {
      cancelled = true;
    };
  }, [key, attempt, retry]);

  return state;
}
