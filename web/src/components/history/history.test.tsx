import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import type { ModelHistoryEntry, ModelsHistory } from "../../contract/types";
import { DATA_BASE, dataStore } from "../../data/store";
import { NAV_ITEMS } from "../../routes/nav";
import { strategiesFixture } from "../../test/fixtures";

const entry = (points: number, cumulative: number, rank: number, extra: Partial<ModelHistoryEntry> = {}): ModelHistoryEntry => ({
  points,
  points_before_hits: points,
  hit_points: 0,
  n_transfers: 1,
  transfers: ["Salah → Saka"],
  captain: "Haaland",
  vice_captain: "Salah",
  captain_points: 12,
  vice_used: false,
  n_autosubs: 0,
  cumulative,
  rank,
  cumulative_rank: rank,
  ...extra,
});

export const historyFixture: ModelsHistory = {
  contract_version: 1,
  season: "2025/26",
  kind: "backtest",
  caveat: "Backtest, not real play: a walk-forward replay.",
  champion: "champion",
  provenance: { frozen_tag: "frozen-2026-10-13" },
  bootstrap: { draws: 2000, seed: 0, unit: "gameweek", level: 0.95 },
  models: [
    { id: "champion", label: "Champion (C3)", role: "champion", available: true, unavailable_reason: null },
    { id: "challenger", label: "Challenger (C1)", role: "challenger", available: true, unavailable_reason: null },
    { id: "engine", label: "Engine", role: "comparison", available: true, unavailable_reason: null },
    { id: "a", label: "Model A", role: "comparison", available: true, unavailable_reason: null },
    { id: "a_odds", label: "A + odds", role: "comparison", available: false, unavailable_reason: "no realistic run" },
  ],
  gameweeks: [
    {
      gameweek: 1,
      models: {
        champion: entry(50, 50, 2),
        challenger: entry(60, 60, 1, { hit_points: -4, captain: "Palmer" }),
        engine: entry(40, 40, 4),
        a: entry(45, 45, 3),
      },
    },
    {
      gameweek: 2,
      models: {
        champion: entry(70, 120, 1),
        challenger: entry(40, 100, 4, { vice_used: true }),
        engine: entry(50, 90, 3),
        a: entry(65, 110, 2),
      },
    },
  ],
  summary: [
    { model: "champion", total: 120, mean_per_gameweek: 60, gameweeks_won: 1, hit_points: 0, final_rank: 1, delta_vs_champion: null },
    {
      model: "challenger", total: 100, mean_per_gameweek: 50, gameweeks_won: 1, hit_points: -4, final_rank: 3,
      delta_vs_champion: { mean: -10, ci_low: -30, ci_high: 10, total: -20, significant: false, gameweeks_better: 1, gameweeks_worse: 1 },
    },
    {
      model: "engine", total: 90, mean_per_gameweek: 45, gameweeks_won: 0, hit_points: 0, final_rank: 4,
      delta_vs_champion: { mean: -15, ci_low: -20, ci_high: -10, total: -30, significant: true, gameweeks_better: 0, gameweeks_worse: 2 },
    },
    {
      model: "a", total: 110, mean_per_gameweek: 55, gameweeks_won: 0, hit_points: 0, final_rank: 2,
      delta_vs_champion: { mean: -5, ci_low: -5, ci_high: -5, total: -10, significant: true, gameweeks_better: 0, gameweeks_worse: 2 },
    },
  ],
};

// The checked-in file carries the old ids; the registry's aliases map them.
const bodies = { models_history: historyFixture, strategies: strategiesFixture };

describe("model history page", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("is folded into the Models page: no separate nav tab", () => {
    expect(NAV_ITEMS.find((n) => n.path === "/history")).toBeUndefined();
    expect(NAV_ITEMS.find((n) => n.path === "/models")?.label).toBe("Models");
  });

  it("shows the backtest caveat, the ranked summary with deltas and CIs", async () => {
    installFetchStub({ bodies });
    renderApp("/history");
    const page = await screen.findByTestId("model-history");
    expect(within(page).getByTestId("history-caveat").textContent).toContain("Backtest, not real play");
    const rows = within(screen.getByTestId("history-summary")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "history-row-c3",
      "history-row-a",
      "history-row-c1",
      "history-row-engine",
    ]);
    expect(screen.getByTestId("history-total-c3").textContent).toBe("120");
    expect(screen.getByTestId("history-delta-c3").textContent).toBe("reference");
    const d = screen.getByTestId("history-delta-engine").textContent ?? "";
    expect(d).toContain("−15.00 [−20.00, −10.00]");
    expect(d).toContain("★");
    expect(screen.getByTestId("history-delta-c1").textContent).not.toContain("★");
    expect(screen.getByTestId("history-unavailable").textContent).toContain("A + odds: unavailable — no realistic run");
  });

  it("draws one chart line per available model and a per-GW table with ranks", async () => {
    installFetchStub({ bodies });
    renderApp("/history");
    await screen.findByTestId("model-history");
    const chart = screen.getByTestId("history-chart");
    expect(chart.querySelectorAll("polyline")).toHaveLength(4);
    expect(chart.querySelector("svg")?.getAttribute("aria-label")).toContain("Champion (C3) 120");
    const table = screen.getByTestId("history-gw-table");
    expect(within(table).getAllByRole("row")).toHaveLength(4); // head, 2 GWs, total
    expect(within(table).getAllByText(/Haaland \(12\) \/ Salah/, { selector: "td" })).toHaveLength(2);
  });

  it("the reused selector highlights a model by click, keyboard and select", async () => {
    installFetchStub({ bodies });
    renderApp("/history");
    await screen.findByTestId("model-history");
    const group = screen.getByRole("radiogroup", { name: "Highlight model" });
    expect(within(group).getAllByRole("radio")).toHaveLength(4);
    expect(screen.queryByTestId("history-model-a_odds")).toBeNull();
    fireEvent.click(screen.getByTestId("history-model-c1"));
    expect(screen.getByTestId("history-row-c1").className).toContain("is-highlight");
    expect(within(screen.getByTestId("history-gw-table")).getByText(/Palmer/)).toBeTruthy();
    expect(within(screen.getByTestId("history-gw-table")).getByText(/vice used/)).toBeTruthy();
    fireEvent.keyDown(screen.getByTestId("history-model-segmented"), { key: "ArrowRight" });
    expect(screen.getByTestId("history-model-engine").getAttribute("aria-checked")).toBe("true");
    fireEvent.change(screen.getByTestId("history-model-select"), { target: { value: "a" } });
    expect(screen.getByTestId("history-row-a").className).toContain("is-highlight");
    expect(screen.getByTestId("history-model-note").textContent).toContain("Model A: 110 pts, ranked 2 of 4");
    // The page's highlight is local: the global live-model choice stays the champion.
    expect(screen.getByTestId("model-toggle-c3").getAttribute("aria-checked")).toBe("true");
  });

  it("says so when the file is missing", async () => {
    installFetchStub();
    renderApp("/history");
    expect(await screen.findByTestId("history-absent")).toBeTruthy();
  });

  it("loads the models history from the published data, and calls a wrong body malformed", async () => {
    const offline = vi.fn((_input: RequestInfo | URL) => Promise.reject(new Error("offline")));
    vi.stubGlobal("fetch", offline);
    expect((await dataStore.get("models_history")).status).toBe("error");
    // Published data now (ORC-06), not a file shipped with the app.
    expect(offline.mock.calls.map(([url]) => String(url))).toContain(`${DATA_BASE}/models_history.json`);
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ x: 1 }), { headers: { "content-type": "application/json" } }))));
    expect((await dataStore.get("models_history")).status).toBe("malformed");
  });
});
