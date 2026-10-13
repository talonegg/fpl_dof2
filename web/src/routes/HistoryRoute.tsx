import { useCallback, useEffect, useState } from "react";
import { fetchModelsHistory } from "../data/api";
import type { ModelsHistory } from "../contract/types";
import { ModelHistoryView } from "../components/history/ModelHistoryView";

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
  return <ModelHistoryView history={state.history} />;
}
