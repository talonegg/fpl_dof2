/**
 * The comparison selection: which two-to-four players the scout view has handed to `/compare`.
 *
 * The **contract between the two routes is the URL**: `#/compare?compare=1,2,3`, a comma-separated
 * list of player ids in the order they were chosen (DL-36). It is readable, editable, bookmarkable
 * and pasteable, and it needs no shared mutable state between two routes that otherwise know
 * nothing about each other. Both sides go through this module rather than hand-writing the format.
 *
 * `useComparisonSelection` additionally mirrors the *in-progress* selection to `localStorage`, so
 * ticking three players, opening one of them and coming back does not silently lose the work. That
 * mirror is a convenience; the URL is the contract, and a `?compare=` parameter always wins over it.
 */

import { useCallback, useEffect, useState } from "react";

/** The query parameter both routes read and write. */
export const COMPARE_PARAM = "compare";

/** Where the in-progress selection is mirrored. Not the contract — see the module comment. */
export const COMPARE_STORAGE_KEY = "fpl-dof.compare-selection";

/**
 * How many players a comparison holds.
 *
 * These are presentation limits from the E6-S4 story ("two to four players side by side"), not FPL
 * rule values, so they belong here rather than in `rules.json` — Invariant 2 is not engaged. Below
 * the minimum there is nothing to compare; above the maximum the columns stop fitting on a phone,
 * which is the constraint that actually sets the number.
 */
export const COMPARE_MIN = 2;
export const COMPARE_MAX = 4;

/**
 * Read a selection out of a router `search` string.
 *
 * Defensive by construction: this parses whatever a URL happens to contain, including one a reader
 * typed. Anything that is not a positive integer is dropped, duplicates are dropped, order is
 * preserved, and the result is capped at `COMPARE_MAX`. It never throws, and callers still have to
 * resolve the ids against the published players — an id in a URL is not a player.
 */
export function parseCompareIds(search: string): number[] {
  const raw = new URLSearchParams(search).get(COMPARE_PARAM);
  if (!raw) return [];
  return normaliseIds(raw.split(","));
}

/** The `/compare` link for a selection. Relative, so it works under the hash and any base path. */
export function compareHref(ids: readonly number[]): string {
  const clean = normaliseIds(ids);
  return clean.length === 0 ? "/compare" : `/compare?${COMPARE_PARAM}=${clean.join(",")}`;
}

/** A selection is comparable once it holds at least two players. */
export function isComparable(ids: readonly number[]): boolean {
  return ids.length >= COMPARE_MIN;
}

function normaliseIds(values: readonly (string | number)[]): number[] {
  const out: number[] = [];
  for (const value of values) {
    const id = typeof value === "number" ? value : Number(value.trim());
    if (!Number.isInteger(id) || id <= 0) continue;
    if (out.includes(id)) continue;
    out.push(id);
    if (out.length === COMPARE_MAX) break;
  }
  return out;
}

function readStored(): number[] {
  try {
    const stored = window.localStorage.getItem(COMPARE_STORAGE_KEY);
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    return Array.isArray(parsed) ? normaliseIds(parsed as (string | number)[]) : [];
  } catch {
    // Storage disabled, or a shape written by an older build. Losing a selection is a lost
    // convenience, never an error page (DP-15).
    return [];
  }
}

function writeStored(ids: readonly number[]): void {
  try {
    window.localStorage.setItem(COMPARE_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    /* see readStored */
  }
}

export interface ComparisonSelection {
  /** The chosen ids, in the order they were ticked. */
  ids: number[];
  isSelected: (id: number) => boolean;
  /** Add or remove an id. Adding beyond `COMPARE_MAX` is ignored rather than silently rotating. */
  toggle: (id: number) => void;
  clear: () => void;
  /** False once the selection is full, so the UI can disable rather than fail silently. */
  canAdd: boolean;
  /** True once there are at least `COMPARE_MIN` — the point at which the compare link is live. */
  comparable: boolean;
  /** The `/compare` link for the current selection. */
  href: string;
}

/**
 * The scout view's selection state, persisted across navigation.
 *
 * Seeded from storage on first render so returning to the table restores what was ticked.
 */
export function useComparisonSelection(): ComparisonSelection {
  const [ids, setIds] = useState<number[]>(readStored);

  useEffect(() => {
    writeStored(ids);
  }, [ids]);

  const toggle = useCallback((id: number) => {
    setIds((current) => {
      if (current.includes(id)) return current.filter((other) => other !== id);
      if (current.length >= COMPARE_MAX) return current;
      return [...current, id];
    });
  }, []);

  const clear = useCallback(() => setIds([]), []);

  return {
    ids,
    isSelected: (id: number) => ids.includes(id),
    toggle,
    clear,
    canAdd: ids.length < COMPARE_MAX,
    comparable: isComparable(ids),
    href: compareHref(ids),
  };
}
