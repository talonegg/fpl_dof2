import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Player } from "../../contract/types";
import { players as fixturePlayers } from "../../test/fixtures";
import { ScoutTable } from "./ScoutTable";

function renderScout(players: Player[] = fixturePlayers.players, ownedIds: Set<number> | null = null) {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ScoutTable players={players} ownedIds={ownedIds} />
    </MemoryRouter>,
  );
}

function rowNames(): string[] {
  return screen.getAllByTestId("player-row").map((row) => row.textContent ?? "");
}

beforeEach(() => {
  // Presets and the comparison selection both outlive a render.
  window.localStorage.clear();
});

describe("ScoutTable", () => {
  it("renders one row per player", () => {
    renderScout();
    expect(screen.getAllByTestId("player-row").length).toBe(fixturePlayers.players.length);
  });

  it("filters by position when a position chip is clicked", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("position-filter-FWD"));
    const rows = screen.getAllByTestId("player-row");
    expect(rows.length).toBe(1);
    expect(within(rows[0]).getByText("Watkins")).toBeTruthy();
  });

  it("selects more than one position at a time, and clears back to all", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("position-filter-FWD"));
    fireEvent.click(screen.getByTestId("position-filter-GKP"));
    expect(screen.getAllByTestId("player-row").length).toBe(2);
    fireEvent.click(screen.getByTestId("position-filter-ALL"));
    expect(screen.getAllByTestId("player-row").length).toBe(3);
  });

  it("filters by search text matching name or club", () => {
    renderScout();
    fireEvent.change(screen.getByTestId("player-search"), { target: { value: "mun" } });
    const rows = screen.getAllByTestId("player-row");
    expect(rows.length).toBe(1);
    expect(within(rows[0]).getByText("Mbeumo")).toBeTruthy();
  });

  it("says so plainly when nothing matches, rather than showing an empty box", () => {
    renderScout();
    fireEvent.change(screen.getByTestId("player-search"), { target: { value: "zzzz" } });
    expect(screen.queryAllByTestId("player-row").length).toBe(0);
    expect(screen.getByTestId("scout-count").textContent).toContain("no player matches");
  });

  it("reorders rows when a sortable column header is clicked, and toggles direction", () => {
    renderScout();
    // Default sort is xP next, best first: Watkins 4.52 > Raya 4.20 > Mbeumo 3.20.
    expect(rowNames()[0]).toContain("Watkins");

    fireEvent.click(screen.getByTestId("sort-price"));
    expect(rowNames()[2]).toContain("Raya");

    fireEvent.click(screen.getByTestId("sort-price"));
    expect(rowNames()[0]).toContain("Raya");
  });

  it("marks the sorted column for assistive technology", () => {
    renderScout();
    const header = screen.getByTestId("sort-xp_next").closest("[role='columnheader']");
    expect(header?.getAttribute("aria-sort")).toBe("descending");
  });

  it("shows the xP decomposition when a row is clicked", () => {
    renderScout();
    expect(screen.queryByTestId("decomposition")).toBeNull();
    fireEvent.click(screen.getAllByTestId("player-row")[0]);
    expect(screen.getByTestId("decomposition")).toBeTruthy();
  });

  it("never shows an expected-points mean without its uncertainty (Invariant 6)", () => {
    renderScout();
    const row = screen.getAllByTestId("player-row")[0];
    // Watkins: 4.517 ±2.033. The band is in the cell, and the range is spelled out in the tooltip.
    expect(row.textContent).toContain("4.52");
    expect(row.textContent).toContain("±2.0");

    const cell = within(row).getByText("4.52").closest("[role='cell']");
    expect(cell?.getAttribute("title")).toContain("plausibly");
  });

  it("only renders the rows in view, not the whole set", () => {
    // The NFR-04 claim, checked rather than assumed: ~700 players must not become ~700 rows in the
    // DOM. With an 800px notional viewport and 38px rows that is well under a hundred.
    const many = manyPlayers(700);
    renderScout(many);
    const rendered = screen.getAllByTestId("player-row").length;
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(100);
    expect(screen.getByTestId("scout-count").textContent).toContain("Showing 700 of 700");
  });
});

describe("ScoutTable column picker", () => {
  beforeEach(() => window.localStorage.clear());

  it("adds a component column and shows its values", () => {
    renderScout();
    expect(screen.queryByTestId("sort-component_bonus")).toBeNull();

    fireEvent.click(screen.getByTestId("scout-columns-toggle"));
    fireEvent.click(screen.getByTestId("scout-column-component_bonus"));

    expect(screen.getByTestId("sort-component_bonus")).toBeTruthy();
    expect(screen.getAllByTestId("player-row")[0].textContent).toContain("0.20");
  });

  it("removes a default column", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("scout-columns-toggle"));
    fireEvent.click(screen.getByTestId("scout-column-selected_by_percent"));
    expect(screen.queryByTestId("sort-selected_by_percent")).toBeNull();
  });

  it("will not let the name column be switched off", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("scout-columns-toggle"));
    const nameToggle = screen.getByTestId("scout-column-name") as HTMLInputElement;
    expect(nameToggle.disabled).toBe(true);
    expect(screen.getByTestId("sort-name")).toBeTruthy();
  });
});

describe("ScoutTable saved presets", () => {
  beforeEach(() => window.localStorage.clear());

  it("saves the current view, restores it, and deletes it again", () => {
    renderScout();

    fireEvent.change(screen.getByTestId("player-search"), { target: { value: "mbeumo" } });
    expect(screen.getAllByTestId("player-row").length).toBe(1);

    fireEvent.click(screen.getByTestId("scout-presets-toggle"));
    fireEvent.change(screen.getByTestId("scout-preset-name"), { target: { value: "Just Bryan" } });
    fireEvent.click(screen.getByTestId("scout-preset-save"));

    // Clear the filter: the table comes back, so applying the preset is a real change.
    fireEvent.change(screen.getByTestId("player-search"), { target: { value: "" } });
    expect(screen.getAllByTestId("player-row").length).toBe(3);

    fireEvent.click(screen.getByTestId("scout-preset-apply-Just Bryan"));
    expect(screen.getAllByTestId("player-row").length).toBe(1);

    fireEvent.click(screen.getByTestId("scout-preset-delete-Just Bryan"));
    expect(screen.queryByTestId("scout-preset-apply-Just Bryan")).toBeNull();
  });

  it("refuses to save a preset with no name", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("scout-presets-toggle"));
    expect((screen.getByTestId("scout-preset-save") as HTMLButtonElement).disabled).toBe(true);
  });

  it("restores presets saved in an earlier session", () => {
    const first = renderScout();
    fireEvent.click(screen.getByTestId("scout-presets-toggle"));
    fireEvent.change(screen.getByTestId("scout-preset-name"), { target: { value: "Keepers" } });
    fireEvent.click(screen.getByTestId("scout-preset-save"));
    first.unmount();

    renderScout();
    fireEvent.click(screen.getByTestId("scout-presets-toggle"));
    expect(screen.getByTestId("scout-preset-apply-Keepers")).toBeTruthy();
  });
});

describe("ScoutTable comparison selection", () => {
  beforeEach(() => window.localStorage.clear());

  it("needs two players before the comparison link appears", () => {
    renderScout();
    expect(screen.queryByTestId("scout-compare-bar")).toBeNull();

    fireEvent.click(screen.getByTestId("compare-1"));
    expect(screen.getByTestId("scout-compare-hint").textContent).toContain("1 more");
    expect(screen.queryByTestId("scout-compare-go")).toBeNull();

    fireEvent.click(screen.getByTestId("compare-2"));
    expect(screen.getByTestId("scout-compare-go")).toBeTruthy();
  });

  it("hands the selection to /compare in the URL, in the order it was chosen", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("compare-3"));
    fireEvent.click(screen.getByTestId("compare-1"));
    const link = screen.getByTestId("scout-compare-go") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/compare?compare=3,1");
  });

  it("stops at four rather than silently dropping a choice", () => {
    const many = manyPlayers(10);
    renderScout(many);
    for (const id of [1, 2, 3, 4]) fireEvent.click(screen.getByTestId(`compare-${id}`));
    expect((screen.getByTestId("compare-5") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId("compare-1") as HTMLInputElement).disabled).toBe(false);
  });

  it("clears the whole selection", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("compare-1"));
    fireEvent.click(screen.getByTestId("compare-2"));
    fireEvent.click(screen.getByTestId("scout-compare-clear"));
    expect(screen.queryByTestId("scout-compare-bar")).toBeNull();
  });

  it("keeps the selection when the table is left and returned to", () => {
    const first = renderScout();
    fireEvent.click(screen.getByTestId("compare-1"));
    fireEvent.click(screen.getByTestId("compare-2"));
    first.unmount();

    renderScout();
    expect((screen.getByTestId("scout-compare-go") as HTMLAnchorElement).getAttribute("href")).toBe(
      "/compare?compare=1,2",
    );
  });

  it("ticking a row does not also expand it", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("compare-1"));
    expect(screen.queryByTestId("decomposition")).toBeNull();
  });
});

describe("ScoutTable on a phone", () => {
  // jsdom has no `matchMedia`, so without this the narrow layout is never rendered by any test and
  // could rot unnoticed between Playwright passes.
  beforeEach(() => {
    window.localStorage.clear();
    stubMatchMedia(true);
  });

  afterEach(() => {
    Reflect.deleteProperty(window, "matchMedia");
  });

  it("renders cards rather than a wide grid, and drops the header", () => {
    renderScout();
    expect(screen.getAllByTestId("player-row").length).toBe(3);
    // No sortable header row: at 390px the sort belongs to the controls, not to a scrolled header.
    expect(screen.queryByTestId("sort-xp_next")).toBeNull();
    expect(screen.queryByTestId("scout-columns-toggle")).toBeNull();
  });

  it("keeps the forecast band on the card (Invariant 6)", () => {
    renderScout();
    const card = screen.getAllByTestId("player-row")[0];
    expect(card.textContent).toContain("4.52");
    expect(card.textContent).toContain("±2.0");
  });

  it("offers sorting as a control, since there is no header to click", () => {
    renderScout();
    expect(rowNames()[0]).toContain("Watkins");

    // "Sort by any column" is the requirement, not "on a laptop".
    fireEvent.change(screen.getByTestId("scout-sort-key"), { target: { value: "price" } });
    expect(rowNames()[2]).toContain("Raya");

    fireEvent.click(screen.getByTestId("scout-sort-direction"));
    expect(rowNames()[0]).toContain("Raya");
  });

  it("shows the compact column set and nothing else", () => {
    renderScout();
    const card = screen.getAllByTestId("player-row")[0];
    expect(card.textContent).toContain("£8.0m");
    // Ownership is a wide-layout column; on a card it would crowd out the forecast.
    expect(card.textContent).not.toContain("12.5%");
  });

  it("still selects players for comparison", () => {
    renderScout();
    fireEvent.click(screen.getByTestId("compare-1"));
    fireEvent.click(screen.getByTestId("compare-2"));
    expect((screen.getByTestId("scout-compare-go") as HTMLAnchorElement).getAttribute("href")).toBe(
      "/compare?compare=1,2",
    );
  });

  it("still expands a card into the decomposition", () => {
    renderScout();
    fireEvent.click(screen.getAllByTestId("player-row")[0]);
    expect(screen.getByTestId("decomposition")).toBeTruthy();
  });
});

describe("ScoutTable — owned players (E13-S2)", () => {
  it("shows no ownership badge or toggle when no team ID has been entered", () => {
    renderScout(fixturePlayers.players, null);
    expect(screen.queryByTestId("scout-my-squad-toggle")).toBeNull();
    expect(screen.queryByTestId(/^scout-owned-/)).toBeNull();
  });

  it("offers a toggle once an owned set is given, and filters down to it", () => {
    renderScout(fixturePlayers.players, new Set([1, 2]));
    expect(screen.getAllByTestId("player-row").length).toBe(3);

    fireEvent.click(screen.getByTestId("scout-my-squad-toggle"));
    const rows = screen.getAllByTestId("player-row");
    expect(rows.length).toBe(2);
    expect(rows.every((row) => row.className.includes("owned"))).toBe(true);

    fireEvent.click(screen.getByTestId("scout-my-squad-toggle"));
    expect(screen.getAllByTestId("player-row").length).toBe(3);
  });
});

function stubMatchMedia(matches: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

/** A synthetic set large enough to make virtualisation observable. */
function manyPlayers(count: number): Player[] {
  const template = fixturePlayers.players[0];
  return Array.from({ length: count }, (_, index) => ({
    ...template,
    id: index + 1,
    name: `Player ${index + 1}`,
    full_name: `Player Number ${index + 1}`,
    xp_next: 10 - (index % 100) / 10,
  }));
}
