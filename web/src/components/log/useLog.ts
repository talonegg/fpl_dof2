import { useCallback, useEffect, useState } from "react";
import type { Log } from "../../contract/types";
import { fetchLog, resetTrendCaches } from "../../data/api";

/**
 * `log.json`, fetched lazily on mount — the same shape `useLeague` has, for the same reason: only
 * this route reads it, so the shell's eager load must not carry it (DL-37, DL-69).
 *
 * **Absent is a normal state.** The log is written only when a team ID is configured and the game
 * has recorded picks for it, so a 404 means "nothing to log yet" and gets a page saying what would
 * populate it rather than an apology (DP-15).
 */
export type LogState =
  | { status: "loading" }
  | { status: "ready"; log: Log }
  | { status: "absent" }
  | { status: "error"; message: string };

export function useLog(): { state: LogState; retry: () => void } {
  const [state, setState] = useState<LogState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setState({ status: "loading" });
    fetchLog()
      .then((log) => {
        if (cancelled) return;
        setState(log ? { status: "ready", log } : { status: "absent" });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });

    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    resetTrendCaches();
    setAttempt((n) => n + 1);
  }, []);

  return { state, retry };
}
