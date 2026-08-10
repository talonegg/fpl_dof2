/** Shared formatting helpers. British English, £ currency, mean-with-uncertainty everywhere. */

export function formatPrice(price: number): string {
  return `£${price.toFixed(1)}m`;
}

/** Invariant 4: never render an expected-points mean without its uncertainty. */
export function formatXp(mean: number, sd: number | undefined): string {
  const sdText = sd === undefined || sd === null ? "?" : sd.toFixed(1);
  return `${mean.toFixed(2)} ±${sdText}`;
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
