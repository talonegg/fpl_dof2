/** Shared formatting helpers. British English, £ currency, mean-with-uncertainty everywhere. */

export function formatPrice(price: number): string {
  return `£${price.toFixed(1)}m`;
}

/** Invariant 4: never render an expected-points mean without its uncertainty. */
export function formatXp(mean: number, sd: number | undefined): string {
  const sdText = sd === undefined || sd === null ? "?" : sd.toFixed(1);
  return `${mean.toFixed(2)} ±${sdText}`;
}

/**
 * The plausible range around a forecast, as prose for a tooltip or a screen reader.
 *
 * Two standard deviations either side, floored at zero because a player cannot score fewer points
 * than the game's own floor allows in the direction this band is used. This exists because
 * "4.20 ±2.03" is a band a reader can skim past; "plausibly 0.1 to 8.3" is one they cannot
 * (Invariant 6, DP-09). A predicted 5.2 that could be anything from 0 to 15 must never read like a
 * measurement.
 */
export function formatXpRange(mean: number, sd: number | undefined): string {
  if (sd === undefined || sd === null) return `${mean.toFixed(2)}, uncertainty unpublished`;
  const low = Math.max(0, mean - 2 * sd);
  const high = mean + 2 * sd;
  return `${mean.toFixed(2)} expected — plausibly ${low.toFixed(1)} to ${high.toFixed(1)}`;
}

export function formatPercent(value: number | undefined): string {
  if (value === undefined || value === null) return "—";
  return `${value.toFixed(1)}%`;
}

export function formatLocalDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Points, to two places. Separate from formatXp because an option's net xP carries no band. */
export function formatPoints(value: number): string {
  return value.toFixed(2);
}
