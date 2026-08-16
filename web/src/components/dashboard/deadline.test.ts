import { describe, expect, it } from "vitest";
import { formatInZone, hasPassed, timeUntil, urgencyOf } from "./deadline";

describe("timeUntil", () => {
  it("says 'passed' once the target instant is in the past", () => {
    const now = new Date("2026-08-21T18:00:00Z");
    expect(timeUntil(new Date("2026-08-21T17:00:00Z"), now)).toBe("passed");
  });

  it("shows days and hours while more than a day remains", () => {
    const now = new Date("2026-08-19T18:30:00Z");
    expect(timeUntil(new Date("2026-08-21T17:30:00Z"), now)).toBe("1d 23h");
  });

  it("drops to hours and minutes inside a day", () => {
    const now = new Date("2026-08-21T15:00:00Z");
    expect(timeUntil(new Date("2026-08-21T17:30:00Z"), now)).toBe("2h 30m");
  });

  it("shows minutes alone in the last hour", () => {
    const now = new Date("2026-08-21T17:15:00Z");
    expect(timeUntil(new Date("2026-08-21T17:30:00Z"), now)).toBe("15m");
  });
});

describe("hasPassed", () => {
  it("is true once the target instant is now or earlier", () => {
    const now = new Date("2026-08-21T18:00:00Z");
    expect(hasPassed(new Date("2026-08-21T17:00:00Z"), now)).toBe(true);
    expect(hasPassed(new Date("2026-08-21T18:00:00Z"), now)).toBe(true);
    expect(hasPassed(new Date("2026-08-21T19:00:00Z"), now)).toBe(false);
  });
});

describe("urgencyOf", () => {
  const target = new Date("2026-08-21T17:30:00Z");

  it("classifies the bands: passed, imminent, soon, distant", () => {
    expect(urgencyOf(target, new Date("2026-08-21T18:00:00Z"))).toBe("passed");
    expect(urgencyOf(target, new Date("2026-08-21T14:00:00Z"))).toBe("imminent");
    expect(urgencyOf(target, new Date("2026-08-20T10:00:00Z"))).toBe("soon");
    expect(urgencyOf(target, new Date("2026-08-15T10:00:00Z"))).toBe("distant");
  });
});

describe("formatInZone", () => {
  it("renders the instant in the named IANA zone", () => {
    const rendered = formatInZone(new Date("2026-08-21T17:30:00Z"), "Europe/London");
    expect(rendered).toContain("18:30");
  });

  it("falls back to a legible UTC string for an unknown zone rather than throwing", () => {
    const rendered = formatInZone(new Date("2026-08-21T17:30:00Z"), "Not/AZone");
    expect(rendered).toContain("UTC");
    expect(rendered).toContain("2026-08-21");
  });
});
