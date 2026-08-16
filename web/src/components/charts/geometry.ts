/**
 * Chart geometry: the arithmetic of turning numbers into coordinates.
 *
 * Pure and DOM-free, in the same spirit as `scout/filters.ts` and `dashboard/roll.ts` — the part of a
 * chart that can be silently wrong is the scaling, not the markup, so it is the part that gets tested
 * (DP-13). A chart whose y-axis quietly excludes zero, or whose single-valued series collapses to a
 * flat line at the top of the plot, misleads without ever throwing.
 *
 * Shared by `/player/:id` (E6-S3) and available to E6-S5's charts unchanged.
 */

export interface Extent {
  min: number;
  max: number;
}

export interface Point {
  x: number;
  y: number;
}

/** The extent of a set of values, or null when there is nothing to plot. */
export function extentOf(values: readonly number[]): Extent | null {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return null;
  return { min: Math.min(...finite), max: Math.max(...finite) };
}

export interface PadOptions {
  /**
   * Extend the domain to include zero. On by default for anything counted — points, minutes, goals —
   * because a bar or line read against a floating baseline exaggerates every difference on it.
   * Off for price and ownership, where the interesting variation is a fraction of the absolute value
   * and anchoring at zero would flatten the series into a straight line.
   */
  includeZero?: boolean;
  /** Smallest span the domain may have, so a constant series does not divide by zero. */
  minSpan?: number;
  /** Fraction of the span added at each end, so markers are not clipped by the plot edge. */
  padFraction?: number;
}

export function padExtent(extent: Extent, options: PadOptions = {}): Extent {
  const { includeZero = true, minSpan = 1, padFraction = 0.08 } = options;

  let min = includeZero ? Math.min(0, extent.min) : extent.min;
  let max = includeZero ? Math.max(0, extent.max) : extent.max;

  const span = max - min;
  if (span < minSpan) {
    // A constant series. Open the domain symmetrically around the value rather than letting the
    // scale divide by zero and put every point at the same pixel with no indication why.
    const centre = (max + min) / 2;
    min = centre - minSpan / 2;
    max = centre + minSpan / 2;
    if (includeZero) {
      min = Math.min(0, min);
      max = Math.max(0, max);
    }
  } else if (padFraction > 0) {
    const pad = span * padFraction;
    // Do not pad past zero: a padded floor below zero implies negative minutes are possible.
    min = includeZero && extent.min >= 0 ? min : min - pad;
    max = max + pad;
  }

  return { min, max };
}

/**
 * A linear scale from a data domain onto a pixel range.
 *
 * `rangeStart` may be greater than `rangeEnd`, which is how the y-axis is inverted: SVG counts pixels
 * downward and points upward.
 */
export function makeScale(
  domain: Extent,
  rangeStart: number,
  rangeEnd: number,
): (value: number) => number {
  const span = domain.max - domain.min;
  if (span === 0) {
    const midpoint = (rangeStart + rangeEnd) / 2;
    return () => midpoint;
  }
  return (value: number) => rangeStart + ((value - domain.min) / span) * (rangeEnd - rangeStart);
}

/**
 * Round tick values inside a domain, at a step from the 1/2/5 family.
 *
 * Approximate `count` rather than exact: a tick at 3.7333 is worse than four ticks where five were
 * requested.
 */
export function ticks(domain: Extent, count = 4): number[] {
  const span = domain.max - domain.min;
  if (!Number.isFinite(span) || span <= 0 || count < 1) return [domain.min];

  const rough = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalised = rough / magnitude;
  const step = (normalised >= 5 ? 10 : normalised >= 2 ? 5 : normalised >= 1 ? 2 : 1) * magnitude;

  const out: number[] = [];
  const first = Math.ceil(domain.min / step) * step;
  for (let value = first; value <= domain.max + step / 1000; value += step) {
    // Snap: repeated addition of a fractional step accumulates error that shows up as a "0.30000004"
    // axis label.
    out.push(Math.round(value / step) * step);
  }
  return out;
}

/**
 * How many standard deviations a drawn uncertainty band spans, either side of the mean.
 *
 * Two, matching `formatXpRange` in `src/format.ts` — the same band the app already states in prose,
 * so the picture and the sentence beside it cannot disagree about how wide the uncertainty is. It is
 * deliberately *not* `SEPARATION_SIGMAS` from `compare/verdict.ts`, which answers a different
 * question: this is the honest width of one forecast, that is the bar for calling two of them apart.
 */
export const BAND_SIGMAS = 2;

export interface Band {
  low: number;
  high: number;
}

export interface BandOptions {
  /** Half-width of the band, in standard deviations. */
  sigmas?: number;
  /**
   * Clamp the lower edge here. Zero by default: a band whose floor is -1.8 expected points draws a
   * region the game cannot produce, and a reader measures the band it can see. Pass `null` for a
   * quantity that genuinely can go negative.
   */
  floor?: number | null;
}

/**
 * The plausible range around a forecast mean, or **null when the uncertainty is not published**.
 *
 * Null rather than a zero-width band, and the distinction is the whole point (Invariant 6, DP-09). A
 * band of width zero renders as a bare tick — visually identical to a measurement, which is the exact
 * misreading the band exists to prevent. A caller that gets null must say the uncertainty is missing;
 * it must not draw a point and let the reader assume certainty.
 */
export function uncertaintyBand(
  mean: number,
  sd: number | undefined | null,
  options: BandOptions = {},
): Band | null {
  if (sd === undefined || sd === null || !Number.isFinite(sd) || sd < 0) return null;
  if (!Number.isFinite(mean)) return null;

  const { sigmas = BAND_SIGMAS, floor = 0 } = options;
  const spread = sd * sigmas;
  const low = mean - spread;

  return { low: floor === null ? low : Math.max(floor, low), high: mean + spread };
}

/** An SVG path through the points, in order. Empty string for nothing to draw. */
export function linePath(points: readonly Point[]): string {
  if (points.length === 0) return "";
  return points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");
}
