/**
 * Saved filter presets: a named filter set, column selection and sort, kept in `localStorage`.
 *
 * There is no account and no server (NFR-11, Invariant 8), so browser storage is the only place a
 * personal convenience like this can live (DL-36). Everything here is read defensively: storage may
 * be absent, disabled by private browsing, full, or holding a shape an older build wrote. Each of
 * those degrades to "no saved presets" and never to an error, which is DP-15 at its smallest useful
 * scale — the reader loses a convenience, not the page.
 */

import { useCallback, useState } from "react";
import { EMPTY_FILTERS, type ScoutFilters, type ScoutSort, DEFAULT_SORT } from "./filters";
import { COLUMNS_BY_KEY, DEFAULT_VISIBLE_COLUMNS, PINNED_COLUMN } from "./columns";

export const PRESET_STORAGE_KEY = "fpl-dof.scout-presets";

/**
 * How many presets are kept.
 *
 * DP-06: a named limit rather than a literal. It exists so a runaway loop or a pasted blob cannot
 * fill the origin's storage quota and take the theme preference down with it; twenty is far more
 * than a person names by hand.
 */
export const MAX_PRESETS = 20;

export interface ScoutPreset {
  name: string;
  filters: ScoutFilters;
  columns: string[];
  sort: ScoutSort;
}

/**
 * Coerce whatever was in storage into a preset, or reject it.
 *
 * Written field by field rather than trusted wholesale: this is parsing untrusted input that
 * happens to live on the same machine. Unknown column keys are dropped, so a preset saved before a
 * column was renamed still applies with the columns that do exist.
 */
function parsePreset(value: unknown): ScoutPreset | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  const name = typeof record.name === "string" ? record.name.trim() : "";
  if (name === "") return null;

  const storedFilters = (record.filters ?? {}) as Record<string, unknown>;
  const filters: ScoutFilters = {
    search: typeof storedFilters.search === "string" ? storedFilters.search : "",
    positions: stringArray(storedFilters.positions) as ScoutFilters["positions"],
    clubs: stringArray(storedFilters.clubs),
    confidences: stringArray(storedFilters.confidences) as ScoutFilters["confidences"],
    minPrice: finiteOrNull(storedFilters.minPrice),
    maxPrice: finiteOrNull(storedFilters.maxPrice),
    availableOnly: storedFilters.availableOnly === true,
  };

  const columns = stringArray(record.columns).filter((key) => key in COLUMNS_BY_KEY);
  const storedSort = (record.sort ?? {}) as Record<string, unknown>;
  const sortKey = typeof storedSort.key === "string" ? storedSort.key : "";
  const sort: ScoutSort =
    sortKey in COLUMNS_BY_KEY
      ? { key: sortKey, direction: storedSort.direction === "asc" ? "asc" : "desc" }
      : DEFAULT_SORT;

  return {
    name,
    filters,
    columns: columns.length > 0 ? ensurePinned(columns) : DEFAULT_VISIBLE_COLUMNS,
    sort,
  };
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function finiteOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The name column may not be switched off, however a preset was written. */
function ensurePinned(columns: string[]): string[] {
  return columns.includes(PINNED_COLUMN) ? columns : [PINNED_COLUMN, ...columns];
}

export function loadPresets(): ScoutPreset[] {
  try {
    const stored = window.localStorage.getItem(PRESET_STORAGE_KEY);
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(parsePreset)
      .filter((preset): preset is ScoutPreset => preset !== null)
      .slice(0, MAX_PRESETS);
  } catch {
    return [];
  }
}

export function savePresets(presets: readonly ScoutPreset[]): void {
  try {
    window.localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(presets.slice(0, MAX_PRESETS)));
  } catch {
    // Quota exceeded, or storage disabled. The preset is still applied in this session; it just
    // will not be there tomorrow.
  }
}

export interface PresetStore {
  presets: ScoutPreset[];
  /** Saving under an existing name replaces it — the same gesture readers expect from a save. */
  save: (preset: ScoutPreset) => void;
  remove: (name: string) => void;
}

export function useScoutPresets(): PresetStore {
  const [presets, setPresets] = useState<ScoutPreset[]>(loadPresets);

  const save = useCallback((preset: ScoutPreset) => {
    setPresets((current) => {
      const withoutSameName = current.filter(
        (existing) => existing.name.toLowerCase() !== preset.name.toLowerCase(),
      );
      const next = [...withoutSameName, preset].slice(-MAX_PRESETS);
      savePresets(next);
      return next;
    });
  }, []);

  const remove = useCallback((name: string) => {
    setPresets((current) => {
      const next = current.filter((preset) => preset.name !== name);
      savePresets(next);
      return next;
    });
  }, []);

  return { presets, save, remove };
}

/** A preset capturing nothing — the starting point a "save current view" builds on. */
export const BLANK_PRESET: ScoutPreset = {
  name: "",
  filters: EMPTY_FILTERS,
  columns: DEFAULT_VISIBLE_COLUMNS,
  sort: DEFAULT_SORT,
};
