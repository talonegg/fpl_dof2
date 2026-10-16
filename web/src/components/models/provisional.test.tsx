import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { challengerWeek, modelsFixture } from "../../test/fixtures";
import type { Models } from "../../contract/types";
import { NOT_PUBLISHED_TITLE } from "./ModelSelector";

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
    installFetchStub({ bodies: { week_challenger: challengerWeek, models: provisional } });
    renderApp("/models");
    const banner = await screen.findByTestId("models-provisional-note");
    expect(banner.textContent).toContain("GW10");
    for (const m of ["challenger", "engine", "a", "a_odds"]) {
      const badge = screen.getByTestId(`summary-provisional-${m}`);
      expect(badge.textContent).toBe("Provisional");
      expect(badge.getAttribute("title")).toContain("freezes at the decision window");
    }
  });

  it("marks provisional models in the selector, and explains a missing one", async () => {
    const oneMissing: Models = structuredClone(provisional);
    delete (oneMissing.gameweeks[3].advice as Record<string, unknown>).a_odds;
    installFetchStub({ bodies: { week_challenger: challengerWeek, models: oneMissing } });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    const engine = screen.getByTestId("model-toggle-engine");
    expect(engine.getAttribute("aria-label")).toBe("Engine (comparison) (provisional)");
    expect(engine.getAttribute("title")).toContain("freezes at the decision window");
    expect(screen.getByTestId("model-toggle-a_odds").getAttribute("title")).toBe(NOT_PUBLISHED_TITLE);
    fireEvent.click(engine);
    expect(await screen.findByTestId("model-provisional")).toBeTruthy();
  });

  it("shows no badge once the frozen decision is published", async () => {
    installFetchStub({ bodies: { week_challenger: challengerWeek, models: modelsFixture } });
    renderApp("/models");
    await screen.findByTestId("models-summary");
    expect(screen.queryByTestId("models-provisional-note")).toBeNull();
    expect(screen.queryByTestId("summary-provisional-engine")).toBeNull();
  });
});
