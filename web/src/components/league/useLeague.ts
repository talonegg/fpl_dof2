import { useCallback, useEffect, useState } from "react";
import type { League } from "../../contract/types";
import { fetchLeague, resetTrendCaches } from "../../data/api";

/**
 * The mini-league, fetched lazily on mount — the same shape `useFixtures` has, for the same reason
 * (DL-37): only this route reads `league.json`, so the shell's eager load must not carry it.
 *
 * **Absent is the normal state here, not an edge case.** Every other lazily fetched artefact is
 * written on every run and 404s only against an older published directory. This one is written
 * *only* when a league is configured, and no league is configured by default — so "absent" means
 * "you have not set this up", which is a first-class answer with something useful to say, not a
 * failure and not an empty table (DP-15).
 */
export type LeagueState =
  | { status: "loading" }
  | { status: "ready"; league: League }
  | { status: "absent" }
  | { status: "error"; message: string };

export function useLeague(): { state: LeagueState; retry: () => void } {
  const [state, setState] = useState<LeagueState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setState({ status: "loading" });
    fetchLeague()
      .then((league) => {
        if (cancelled) return;
        setState(league ? { status: "ready", league } : { status: "absent" });
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
