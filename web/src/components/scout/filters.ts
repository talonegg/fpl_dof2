/**
 * Scout filtering and sorting: pure functions over the published player array.
 *
 * Q-06 as the epic scopes it — ~700 rows is a JavaScript `filter` and `sort`, not a query engine
 * (DL-36). Keeping this separate from the component means it is testable without a DOM, which is
 * where the interesting cases live: an empty facet means "all" rather than "none", and a missing
 * value sorts last in both directions rather than pretending to be zero.
 */

import type { Player } from "../../contract/types";
import { AVAILABLE_STATUS, COLUMNS_BY_KEY } from "./columns";

export type Position = Player["position"];
export type Confidence = Player["confidence"];

export const POSITIONS: Position[] = ["GKP", "DEF", "MID", "FWD"];
export const CONFIDENCES: Confidence[] = ["high", "medium", "low", "none"];

export interface ScoutFilters {
  /** Matched against name, full name and club, case-insensitively. */
  search: string;
  /** Empty means every position. A facet with nothing ticked is "no filter", never "no rows". */
  positions: Position[];
  clubs: string[];
  confidences: Confidence[];
  /** In £m. `null` means unbounded on that side. */
  minPrice: number | null;
  maxPrice: number | null;
  /** Hide anyone the game does not currently list as available. */
  availableOnly: boolean;
}

export const EMPTY_FILTERS: ScoutFilters = {
  search: "",
  positions: [],
  clubs: [],
  confidences: [],
  minPrice: null,
  maxPrice: null,
  availableOnly: false,
};

export type SortDirection = "asc" | "desc";

export interface ScoutSort {
  key: string;
  direction: SortDirection;
}

/** The forecast, best first — the question the table is usually opened to answer. */
export const DEFAULT_SORT: ScoutSort = { key: "xp_next", direction: "desc" };

/** Every club in the data, sorted, for the club facet. Derived, never hardcoded. */
export function clubsIn(players: readonly Player[]): string[] {
  return Array.from(new Set(players.map((p) => p.team))).sort((a, b) => a.localeCompare(b));
}

/** The price range present in the data, rounded outwards to whole £m for a usable slider. */
export function priceBounds(players: readonly Player[]): { min: number; max: number } {
  if (players.length === 0) return { min: 0, max: 0 };
  let min = Infinity;
  let max = -Infinity;
  for (const p of players) {
    if (p.price < min) min = p.price;
    if (p.price > max) max = p.price;
  }
  return { min: Math.floor(min), max: Math.ceil(max) };
}

export function isDefaultFilters(filters: ScoutFilters): boolean {
  return (
    filters.search.trim() === "" &&
    filters.positions.length === 0 &&
    filters.clubs.length === 0 &&
    filters.confidences.length === 0 &&
    filters.minPrice === null &&
    filters.maxPrice === null &&
    !filters.availableOnly
  );
}

/** How many facets are narrowing the table, for the "filters active" badge. */
export function activeFilterCount(filters: ScoutFilters): number {
  let count = 0;
  if (filters.search.trim() !== "") count += 1;
  if (filters.positions.length > 0) count += 1;
  if (filters.clubs.length > 0) count += 1;
  if (filters.confidences.length > 0) count += 1;
  if (filters.minPrice !== null || filters.maxPrice !== null) count += 1;
  if (filters.availableOnly) count += 1;
  return count;
}

export function filterPlayers(players: readonly Player[], filters: ScoutFilters): Player[] {
  const needle = filters.search.trim().toLowerCase();
  const positions = new Set(filters.positions);
  const clubs = new Set(filters.clubs);
  const confidences = new Set(filters.confidences);

  return players.filter((p) => {
    if (positions.size > 0 && !positions.has(p.position)) return false;
    if (clubs.size > 0 && !clubs.has(p.team)) return false;
    if (confidences.size > 0 && !confidences.has(p.confidence)) return false;
    if (filters.minPrice !== null && p.price < filters.minPrice) return false;
    if (filters.maxPrice !== null && p.price > filters.maxPrice) return false;
    if (filters.availableOnly && p.status !== AVAILABLE_STATUS) return false;
    if (!needle) return true;
    return (
      p.name.toLowerCase().includes(needle) ||
      (p.full_name ?? "").toLowerCase().includes(needle) ||
      p.team.toLowerCase().includes(needle)
    );
  });
}

/**
 * Sort a filtered set.
 *
 * The tie-break on `id` is not decoration: without it two runs over equal keys can order rows
 * differently, and a table that reshuffles under an unchanged filter is a table nobody trusts
 * (DP-11's "stable sort orders", at UI scale).
 */
export function sortPlayers(players: readonly Player[], sort: ScoutSort): Player[] {
  const column = COLUMNS_BY_KEY[sort.key];
  const copy = [...players];
  if (!column) return copy;

  const sign = sort.direction === "asc" ? 1 : -1;
  copy.sort((a, b) => {
    const av = column.sortValue(a);
    const bv = column.sortValue(b);

    // Missing values sort last whichever way the column is pointing: an unpublished figure is not
    // a small one, and floating it to the top of a descending sort would say that it was.
    if (av === null && bv === null) return a.id - b.id;
    if (av === null) return 1;
    if (bv === null) return -1;

    let cmp: number;
    if (typeof av === "number" && typeof bv === "number") cmp = av - bv;
    else cmp = String(av).localeCompare(String(bv));

    return cmp === 0 ? a.id - b.id : cmp * sign;
  });
  return copy;
}

/** Clicking a header: same column flips direction, a new column starts the way that column reads. */
export function nextSort(current: ScoutSort, key: string): ScoutSort {
  if (current.key === key) {
    return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  }
  const column = COLUMNS_BY_KEY[key];
  // A number is nearly always most interesting at its largest; a name is most useful from A.
  return { key, direction: column?.numeric ? "desc" : "asc" };
}
