import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { historyFixture } from "../history/history.test";
import { strategiesFixture } from "../../test/fixtures";
import type { Strategies } from "../../contract/types";
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

  it("has compare, summary, details and accuracy sections with one summary row per model", async () => {
    installFetchStub({ bodies: { models_history: historyFixture, xp_accuracy: accuracy, strategies: strategiesFixture } });
    renderApp("/models");
    const page = await screen.findByTestId("models-page");
    for (const s of ["compare", "summary", "details", "accuracy"]) expect(within(page).getByTestId(`models-jump-${s}`)).toBeTruthy();
    const rows = within(screen.getByTestId("models-summary")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "models-summary-c3",
      "models-summary-c1",
      "models-summary-engine",
      "models-summary-a",
      "models-summary-a_odds",
    ]);
    expect((await screen.findAllByText("0.910")).length).toBe(2);
    expect(screen.getByTestId("summary-mae-c1").textContent).toBe("0.910");
    expect(screen.getByTestId("summary-mae-a_odds").textContent).toBe("—");
    expect(screen.getByTestId("models-summary-a_odds").textContent).toContain("Currently duplicates A");
    expect(screen.getByTestId("accuracy-2025/26-c1").textContent).toBe("0.910");
    expect(screen.getByTestId("accuracy-2025/26").textContent).toContain("A + odds: no saved predictions");
  });

  it("reads the live season from the published data, and no frozen-era replay", async () => {
    const live = { season: "2026/27", kind: "prospective" as const, gameweeks: [], pooled_mae: { champion: 1.234 }, missing_models: {} };
    const spy = installFetchStub({
      bodies: { models_history: historyFixture, xp_accuracy: { ...accuracy, seasons: [...accuracy.seasons, live] }, strategies: strategiesFixture },
    });
    renderApp("/models");
    await screen.findByTestId("models-page");
    await screen.findAllByText("1.234");
    expect(screen.getByTestId("summary-live-mae-c3").textContent).toBe("1.234");
    expect(spy.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("replay"))).toEqual([]);
  });

  it("degrades when the static files are missing", async () => {
    installFetchStub({ missing: ["models_history", "xp_accuracy"] as never });
    renderApp("/models");
    expect(await screen.findByTestId("accuracy-absent")).toBeTruthy();
    expect(screen.getByTestId("summary-xi-champion").textContent).toBe("—");
  });

  it("says so on the 2025/26 tab when the models history is missing", async () => {
    installFetchStub({ missing: ["models_history"] as never });
    renderApp("/models/2025-26");
    expect(await screen.findByTestId("history-absent")).toBeTruthy();
  });

  it("labels experiments as not published and lists no retired strategy", async () => {
    const strategies: Strategies = {
      contract_version: 1,
      champion: "c3",
      strategies: [
        { ...strategiesFixture.strategies[0] },
        { ...strategiesFixture.strategies[1] },
        { ...strategiesFixture.strategies[2], id: "c3_f3", label: "Experiment (C3 F3)", role: "experiment", published: false },
        { ...strategiesFixture.strategies[2], id: "old_c2", label: "Old (C2)", role: "retired", published: false },
      ],
    };
    installFetchStub({ bodies: { models_history: historyFixture, xp_accuracy: accuracy, strategies } });
    renderApp("/models");
    await screen.findByTestId("models-page");
    const summary = screen.getByTestId("models-summary");
    expect(within(summary).getByTestId("models-summary-c3_f3").textContent).toContain("Experiment, not published.");
    expect(within(summary).getByTestId("models-summary-c3_f3").textContent).not.toContain("Comparison");
    expect(within(summary).queryByTestId("models-summary-old_c2")).toBeNull();
    expect(screen.getByTestId("models-detail-c3_f3")).toBeTruthy();
    expect(screen.queryByTestId("models-detail-old_c2")).toBeNull();
  });

  it("sends an old ?section= link for a part that moved to its new tab", async () => {
    installFetchStub({ bodies: { models_history: historyFixture, xp_accuracy: accuracy, strategies: strategiesFixture } });
    renderApp("/models?section=history");
    expect(await screen.findByTestId("model-history")).toBeTruthy();
    expect(screen.queryByTestId("models-page")).toBeNull();
  });
});
