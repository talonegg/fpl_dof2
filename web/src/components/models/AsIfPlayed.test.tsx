import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { historyFixture } from "../history/history.test";
import { modelsFixture, strategiesFixture } from "../../test/fixtures";
import type { AsIfPlayed } from "../../contract/types";

/** The live season as if played: c3 (legacy "champion") live from GW6, c1 never live. */
const played: AsIfPlayed = {
  ...historyFixture,
  season: "2026/27",
  kind: "as_if_played",
  caveat: "Each strategy's 2026/27 as if it had played it.",
  models: historyFixture.models.map((m) => ({ ...m, live_from: m.id === "champion" ? 6 : null })),
  gameweeks: historyFixture.gameweeks.map((g, i) => ({
    ...g,
    gameweek: 5 + i,
    models: Object.fromEntries(
      Object.entries(g.models).map(([m, e]) => [m, { ...e, record: m === "champion" && 5 + i >= 6 ? "live" : "replayed" }]),
    ),
  })),
};

const bodies = { strategies: strategiesFixture, models: modelsFixture, models_history: historyFixture };

describe("Models, this season as if played (ORC-13)", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("ranks every model as if it had played, beside the ladder on your squad, each gameweek labelled", async () => {
    installFetchStub({ bodies: { ...bodies, as_if_played: played } });
    renderApp("/models/season");
    const ladder = await screen.findByTestId("as-if-played-ladder");
    expect(screen.getByTestId("season-ladder")).toBeTruthy(); // the ladder of advice on your squad
    const rows = within(ladder).getAllByRole("row").slice(1).map((r) => r.getAttribute("data-testid"));
    expect(rows).toEqual(["c3", "a", "c1", "engine", "a_odds"].map((m) => `as-if-played-row-${m}`)); // a_odds unavailable, last
    expect(screen.getByTestId("as-if-played-live-from-c3").textContent).toBe("GW6");
    expect(screen.getByTestId("as-if-played-live-from-c1").textContent).toBe("Not live yet");
    expect(screen.getByTestId("as-if-played-5-c3").textContent).toContain("replayed");
    expect(screen.getByTestId("as-if-played-6-c3").textContent).toContain("live");
    expect(screen.getByTestId("as-if-played-6-c1").textContent).toContain("replayed");
    expect(screen.getByTestId("as-if-played-kind").textContent).toBe("Live season 2026/27, as if played");
    expect(screen.getByTestId("as-if-played").textContent).toContain("not the 2025/26 replay");
  });

  it("says the live season has not been replayed yet when the file is absent", async () => {
    installFetchStub({ bodies, missing: ["as_if_played"] as never });
    renderApp("/models/season");
    expect((await screen.findByTestId("as-if-played-absent")).textContent).toContain("has not been replayed yet");
  });

  it("keeps the 2025/26 replay on its own tab, without the live season", async () => {
    installFetchStub({ bodies: { ...bodies, as_if_played: played } });
    renderApp("/models/2025-26");
    expect((await screen.findByTestId("history-kind")).textContent).toBe("2025/26 replay");
    expect(screen.queryByTestId("as-if-played")).toBeNull();
  });
});
