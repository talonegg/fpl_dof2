import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import { IDENTITY_STORAGE_KEY } from "../components/settings/identity";

/**
 * `/settings` (E13-S2, E13-S3, DL-44).
 *
 * The behaviour worth protecting: nothing entered here is ever fetched anywhere (Invariant 8) — it
 * only ever compares against `league.json`'s own published id, and it says so plainly when the two
 * disagree rather than pretending the entered league is what is shown (DP-09, DP-15).
 */
describe("SettingsRoute", () => {
  beforeEach(() => {
    resetAppState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts with nothing entered and nothing in storage", async () => {
    installFetchStub();
    renderApp("/settings");

    await waitFor(() => expect(screen.getByTestId("settings-view")).toBeTruthy());
    expect(screen.getByTestId("settings-team-id")).toHaveProperty("value", "");
    expect(screen.getByTestId("settings-league-id")).toHaveProperty("value", "");
    expect(window.localStorage.getItem(IDENTITY_STORAGE_KEY)).toBeNull();
  });

  it("persists a typed team ID to localStorage", async () => {
    installFetchStub();
    renderApp("/settings");

    await waitFor(() => expect(screen.getByTestId("settings-view")).toBeTruthy());
    fireEvent.change(screen.getByTestId("settings-team-id"), { target: { value: "1234567" } });

    await waitFor(() =>
      expect(JSON.parse(window.localStorage.getItem(IDENTITY_STORAGE_KEY) ?? "{}")).toEqual({
        teamId: 1234567,
        leagueId: null,
      }),
    );
    expect(screen.getByTestId("settings-copy-team-id").textContent).toBe("1234567");
  });

  it("says nothing about a mismatch when the entered league ID matches what was published", async () => {
    installFetchStub();
    renderApp("/settings");

    await waitFor(() => expect(screen.getByTestId("settings-view")).toBeTruthy());
    fireEvent.change(screen.getByTestId("settings-league-id"), { target: { value: "314159" } });

    await waitFor(() =>
      expect(screen.getByTestId("settings-league-id")).toHaveProperty("value", "314159"),
    );
    expect(screen.queryByTestId("settings-league-mismatch")).toBeNull();
  });

  it("states plainly when the entered league ID does not match the published league", async () => {
    installFetchStub();
    renderApp("/settings");

    await waitFor(() => expect(screen.getByTestId("settings-view")).toBeTruthy());
    fireEvent.change(screen.getByTestId("settings-league-id"), { target: { value: "999999" } });

    await waitFor(() => expect(screen.getByTestId("settings-league-mismatch")).toBeTruthy());
    const note = screen.getByTestId("settings-league-mismatch");
    expect(note.textContent).toContain("The Sunday League");
    expect(note.textContent).toContain("314159");
  });

  it("says there is nothing to match against when no league is published", async () => {
    installFetchStub({ missing: ["league"] });
    renderApp("/settings");

    await waitFor(() => expect(screen.getByTestId("settings-view")).toBeTruthy());
    fireEvent.change(screen.getByTestId("settings-league-id"), { target: { value: "314159" } });

    await waitFor(() => expect(screen.getByTestId("settings-league-absent")).toBeTruthy());
  });

  it("clears both ids and the storage key", async () => {
    installFetchStub();
    renderApp("/settings");

    await waitFor(() => expect(screen.getByTestId("settings-view")).toBeTruthy());
    fireEvent.change(screen.getByTestId("settings-team-id"), { target: { value: "1234567" } });
    await waitFor(() => expect(window.localStorage.getItem(IDENTITY_STORAGE_KEY)).not.toBeNull());

    fireEvent.click(screen.getByTestId("settings-clear"));
    await waitFor(() =>
      expect(screen.getByTestId("settings-team-id")).toHaveProperty("value", ""),
    );
    expect(JSON.parse(window.localStorage.getItem(IDENTITY_STORAGE_KEY) ?? "{}")).toEqual({
      teamId: null,
      leagueId: null,
    });
  });

  it("composes the workflow dispatch link with no token or personal data in it", async () => {
    installFetchStub();
    renderApp("/settings");

    await waitFor(() => expect(screen.getByTestId("settings-view")).toBeTruthy());
    const link = screen.getByTestId("settings-dispatch-link") as HTMLAnchorElement;
    expect(link.href).toBe("https://github.com/talonegg/fpl_dof2/actions/workflows/pipeline.yml");
    expect(link.href).not.toContain("token");
  });

  it("is reachable from the main navigation", async () => {
    installFetchStub();
    renderApp("/");

    await waitFor(() => expect(screen.getByTestId("app-nav")).toBeTruthy());
    fireEvent.click(screen.getByTestId("nav-settings"));
    await waitFor(() => expect(screen.getByTestId("settings-view")).toBeTruthy());
  });
});
