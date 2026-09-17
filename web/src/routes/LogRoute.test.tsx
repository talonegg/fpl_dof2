import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";

/**
 * The season log (DL-69, E8 §3).
 *
 * The states worth spending assertions on are the ones where being wrong would flatter the tool
 * (DP-13): a gameweek decided without it must read "no advice recorded", not blank; an
 * unexplained divergence must be named as such rather than folded into "overridden"; and the
 * absent artefact must explain what would populate it rather than error.
 */
describe("LogRoute", () => {
  beforeEach(() => {
    resetAppState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("explains what populates the log when the artefact is absent", async () => {
    installFetchStub({ missing: ["log"] });
    renderApp("/log");
    await waitFor(() => expect(screen.getByTestId("log-absent")).toBeTruthy());
    expect(screen.getByTestId("log-absent").textContent).toContain("No season log yet");
  });

  it("renders one row per gameweek, newest first, with the summary", async () => {
    installFetchStub();
    renderApp("/log");
    await waitFor(() => expect(screen.getByTestId("log-table")).toBeTruthy());
    expect(screen.getByTestId("log-summary").textContent).toContain("3 gameweeks played");
    expect(screen.getByTestId("log-summary").textContent).toContain("171 points");
    const rows = screen.getAllByTestId(/^log-row-/);
    expect(rows.map((row) => row.getAttribute("data-testid"))).toEqual([
      "log-row-3",
      "log-row-2",
      "log-row-1",
    ]);
  });

  it("says plainly when a gameweek was decided without the tool", async () => {
    installFetchStub();
    renderApp("/log");
    await waitFor(() => expect(screen.getByTestId("log-table")).toBeTruthy());
    expect(screen.getByTestId("log-advised-1").textContent).toContain("no advice recorded");
    expect(screen.getByTestId("log-followed-1").textContent).toBe("—");
  });

  it("distinguishes followed advice from an unexplained divergence", async () => {
    installFetchStub();
    renderApp("/log");
    await waitFor(() => expect(screen.getByTestId("log-table")).toBeTruthy());
    expect(screen.getByTestId("log-followed-2").textContent).toContain("followed");
    expect(screen.getByTestId("log-followed-3").textContent).toContain("1 unexplained difference");
    const advised = within(screen.getByTestId("log-advised-2"));
    expect(advised.getByText(/captain Watkins/)).toBeTruthy();
  });

  it("reports a failed load rather than an empty page", async () => {
    installFetchStub({ failing: ["log"] });
    renderApp("/log");
    await waitFor(() => expect(screen.getByTestId("log-error")).toBeTruthy());
  });
});
