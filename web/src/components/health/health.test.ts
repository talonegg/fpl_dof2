import { describe, expect, it } from "vitest";
import type { HealthSource } from "../../contract/types";
import {
  checkReading,
  countsTowardOk,
  formatAsOf,
  isReference,
  sourceName,
  sourceStatus,
  troubledSources,
} from "./health";
import { allStatesHealth, health, mismatchHealth } from "./testFixtures";

/**
 * The Sources section's pure derivations (T-003). Labels are Scribe's (T-004); source names are
 * invented, because nothing in `web/` may know a real one (Invariant 1).
 */
function source(overrides: Partial<HealthSource>): HealthSource {
  return { source: "invented-feed", status: "ok", ...overrides };
}

describe("sourceStatus", () => {
  it.each([
    ["ok", "OK", "good"],
    ["stale", "Stale", "warn"],
    ["degraded", "Degraded", "bad"],
    ["not_configured", "Not set up", "neutral"],
    ["disabled", "Switched off", "neutral"],
    ["unknown", "Not seen", "warn"],
  ] as const)("reads %s as %s", (status, label, tone) => {
    const reading = sourceStatus(source({ status, network_calls: 1 }));
    expect(reading.label).toBe(label);
    expect(reading.tone).toBe(tone);
    expect(reading.detail).toBeTruthy();
  });

  it("never reads zero requests and zero cache reads as OK", () => {
    // T-001 F2: a source with no key "fetched without error" by doing nothing at all.
    const reading = sourceStatus(source({ status: "ok", network_calls: 0, cache_hits: 0 }));
    expect(reading.label).toBe("Not seen");
  });

  it("shows the pipeline's own reason for an OK it inferred from a scheduled ingest", () => {
    const reading = sourceStatus(allStatesHealth.sources[0]);
    expect(reading.label).toBe("OK");
    expect(reading.detail).toContain("scheduled ingest");
  });

  it("reads reference data as Reference rather than OK", () => {
    const reading = sourceStatus(source({ kind: "reference", status: "ok", detail: "fixed" }));
    expect(reading.label).toBe("Reference");
    expect(reading.tone).toBe("neutral");
    expect(reading.detail).toBe("fixed");
  });

  it("reads a failed file check as Mismatch, with the reason", () => {
    const failed = mismatchHealth.sources.find((s) => s.source === "eta-set");
    expect(failed).toBeDefined();
    const reading = sourceStatus(failed as HealthSource);
    expect(reading.label).toBe("Mismatch");
    expect(reading.tone).toBe("bad");
    expect(reading.detail).toContain("upstream file differs");
  });

  it("keeps the stage and the reason on a degraded fetch", () => {
    const reading = sourceStatus(health.sources[1]);
    expect(reading.detail).toContain("ingest");
    expect(reading.detail).toContain("HTTPError");
  });
});

describe("the tally and the banner", () => {
  it("counts only live feeds that are switched on and set up", () => {
    const counted = allStatesHealth.sources.filter(countsTowardOk).map((s) => s.source);
    expect(counted).toEqual(["alpha-feed", "omega-feed"]);
  });

  it("banners stale and mismatched sources but not deliberate, explained states", () => {
    expect(troubledSources(allStatesHealth).map((s) => s.source)).toEqual(["omega-feed"]);
    expect(troubledSources(mismatchHealth).map((s) => s.source)).toEqual([
      "eta-set",
      "omega-feed",
    ]);
  });
});

describe("labels and dates", () => {
  it("renders the declared label, or the opaque key when there is none", () => {
    expect(sourceName(allStatesHealth.sources[0])).toBe("Alpha feed");
    expect(sourceName(health.sources[0])).toBe("alpha-feed");
  });

  it("treats an artefact from before kinds existed as live", () => {
    expect(isReference(health.sources[0])).toBe(false);
  });

  it("formats an as-of date without shifting it across a timezone", () => {
    expect(formatAsOf("2026-05-24")).toContain("24");
    expect(formatAsOf("2026-05-24")).toContain("2026");
    expect(formatAsOf(null)).toBe("—");
  });

  it("reads the file check as Verified or Mismatch, and nothing when there is none", () => {
    expect(checkReading(source({ check: "pass" }))?.label).toBe("Verified");
    expect(checkReading(source({ check: "fail" }))?.label).toBe("Mismatch");
    expect(checkReading(source({ check: null }))).toBeNull();
  });
});
