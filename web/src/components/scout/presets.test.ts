import { beforeEach, describe, expect, it } from "vitest";
import { PRESET_STORAGE_KEY, loadPresets, savePresets, type ScoutPreset } from "./presets";
import { DEFAULT_VISIBLE_COLUMNS } from "./columns";
import { EMPTY_FILTERS, DEFAULT_SORT } from "./filters";

const preset: ScoutPreset = {
  name: "Cheap defenders",
  filters: { ...EMPTY_FILTERS, positions: ["DEF"], maxPrice: 4.5 },
  columns: ["name", "price", "xp_next"],
  sort: { key: "price", direction: "asc" },
};

describe("saved filter presets", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips a preset through storage", () => {
    savePresets([preset]);
    expect(loadPresets()).toEqual([preset]);
  });

  it("reports no presets when nothing has been saved", () => {
    expect(loadPresets()).toEqual([]);
  });

  // The rest of this block is DP-15 at its smallest scale: storage is shared with other tabs, other
  // builds and the reader's own browser settings, so everything in it is untrusted input. Each of
  // these degrades to "no saved presets", never to a thrown error on a page the reader is using.

  it("survives a stored value that is not JSON", () => {
    window.localStorage.setItem(PRESET_STORAGE_KEY, "{ not json");
    expect(loadPresets()).toEqual([]);
  });

  it("survives a stored value that is JSON but the wrong shape", () => {
    window.localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify({ nope: true }));
    expect(loadPresets()).toEqual([]);
  });

  it("drops entries with no usable name and keeps the rest", () => {
    window.localStorage.setItem(
      PRESET_STORAGE_KEY,
      JSON.stringify([{ ...preset, name: "  " }, preset, null, 42]),
    );
    expect(loadPresets().map((p) => p.name)).toEqual(["Cheap defenders"]);
  });

  it("drops column keys that no longer exist rather than rejecting the preset", () => {
    // A preset saved before a column was renamed should still apply, minus the column that went.
    window.localStorage.setItem(
      PRESET_STORAGE_KEY,
      JSON.stringify([{ ...preset, columns: ["name", "retired_column", "price"] }]),
    );
    expect(loadPresets()[0].columns).toEqual(["name", "price"]);
  });

  it("falls back to the default columns when a preset stores none", () => {
    window.localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify([{ ...preset, columns: [] }]));
    expect(loadPresets()[0].columns).toEqual(DEFAULT_VISIBLE_COLUMNS);
  });

  it("keeps the name column even if a preset was written without it", () => {
    window.localStorage.setItem(
      PRESET_STORAGE_KEY,
      JSON.stringify([{ ...preset, columns: ["price"] }]),
    );
    expect(loadPresets()[0].columns).toContain("name");
  });

  it("falls back to the default sort when the stored sort names an unknown column", () => {
    window.localStorage.setItem(
      PRESET_STORAGE_KEY,
      JSON.stringify([{ ...preset, sort: { key: "retired_column", direction: "asc" } }]),
    );
    expect(loadPresets()[0].sort).toEqual(DEFAULT_SORT);
  });

  it("coerces filter fields written with the wrong types", () => {
    window.localStorage.setItem(
      PRESET_STORAGE_KEY,
      JSON.stringify([
        { name: "Odd", filters: { search: 5, positions: "DEF", minPrice: "cheap" } },
      ]),
    );
    expect(loadPresets()[0].filters).toEqual(EMPTY_FILTERS);
  });
});
