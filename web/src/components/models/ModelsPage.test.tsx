import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { historyFixture } from "../history/history.test";
import { challengerWeek, modelsFixture, strategiesFixture } from "../../test/fixtures";
import type { Models, Strategies } from "../../contract/types";
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
    {
      season: "2026/27",
      kind: "prospective",
      gameweeks: [{ gameweek: 7, phase: "prospective", mae: { champion: 1.2, challenger: 1.3 } }],
      pooled_mae: { champion: 1.234, challenger: 1.3 },
      missing_models: {},
    },
  ],
};

/** GW10's engine had no advice: a source it needs was missing. */
const engineOut: Models = {
  ...modelsFixture,
  gameweeks: modelsFixture.gameweeks.map((g, i, all) =>
    i === all.length - 1
      ? { ...g, availability: { ...g.availability, engine: { available: false, reason: "odds not posted" } } }
      : g,
  ),
};

const bodies = { models_history: historyFixture, xp_accuracy: accuracy, strategies: strategiesFixture, week_c1: challengerWeek };

describe("Models", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("outlines every model from the registry: description, role, plan and whether it advises now", async () => {
    installFetchStub({ bodies: { ...bodies, models: engineOut } });
    renderApp("/models");
    const outline = await screen.findByTestId("models-outline");
    expect(within(outline).getAllByRole("article").map((a) => a.getAttribute("data-testid"))).toEqual([
      "models-outline-c3",
      "models-outline-c1",
      "models-outline-engine",
      "models-outline-a",
      "models-outline-a_odds",
    ]);
    expect(screen.getByTestId("models-outline-a_odds").textContent).toContain("Currently duplicates A");
    expect(screen.getByTestId("outline-role-c3").textContent).toBe("Champion: its advice is the live advice");
    expect(screen.getByTestId("outline-role-engine").textContent).toBe("Comparison, not yet run live");
    expect(screen.getByTestId("models-outline-c1").textContent).toContain("A multi-gameweek plan, with chips");
    expect(screen.getByTestId("models-outline-engine").textContent).toContain("This gameweek only, without chips");
    expect(screen.getByTestId("outline-now-c3").textContent).toBe("Advice published for GW10");
    expect(screen.getByTestId("outline-now-engine").textContent).toBe("Unavailable for GW10: odds not posted");
    expect(screen.getByTestId("outline-engine-unavailable")).toBeTruthy();
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
    installFetchStub({ bodies: { ...bodies, strategies } });
    renderApp("/models");
    expect((await screen.findByTestId("outline-role-c3_f3")).textContent).toBe("Experiment, not published");
    expect(screen.queryByTestId("models-outline-old_c2")).toBeNull();
  });

  it("ranks every model on this season's ladder, ties sharing a rank, and says it is the live season", async () => {
    installFetchStub({ bodies: { ...bodies, models: engineOut } });
    renderApp("/models/season");
    const ladder = await screen.findByTestId("season-ladder");
    const rows = within(ladder).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "ladder-row-c3",
      "ladder-row-a",
      "ladder-row-a_odds",
      "ladder-row-c1",
      "ladder-row-engine",
    ]);
    expect(["c3", "a", "a_odds", "c1", "engine"].map((m) => screen.getByTestId(`ladder-rank-${m}`).textContent)).toEqual([
      "1",
      "1",
      "1",
      "4",
      "5",
    ]);
    expect(screen.getByTestId("ladder-total-c1").textContent).toBe("179");
    expect(screen.getByTestId("ladder-engine-unavailable").textContent).toContain("odds not posted");
    expect(screen.getByTestId("season-kind").textContent).toBe("Live season 2026/27");
    expect(screen.getByTestId("season-kind-note").textContent).toContain("Not the replay of a past season");
  });

  it("shows this season's xP accuracy on the season tab and the backtest's on the 2025/26 tab", async () => {
    installFetchStub({ bodies: { ...bodies, models: modelsFixture } });
    const { unmount } = renderApp("/models/season");
    expect((await screen.findByTestId("accuracy-2026/27-c3")).textContent).toBe("1.234");
    expect(screen.queryByTestId("accuracy-2025/26")).toBeNull();
    unmount();
    renderApp("/models/2025-26");
    expect((await screen.findByTestId("accuracy-2025/26-c1")).textContent).toBe("0.910");
    expect(screen.getByTestId("accuracy-2025/26").textContent).toContain("A + odds: no saved predictions");
    expect(screen.queryByTestId("accuracy-2026/27")).toBeNull();
    expect(screen.getByTestId("history-kind").textContent).toBe("2025/26 replay");
  });

  it("degrades when the accuracy and history files are missing", async () => {
    installFetchStub({ missing: ["models_history", "xp_accuracy"] as never });
    const { unmount } = renderApp("/models/season");
    expect(await screen.findByTestId("accuracy-absent")).toBeTruthy();
    unmount();
    renderApp("/models/2025-26");
    expect(await screen.findByTestId("history-absent")).toBeTruthy();
  });

  it("says a malformed or failed file is that, not unpublished, and loads it on a retry (DP-15)", async () => {
    installFetchStub({ bodies: { ...bodies, models_history: {} }, failing: ["xp_accuracy"] as never });
    renderApp("/models/2025-26");
    const history = await screen.findByTestId("history-absent");
    expect(history.textContent).toContain("malformed");
    expect(history.textContent).not.toContain("not been published");
    expect((await screen.findByTestId("accuracy-unavailable")).textContent).toContain("500");

    installFetchStub({ bodies });
    fireEvent.click(within(history).getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("model-history")).toBeTruthy();
    fireEvent.click(within(screen.getByTestId("accuracy-unavailable")).getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("accuracy-2025/26")).toBeTruthy();
  });

  it("names the playthrough's tab by the season its history covers", async () => {
    installFetchStub({ bodies: { ...bodies, models_history: { ...historyFixture, season: "2024/25" } } });
    renderApp("/models/2025-26");
    await waitFor(() => expect(screen.getByTestId("tab-models-2025-26").textContent).toBe("2024/25"));
  });

  it("sends an old ?section= link for a part that moved to its new tab", async () => {
    installFetchStub({ bodies });
    const { unmount } = renderApp("/models?section=history");
    expect(await screen.findByTestId("model-history")).toBeTruthy();
    expect(screen.queryByTestId("models-page")).toBeNull();
    unmount();
    renderApp("/models?section=accuracy");
    expect(await screen.findByTestId("models-season-page")).toBeTruthy();
  });
});
