import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { historyFixture } from "../history/history.test";
import { modelsFixture, strategiesFixture } from "../../test/fixtures";
import type { AsIfPlayed } from "../../contract/types";
import { IN_SAMPLE_LABEL } from "./AsIfPlayedSection";

/** Today's models replayed in-sample on 2026/27: c3 plays a chip in GW2, engine sits GW1 out. */
const played: AsIfPlayed = {
  ...historyFixture,
  season: "2026/27",
  kind: "in_sample",
  caveat: "In-sample: today's models replayed on past gameweeks; not evidence of skill. More.",
  gameweeks: historyFixture.gameweeks.map((g) => {
    const { engine, ...rest } = g.models;
    if (g.gameweek === 1) {
      return { ...g, models: rest, unavailable: { engine: "ColdStartError: no feature row could be built" } };
    }
    return { ...g, models: { ...g.models, champion: { ...g.models.champion, chip: "bboost" }, engine } };
  }),
};

const replay = { ...historyFixture, season: "2024/25" }; // the replay's season comes from its file
const bodies = { strategies: strategiesFixture, models: modelsFixture, models_history: replay };

describe("Models, this season as if played (ORC-13, DL-97)", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("ranks today's models on their own teams, labelled in-sample, beside the ladder on your squad", async () => {
    installFetchStub({ bodies: { ...bodies, as_if_played: played } });
    renderApp("/models/season");
    const section = await screen.findByTestId("as-if-played");
    expect(screen.getByTestId("season-ladder")).toBeTruthy(); // the ladder of advice on your squad
    expect(within(section).getByTestId("in-sample-label").textContent).toBe(`${IN_SAMPLE_LABEL}.`);
    expect(within(section).getByTestId("history-kind").textContent).toBe("In-sample");
    const rows = within(within(section).getByTestId("history-summary")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual(
      ["c3", "a", "c1", "engine", "a_odds"].map((m) => `history-row-${m}`), // a_odds unavailable, last
    );
    expect(section.textContent).toContain("not the 2024/25 replay");
    expect(section.textContent).not.toContain("★"); // in-sample: no interval is evidence
  });

  it("shows the chip played and each unavailable gameweek with its reason", async () => {
    installFetchStub({ bodies: { ...bodies, as_if_played: played } });
    renderApp("/models/season");
    const section = await screen.findByTestId("as-if-played");
    const table = within(section).getByTestId("history-gw-table");
    expect(table.textContent).toContain("bboost");
    expect(table.textContent).toContain("unavailable");
    expect(within(section).getByTestId("history-unavailable-1-engine").textContent).toBe(
      "GW1, Engine: ColdStartError: no feature row could be built",
    );
  });

  it("says the season has not been replayed yet when the file is absent", async () => {
    installFetchStub({ bodies, missing: ["as_if_played"] as never });
    renderApp("/models/season");
    expect((await screen.findByTestId("as-if-played-absent")).textContent).toContain("has not been replayed yet");
  });

  it("keeps the backtest's replay on its own tab, without the live season", async () => {
    installFetchStub({ bodies: { ...bodies, as_if_played: played } });
    renderApp("/models/2025-26");
    expect((await screen.findByTestId("history-kind")).textContent).toBe("2024/25 replay");
    expect(screen.queryByTestId("as-if-played")).toBeNull();
    expect(screen.queryByTestId("in-sample-label")).toBeNull();
  });
});
