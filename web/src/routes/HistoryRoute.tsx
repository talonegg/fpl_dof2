import { useCallback, useEffect, useState } from "react";
import { fetchModels, fetchModelsHistory, fetchSeasonReplay } from "../data/api";
import type { Models, ModelsHistory, SeasonReplay } from "../contract/types";
import { ModelHistoryView } from "../components/history/ModelHistoryView";
import { SeasonView } from "../components/history/SeasonView";

type State = { status: "loading" } | { status: "absent" } | { status: "ready"; history: ModelsHistory };

/**
 * `/history` — the five frozen models replayed over 2025/26. The artefact is a static, checked-in
 * backtest (CI cannot run the backtest), fetched lazily here rather than in the shell's eager load.
 */
export function HistoryRoute() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    void fetchModelsHistory().then((history) => {
      if (!cancelled) setState(history ? { status: "ready", history } : { status: "absent" });
    });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // The current season is optional: replay (static) + prospective (models.json). Never blocks 2025/26.
  const [current, setCurrent] = useState<{ replay: SeasonReplay | null; models: Models | null }>({ replay: null, models: null });
  useEffect(() => {
    let cancelled = false;
    void Promise.all([fetchSeasonReplay(), fetchModels()]).then(([replay, models]) => {
      if (!cancelled) setCurrent({ replay, models });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return (
      <section data-testid="history-loading">
        <p>Loading the model history…</p>
      </section>
    );
  }
  if (state.status === "absent") {
    return (
      <section data-testid="history-absent">
        <h2>Model history unavailable</h2>
        <p>The 2025/26 backtest file could not be loaded.</p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  }
  return (
    <>
      <SeasonView replay={current.replay} models={current.models} />
      <ModelHistoryView history={state.history} />
    </>
  );
}
