import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { challengerWeek, modelsFixture, week } from "../../test/fixtures";
import { MODEL_STORAGE_KEY, parseModel } from "../../data/model";
import { fetchModels } from "../../data/api";

const all = { week_challenger: challengerWeek, models: modelsFixture };

describe("five-model selector", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("offers all five models with champion as the default", async () => {
    installFetchStub({ bodies: all });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    const group = screen.getByRole("radiogroup", { name: "Recommendation model" });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(5);
    expect(radios.every((r) => !(r as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getByTestId("model-toggle-champion").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("model-toggle-champion").getAttribute("aria-label")).toBe("Champion (live)");
    expect(screen.getByTestId("model-toggle-a").getAttribute("aria-label")).toBe("Model A (comparison)");
    // Roving tabindex: only the checked radio is in the tab order.
    expect(radios.filter((r) => r.getAttribute("tabindex") === "0")).toHaveLength(1);
    const select = screen.getByTestId("model-select") as HTMLSelectElement;
    expect(select.value).toBe("champion");
    expect(select.options).toHaveLength(5);
    expect(screen.queryByTestId("model-advice-card")).toBeNull();
  });

  it("shows a comparison model's advice as a labelled comparison, keeping the champion live", async () => {
    installFetchStub({ bodies: all });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    fireEvent.click(screen.getByTestId("model-toggle-engine"));
    const card = await screen.findByTestId("model-advice-card");
    expect(card.dataset.model).toBe("engine");
    expect(within(card).getByTestId("model-badge").textContent).toContain("comparison");
    expect(within(card).getByTestId("model-comparison-banner").textContent).toContain("not live advice");
    expect(within(card).getByTestId("model-advice-captain").textContent).toBe("Palmer");
    // The champion's own recommendation is still on the page, labelled as the champion.
    const rec = screen.getByTestId("dashboard-recommendation");
    expect(within(rec).getByTestId("model-badge").dataset.model).toBe("champion");
    expect(screen.getByTestId("week-rationale").textContent).toBe(week.recommendation!.rationale);
    expect(screen.getByTestId("model-toggle-note").textContent).toContain("Comparison only");
    expect(window.localStorage.getItem(MODEL_STORAGE_KEY)).toBe("engine");
  });

  it("is keyboard operable: arrows, Home and End move and select", async () => {
    installFetchStub({ bodies: all });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    const group = screen.getByTestId("model-segmented");
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(screen.getByTestId("model-toggle-challenger").getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement).toBe(screen.getByTestId("model-toggle-challenger"));
    fireEvent.keyDown(group, { key: "End" });
    expect(screen.getByTestId("model-toggle-a_odds").getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(screen.getByTestId("model-toggle-champion").getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    expect(screen.getByTestId("model-toggle-a_odds").getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(group, { key: "Home" });
    expect(screen.getByTestId("model-toggle-champion").getAttribute("aria-checked")).toBe("true");
  });

  it("the small-screen select changes the model too", async () => {
    installFetchStub({ bodies: all });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    fireEvent.change(screen.getByTestId("model-select"), { target: { value: "a" } });
    const card = await screen.findByTestId("model-advice-card");
    expect(card.dataset.model).toBe("a");
    expect(screen.getByTestId("model-toggle-a").getAttribute("aria-checked")).toBe("true");
  });

  it("honours ?model= for the new ids", async () => {
    installFetchStub({ bodies: all });
    window.history.replaceState(null, "", "/?model=a_odds");
    renderApp("/");
    const card = await screen.findByTestId("model-advice-card");
    expect(card.dataset.model).toBe("a_odds");
  });

  it("disables unpublished models and falls back to the champion", async () => {
    installFetchStub();
    window.localStorage.setItem(MODEL_STORAGE_KEY, "a");
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    expect((screen.getByTestId("model-toggle-a") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("model-toggle-champion").getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByTestId("model-advice-card")).toBeNull();
  });

  it("the models page shows season-to-date totals, the per-GW table and the chart", async () => {
    installFetchStub({ bodies: all });
    renderApp("/models");
    const season = await screen.findByTestId("models-season");
    const table = within(season).getByTestId("models-table");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(6);
    expect(within(table).getAllByRole("row")).toHaveLength(5); // header, 3 GWs, total
    expect(screen.getByTestId("models-total-champion").textContent).toBe("181");
    expect(screen.getByTestId("models-total-a").textContent).toBe("181");
    const chart = screen.getByTestId("models-chart");
    expect(chart.querySelectorAll("polyline")).toHaveLength(5);
    expect(chart.querySelector("svg")?.getAttribute("aria-label")).toContain("Cumulative points");
    expect(within(screen.getByTestId("models-advice-challenger")).getByText(/-4 hit/)).toBeTruthy();
  });

  it("the models page says so when models.json is absent", async () => {
    installFetchStub();
    renderApp("/models");
    expect(await screen.findByTestId("models-season-empty")).toBeTruthy();
  });
});

describe("models data", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parseModel accepts only known ids", () => {
    expect(parseModel("a_odds")).toBe("a_odds");
    expect(parseModel("C3")).toBeNull();
    expect(parseModel(null)).toBeNull();
  });

  it("fetchModels never throws and rejects non-JSON or malformed bodies", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    expect(await fetchModels()).toBeNull();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("<html>", { headers: { "content-type": "text/html" } }))),
    );
    expect(await fetchModels()).toBeNull();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify({ nope: 1 }), { headers: { "content-type": "application/json" } }))),
    );
    expect(await fetchModels()).toBeNull();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify(modelsFixture), { headers: { "content-type": "application/json" } }))),
    );
    expect((await fetchModels())?.models).toHaveLength(5);
  });
});
