import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { loadPublishedData, resetPublishedDataCache } from "./published";
import type { PublishedData } from "./published";

/** Loading state, as a discriminated union so no view can read `data` before it exists. */
export type DataState =
  | { status: "loading" }
  | { status: "ready"; data: PublishedData }
  | { status: "error"; error: string };

interface DataContextValue {
  state: DataState;
  /** Clears the cache and loads again. The error view's retry button. */
  reload: () => void;
}

const DataContext = createContext<DataContextValue | null>(null);

export function DataProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DataState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

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

  const value = useMemo<DataContextValue>(() => ({ state, reload }), [state, reload]);

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
  const { state } = useDataState();
  if (state.status !== "ready") {
    throw new Error("useData was called before the published data was ready");
  }
  return state.data;
}
