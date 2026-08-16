import { useCallback, useEffect, useState } from "react";
import type { Health } from "../../contract/types";
import { fetchHealth, resetTrendCaches } from "../../data/api";

/**
 * `health.json`, fetched lazily on mount — the same shape `useFixtures` and `useLeague` have.
 *
 * **This route has an obligation the others do not.** It is the page a reader opens *because*
 * something looks wrong, so it is the one page that must still render when the published data is in
 * a bad state. Every other view may reasonably show an error when its artefact is broken; showing an
 * error here means the reader learns nothing at the exact moment they came to find something out.
 * So there are four failure states below, and each one says something different.
 *
 * `malformed` is the state the others do not have. A 404 is honest and a network failure is honest,
 * but a file that parses as JSON and is not this artefact would otherwise be handed to the component
 * as a `Health` the type system believes in, and the page would crash on the first missing field.
 * TypeScript cannot check the shape of something that came off the network; a guard can (DP-15).
 */
export type HealthState =
  | { status: "loading" }
  | { status: "ready"; health: Health }
  | { status: "absent" }
  | { status: "malformed" }
  | { status: "error"; message: string };

/**
 * The minimum shape the page renders from: the run excerpt, a source list, and the gate slot.
 *
 * Deliberately a floor and not a full validation. The publisher validates against the JSON Schema
 * before writing (DP-04), so a payload that reaches here and fails *this* is not a schema drift — it
 * is a different file entirely, or a truncated one. Re-implementing the schema in the browser would
 * be a second definition of the contract, which is what generating the types avoids.
 */
export function looksLikeHealth(value: unknown): value is Health {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<Health>;
  return (
    typeof candidate.generated_at === "string" &&
    typeof candidate.run === "object" &&
    candidate.run !== null &&
    Array.isArray(candidate.run.stages) &&
    Array.isArray(candidate.sources) &&
    // Present-and-null is the documented "no report" case, so the check is on the key existing
    // rather than on the value being truthy — `gates: null` is a valid, meaningful payload.
    "gates" in candidate
  );
}

export function useHealth(): { state: HealthState; retry: () => void } {
  const [state, setState] = useState<HealthState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setState({ status: "loading" });
    fetchHealth()
      .then((health) => {
        if (cancelled) return;
        if (health === null) {
          setState({ status: "absent" });
          return;
        }
        setState(
          looksLikeHealth(health) ? { status: "ready", health } : { status: "malformed" },
        );
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
