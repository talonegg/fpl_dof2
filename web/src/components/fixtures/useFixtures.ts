import { useCallback, useEffect, useState } from "react";
import type { Fixtures } from "../../contract/types";
import { fetchFixtures, resetTrendCaches } from "../../data/api";

/**
 * The fixture grid, fetched lazily on mount.
 *
 * `fixtures.json` is deliberately outside the shell's eager load (DL-37): only this route and the
 * fixture run on the player page ever want it, and the initial payload budget is not there to be
 * spent on data the dashboard never opens. So the route owns its own loading, error and
 * not-published states rather than getting a non-nullable artefact from `useData()`.
 *
 * **Absent is a state, not a failure.** A bundle deployed against an older published data directory
 * 404s here, and the correct answer is "this is not published yet", shown plainly — not an error
 * page, and certainly not an empty grid that looks like twenty clubs with no fixtures (DP-15).
 */
export type FixturesState =
  | { status: "loading" }
  | { status: "ready"; fixtures: Fixtures }
  | { status: "absent" }
  | { status: "error"; message: string };

export function useFixtures(): { state: FixturesState; retry: () => void } {
  const [state, setState] = useState<FixturesState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setState({ status: "loading" });
    fetchFixtures()
      .then((fixtures) => {
        if (cancelled) return;
        setState(fixtures ? { status: "ready", fixtures } : { status: "absent" });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });

    // A route unmounted mid-flight must not write to a component that is gone; the promise itself
    // is cached in `api.ts`, so remounting costs a render and not a request.
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
