import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Fixtures } from "../../contract/types";
import { fixtureGrid } from "../../test/fixtures";
import { FixtureTicker } from "./FixtureTicker";

function renderTicker(fixtures: Fixtures = fixtureGrid) {
  return render(
    <MemoryRouter>
      <FixtureTicker fixtures={fixtures} />
    </MemoryRouter>,
  );
}

function rowOrder(): string[] {
  return screen.getAllByTestId("ticker-row").map((row) => row.getAttribute("data-team") ?? "");
}

function cell(team: string, gameweek: number) {
  return screen.getByTestId(`ticker-cell-${team}-GW${gameweek}`);
}

describe("FixtureTicker", () => {
  it("renders a row per club and a column per gameweek in the window", () => {
    renderTicker();
    expect(screen.getAllByTestId("ticker-row")).toHaveLength(fixtureGrid.teams.length);
    for (const gameweek of [1, 2, 3, 4]) {
      expect(screen.getByRole("columnheader", { name: `GW${gameweek}` })).toBeTruthy();
    }
  });

  it("shows both fixtures of a double gameweek, and marks the cell as a double", () => {
    renderTicker();
    const double = cell("ARS", 3);
    expect(double.getAttribute("data-double")).toBe("true");
    expect(within(double).getAllByTestId("ticker-fixture")).toHaveLength(2);
    expect(within(double).getByText("Double")).toBeTruthy();
    expect(within(double).getByText("MCI")).toBeTruthy();
    expect(within(double).getByText("AVL")).toBeTruthy();
  });

  it("marks a blank gameweek as blank rather than leaving the cell empty", () => {
    renderTicker();
    const blank = cell("MUN", 1);
    expect(blank.getAttribute("data-blank")).toBe("true");
    expect(within(blank).queryAllByTestId("ticker-fixture")).toHaveLength(0);
    expect(within(blank).getByText("Blank")).toBeTruthy();
  });

  it("names the venue and the difficulty in every fixture chip, never colour alone", () => {
    renderTicker();
    const chip = within(cell("ARS", 1)).getByTestId("ticker-fixture");
    expect(chip.textContent).toContain("BUR");
    expect(chip.textContent).toContain("(H)");
    // 1.6 overall, which is the easiest band on a 1-5 scale with a neutral of 3.
    expect(chip.textContent).toContain("1.6");
    expect(chip.getAttribute("data-band")).toBe("1");
  });

  it("puts the expected goals behind the score in the chip's title, so it can be checked", () => {
    renderTicker();
    const title = within(cell("ARS", 1)).getByTestId("ticker-fixture").getAttribute("title") ?? "";
    expect(title).toContain("2.40 goals for");
    expect(title).toContain("0.70 against");
    expect(title).toContain("Very easy");
  });

  it("sorts by run quality, easiest first by default", () => {
    renderTicker();
    expect(rowOrder()).toEqual(["MCI", "ARS", "MUN", "AVL", "BUR"]);
  });

  it("re-sorts when the sort control changes", () => {
    renderTicker();
    fireEvent.change(screen.getByTestId("ticker-sort"), { target: { value: "hardest" } });
    expect(rowOrder()[0]).toBe("BUR");
    fireEvent.change(screen.getByTestId("ticker-sort"), { target: { value: "team" } });
    expect(rowOrder()).toEqual(["ARS", "AVL", "BUR", "MCI", "MUN"]);
  });

  it("shows the blank count next to the mean, so an easy-looking run with no fixtures is visible", () => {
    renderTicker();
    // City top the easiest sort on 1.50 while playing twice in four. The counts are what stop that
    // being a lie by omission.
    expect(screen.getByTestId("ticker-mean-MCI").textContent).toContain("1.50");
    expect(screen.getByTestId("ticker-counts-MCI").textContent).toBe("2 fixtures, 2 blanks");
    expect(screen.getByTestId("ticker-counts-ARS").textContent).toBe("5 fixtures, 1 double");
  });

  it("switches which half of the scale is shaded and sorted on", () => {
    renderTicker();
    const arsenalHome = () => within(cell("ARS", 1)).getByTestId("ticker-fixture").textContent ?? "";
    expect(arsenalHome()).toContain("1.6");

    fireEvent.change(screen.getByTestId("ticker-metric"), { target: { value: "attack" } });
    expect(arsenalHome()).toContain("1.4");

    fireEvent.change(screen.getByTestId("ticker-metric"), { target: { value: "defence" } });
    expect(arsenalHome()).toContain("1.8");
  });

  it("trims the window when a shorter horizon is chosen, and recomputes the means", () => {
    renderTicker();
    fireEvent.change(screen.getByTestId("ticker-horizon"), { target: { value: "3" } });
    expect(screen.queryByRole("columnheader", { name: "GW4" })).toBeNull();
    // Arsenal over three: 1.6, 3.4, 1.9 and 3.0 — a different number from the full-window 2.46.
    expect(screen.getByTestId("ticker-mean-ARS").textContent).toContain("2.48");
    expect(screen.getByTestId("ticker-counts-ARS").textContent).toBe("4 fixtures, 1 double");
  });

  it("explains the scale and names the model that produced it", () => {
    renderTicker();
    expect(screen.getByTestId("ticker-legend").textContent).toContain("Very easy");
    expect(screen.getByTestId("ticker-legend").textContent).toContain("Very hard");
    const provenance = screen.getByTestId("ticker-provenance").textContent ?? "";
    expect(provenance).toContain("M2_team_strength");
    expect(provenance).toContain("league-average");
    expect(provenance).toContain("not");
  });

  it("says the grid is unrated rather than presenting neutral scores as ratings", () => {
    const unrated: Fixtures = {
      ...fixtureGrid,
      model: { ...fixtureGrid.model, teams_rated: 0 },
    };
    renderTicker(unrated);
    expect(screen.getByTestId("ticker-unrated").textContent).toContain("no ratings yet");
  });

  it("says so plainly when a club has no fixture at all in the window", () => {
    const absent: Fixtures = {
      ...fixtureGrid,
      teams: [
        {
          ...fixtureGrid.teams[0],
          gameweeks: fixtureGrid.teams[0].gameweeks.map((gw) => ({
            ...gw,
            is_double: false,
            is_blank: true,
            fixtures: [],
          })),
        },
      ],
    };
    renderTicker(absent);
    expect(screen.getByTestId("ticker-mean-ARS").textContent).toBe("no fixtures");
    expect(screen.getByTestId("ticker-counts-ARS").textContent).toBe("0 fixtures, 4 blanks");
  });
});

describe("FixtureTicker odds (ORC-15)", () => {
  const priced: Fixtures = {
    ...fixtureGrid,
    odds_next_check: "2026-08-19T06:00:00Z",
    teams: fixtureGrid.teams.map((t) =>
      t.team !== "ARS"
        ? t
        : {
            ...t,
            gameweeks: t.gameweeks.map((g, i) =>
              i !== 0
                ? g
                : {
                    ...g,
                    fixtures: g.fixtures.map((f) => ({
                      ...f,
                      odds: { win: 0.55, draw: 0.25, loss: 0.2, over_2_5: 0.63, as_of: "2026-08-18T09:00:00Z" },
                    })),
                  },
            ),
          },
    ),
  };

  it("shows the odds beside a priced fixture, readable by a screen reader", () => {
    renderTicker(priced);
    const odds = within(cell("ARS", 1)).getByTestId("ticker-odds");
    // Over 2.5 is visible text, not hover-only; the sentence is real (visually hidden) text, not an
    // aria-label on a role-less span (NFR-14).
    expect(odds.querySelector("[aria-hidden='true']")?.textContent).toBe("W 55% D 25% L 20% O2.5 63%");
    expect(odds.querySelector(".visually-hidden")?.textContent).toContain("over 2.5 goals 63%");
    expect(odds.getAttribute("aria-label")).toBeNull();
  });

  it("says when the next check is for fixtures without odds", () => {
    renderTicker(priced);
    expect(screen.getByTestId("ticker-odds-missing").textContent).toMatch(
      /^Odds not posted yet; next check at .+\.$/,
    );
    expect(within(cell("MUN", 2)).queryAllByTestId("ticker-odds")).toHaveLength(0);
  });
});
