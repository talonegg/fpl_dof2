import type { Health, HealthMetricsPoint, HealthSource } from "../../contract/types";

/**
 * Pure derivations behind the data health page (E7-S6, DL-41).
 *
 * Nothing here knows a data source exists. `HealthSource["source"]` is an opaque label that arrived
 * in the artefact, and every function below sorts, counts and formats it without ever testing what
 * it says (Invariant 1, DP-01). Adding a fourth source changes an adapter module in the pipeline and
 * not one line of this file.
 *
 * Split out of the component so the states that matter can be asserted without rendering: the ones
 * worth being sure about are the ones that read as fine when they are wrong.
 */

/** How a status should read. Deliberately not a colour — colour is never the only carrier. */
export type Tone = "good" | "warn" | "bad" | "neutral";

export interface StatusReading {
  label: string;
  tone: Tone;
  /** The derivation, in words. A badge without one is an assertion (DP-09). */
  detail: string;
}

/**
 * Seconds as a human span. Coarse on purpose: "about 3 hours" is what a freshness figure is
 * actually read at, and a spurious "3 hours, 14 minutes and 9 seconds" invites precision that the
 * underlying snapshot time does not have.
 */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "unknown";
  if (seconds < 90) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min ago`;
  const hours = Math.round(seconds / 3600);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

/** Seconds as a duration, for solve times and stage timings. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 90) return `${seconds.toFixed(1)} s`;
  return `${Math.round(seconds / 60)} min`;
}

/**
 * How one source should read.
 *
 * `unknown` is deliberately a warning rather than a neutral note. A source the run recorded nothing
 * about has not been shown to be working, and rendering "no news" the same way as "good news" is
 * how a feed that quietly stopped being fetched goes unnoticed for a month.
 */
export function sourceStatus(source: HealthSource): StatusReading {
  if (source.status === "degraded") {
    return {
      label: "Degraded",
      tone: "bad",
      detail: source.detail
        ? `The run continued without this source's fields. Reported by the ${
            source.degraded_at_stage ?? "pipeline"
          } stage as: ${source.detail}`
        : "The run continued without this source's fields.",
    };
  }
  if (source.status === "unknown") {
    return {
      label: "Not seen",
      tone: "warn",
      detail:
        source.detail ??
        "This run recorded no activity for this source, which is not the same as it being healthy.",
    };
  }
  const served =
    source.network_calls === 0 && (source.cache_hits ?? 0) > 0
      ? " Served entirely from cache, so its snapshots are no newer than the run before."
      : "";
  return { label: "OK", tone: "good", detail: `Fetched without error.${served}` };
}

/** Sources that are not healthy, degraded first. What the banner is built from. */
export function troubledSources(health: Health): HealthSource[] {
  return health.sources
    .filter((source) => source.status !== "ok")
    .sort((a, b) => {
      if (a.status !== b.status) return a.status === "degraded" ? -1 : 1;
      return a.source.localeCompare(b.source);
    });
}

/**
 * How the last run ended.
 *
 * The run that published this file is still in flight when it writes it, so a null status is the
 * ordinary case and must not read as a failure. A run whose own manifest says a stage failed is a
 * different matter, and is called that.
 */
export function runOutcome(health: Health): StatusReading {
  const failed = health.run.stages.filter((stage) => stage.status === "failed");
  if (failed.length > 0) {
    return {
      label: "Failed",
      tone: "bad",
      detail: `${failed.map((stage) => stage.name).join(", ")} did not complete.`,
    };
  }
  if (health.run.status === "succeeded") {
    return { label: "Succeeded", tone: "good", detail: "Every stage completed." };
  }
  if (health.run.status === "failed") {
    return { label: "Failed", tone: "bad", detail: "The run did not complete." };
  }
  return {
    label: "Published",
    tone: "good",
    detail:
      "Every stage up to publication completed. The run records its own outcome after this file " +
      "is written, so it is reported as unfinished here rather than guessed at.",
  };
}

/**
 * How the gates read.
 *
 * A null report is a warning, never a pass. This page exists to be trusted about exactly this
 * question, and an absent report assembled into a green tick is the most expensive thing it could
 * get wrong (DP-13).
 */
export function gateOutcome(health: Health): StatusReading {
  const gates = health.gates;
  if (!gates) {
    return {
      label: "Not reported",
      tone: "warn",
      detail:
        "No gate report was published with this run, so nothing here has been checked. That is " +
        "not the same as everything passing.",
    };
  }
  if (!gates.passed) {
    return {
      label: "Blocked",
      tone: "bad",
      detail:
        `${gates.blocking.length} gate(s) blocked publication, so nothing new was published and ` +
        "the artefacts on this site are from an earlier run.",
    };
  }
  const failed = gates.counts.failed;
  if (failed > 0) {
    return {
      label: "Passed with warnings",
      tone: "warn",
      detail: `${failed} non-blocking gate(s) failed. Publication went ahead.`,
    };
  }
  return {
    label: "Passed",
    tone: "good",
    detail: `${gates.counts.passed} passed, ${gates.counts.skipped} skipped for absent data.`,
  };
}

/** A metrics series as chart points, with runs that have no value for it dropped, never zeroed. */
export function seriesOf(
  runs: readonly HealthMetricsPoint[],
  pick: (point: HealthMetricsPoint) => number | null | undefined,
): { x: number; y: number }[] {
  const points: { x: number; y: number }[] = [];
  runs.forEach((run, index) => {
    const value = pick(run);
    // A run that never reached this stage has no value for it. Dropping the point draws a gap;
    // substituting a zero would draw an instant solve or an empty database, both of which look
    // like measurements and neither of which happened.
    if (value === null || value === undefined || !Number.isFinite(value)) return;
    points.push({ x: index + 1, y: value });
  });
  return points;
}
