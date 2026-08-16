import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";

/**
 * The three answers the route has to handle beyond "here is the grid".
 *
 * `fixtures.json` is fetched lazily and can legitimately be absent — a bundle deployed against an
 * older published data directory 404s on it — so "not published yet" must read as a state of the
 * data rather than as a broken page (DP-15).
 */
describe("FixturesRoute", () => {
  beforeEach(() => {
    resetAppState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the grid when the artefact is published", async () => {
    installFetchStub();
    renderApp("/fixtures");
    await waitFor(() => expect(screen.getByTestId("fixture-ticker")).toBeTruthy());
  });

  it("says the grid is not published yet rather than showing an empty one", async () => {
    installFetchStub({ missing: ["fixtures"] });
    renderApp("/fixtures");
    await waitFor(() => expect(screen.getByTestId("fixtures-absent")).toBeTruthy());
    expect(screen.queryByTestId("fixture-ticker")).toBeNull();
    expect(screen.getByTestId("fixtures-absent").textContent).toContain("next successful run");
  });

  it("reports a failed load and offers a retry that reaches the network again", async () => {
    installFetchStub({ failing: ["fixtures"] });
    renderApp("/fixtures");
    await waitFor(() => expect(screen.getByTestId("fixtures-error")).toBeTruthy());

    // The retry must drop the cached rejection, or it replays the same failure without a request.
    installFetchStub();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByTestId("fixture-ticker")).toBeTruthy());
  });
});
