import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { HindsightSection } from "./HindsightSection";
import { mockLog, mockPlayers } from "./HindsightSection.fixtures";

describe("HindsightSection", () => {
  it("renders empty state when log is absent or has no finished gameweeks", () => {
    render(<HindsightSection log={null} players={null} status="absent" />);
    expect(screen.getByTestId("hindsight-empty")).toBeTruthy();
    expect(screen.getByText(/Hindsight review and oracle analysis will appear here/)).toBeTruthy();
  });

  it("renders prior-week selector pills and defaults to latest completed gameweek", () => {
    render(<HindsightSection log={mockLog} players={mockPlayers} status="ready" />);

    // Selector pills exist for GW5 and GW6
    expect(screen.getByTestId("gw-pill-5")).toBeTruthy();
    const pill6 = screen.getByTestId("gw-pill-6");
    expect(pill6).toBeTruthy();
    expect(pill6.getAttribute("aria-checked")).toBe("true");

    // Leaderboard shows rankings for default active GW6
    expect(screen.getByText("Model Recommendation Performance — GW6")).toBeTruthy();
    expect(screen.getByTestId("rank-row-c1")).toBeTruthy();
    expect(screen.getByTestId("rank-row-xp_v1")).toBeTruthy();

    // Oracle card displays ceiling points
    expect(screen.getByTestId("oracle-ceiling-pts").textContent).toBe("84 pts");
    expect(screen.getByText("Raya (£5.5m)")).toBeTruthy();
    expect(screen.getByText("Watkins (£9.0m)")).toBeTruthy();

    // Diagnostics list shows the blindspot tag
    expect(screen.getByText("model blindspot")).toBeTruthy();
    expect(screen.getByText("Watkins")).toBeTruthy();
  });

  it("switches gameweek when a different prior-week pill is clicked", () => {
    render(<HindsightSection log={mockLog} players={mockPlayers} status="ready" />);

    // Click GW5 pill
    fireEvent.click(screen.getByTestId("gw-pill-5"));

    expect(screen.getByTestId("gw-pill-5").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("Model Recommendation Performance — GW5")).toBeTruthy();
    expect(screen.getByTestId("oracle-ceiling-pts").textContent).toBe("60 pts");
  });
});
