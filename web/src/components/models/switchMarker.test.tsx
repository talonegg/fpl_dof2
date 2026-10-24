import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { challengerWeek, modelsFixture, strategiesFixture } from "../../test/fixtures";
import type { Models } from "../../contract/types";

const withSwitch = (switchGameweek: number | null): Models => ({
  ...modelsFixture,
  switch_gameweek: switchGameweek,
  gameweeks: modelsFixture.gameweeks.map((g) => ({
    ...g,
    record: switchGameweek !== null && g.gameweek >= switchGameweek ? "live" : "frozen",
  })),
});

const bodies = (models: Models) => ({
  strategies: strategiesFixture,
  week_c1: challengerWeek,
  models,
});

describe("the switch from the frozen record to the live ledger", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("marks the switch gameweek on the history chart with a text label", async () => {
    installFetchStub({ bodies: bodies(withSwitch(9)) });
    renderApp("/models/season");
    const marker = await screen.findByTestId("models-switch-marker");
    expect(marker.textContent).toBe("Live from GW9");
    expect(screen.getByTestId("models-chart").querySelector("svg")?.getAttribute("aria-label")).toContain(
      "Live from GW9",
    );
    expect(screen.getByTestId("models-switch-note").textContent).toContain("frozen-2026-10-13");
  });

  it("still shows the frozen history, with no marker when nothing has switched", async () => {
    installFetchStub({ bodies: bodies(withSwitch(null)) });
    renderApp("/models/season");
    await screen.findByTestId("models-chart");
    expect(screen.queryByTestId("models-switch-marker")).toBeNull();
    expect(screen.getByTestId("models-total-c3").textContent).toBe("181");
  });
});
