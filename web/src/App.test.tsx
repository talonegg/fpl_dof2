import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "./test/render";
import { IDENTITY_STORAGE_KEY } from "./components/settings/identity";

describe("App shell", () => {
  beforeEach(() => {
    resetAppState();
    installFetchStub();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the dashboard route with the week, plan, squad and bench", async () => {
    renderApp("/");

    await waitFor(() => expect(screen.getByTestId("header")).toBeTruthy());

    expect(screen.getByTestId("app-nav")).toBeTruthy();
    expect(screen.getByTestId("week-deadline")).toBeTruthy();
    expect(screen.getByTestId("squad-pitch")).toBeTruthy();
    expect(screen.getByTestId("bench")).toBeTruthy();

    // Quiet model warning for an "informative" price dependence.
    expect(screen.getByTestId("model-warning").className).toContain("model-warning-quiet");
  });

  it("renders the scout route with the player table", async () => {
    renderApp("/scout");

    await waitFor(() => expect(screen.getByTestId("player-table")).toBeTruthy());
    expect(screen.queryByTestId("squad-pitch")).toBeNull();
  });

  it("offers a 'my squad' filter on scout once a team ID is entered in Settings (E13-S2)", async () => {
    window.localStorage.setItem(
      IDENTITY_STORAGE_KEY,
      JSON.stringify({ teamId: 1234567, leagueId: null }),
    );
    renderApp("/scout");

    await waitFor(() => expect(screen.getByTestId("player-table")).toBeTruthy());
    // Fixture squad.json holds players 1, 2 and 3 — the whole fixture pool.
    fireEvent.click(screen.getByTestId("scout-my-squad-toggle"));
    expect(screen.getAllByTestId("player-row").length).toBe(3);
  });

  it("names whose squad this is against the team ID entered in Settings (E13-S2)", async () => {
    window.localStorage.setItem(
      IDENTITY_STORAGE_KEY,
      JSON.stringify({ teamId: 1234567, leagueId: null }),
    );
    renderApp("/squad");

    await waitFor(() => expect(screen.getByTestId("squad-pitch")).toBeTruthy());
    // Fixture week.squad_state.entry_id is 1234567 — the same id, so it is confirmed, not disputed.
    expect(screen.getByTestId("squad-owned-match")).toBeTruthy();
    expect(screen.queryByTestId("squad-owned-mismatch")).toBeNull();
  });

  it("says plainly when the published squad belongs to a different entry than the one entered", async () => {
    window.localStorage.setItem(
      IDENTITY_STORAGE_KEY,
      JSON.stringify({ teamId: 7654321, leagueId: null }),
    );
    renderApp("/squad");

    await waitFor(() => expect(screen.getByTestId("squad-pitch")).toBeTruthy());
    const note = screen.getByTestId("squad-owned-mismatch");
    expect(note.textContent).toContain("1234567");
    expect(note.textContent).toContain("7654321");
  });

  it("renders the comparison route from the ids in the URL", async () => {
    renderApp("/compare?compare=1,2");
    await waitFor(() => expect(screen.getByTestId("compare-table")).toBeTruthy());
    expect(screen.getByTestId("compare-verdict")).toBeTruthy();
  });

  it("explains how to get to a comparison when /compare is opened with no selection", async () => {
    renderApp("/compare");
    await waitFor(() => expect(screen.getByTestId("compare-empty")).toBeTruthy());
    expect(screen.getByTestId("compare-empty-scout")).toBeTruthy();
  });

  it("renders the fixture ticker on its own route", async () => {
    renderApp("/fixtures");
    await waitFor(() => expect(screen.getByTestId("fixture-ticker")).toBeTruthy());
    expect(screen.getAllByTestId("ticker-row").length).toBeGreaterThan(0);
  });

  it("renders the squad route with the pitch, the builder and the plan timeline", async () => {
    renderApp("/squad");
    await waitFor(() => expect(screen.getByTestId("squad-pitch")).toBeTruthy());
    expect(screen.getByTestId("squad-builder")).toBeTruthy();
    expect(screen.getByTestId("plan-timeline")).toBeTruthy();
  });

  it("resolves a player detail route from its id parameter", async () => {
    renderApp("/player/2");
    await waitFor(() => expect(screen.getByTestId("player-detail")).toBeTruthy());
    expect(screen.getByText("Ollie Watkins")).toBeTruthy();
  });

  it("says so plainly when the player id is not in the published data", async () => {
    renderApp("/player/999");
    await waitFor(() => expect(screen.getByTestId("player-not-found")).toBeTruthy());
  });

  it("shows a not-found view for an unknown route rather than a blank page", async () => {
    renderApp("/nonsense");
    await waitFor(() => expect(screen.getByTestId("not-found")).toBeTruthy());
  });

  it("navigating between routes does not re-fetch the published data", async () => {
    // The caching claim in DL-35, checked rather than assumed. Six artefacts, one request each,
    // however many times the reader moves between views.
    const fetchSpy = installFetchStub();
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("squad-pitch")).toBeTruthy());
    const afterFirstLoad = fetchSpy.mock.calls.length;
    expect(afterFirstLoad).toBe(6);

    fireEvent.click(screen.getByTestId("nav-scout"));
    await waitFor(() => expect(screen.getByTestId("player-table")).toBeTruthy());
    fireEvent.click(screen.getByTestId("nav-dashboard"));
    await waitFor(() => expect(screen.getByTestId("squad-pitch")).toBeTruthy());

    expect(fetchSpy.mock.calls.length).toBe(afterFirstLoad);
  });
});

describe("App shell without a weekly recommendation", () => {
  beforeEach(() => {
    resetAppState();
    // 404 is the normal preseason answer, not a failure (DL-20).
    installFetchStub({ missing: ["week", "plan"] });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("still renders the squad when week.json is absent", async () => {
    // DP-15. A missing weekly panel must degrade to no panel, not to an error page — the forecast
    // and the squad are still worth looking at.
    renderApp("/");

    await waitFor(() => expect(screen.getByTestId("header")).toBeTruthy());
    expect(screen.getByTestId("squad-pitch")).toBeTruthy();
    expect(screen.queryByTestId("week-deadline")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("App shell when the data cannot be loaded", () => {
  beforeEach(() => {
    resetAppState();
    installFetchStub({ failing: ["players"] });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the navigation on screen and offers a retry", async () => {
    renderApp("/");

    await waitFor(() => expect(screen.getByTestId("app-error")).toBeTruthy());
    // Degrade, never break: a failed load must not strand the reader on a dead page (DP-15).
    expect(screen.getByTestId("app-nav")).toBeTruthy();

    // The failure is not cached, so a retry genuinely retries.
    installFetchStub();
    fireEvent.click(screen.getByText("Try again"));
    await waitFor(() => expect(screen.getByTestId("squad-pitch")).toBeTruthy());
  });
});
