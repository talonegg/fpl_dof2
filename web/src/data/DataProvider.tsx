import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { loadPublishedData, resetPublishedDataCache } from "./published";
import type { PublishedData } from "./published";
import { MODEL_CHOICES, readModelChoice, storeModelChoice } from "./model";
import type { ModelGameweek } from "../contract/types";
import type { ModelChoice } from "./model";
import { effectiveSquad } from "../components/squad/effective";

/** Loading state, as a discriminated union so no view can read `data` before it exists. */
export type DataState =
  | { status: "loading" }
  | { status: "ready"; data: PublishedData }
  | { status: "error"; error: string };

interface DataContextValue {
  state: DataState;
  /** Clears the cache and loads again. The error view's retry button. */
  reload: () => void;
  /** The model the reader chose. The challenger is only *in effect* when it was published. */
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

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    loadPublishedData()
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            error: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

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
  return useMemo(() => withModel(state.data, model), [state.data, model]);
}

/**
 * The published data as the chosen model sees it. Choosing the challenger swaps `week` (and the
 * in-season squad derived from it) for the challenger's; everything else is model-independent.
 * With no challenger published, the champion is shown whatever was chosen.
 */
export function withModel(data: PublishedData, model: ModelChoice): PublishedData {
  if (model !== "challenger" || !data.challenger) return data;
  return {
    ...data,
    week: data.challenger,
    squad: effectiveSquad(data.publishedSquad, data.challenger, data.players),
  };
}

/** Which models have something published to show. The champion always does. */
export function availableModels(data: PublishedData): ModelChoice[] {
  // A model whose inputs failed the freshness check is never shown, even partially.
  const inModels = new Set(
    (data.models?.models ?? []).filter((m) => m.available !== false).map((m) => m.id),
  );
  const latest = latestModelGameweek(data);
  return MODEL_CHOICES.filter((m) => {
    if (m === "champion") return true;
    if (m === "challenger") return data.challenger !== null;
    return inModels.has(m) && latest?.advice[m] !== undefined;
  });
}

/**
 * Models whose latest published advice is a provisional preview: computed before the frozen
 * decision exists, and replaced by it at the decision window.
 */
export function provisionalModels(data: PublishedData): ModelChoice[] {
  const latest = latestModelGameweek(data);
  if (!latest?.provisional) return [];
  return MODEL_CHOICES.filter((m) => m !== "champion" && latest.advice[m] !== undefined);
}

/** The most recent gameweek the harness recorded advice for, or null. */
export function latestModelGameweek(data: PublishedData): ModelGameweek | null {
  const gws = data.models?.gameweeks ?? [];
  return gws.length > 0 ? gws[gws.length - 1] : null;
}

/** The model actually in effect, which models are available, and which one `week` is from. */
export function useModel(): {
  model: ModelChoice;
  effective: ModelChoice;
  /** The model the week (and squad) on screen came from: the champion unless C1 is chosen. */
  weekModel: "champion" | "challenger";
  setModel: (model: ModelChoice) => void;
  available: ModelChoice[];
  /** Available models whose advice is provisional (not yet frozen). */
  provisional: ModelChoice[];
  challengerAvailable: boolean;
} {
  const { state, model, setModel } = useDataState();
  const available = state.status === "ready" ? availableModels(state.data) : ["champion" as const];
  const effective = available.includes(model) ? model : "champion";
  return {
    model,
    effective,
    weekModel: effective === "challenger" ? "challenger" : "champion",
    setModel,
    available,
    provisional: state.status === "ready" ? provisionalModels(state.data) : [],
    challengerAvailable: available.includes("challenger"),
  };
}
