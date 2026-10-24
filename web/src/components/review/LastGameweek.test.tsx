import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { modelsFixture, optionSet, strategiesFixture } from "../../test/fixtures";
import type { Log, Models } from "../../contract/types";
import { mockLog } from "./fixtures";

/** The hindsight log moved onto the models fixture's gameweeks: GW8 and GW9 evaluated in both. */
const log: Log = {
  ...mockLog,
  gameweeks: mockLog.gameweeks.map((g) => ({
    ...g,
    gameweek: g.gameweek + 3,
    hindsight: g.hindsight && {
      ...g.hindsight,
      optimal: g.hindsight.optimal && { ...g.hindsight.optimal, gameweek: g.gameweek + 3 },
    },
  })),
};

const bodies = { strategies: strategiesFixture, models: modelsFixture, log };
const points = (key: string) => screen.getByTestId(`review-points-${key}`).textContent;

describe("Last gameweek", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("opens on the latest evaluated gameweek with every model's points, yours and the optimum's, ranked", async () => {
    installFetchStub({ bodies });
    renderApp("/review");
    const table = await screen.findByTestId("review-models");
    expect((screen.getByTestId("review-gameweek") as HTMLSelectElement).value).toBe("9");
    expect(points("played")).toBe("65");
    expect(points("optimum")).toBe("84");
    expect(["c3", "c1", "engine", "a", "a_odds"].map(points)).toEqual(["71", "66", "69", "74", "72"]);
    const order = within(table).getAllByRole("row").slice(1).map((r) => r.getAttribute("data-testid"));
    expect(order).toEqual([
      "review-row-optimum",
      "review-row-a",
      "review-row-a_odds",
      "review-row-c3",
      "review-row-engine",
      "review-row-c1",
      "review-row-played",
    ]);
    expect(screen.getByTestId("review-did-c1").textContent).toContain("captain Salah");
    expect(screen.getByTestId("review-did-played").textContent).toContain("1 transfer");
    expect(screen.getByTestId("review-did-played").textContent).toContain("no advice recorded");
    expect(screen.getByTestId("review-frozen-note").textContent).toContain("frozen record");
  });

  it("lets any earlier gameweek be chosen", async () => {
    installFetchStub({ bodies });
    renderApp("/review");
    const select = (await screen.findByTestId("review-gameweek")) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["7", "8", "9"]);
    fireEvent.change(select, { target: { value: "8" } });
    expect(points("played")).toBe("55");
    expect(points("optimum")).toBe("60");
    expect(points("c3")).toBe("48");
    fireEvent.change(select, { target: { value: "7" } });
    expect(points("c3")).toBe("62");
    expect(points("played")).toBe("—");
    expect(screen.getByTestId("review-no-optimal").textContent).toContain("GW7 is not in the season log");
  });

  it("sets out the hindsight options and the players who decided them, without the unreliable per-model xP", async () => {
    installFetchStub({ bodies });
    renderApp("/review");
    const options = await screen.findByTestId("review-options");
    expect(within(options).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByTestId("review-options-0").textContent).toContain("roll");
    expect(screen.getByTestId("review-options-1").textContent).toContain("best single transfer, best overall");
    expect(screen.getByTestId("review-options-1").textContent).toContain("Raya → Watkins");
    const watkins = screen.getByTestId("review-diagnostic-17");
    expect(watkins.textContent).toContain("Model blind spot");
    expect(watkins.textContent).toContain("14 pts");
    expect(watkins.textContent).toContain("Caught out: Champion (C3)");
    expect(watkins.textContent).not.toContain("5.8");
    expect(screen.getByTestId("review-diagnostics-xp-note")).toBeTruthy();
  });

  it("sets each model's options at the deadline beside the hindsight's (ORC-11)", async () => {
    const weighed: Models = {
      ...modelsFixture,
      gameweeks: modelsFixture.gameweeks.map((g) =>
        g.gameweek !== 9
          ? g
          : {
              ...g,
              advice: {
                ...g.advice,
                c3: {
                  ...g.advice.c3,
                  option_set: optionSet(9, "Haaland", [
                    [0, [], 60.5, 0],
                    [1, [["Raya", "Pope"]], 61.25, 0],
                  ]),
                },
              },
            },
      ),
    };
    installFetchStub({ bodies: { ...bodies, models: weighed } });
    renderApp("/review");
    const table = await screen.findByTestId("review-weighed");
    const optimum = within(table).getByTestId("review-weighed-optimum").textContent;
    expect(optimum).toContain("70");
    expect(optimum).toContain("Raya → Watkins · 84 (+14)");
    const c3 = within(table).getByTestId("review-weighed-c3").textContent;
    expect(c3).toContain("60.50");
    expect(c3).toContain("Raya → Pope · 61.25 (+0.75)");
    expect(within(table).getByTestId("review-weighed-c1").textContent).toContain("Not recorded at the deadline");

    fireEvent.change(screen.getByTestId("review-gameweek"), { target: { value: "8" } });
    expect(screen.getByTestId("review-no-weighed").textContent).toContain("GW8 deadline");
  });

  it("says why when the optimum was not worked out", async () => {
    const noOptimal: Log = {
      ...log,
      gameweeks: log.gameweeks.map((g) =>
        g.hindsight ? { ...g, hindsight: { ...g.hindsight, optimal: null, optimal_unavailable_reason: "the bank was not recorded" } } : g,
      ),
    };
    installFetchStub({ bodies: { ...bodies, log: noOptimal } });
    renderApp("/review");
    expect((await screen.findByTestId("review-no-optimal")).textContent).toBe("the bank was not recorded");
    expect(screen.queryByTestId("review-row-optimum")).toBeNull();
    expect(points("played")).toBe("65");
  });

  it("names an unavailable model and leaves it unranked", async () => {
    const out: Models = {
      ...modelsFixture,
      gameweeks: modelsFixture.gameweeks.map((g) => {
        if (g.gameweek !== 9 || !g.actual) return g;
        const { engine: _advice, ...advice } = g.advice;
        const { engine: _actual, ...actual } = g.actual;
        return { ...g, advice, actual, availability: { ...g.availability, engine: { available: false, reason: "odds not posted" } } };
      }),
    };
    installFetchStub({ bodies: { ...bodies, models: out } });
    renderApp("/review");
    expect((await screen.findByTestId("review-did-engine")).textContent).toBe("Unavailable: odds not posted");
    expect(points("engine")).toBe("—");
    expect(within(screen.getByTestId("review-row-engine")).getAllByRole("cell")[0].textContent).toBe("—");
  });

  it("keeps the models' points when the season log is missing, and says what is missing", async () => {
    installFetchStub({ bodies, missing: ["log"] });
    renderApp("/review");
    expect((await screen.findByTestId("review-log-problem")).textContent).toContain("No season log is published yet");
    expect(points("c3")).toBe("71");
    expect(points("played")).toBe("—");
  });

  it("explains an empty review before anything is evaluated", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture }, missing: ["log"] });
    renderApp("/review");
    expect((await screen.findByTestId("review-empty")).textContent).toContain("Nothing has been evaluated yet");
  });
});
