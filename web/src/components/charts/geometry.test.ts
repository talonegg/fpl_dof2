import { describe, expect, it } from "vitest";
import {
  BAND_SIGMAS,
  extentOf,
  linePath,
  makeScale,
  padExtent,
  ticks,
  uncertaintyBand,
} from "./geometry";

describe("extentOf", () => {
  it("returns null for nothing to plot, so a caller must handle the empty case", () => {
    expect(extentOf([])).toBeNull();
  });

  it("ignores non-finite values rather than poisoning the whole domain with NaN", () => {
    expect(extentOf([1, Number.NaN, 5, Number.POSITIVE_INFINITY])).toEqual({ min: 1, max: 5 });
  });

  it("returns null when every value is non-finite", () => {
    expect(extentOf([Number.NaN])).toBeNull();
  });

  it("takes the range of the finite values", () => {
    expect(extentOf([3, -2, 7])).toEqual({ min: -2, max: 7 });
  });
});

describe("padExtent", () => {
  it("includes zero by default, so a counted series is read against a true baseline", () => {
    const padded = padExtent({ min: 4, max: 9 });
    expect(padded.min).toBe(0);
    expect(padded.max).toBeGreaterThan(9);
  });

  it("does not include zero when asked not to, so price variation stays visible", () => {
    const padded = padExtent({ min: 7.8, max: 8.3 }, { includeZero: false, minSpan: 0.1 });
    expect(padded.min).toBeGreaterThan(0);
    expect(padded.min).toBeLessThanOrEqual(7.8);
    expect(padded.max).toBeGreaterThanOrEqual(8.3);
  });

  it("opens a domain around a constant series instead of collapsing it to a point", () => {
    const padded = padExtent({ min: 8, max: 8 }, { includeZero: false, minSpan: 0.4 });
    expect(padded.max - padded.min).toBeCloseTo(0.4, 6);
    expect(padded.min).toBeLessThan(8);
    expect(padded.max).toBeGreaterThan(8);
  });

  it("never pads a non-negative counted series below zero", () => {
    // Minutes cannot be negative, and an axis that starts at -12 says they can.
    const padded = padExtent({ min: 0, max: 90 });
    expect(padded.min).toBe(0);
  });
});

describe("makeScale", () => {
  it("maps the domain onto the range linearly", () => {
    const scale = makeScale({ min: 0, max: 10 }, 0, 100);
    expect(scale(0)).toBe(0);
    expect(scale(5)).toBe(50);
    expect(scale(10)).toBe(100);
  });

  it("inverts when the range runs backwards, which is how y points upward in SVG", () => {
    const scale = makeScale({ min: 0, max: 10 }, 180, 20);
    expect(scale(0)).toBe(180);
    expect(scale(10)).toBe(20);
  });

  it("puts a zero-span domain at the middle of the range rather than dividing by zero", () => {
    const scale = makeScale({ min: 5, max: 5 }, 0, 100);
    expect(scale(5)).toBe(50);
    expect(Number.isNaN(scale(5))).toBe(false);
  });
});

describe("ticks", () => {
  it("produces round values from the 1/2/5 family inside the domain", () => {
    const values = ticks({ min: 0, max: 10 }, 4);
    expect(values.every((v) => v >= 0 && v <= 10)).toBe(true);
    expect(values).toContain(0);
    expect(values).toContain(10);
  });

  it("does not emit floating-point noise as an axis label", () => {
    for (const value of ticks({ min: 0, max: 1 }, 5)) {
      expect(value.toString().length).toBeLessThan(8);
    }
  });

  it("degrades to a single tick for a degenerate domain", () => {
    expect(ticks({ min: 3, max: 3 })).toEqual([3]);
  });
});

describe("uncertaintyBand", () => {
  it("spans two standard deviations either side, matching the band the app states in prose", () => {
    expect(BAND_SIGMAS).toBe(2);
    expect(uncertaintyBand(5.2, 1.5)).toEqual({ low: 5.2 - 3, high: 5.2 + 3 });
  });

  it("is null when the uncertainty is not published, rather than a zero-width band", () => {
    // The whole point (Invariant 6): a zero-width band renders as a bare tick, which is visually a
    // measurement. A caller must be forced to say the uncertainty is missing.
    expect(uncertaintyBand(5.2, undefined)).toBeNull();
    expect(uncertaintyBand(5.2, null)).toBeNull();
    expect(uncertaintyBand(5.2, Number.NaN)).toBeNull();
  });

  it("is null for a negative standard deviation, which is not a band with a direction", () => {
    expect(uncertaintyBand(5.2, -1)).toBeNull();
  });

  it("keeps a genuinely zero standard deviation as a band, because that is a published claim", () => {
    // Distinct from an absent sd: the model saying "no variance" is information, not a gap.
    expect(uncertaintyBand(3, 0)).toEqual({ low: 3, high: 3 });
  });

  it("floors at zero, so the band never draws returns the game cannot produce", () => {
    const band = uncertaintyBand(1.2, 2.0);
    expect(band).toEqual({ low: 0, high: 1.2 + 4 });
  });

  it("lets the floor be lifted for a quantity that really can go negative", () => {
    expect(uncertaintyBand(1.2, 2.0, { floor: null })).toEqual({ low: 1.2 - 4, high: 1.2 + 4 });
  });

  it("takes a different half-width when asked", () => {
    expect(uncertaintyBand(10, 1, { sigmas: 1 })).toEqual({ low: 9, high: 11 });
  });

  it("is null for a non-finite mean rather than producing a NaN domain", () => {
    expect(uncertaintyBand(Number.NaN, 1)).toBeNull();
  });
});

describe("linePath", () => {
  it("is empty when there is nothing to draw", () => {
    expect(linePath([])).toBe("");
  });

  it("moves to the first point and lines to the rest", () => {
    expect(
      linePath([
        { x: 0, y: 10 },
        { x: 5, y: 20 },
      ]),
    ).toBe("M0.00 10.00 L5.00 20.00");
  });
});
