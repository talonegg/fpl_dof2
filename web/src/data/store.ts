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
  Week,
} from "../contract/types";
import { effectiveSquad } from "../components/squad/effective";
import type { SeasonReplay } from "../components/history/season";
import type { XpAccuracy } from "../contract/types";
import { warmPublishedCache } from "./offline";
import type { WarmOptions, WarmResult } from "./offline";

/** Base for published data files. Never points outside this origin (Invariant 8). */
export const DATA_BASE = `${import.meta.env.BASE_URL}data/v1`;

/** The checked-in 2025/26 model-history backtest. Static, shipped with the app. */
export const MODELS_HISTORY_URL = `${import.meta.env.BASE_URL}static/models_history_2526.json`;

/** The checked-in 2026/27 GW1–6 replay. Static, shipped with the app. */
export const SEASON_REPLAY_URL = `${import.meta.env.BASE_URL}static/models_history_2627_replay.json`;

/** Per-GW all-player xP MAE. Static app data. */
export const XP_ACCURACY_URL = `${import.meta.env.BASE_URL}static/xp_accuracy.json`;

export interface ArtefactMap {
  meta: Meta;
  rules: Rules;
  players: Players;
  squad: Squad;
  week: Week | null;
  plan: Plan | null;
  week_challenger: Week | null;
  models: Models | null;
  history: History | null;
  fixtures: Fixtures | null;
  league: League | null;
  health: Health | null;
  log: Log | null;
  models_history_2526: ModelsHistory | null;
  models_history_2627_replay: SeasonReplay | null;
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
  week: Week | null;
  plan: Plan | null;
  challenger: Week | null;
  models: Models | null;
  publishedSquad: Squad;
}

export interface ArtefactState<T> {
  status: "loading" | "ready" | "error";
  data: T | null;
  value: T | null;
  error: string | null;
  retry: () => void;
}

async function fetchRequired<T>(name: string): Promise<T> {
  const res = await fetch(`${DATA_BASE}/${name}.json`);
  if (!res.ok) {
    throw new Error(`Failed to load ${name}.json: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

async function fetchNullable<T>(name: string): Promise<T | null> {
  const res = await fetch(`${DATA_BASE}/${name}.json`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to load ${name}.json: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

async function fetchLazy<T>(name: string): Promise<T | null> {
  const res = await fetch(`${DATA_BASE}/${name}.json`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to load ${name}.json: ${res.status} ${res.statusText}`);
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

function isChallengerWeek(body: unknown): body is Week {
  return typeof body === "object" && body !== null && "deadline" in body;
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

function isSeasonReplay(body: unknown): body is SeasonReplay {
  return (
    typeof body === "object" &&
    body !== null &&
    (body as SeasonReplay).kind === "replay" &&
    Array.isArray((body as SeasonReplay).gameweeks)
  );
}

function isXpAccuracy(body: unknown): body is XpAccuracy {
  return typeof body === "object" && body !== null && Array.isArray((body as XpAccuracy).seasons);
}

class DataStore {
  readonly DATA_BASE = DATA_BASE;
  readonly MODELS_HISTORY_URL = MODELS_HISTORY_URL;
  readonly SEASON_REPLAY_URL = SEASON_REPLAY_URL;
  readonly XP_ACCURACY_URL = XP_ACCURACY_URL;

  private cache = new Map<ArtefactKey, Promise<unknown>>();
  private publishedPromise: Promise<PublishedData> | null = null;

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

  loadPublished(): Promise<PublishedData> {
    if (!this.publishedPromise) {
      this.publishedPromise = Promise.all([
        this.get("meta"),
        this.get("rules"),
        this.get("players"),
        this.get("squad"),
        this.get("week"),
        this.get("plan"),
        this.get("week_challenger"),
        this.get("models"),
      ])
        .then(([meta, rules, players, squad, week, plan, challenger, models]) => {
          void warmPublishedCache({ dataBase: this.DATA_BASE });
          return {
            meta,
            rules,
            players,
            squad: effectiveSquad(squad, week, players),
            week,
            plan,
            challenger,
            models,
            publishedSquad: squad,
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
    this.publishedPromise = null;
  }

  resetTrends(): void {
    const trends: ArtefactKey[] = [
      "history",
      "fixtures",
      "league",
      "health",
      "log",
      "models_history_2526",
      "models_history_2627_replay",
      "xp_accuracy",
    ];
    for (const key of trends) {
      this.cache.delete(key);
    }
  }

  resetKey(key: ArtefactKey): void {
    this.cache.delete(key);
  }

  warm(options?: WarmOptions): Promise<WarmResult> {
    return warmPublishedCache({ dataBase: this.DATA_BASE, ...options });
  }

  private fetchArtefact(key: ArtefactKey): Promise<unknown> {
    switch (key) {
      case "meta":
      case "rules":
      case "players":
      case "squad":
        return fetchRequired(key);
      case "week":
      case "plan":
        return fetchNullable(key);
      case "week_challenger":
        return fetchStaticSafe(`${this.DATA_BASE}/week_challenger.json`, isChallengerWeek);
      case "models":
        return fetchStaticSafe(`${this.DATA_BASE}/models.json`, isModels);
      case "history":
      case "fixtures":
      case "league":
      case "health":
      case "log":
        return fetchLazy(key);
      case "models_history_2526":
        return fetchStaticSafe(this.MODELS_HISTORY_URL, isModelsHistory);
      case "models_history_2627_replay":
        return fetchStaticSafe(this.SEASON_REPLAY_URL, isSeasonReplay);
      case "xp_accuracy":
        return fetchStaticSafe(this.XP_ACCURACY_URL, isXpAccuracy);
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
