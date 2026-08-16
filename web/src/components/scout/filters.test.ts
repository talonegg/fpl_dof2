import { describe, expect, it } from "vitest";
import type { Player } from "../../contract/types";
import { players as fixturePlayers } from "../../test/fixtures";
import {
  DEFAULT_SORT,
  EMPTY_FILTERS,
  activeFilterCount,
  clubsIn,
  filterPlayers,
  isDefaultFilters,
  nextSort,
  priceBounds,
  sortPlayers,
} from "./filters";

const all = fixturePlayers.players;

function withOverrides(base: Player, overrides: Partial<Player>): Player {
  return { ...base, ...overrides };
}

function names(players: readonly Player[]): string[] {
  return players.map((p) => p.name);
}

describe("scout filtering", () => {
  it("treats an empty facet as no filter rather than no rows", () => {
    // The bug this pins: reading "nothing ticked" as "match nothing" empties the table on load.
    expect(filterPlayers(all, EMPTY_FILTERS).length).toBe(all.length);
    expect(isDefaultFilters(EMPTY_FILTERS)).toBe(true);
  });

  it("filters by position, and by more than one at once", () => {
    expect(names(filterPlayers(all, { ...EMPTY_FILTERS, positions: ["FWD"] }))).toEqual(["Watkins"]);
    expect(filterPlayers(all, { ...EMPTY_FILTERS, positions: ["FWD", "GKP"] }).length).toBe(2);
  });

  it("matches search against name, full name and club", () => {
    expect(names(filterPlayers(all, { ...EMPTY_FILTERS, search: "watk" }))).toEqual(["Watkins"]);
    expect(names(filterPlayers(all, { ...EMPTY_FILTERS, search: "Bryan" }))).toEqual(["Mbeumo"]);
    expect(names(filterPlayers(all, { ...EMPTY_FILTERS, search: "mun" }))).toEqual(["Mbeumo"]);
  });

  it("applies price bounds inclusively on both sides", () => {
    expect(filterPlayers(all, { ...EMPTY_FILTERS, minPrice: 8.0 }).length).toBe(2);
    expect(filterPlayers(all, { ...EMPTY_FILTERS, maxPrice: 6.0 }).length).toBe(1);
    expect(filterPlayers(all, { ...EMPTY_FILTERS, minPrice: 6.0, maxPrice: 8.0 }).length).toBe(3);
  });

  it("hides unavailable players only when asked to", () => {
    const injured = withOverrides(all[0], { id: 99, name: "Injured", status: "i" });
    const set = [...all, injured];
    expect(filterPlayers(set, EMPTY_FILTERS).length).toBe(4);
    expect(names(filterPlayers(set, { ...EMPTY_FILTERS, availableOnly: true }))).not.toContain(
      "Injured",
    );
  });

  it("filters by forecast confidence", () => {
    expect(names(filterPlayers(all, { ...EMPTY_FILTERS, confidences: ["medium"] }))).toEqual([
      "Mbeumo",
    ]);
  });

  it("combines facets conjunctively", () => {
    const result = filterPlayers(all, {
      ...EMPTY_FILTERS,
      positions: ["MID", "FWD"],
      maxPrice: 8.0,
      confidences: ["high"],
    });
    expect(names(result)).toEqual(["Watkins"]);
  });

  it("counts the facets that are actually narrowing anything", () => {
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0);
    expect(activeFilterCount({ ...EMPTY_FILTERS, search: "   " })).toBe(0);
    expect(activeFilterCount({ ...EMPTY_FILTERS, search: "salah", availableOnly: true })).toBe(2);
    // Both price bounds are one facet, not two.
    expect(activeFilterCount({ ...EMPTY_FILTERS, minPrice: 4, maxPrice: 9 })).toBe(1);
  });

  it("derives the club and price facets from the data rather than a hardcoded list", () => {
    expect(clubsIn(all)).toEqual(["ARS", "AVL", "MUN"]);
    expect(priceBounds(all)).toEqual({ min: 6, max: 8 });
  });
});

describe("scout sorting", () => {
  it("defaults to the forecast, best first", () => {
    expect(names(sortPlayers(all, DEFAULT_SORT))).toEqual(["Watkins", "Raya", "Mbeumo"]);
  });

  it("reverses on direction", () => {
    expect(names(sortPlayers(all, { key: "xp_next", direction: "asc" }))).toEqual([
      "Mbeumo",
      "Raya",
      "Watkins",
    ]);
  });

  it("breaks ties on id, so an unchanged filter never reshuffles the table", () => {
    const first = sortPlayers(all, { key: "price", direction: "desc" });
    const second = sortPlayers([...all].reverse(), { key: "price", direction: "desc" });
    expect(names(first)).toEqual(names(second));
  });

  it("sorts a missing value last in both directions", () => {
    // An unpublished ownership figure is not a zero, and floating it to the head of a descending
    // sort would say that it was.
    const unknown = withOverrides(all[0], {
      id: 99,
      name: "Unknown",
      selected_by_percent: undefined,
    });
    const set = [...all, unknown];
    expect(names(sortPlayers(set, { key: "selected_by_percent", direction: "desc" })).pop()).toBe(
      "Unknown",
    );
    expect(names(sortPlayers(set, { key: "selected_by_percent", direction: "asc" })).pop()).toBe(
      "Unknown",
    );
  });

  it("leaves the order alone for a column that does not exist", () => {
    expect(names(sortPlayers(all, { key: "nonsense", direction: "desc" }))).toEqual(names(all));
  });

  it("flips direction on the same column and picks a sensible one on a new column", () => {
    expect(nextSort({ key: "price", direction: "desc" }, "price")).toEqual({
      key: "price",
      direction: "asc",
    });
    // A number is most interesting at its largest; a name is most useful from A.
    expect(nextSort({ key: "price", direction: "desc" }, "xp_next").direction).toBe("desc");
    expect(nextSort({ key: "price", direction: "desc" }, "name").direction).toBe("asc");
  });
});
