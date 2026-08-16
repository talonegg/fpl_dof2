/**
 * Load one of the lazy trend artefacts, degrading rather than breaking (DP-15).
 *
 * `history.json` and `fixtures.json` are fetched per route rather than in the shell's eager load
 * (DL-37), which means every consumer has to answer three questions the eagerly-loaded artefacts
 * never pose: it might still be loading, it might be absent from the published data entirely, and
 * the request might fail. All three collapse to the same obligation here — the rest of the player
 * page must render regardless. A missing fixture grid costs the reader the fixture panel; it must
 * not cost them the decomposition, the availability or the price history.
 *
 * `unavailable` is deliberately not `error`: for these two artefacts a 404 is a normal answer (a
 * bundle deployed against an older published data directory), and rendering it as a failure would
 * teach the reader to ignore failures.
 */

import { useEffect, useState } from "react";

export type LazyArtefact<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "unavailable"; reason: string };

export function useLazyArtefact<T>(
  load: () => Promise<T | null>,
  absentReason: string,
): LazyArtefact<T> {
  const [state, setState] = useState<LazyArtefact<T>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    load()
      .then((data) => {
        if (cancelled) return;
        setState(data === null ? { status: "unavailable", reason: absentReason } : { status: "ready", data });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // Swallowed on purpose: the promise is caught here so a failed optional artefact cannot
        // surface as an unhandled rejection or reach an error boundary and blank the page.
        setState({
          status: "unavailable",
          reason: error instanceof Error ? error.message : String(error),
        });
      });

    return () => {
      cancelled = true;
    };
    // `load` is a module-scope function with its own promise cache, so it is stable by construction
    // and is not a dependency. Including it would re-run this effect on every render of a caller
    // that passes an inline arrow.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [absentReason]);

  return state;
}
