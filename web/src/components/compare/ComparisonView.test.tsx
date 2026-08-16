import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { players as fixturePlayers } from "../../test/fixtures";
import { resetTrendCaches } from "../../data/api";
import { history } from "../player/testFixtures";
import { ComparisonView } from "./ComparisonView";

/**
 * `history.json` is fetched lazily on this route (DL-37), so every test here needs it served.
 * Local to this suite for the same reason the player suite keeps its own: the shared stub in
 * `test/render.tsx` covers the shell's eager load and deliberately rejects anything else.
 */
function installStub(options: { missing?: boolean } = {}) {
  const spy = vi.fn((input: RequestInfo | URL) => {
    const name = String(input).split("/").pop()?.replace(".json", "") ?? "";
    if (name === "history") {
      if (options.missing) return Promise.resolve(new Response(null, { status: 404 }));
      return Promise.resolve(
        new Response(JSON.stringify(history), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.reject(new Error(`Unexpected fetch: ${String(input)}`));
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

beforeEach(() => {
  resetTrendCaches();
  installStub();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderCompare(search = "") {
  return render(
    <MemoryRouter
      initialEntries={[`/compare${search}`]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route
          path="/compare"
          element={
            <ComparisonView allPlayers={fixturePlayers.players} horizonGameweeks={6} />
          }
        />
        <Route path="/scout" element={<div data-testid="scout-stub" />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Column headers, in the order they are rendered. The corner cell is excluded. */
function columnNames(): string[] {
  const heads = screen.getByTestId("compare-table").querySelectorAll("thead .compare-player-head");
  return [...heads].map((head) => head.querySelector(".compare-player-name")?.textContent ?? "");
}

describe("ComparisonView with a valid selection", () => {
  it("puts the selected players side by side", () => {
    renderCompare("?compare=1,2");
    expect(screen.getByTestId("compare-table")).toBeTruthy();
    expect(columnNames()).toEqual(["Raya", "Watkins"]);
  });

  it("keeps the order the players were chosen in", () => {
    renderCompare("?compare=2,1");
    expect(columnNames()).toEqual(["Watkins", "Raya"]);
  });

  it("compares more than two", () => {
    // The contract allows four; the fixture publishes three, which is the ceiling here.
    renderCompare("?compare=1,2,3");
    expect(columnNames()).toEqual(["Raya", "Watkins", "Mbeumo"]);
  });

  it("shows the verdict, and its caveats", () => {
    renderCompare("?compare=1,2");
    expect(screen.getByTestId("compare-verdict")).toBeTruthy();
    expect(screen.getByTestId("compare-verdict-forecast_next")).toBeTruthy();
    expect(screen.getByTestId("compare-caveats")).toBeTruthy();
  });

  it("marks a verdict line that the numbers do not settle, rather than picking a winner", () => {
    renderCompare("?compare=1,2");
    const next = screen.getByTestId("compare-verdict-forecast_next");
    expect(next.getAttribute("data-decisive")).toBe("false");
    expect(next.textContent).toContain("too close to call");
  });

  it("never shows an expected-points mean without its uncertainty (Invariant 6)", () => {
    renderCompare("?compare=1,2");
    const row = screen.getByTestId("compare-row-xp_next");
    expect(row.textContent).toContain("4.20");
    expect(row.textContent).toContain("±1.9");
    expect(row.textContent).toContain("4.52");
    expect(row.textContent).toContain("±2.0");

    const cells = row.querySelectorAll(".compare-cell");
    for (const cell of cells) {
      expect(cell.getAttribute("title")).toContain("plausibly");
    }
  });

  it("badges the leader on price but not on a forecast whose bands overlap", () => {
    renderCompare("?compare=1,2");
    expect(within(screen.getByTestId("compare-row-price")).getByText("best")).toBeTruthy();
    expect(within(screen.getByTestId("compare-row-xp_next")).queryByText("best")).toBeNull();
  });

  it("links each column through to the player's own page", () => {
    renderCompare("?compare=1,2");
    // Scoped to the table: the trend charts below now label the same player on their axes.
    const link = within(screen.getByTestId("compare-table")).getByText("Watkins").closest("a");
    expect(link?.getAttribute("href")).toBe("/player/2");
  });

  it("offers the way back to the scout table", () => {
    renderCompare("?compare=1,2");
    expect(screen.getByTestId("compare-change").getAttribute("href")).toBe("/scout");
  });

  it("shows the trend and forecast section E6-S5 filled in", () => {
    renderCompare("?compare=1,2");
    expect(screen.getByTestId("compare-trends")).toBeTruthy();
    expect(screen.getByTestId("compare-chart-xp-next")).toBeTruthy();
  });

  it("still leaves a named slot for the fixture run", () => {
    // E6-S8 fills this. Until it does it says so, rather than inventing a difficulty run (DP-09).
    renderCompare("?compare=1,2");
    expect(screen.getByTestId("compare-pending").textContent).toContain("E6-S8");
  });
});

describe("ComparisonView editing the selection", () => {
  it("removes a player by navigating, so the URL stays the record", () => {
    renderCompare("?compare=1,2,3");
    fireEvent.click(screen.getByTestId("compare-remove-2"));
    expect(columnNames()).toEqual(["Raya", "Mbeumo"]);
  });

  it("will not remove below two, and says why", () => {
    renderCompare("?compare=1,2");
    const button = screen.getByTestId("compare-remove-1") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("title")).toContain("at least 2 players");
  });
});

describe("ComparisonView with nothing to compare", () => {
  it("explains how to get here when the route is opened directly", () => {
    renderCompare();
    expect(screen.getByTestId("compare-empty")).toBeTruthy();
    expect(screen.queryByTestId("compare-table")).toBeNull();
    expect(screen.getByTestId("compare-empty-scout").getAttribute("href")).toBe("/scout");
  });

  it("says so when only one of the ids resolves", () => {
    renderCompare("?compare=1");
    expect(screen.getByTestId("compare-empty")).toBeTruthy();
    expect(screen.getByTestId("compare-empty-resolved").textContent).toContain("Raya");
  });

  it("names the ids that are not in this publication", () => {
    renderCompare("?compare=998,999");
    expect(screen.getByTestId("compare-empty-missing").textContent).toContain("998, 999");
  });

  it("survives a URL that is not a selection at all", () => {
    // `parseCompareIds` never throws; the view must not either (DP-15).
    renderCompare("?compare=not,a,number&other=1");
    expect(screen.getByTestId("compare-empty")).toBeTruthy();
  });

  it("compares what it can when only some ids are unknown, and reports the rest", () => {
    renderCompare("?compare=1,2,999");
    expect(columnNames()).toEqual(["Raya", "Watkins"]);
    expect(screen.getByTestId("compare-missing").textContent).toContain("999");
  });
});
