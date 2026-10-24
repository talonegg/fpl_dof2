import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import { challengerWeek, modelsFixture, players, seasonLog, squad, strategiesFixture, week } from "../test/fixtures";
import { history } from "../components/player/testFixtures";
import { blockedHealth } from "../components/health/testFixtures";
import { mockLog } from "../components/review/fixtures";
import type { Models, Squad, Week } from "../contract/types";

/** Home (WEB-08): the acceptance criteria, through the rendered route. */
const hindsightLog = { ...mockLog, gameweeks: [mockLog.gameweeks[1]] };
const served = { strategies: strategiesFixture, models: modelsFixture, week_c1: challengerWeek, history };

describe("Home", () => {
  beforeEach(() => resetAppState());
  afterEach(() => vi.unstubAllGlobals());

  it("shows every model's recommendation, linked to This gameweek, with the roll beside the xP", async () => {
    installFetchStub({ bodies: served });
    renderApp("/");
    const card = await screen.findByTestId("home-models");
    for (const m of modelsFixture.models) expect(within(card).getByTestId(`home-model-${m.id}`)).toBeTruthy();
    const c1 = within(card).getByTestId("home-model-c1");
    expect(c1.textContent).toContain("Captain Salah");
    expect(c1.textContent).toContain("63.40 xP");
    expect(c1.textContent).toContain("roll");
    expect(within(c1).getByRole("link").getAttribute("href")).toBe("/gameweek?model=c1");
    // A model with no published decision has nothing to open.
    expect(within(within(card).getByTestId("home-model-engine")).queryByRole("link")).toBeNull();
  });

  it("opens each model's own decision in This gameweek", async () => {
    installFetchStub({ bodies: served });
    renderApp("/");
    fireEvent.click(within(await screen.findByTestId("home-model-c1")).getByRole("link"));
    await waitFor(() => expect(screen.getByTestId("week-rationale").textContent).toBe("Roll the free transfer"));
    expect(screen.getByTestId("model-toggle-c1").getAttribute("aria-checked")).toBe("true");
  });

  it("shows your current team in-season, not the fifteen a model advises", async () => {
    // In-season the solve is skipped; the champion advises selling 4 for 2.
    const skipped: Squad = { ...squad, status: "skipped", skipped: true, captain_id: null, vice_captain_id: null, players: [] };
    const isak = { ...players.players[1], id: 4, name: "Isak", team: "NEW" };
    const inSeason: Week = {
      ...week,
      recommendation: {
        ...week.recommendation!,
        moves: [{ out: { player_id: 4, web_name: "Isak", price: 8 }, in: { player_id: 2, web_name: "Watkins", price: 8 } }],
      },
      reconciliation: { gameweek: 1, entry_id: 1, followed: true, played: { squad: [1, 4, 3], starting: [1, 4], captain: 4 } },
    };
    installFetchStub({
      bodies: { ...served, squad: skipped, week: inSeason, players: { ...players, players: [...players.players, isak] } },
    });
    renderApp("/");
    const yours = await screen.findByTestId("home-squad-4");
    expect(yours.textContent).toContain("captain");
    expect(screen.queryByTestId("home-squad-2")).toBeNull();
    expect(screen.getByTestId("home-squad-3").textContent).toContain("bench");
  });

  it("names an unavailable model with its reason", async () => {
    const gameweeks = modelsFixture.gameweeks.map((g, i, all) =>
      i < all.length - 1
        ? g
        : { ...g, availability: { ...g.availability, a_odds: { available: false, reason: "no advice: MissingOddsError", sources: ["Match odds"] } } },
    );
    const models: Models = { ...modelsFixture, gameweeks };
    installFetchStub({ bodies: { ...served, models } });
    renderApp("/");
    const row = await screen.findByTestId("home-model-a_odds");
    expect(row.textContent).toContain("Unavailable: no advice: MissingOddsError");
    expect(screen.getByTestId("home-waiting").textContent).toContain("Match odds");
  });

  it("says so when no model comparison is published", async () => {
    installFetchStub({ bodies: { history } });
    renderApp("/");
    expect((await screen.findByTestId("home-models")).textContent).toContain("No model comparison is published yet");
  });

  it("lists the squad with last gameweek's points beside next gameweek's xP", async () => {
    installFetchStub({ bodies: served });
    renderApp("/");
    const raya = await screen.findByTestId("home-squad-1");
    await waitFor(() => expect(raya.textContent).toContain("8"));
    expect(screen.getByRole("columnheader", { name: "GW4 pts" })).toBeTruthy();
    expect(within(screen.getByTestId("home-squad-2")).getAllByRole("cell")[0].textContent).toBe("—");
  });

  it("renders the last gameweek card with hindsight, linked to the review", async () => {
    installFetchStub({ bodies: { ...served, log: hindsightLog } });
    renderApp("/");
    expect((await screen.findByTestId("home-last-yours")).textContent).toBe("65");
    expect(screen.getByTestId("home-last-best").textContent).toContain("70");
    expect(screen.getByTestId("home-last-optimal").textContent).not.toBe("not available");
    const link = within(screen.getByTestId("home-last")).getByRole("link");
    expect(link.getAttribute("href")).toBe("/review");
  });

  it("shows only your points when the gameweek has no hindsight", async () => {
    installFetchStub({ bodies: served });
    renderApp("/");
    expect((await screen.findByTestId("home-last-yours")).textContent).toBe(String(seasonLog.gameweeks[2].score?.points));
    expect(screen.getByTestId("home-last").textContent).toContain("Hindsight is not published");
  });

  it("renders without the last gameweek card and says why when there is no log", async () => {
    installFetchStub({ bodies: served, missing: ["log"] });
    renderApp("/");
    await waitFor(() =>
      expect(screen.getByTestId("home-last-absent").textContent).toContain("No season log is published yet"),
    );
    expect(screen.queryByTestId("home-last-yours")).toBeNull();
  });

  it("summarises data health and raises a blocked gate as an alert", async () => {
    installFetchStub({ bodies: { ...served, health: blockedHealth } });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("home-health-gates").textContent).toContain("Blocked"));
    expect(screen.getByTestId("home-health").getAttribute("role")).toBe("alert");
    expect(within(screen.getByTestId("home-health")).getByRole("link").getAttribute("href")).toBe("/health");
  });

  it("says why there are no points when no history is published", async () => {
    installFetchStub({ bodies: served, missing: ["history" as never] });
    renderApp("/");
    expect((await screen.findByTestId("home-squad-no-points")).textContent).toContain("no points last gameweek");
  });
});
