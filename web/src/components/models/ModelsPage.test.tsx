import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { historyFixture } from "../history/history.test";
import type { XpAccuracy } from "./accuracy";

const accuracy: XpAccuracy = {
  contract_version: 1,
  metric: "all-player MAE",
  seasons: [
    {
      season: "2025/26",
      kind: "backtest",
      gameweeks: [
        { gameweek: 1, phase: "backtest", mae: { champion: 1.0, challenger: 0.9 } },
        { gameweek: 2, phase: "backtest", mae: { champion: 0.95, challenger: 0.92 } },
      ],
      pooled_mae: { champion: 0.975, challenger: 0.91 },
      missing_models: { a_odds: "no saved predictions" },
    },
  ],
};

describe("Models page", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("has summary, details, accuracy and history sections with one summary row per model", async () => {
    installFetchStub({ bodies: { models_history_2526: historyFixture, xp_accuracy: accuracy } });
    renderApp("/models");
    const page = await screen.findByTestId("models-page");
    for (const s of ["summary", "details", "accuracy", "hindsight", "history"]) expect(within(page).getByTestId(`models-jump-${s}`)).toBeTruthy();
    const rows = within(screen.getByTestId("models-summary")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "models-summary-champion",
      "models-summary-challenger",
      "models-summary-engine",
      "models-summary-a",
      "models-summary-a_odds",
    ]);
    expect((await screen.findAllByText("0.910")).length).toBe(2);
    expect(screen.getByTestId("summary-mae-challenger").textContent).toBe("0.910");
    expect(screen.getByTestId("summary-mae-a_odds").textContent).toBe("—");
    expect(screen.getByTestId("models-summary-a_odds").textContent).toContain("Currently duplicates A");
    expect(screen.getByTestId("accuracy-2025/26-challenger").textContent).toBe("0.910");
    expect(screen.getByTestId("accuracy-2025/26").textContent).toContain("A + odds: no saved predictions");
    expect(await screen.findByTestId("model-history")).toBeTruthy();
  });

  it("degrades when the static files are missing", async () => {
    installFetchStub({ missing: ["models_history_2526", "xp_accuracy", "models_history_2627_replay"] as never });
    renderApp("/models");
    expect(await screen.findByTestId("accuracy-absent")).toBeTruthy();
    expect(await screen.findByTestId("history-absent")).toBeTruthy();
    expect(screen.getByTestId("summary-xi-champion").textContent).toBe("—");
  });

  it("redirects the old /history tab to the Models page", async () => {
    installFetchStub({ bodies: { models_history_2526: historyFixture, xp_accuracy: accuracy } });
    renderApp("/history");
    expect(await screen.findByTestId("models-page")).toBeTruthy();
    expect(await screen.findByTestId("model-history")).toBeTruthy();
  });
});
