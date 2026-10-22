import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { challengerWeek, modelsFixture, strategiesFixture } from "../../test/fixtures";
import type { Models } from "../../contract/types";

/** GW10 has no frozen decision yet: the published advice is the dry-run preview. */
const provisional: Models = {
  ...modelsFixture,
  provisional: true,
  models: modelsFixture.models.map((m) => ({ ...m, provisional: true })),
  gameweeks: modelsFixture.gameweeks.map((g, i, all) =>
    i === all.length - 1 ? { ...g, provisional: true, decided_at: null } : g,
  ),
};

describe("provisional (pre-window) advice", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("badges every model on the Models page with freeze-at-window hover text", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture, week_c1: challengerWeek, models: provisional } });
    renderApp("/models");
    const banner = await screen.findByTestId("models-provisional-note");
    expect(banner.textContent).toContain("GW10");
    for (const m of ["c1", "engine", "a", "a_odds"]) {
      const badge = screen.getByTestId(`summary-provisional-${m}`);
      expect(badge.textContent).toBe("Provisional");
      expect(badge.getAttribute("title")).toContain("freezes at the decision window");
    }
  });

  it("marks a provisional strategy in the selector", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture, week_c1: challengerWeek, models: provisional } });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    const c1 = screen.getByTestId("model-toggle-c1");
    expect(c1.getAttribute("aria-label")).toBe("Challenger (C1) (comparison) (provisional)");
    expect(c1.getAttribute("title")).toContain("freezes at the decision window");
    fireEvent.click(c1);
    expect(await screen.findByTestId("model-provisional")).toBeTruthy();
  });

  it("shows no badge once the frozen decision is published", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture, week_c1: challengerWeek, models: modelsFixture } });
    renderApp("/models");
    await screen.findByTestId("models-summary");
    expect(screen.queryByTestId("models-provisional-note")).toBeNull();
    expect(screen.queryByTestId("summary-provisional-engine")).toBeNull();
  });
});
