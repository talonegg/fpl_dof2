import { describe, expect, it } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { PlayerTable } from "./PlayerTable";
import { players as fixturePlayers } from "../test/fixtures";

function setup() {
  return render(<PlayerTable players={fixturePlayers.players} />);
}

describe("PlayerTable", () => {
  it("renders one row per player initially", () => {
    setup();
    const rows = screen.getAllByTestId("player-row");
    expect(rows.length).toBe(fixturePlayers.players.length);
  });

  it("filters by position when a position filter button is clicked", () => {
    setup();
    fireEvent.click(screen.getByTestId("position-filter-FWD"));
    const rows = screen.getAllByTestId("player-row");
    expect(rows.length).toBe(1);
    expect(within(rows[0]).getByText("Watkins")).toBeTruthy();
  });

  it("filters by search text matching name or club", () => {
    setup();
    const input = screen.getByTestId("player-search") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "mun" } });
    const rows = screen.getAllByTestId("player-row");
    expect(rows.length).toBe(1);
    expect(within(rows[0]).getByText("Mbeumo")).toBeTruthy();
  });

  it("reorders rows when a sortable column header is clicked", () => {
    setup();
    // default sort is xp_next desc: Watkins (4.517) > Raya (4.199) > Mbeumo (3.2)
    let names = screen.getAllByTestId("player-row").map((r) => r.textContent ?? "");
    expect(names[0]).toContain("Watkins");

    // click price header: toggles to desc first -> Watkins/Mbeumo (8.0) tie, then Raya (6.0)
    fireEvent.click(screen.getByTestId("sort-price"));
    names = screen.getAllByTestId("player-row").map((r) => r.textContent ?? "");
    expect(names[names.length - 1]).toContain("Raya");

    // click again to reverse to ascending -> Raya (6.0) first
    fireEvent.click(screen.getByTestId("sort-price"));
    names = screen.getAllByTestId("player-row").map((r) => r.textContent ?? "");
    expect(names[0]).toContain("Raya");
  });

  it("shows the xP decomposition panel when a player row is clicked", () => {
    setup();
    expect(screen.queryByTestId("decomposition")).toBeNull();
    const rows = screen.getAllByTestId("player-row");
    fireEvent.click(rows[0]);
    expect(screen.getByTestId("decomposition")).toBeTruthy();
  });
});
