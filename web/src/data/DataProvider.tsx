import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { loadPublishedData, resetPublishedDataCache } from "./published";
import type { PublishedData } from "./published";
import { useRefreshWhenVisible } from "./refresh";
import { useRefreshGeneration } from "./store";
import { ContractMajorError } from "./compat";
import { MODEL_STORAGE_KEY, readModelChoice, storeModelChoice } from "./model";
import { EMPTY_REGISTRY, resolveModel } from "./registry";
import type { Registry } from "./registry";
import type { ModelChoice } from "./model";
import { effectiveSquad } from "./effective";
import { latestGameweek } from "./season";

/** Loading state, as a discriminated union so no view can read `data` before it exists. */
export type DataState =
  | { status: "loading" }
  | { status: "ready"; data: PublishedData }
  | { status: "error"; error: string; refused?: boolean };

interface DataContextValue {
  state: DataState;
  /** Clears the cache and loads again. The error view's retry button. */
  reload: () => void;
  /** The strategy the reader asked for, as written (an id, a legacy alias, or empty). Use `useModel().effective`. */
  model: ModelChoice;
  setModel: (model: ModelChoice) => void;
}

const DataContext = createContext<DataContextValue | null>(null);

export function DataProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DataState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [model, setModelState] = useState<ModelChoice>(() => readModelChoice());
  const setModel = useCallback((next: ModelChoice) => {
    storeModelChoice(next);
    setModelState(next);
  }, []);

  // An old `?model=champion` link or saved preference means a registry id: map it once, and
  // rewrite the saved preference so the alias is not needed again.
  const registry = state.status === "ready" ? state.data.registry : null;
  useEffect(() => {
    if (!registry) return;
    const id = resolveModel(registry, model);
    if (!id || id === model) return;
    setModelState(id);
    try {
      if (window.localStorage.getItem(MODEL_STORAGE_KEY) === model) storeModelChoice(id);
    } catch {
      // Storage can be unavailable; the mapping then happens again next visit.
    }
  }, [registry, model]);

  // An app that becomes visible again re-reads the published files (LIVE-06); the store announces
  // it as a new generation, and the load below runs again in place.
  useRefreshWhenVisible();
  const generation = useRefreshGeneration();
  const loadedAttempt = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    // A refresh keeps the screen as it is until the new data arrives; a first load, and the error
    // view's retry, show the loading view.
    const refreshing = loadedAttempt.current === attempt;
    loadedAttempt.current = attempt;
    if (!refreshing) setState({ status: "loading" });
    loadPublishedData()
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const refused = error instanceof ContractMajorError;
        // A refresh that fails keeps the data on screen (stale and honest); a contract this app
        // cannot read replaces it, as it would on a first load.
        setState((previous) =>
          refreshing && previous.status === "ready" && !refused
            ? previous
            : { status: "error", error: error instanceof Error ? error.message : String(error), refused },
        );
      });
    return () => {
      cancelled = true;
    };
  }, [attempt, generation]);

  const reload = useCallback(() => {
    resetPublishedDataCache();
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo<DataContextValue>(
    () => ({ state, reload, model, setModel }),
    [state, reload, model, setModel],
  );

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

/**
 * The raw loading state. The shell uses this to render the loading and error views once, so no
 * individual view has to.
 */
export function useDataState(): DataContextValue {
  const value = useContext(DataContext);
  if (!value) throw new Error("useDataState must be used inside a DataProvider");
  return value;
}

/**
 * The published data, for a component rendered under a resolved shell.
 *
 * This is the hook route components use:
 *
 * ```tsx
 * export function ScoutRoute() {
 *   const { players, meta } = useData();
 *   return <ScoutTable players={players.players} />;
 * }
 * ```
 *
 * Routes render inside `AppLayout`, which only mounts its `Outlet` once the state is `ready`, so
 * the data is non-nullable here and no view needs its own loading branch. Throwing rather than
 * returning null keeps that guarantee honest if a future route is ever mounted outside the shell.
 */
export function useData(): PublishedData {
  const { state, model } = useDataState();
  if (state.status !== "ready") {
    throw new Error("useData was called before the published data was ready");
  }
  return useMemo(() => withModel(state.data, effectiveModel(state.data, model)), [state.data, model]);
}

/**
 * The published data as the chosen strategy sees it: its week (and the in-season squad derived
 * from it) and its plan. Everything else is strategy-independent. A strategy with no week of its
 * own shows the champion. The one place the effective squad is applied (DL-67).
 */
export function withModel(data: PublishedData, model: ModelChoice): PublishedData {
  const own = model === data.registry.champion ? undefined : data.weeks[model];
  const week = own ?? data.week;
  return {
    ...data,
    week,
    plan: own ? (data.plans[model] ?? null) : data.plan,
    squad: effectiveSquad(data.publishedSquad, week, data.players),
  };
}

/** What a requested model means in this data: its registry id if it can be shown, else the champion. */
export function effectiveModel(data: PublishedData, requested: string): ModelChoice {
  const id = resolveModel(data.registry, requested);
  return id && availableModels(data).includes(id) ? id : data.registry.champion;
}

/** Strategies with something to show: the champion always, and every other published one that
 * has a week and has not failed the input freshness check. */
export function availableModels(data: PublishedData): ModelChoice[] {
  const stale = new Set(
    (data.models?.models ?? []).filter((m) => m.available === false).map((m) => m.id),
  );
  return data.registry.entries
    .filter(
      (e) => e.id === data.registry.champion || (e.published && data.weeks[e.id] !== undefined && !data.weeks[e.id].skipped && !stale.has(e.id)),
    )
    .map((e) => e.id);
}

/**
 * Strategies whose latest published advice is a provisional preview: computed before the frozen
 * decision exists, and replaced by it at the decision window.
 */
export function provisionalModels(data: PublishedData): ModelChoice[] {
  const latest = latestGameweek(data.models);
  if (!latest?.provisional) return [];
  return Object.keys(latest.advice).filter((m) => m !== data.registry.champion);
}

/** The registry, for any view: empty outside a provider or before the data is ready. */
export function useRegistry(): Registry {
  const value = useContext(DataContext);
  return value?.state.status === "ready" ? value.state.data.registry : EMPTY_REGISTRY;
}

/** The strategy in effect, which strategies can be shown, and which have provisional advice. */
export function useModel(): {
  model: ModelChoice;
  effective: ModelChoice;
  setModel: (model: ModelChoice) => void;
  available: ModelChoice[];
  /** Available strategies whose advice is provisional (not yet frozen). */
  provisional: ModelChoice[];
} {
  const { state, model, setModel } = useDataState();
  if (state.status !== "ready") return { model, effective: model, setModel, available: [], provisional: [] };
  return {
    model,
    effective: effectiveModel(state.data, model),
    setModel,
    available: availableModels(state.data),
    provisional: provisionalModels(state.data),
  };
}
