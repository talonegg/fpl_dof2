export interface Ranked<T> {
  item: T;
  score: number | null;
  /** Competition rank ("1, 1, 3"); null for an item with no score. */
  rank: number | null;
}

/**
 * Highest score first, ties sharing a rank and keeping the order given; items with no score come
 * last, unranked, so a ladder can list every model and still say which ones it could not place.
 */
export function rankBy<T>(items: readonly T[], score: (item: T) => number | null): Ranked<T>[] {
  const scored = items.map((item) => ({ item, score: score(item) }));
  const placed = scored.filter((s) => s.score !== null).sort((a, b) => (b.score as number) - (a.score as number));
  return [
    ...placed.map((s) => ({ ...s, rank: 1 + placed.findIndex((p) => p.score === s.score) })),
    ...scored.filter((s) => s.score === null).map((s) => ({ ...s, rank: null })),
  ];
}
