import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { preseasonLeague } from "../test/fixtures";
import { installFetchStub, renderApp, resetAppState } from "../test/render";

/**
 * `/league` (E6-S10).
 *
 * The state exercised hardest here is **absent**, because it is the state a working installation is
 * actually in: no `league_id` is configured by default, so the pipeline publishes no `league.json`
 * at all. That page has to say what is missing and what setting it up would give you — a blank
 * panel would read as a broken view rather than an unconfigured one (DP-15).
 */
describe("LeagueRoute", () => {
  beforeEach(() => {
    resetAppState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("explains that no mini-league is configured when the artefact is absent", async () => {
    installFetchStub({ missing: ["league"] });
    renderApp("/league");

    await waitFor(() => expect(screen.getByTestId("league-absent")).toBeTruthy());
    const panel = screen.getByTestId("league-absent");
    expect(panel.textContent).toContain("No mini-league configured");
    // It must say what to set, not merely that something is unset.
    expect(panel.textContent).toContain("entry.league_id");
    // And it must name what configuring one buys, or it is just an error message.
    expect(panel.textContent).toContain("captained");
    expect(screen.queryByTestId("league-table")).toBeNull();
  });

  it("renders the standings and the comparison when a league is published", async () => {
    installFetchStub();
    renderApp("/league");

    await waitFor(() => expect(screen.getByTestId("league-table")).toBeTruthy());
    expect(screen.getByText("The Sunday League")).toBeTruthy();
    expect(screen.getByTestId("league-row-100")).toBeTruthy();
    expect(screen.getByTestId("league-anchor").textContent).toContain("against your own squad");
  });

  it("says why there is no comparison before a gameweek has been scored", async () => {
    installFetchStub({ bodies: { league: preseasonLeague } });
    renderApp("/league");

    await waitFor(() => expect(screen.getByTestId("league-table")).toBeTruthy());
    // The table still renders — a league table is worth reading on its own — but the comparison
    // columns are gone and the reason is on the page rather than left to be inferred.
    expect(screen.getByTestId("league-anchor").textContent).toContain("No gameweek has been scored");
    expect(screen.queryByText("Shared")).toBeNull();
  });

  it("reports a failed load and offers a retry that reaches the network again", async () => {
    installFetchStub({ failing: ["league"] });
    renderApp("/league");

    await waitFor(() => expect(screen.getByTestId("league-error")).toBeTruthy());

    installFetchStub();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByTestId("league-table")).toBeTruthy());
  });

  it("is reachable from the main navigation", async () => {
    installFetchStub({ missing: ["league"] });
    renderApp("/");

    await waitFor(() => expect(screen.getByTestId("app-nav")).toBeTruthy());
    fireEvent.click(screen.getByTestId("nav-mini-league"));
    await waitFor(() => expect(screen.getByTestId("league-absent")).toBeTruthy());
  });
});
