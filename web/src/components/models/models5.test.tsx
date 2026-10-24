import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { modelsFixture, novelRegistry, strategiesFixture } from "../../test/fixtures";
import { MODEL_STORAGE_KEY } from "../../data/model";
import { dataStore } from "../../data/store";

// Five published strategies, none of which the TypeScript has ever named.
const novel = novelRegistry(5);
const five = { strategies: novel.registry, ...novel.weeks };

describe("the strategy selector is driven by the registry", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("offers every published strategy with the champion as the default", async () => {
    installFetchStub({ bodies: five });
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    const group = screen.getByRole("radiogroup", { name: "Recommendation model" });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(5);
    expect(radios.every((r) => !(r as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getByTestId("model-toggle-zeta_1").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("model-toggle-zeta_1").getAttribute("aria-label")).toBe("Zeta 1 (live)");
    expect(screen.getByTestId("model-toggle-zeta_4").getAttribute("aria-label")).toBe("Zeta 4 (comparison)");
    // Roving tabindex: only the checked radio is in the tab order.
    expect(radios.filter((r) => r.getAttribute("tabindex") === "0")).toHaveLength(1);
    const select = screen.getByTestId("model-select") as HTMLSelectElement;
    expect(select.value).toBe("zeta_1");
    expect(select.options).toHaveLength(5);
  });

  it("is keyboard operable: arrows, Home and End move and select", async () => {
    installFetchStub({ bodies: five });
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    const group = screen.getByTestId("model-segmented");
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(screen.getByTestId("model-toggle-zeta_2").getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement).toBe(screen.getByTestId("model-toggle-zeta_2"));
    fireEvent.keyDown(group, { key: "End" });
    expect(screen.getByTestId("model-toggle-zeta_5").getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(screen.getByTestId("model-toggle-zeta_1").getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    expect(screen.getByTestId("model-toggle-zeta_5").getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(group, { key: "Home" });
    expect(screen.getByTestId("model-toggle-zeta_1").getAttribute("aria-checked")).toBe("true");
  });

  it("the small-screen select applies the strategy to the dashboard and remembers it", async () => {
    installFetchStub({ bodies: five });
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    fireEvent.change(screen.getByTestId("model-select"), { target: { value: "zeta_3" } });
    await waitFor(() => expect(screen.getByTestId("week-rationale").textContent).toBe("Roll the free transfer"));
    expect(screen.getByTestId("model-toggle-note").textContent).toContain("Comparison only");
    expect(window.localStorage.getItem(MODEL_STORAGE_KEY)).toBe("zeta_3");
  });

  it("honours ?model= for an id only the registry knows", async () => {
    installFetchStub({ bodies: five });
    window.history.replaceState(null, "", "/?model=zeta_5");
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("model-toggle-zeta_5").getAttribute("aria-checked")).toBe("true"));
  });

  it("lists only the strategies with a week, and falls back to the champion for one without", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture } });
    window.localStorage.setItem(MODEL_STORAGE_KEY, "a");
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    expect(screen.queryByTestId("model-toggle-a")).toBeNull();
    expect(screen.getByTestId("model-toggle-c3").getAttribute("aria-checked")).toBe("true");
  });

  it("the models page shows season-to-date totals, the per-GW table and the chart", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture, models: modelsFixture } });
    renderApp("/models/season");
    const season = await screen.findByTestId("models-season");
    const table = within(season).getByTestId("models-table");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(6);
    expect(within(table).getAllByRole("row")).toHaveLength(5); // header, 3 GWs, total
    expect(screen.getByTestId("models-total-c3").textContent).toBe("181");
    expect(screen.getByTestId("models-total-a").textContent).toBe("181");
    const chart = screen.getByTestId("models-chart");
    expect(chart.querySelectorAll("polyline")).toHaveLength(5);
    expect(chart.querySelector("svg")?.getAttribute("aria-label")).toContain("Cumulative points");
    expect(within(screen.getByTestId("models-advice-c1")).getByText(/-4 hit/)).toBeTruthy();
  });

  it("the models page splits each model's miss into forecast error and luck per gameweek (ORC-12)", async () => {
    const last = modelsFixture.gameweeks.find((g) => g.actual?.c3);
    const c3 = last?.actual?.c3;
    if (!last || !c3) throw new Error("the fixture scores c3 in some gameweek");
    const models = {
      ...modelsFixture,
      gameweeks: modelsFixture.gameweeks.map((g) =>
        g === last ? { ...g, actual: { ...g.actual, c3: { ...c3, underlying_points: 50.25, forecast_error: 4.2, luck: -3.14 } } } : g,
      ),
    };
    installFetchStub({ bodies: { strategies: strategiesFixture, models } });
    renderApp("/models/season");
    const table = await screen.findByTestId("models-split-table");
    expect(within(table).getAllByRole("row")).toHaveLength(2); // header and the one gameweek with it
    expect(screen.getByTestId(`models-split-${last.gameweek}-c3`).textContent).toBe("error +4.2, luck −3.1");
    expect(screen.getByTestId(`models-split-${last.gameweek}-a`).textContent).toBe("—");
  });

  it("the models page says when no gameweek has underlying xP yet", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture, models: modelsFixture } });
    renderApp("/models/season");
    expect(await screen.findByTestId("models-split-empty")).toBeTruthy();
  });

  it("the models page says so when models.json is absent", async () => {
    installFetchStub();
    renderApp("/models/season");
    expect(await screen.findByTestId("models-season-empty")).toBeTruthy();
  });
});

describe("models data", () => {
  beforeEach(() => resetAppState());
  afterEach(() => vi.unstubAllGlobals());

  it("loads models.json as error, absent, malformed or ready, never throwing", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    expect((await dataStore.get("models")).status).toBe("error");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("<html>", { headers: { "content-type": "text/html" } }))),
    );
    expect((await dataStore.get("models")).status).toBe("absent");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify({ nope: 1 }), { headers: { "content-type": "application/json" } }))),
    );
    expect((await dataStore.get("models")).status).toBe("malformed");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify(modelsFixture), { headers: { "content-type": "application/json" } }))),
    );
    const loaded = await dataStore.get("models");
    expect(loaded.status === "ready" && loaded.data.models).toHaveLength(5);
  });
});
