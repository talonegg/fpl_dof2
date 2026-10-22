import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { challengerWeek, novelRegistry, strategiesFixture, week } from "../../test/fixtures";
import { historyFixture } from "../history/history.test";

// Five published strategies, none of which the TypeScript has ever named; the first is the champion.
const novel = novelRegistry(5);
const bodies = { strategies: novel.registry, ...novel.weeks };

const col = (id: string) => screen.queryByTestId(`compare-col-${id}`);

describe("/models comparison", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("selects every published strategy by default and compares them side by side against the champion", async () => {
    installFetchStub({ bodies });
    renderApp("/models");
    await screen.findByTestId("compare-advice");
    for (const id of ["zeta_1", "zeta_2", "zeta_3", "zeta_4", "zeta_5"]) {
      expect((screen.getByTestId(`compare-pick-${id}`) as HTMLInputElement).checked).toBe(true);
      expect(col(id)).toBeTruthy();
    }
    expect(col("zeta_1")!.textContent).toContain("Zeta 1");
    expect(col("zeta_1")!.textContent).toContain("baseline");
    expect(screen.getByTestId("compare-baseline").textContent).toContain("Zeta 1");
    // The novel registry gives even-numbered challengers the champion's captain and odd ones another.
    expect(screen.getByTestId("compare-captain-zeta_2").className).toContain("differs");
    expect(screen.getByTestId("compare-captain-zeta_2").textContent).toContain("Differs from the baseline");
    expect(screen.getByTestId("compare-captain-zeta_1").className).not.toContain("differs");
    expect(screen.getByTestId("compare-captain-zeta_3").className).not.toContain("differs");
    expect(screen.getByTestId("compare-transfers-zeta_2").className).toContain("differs");
    expect(screen.getByTestId("compare-xi-zeta_2").textContent).toMatch(/In: .*Out: /);
  });

  it("shows the players they disagree on with each strategy's view", async () => {
    installFetchStub({ bodies });
    renderApp("/models");
    const table = await screen.findByTestId("compare-players");
    expect(within(table).getAllByRole("row").length).toBeGreaterThan(1);
    const xi = challengerWeek.advised!.starting;
    const dropped = week.advised!.starting.find((id) => !xi.includes(id))!;
    expect(screen.getByTestId(`compare-player-${dropped}-zeta_1`).textContent).toContain("In XI");
    expect(screen.getByTestId(`compare-player-${dropped}-zeta_2`).textContent).toContain("Not in XI");
  });

  it("compares any two to five: deselecting removes a column, fewer than two explains itself", async () => {
    installFetchStub({ bodies });
    renderApp("/models");
    await screen.findByTestId("compare-advice");
    for (const id of ["zeta_3", "zeta_4", "zeta_5"]) fireEvent.click(screen.getByTestId(`compare-pick-${id}`));
    expect(col("zeta_3")).toBeNull();
    expect(col("zeta_1")).toBeTruthy();
    expect(col("zeta_2")).toBeTruthy();
    fireEvent.click(screen.getByTestId("compare-pick-zeta_2"));
    expect(screen.getByTestId("compare-too-few")).toBeTruthy();
    expect(screen.queryByTestId("compare-advice")).toBeNull();
  });

  it("falls back to the first selected strategy as the baseline when the champion is deselected", async () => {
    installFetchStub({ bodies });
    renderApp("/models");
    await screen.findByTestId("compare-advice");
    fireEvent.click(screen.getByTestId("compare-pick-zeta_1"));
    expect(col("zeta_1")).toBeNull();
    expect(col("zeta_2")!.textContent).toContain("baseline");
    expect(screen.getByTestId("compare-baseline").textContent).toContain("the champion is not selected");
  });

  it("compares the registry's real pair, with historical performance from the history file", async () => {
    installFetchStub({
      bodies: { strategies: strategiesFixture, week_challenger: challengerWeek, models_history_2526: historyFixture },
    });
    renderApp("/models");
    await screen.findByTestId("compare-advice");
    expect(col("c3")).toBeTruthy();
    expect(col("c1")).toBeTruthy();
    expect(screen.getByTestId("compare-history-c1").textContent).toContain("50.00");
    expect(screen.getByTestId("compare-history-c3").textContent).toContain("reference");
  });

  it("marks a published strategy with no week and leaves it out of the table", async () => {
    installFetchStub({ bodies: { strategies: novel.registry, [`week_zeta_1`]: week } });
    renderApp("/models");
    expect(await screen.findByTestId("compare-too-few")).toBeTruthy();
    expect(screen.getAllByText("(no week published)").length).toBe(4);
  });
});

describe("a strategy the TypeScript has never named, in every model view", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders in the switcher, the summary, the details and the history views", async () => {
    const history = JSON.parse(
      JSON.stringify(historyFixture).replace(/"champion"/g, '"zeta_1"').replace(/"challenger"/g, '"zeta_2"'),
    );
    installFetchStub({ bodies: { ...bodies, models_history_2526: history } });
    renderApp("/models");
    await screen.findByTestId("model-history");
    expect(screen.getByTestId("model-toggle-zeta_2").textContent).toBe("Zeta 2");
    expect(screen.getByTestId("models-summary-zeta_2").textContent).toContain("Zeta 2");
    expect(screen.getByTestId("models-detail-zeta_2").textContent).toContain("Zeta 2 description.");
    expect(screen.getByTestId("history-row-zeta_2").textContent).toContain("Zeta 2");
    expect(screen.getByTestId("history-chart").querySelector('polyline[data-model="zeta_2"]')).toBeTruthy();
    expect(screen.getByTestId("history-chart").textContent).toContain("Zeta 1");
  });
});
