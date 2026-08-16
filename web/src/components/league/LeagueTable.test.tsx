import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";

/**
 * The rendered comparison (E6-S10).
 *
 * The assertions worth having are the ones about what the table refuses to claim: a rival whose
 * squad was never fetched must not render as a rival who shares nobody, and an unpublished captain
 * must not render as an agreeing one. Both would be plausible-looking and wrong (DP-13).
 */
describe("LeagueTable", () => {
  beforeEach(() => {
    resetAppState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function renderLeague() {
    installFetchStub();
    renderApp("/league");
    await waitFor(() => expect(screen.getByTestId("league-table")).toBeTruthy());
  }

  it("shows the overlap and both differential directions for a compared rival", async () => {
    await renderLeague();
    const row = within(screen.getByTestId("league-row-100"));

    // Owner holds 1,2,3; rival 100 holds 1,2,4 — two shared, one each way.
    expect(row.getByRole("button", { name: /players shared/ }).textContent).toContain("2");
    expect(row.getByText("210")).toBeTruthy();
  });

  it("marks the owner's own row and does not compare it against itself", async () => {
    await renderLeague();
    const row = screen.getByTestId("league-row-200");

    expect(row.className).toContain("owner");
    expect(within(row).getByText("You")).toBeTruthy();
    expect(within(row).getByText(/measured against this row/)).toBeTruthy();
  });

  it("says a rival's squad was not published rather than showing a zero overlap", async () => {
    await renderLeague();
    const row = within(screen.getByTestId("league-row-300"));

    expect(row.getByText("Squad not published for this entry")).toBeTruthy();
    expect(row.queryByRole("button", { name: /players shared/ })).toBeNull();
  });

  it("flags a divergent captain in words, not only in colour", async () => {
    await renderLeague();
    // Owner captains Watkins; rival 100 captains Raya.
    const row = within(screen.getByTestId("league-row-100"));

    expect(row.getByText("Raya")).toBeTruthy();
    expect(row.getByText("differs")).toBeTruthy();
  });

  it("shows an unpublished captain as unknown rather than as agreement", async () => {
    await renderLeague();
    const row = within(screen.getByTestId("league-row-400"));

    expect(row.getByText("Not published")).toBeTruthy();
    expect(row.queryByText("same")).toBeNull();
    expect(row.queryByText("differs")).toBeNull();
  });

  it("names the shared and differential players on demand", async () => {
    await renderLeague();
    fireEvent.click(
      within(screen.getByTestId("league-row-100")).getByRole("button", {
        name: /players shared/,
      }),
    );

    const detail = within(screen.getByTestId("league-detail-100"));
    expect(detail.getByText(/Raya, Watkins/)).toBeTruthy();
    expect(detail.getByText("Only you have (1)")).toBeTruthy();
    expect(detail.getByText("Only they have (1)")).toBeTruthy();
  });

  it("re-orders by squad overlap without losing any row", async () => {
    await renderLeague();
    const rowCount = () => screen.getAllByTestId(/^league-row-/).length;
    const before = rowCount();

    fireEvent.click(screen.getByRole("button", { name: "By squad overlap" }));
    expect(rowCount()).toBe(before);
    expect(screen.getByRole("button", { name: "By squad overlap" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
  });
});
