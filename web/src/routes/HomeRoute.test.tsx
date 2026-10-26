import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import { challengerWeek, modelsFixture, players, seasonLog, squad, strategiesFixture, week } from "../test/fixtures";
import { history } from "../components/player/testFixtures";
import { blockedHealth } from "../components/health/testFixtures";
import { mockLog } from "../components/review/fixtures";
import { liveGameweek, liveRoster } from "../test/liveFixtures";
import { formatLocalDateTime } from "../format";
import type { Live, Models, Squad, Week } from "../contract/types";

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

/** The squad card while a gameweek is in play (LIVE-06): every state `live.json` can be in. */
describe("Home with the gameweek in play (LIVE-06)", () => {
  beforeEach(() => resetAppState());
  afterEach(() => vi.unstubAllGlobals());

  const liveServed = (live: Live) => ({ ...served, players: liveRoster, live });
  const cell = (id: number) => screen.getByTestId(`home-squad-${id}-pts`).textContent;

  it("shows each player's points so far, the captain's multiplied, and the gameweek total and status", async () => {
    installFetchStub({ bodies: liveServed(liveGameweek("in_play")) });
    renderApp("/");

    const card = await screen.findByTestId("home-live");
    expect(card.textContent).toContain("Gameweek 4");
    expect(screen.getByTestId("home-live-status").textContent).toBe("In play");
    expect(screen.getByTestId("home-live-points").textContent).toContain("41");
    expect(screen.getByTestId("home-live-points").textContent).toContain("after a 4-point hit");
    expect(screen.getByTestId("home-live-total").textContent).toBe("239");
    expect(screen.getByTestId("home-live-rank").textContent).toBe("1");
    // Watkins is the captain: 8 points doubled, with the sum said.
    expect(cell(2)).toContain("16");
    expect(cell(2)).toContain("8 × 2");
    expect(cell(1)).toBe("6");
    // A bench player who did not come on shows his raw points and says he is on the bench.
    expect(within(screen.getByTestId("home-squad-13")).getAllByRole("cell")[1].textContent).toBe("0");
    expect(screen.getByTestId("home-squad-13").textContent).toContain("bench");
    // The fifteen are there, minutes included.
    expect(screen.getAllByTestId(/^home-squad-\d+$/)).toHaveLength(15);
    expect(within(screen.getByTestId("home-squad-3")).getAllByRole("cell")[0].textContent).toBe("67");
  });

  it("marks the figures provisional and says when they were last refreshed, in the reader's zone", async () => {
    installFetchStub({ bodies: liveServed(liveGameweek("in_play")) });
    renderApp("/");

    expect((await screen.findByTestId("home-live-provisional")).textContent).toBe("Provisional");
    const asOf = screen.getByTestId("home-live-as-of");
    expect(asOf.textContent).toBe(`Updated ${formatLocalDateTime("2026-09-19T21:30:00Z")}`);
    expect(asOf.querySelector("time")?.getAttribute("datetime")).toBe("2026-09-19T21:30:00Z");
  });

  it("names the projected substitution on both players, and under the table", async () => {
    installFetchStub({ bodies: liveServed(liveGameweek("in_play")) });
    renderApp("/");

    await screen.findByTestId("home-live");
    expect(screen.getByTestId("home-squad-12").textContent).toContain("on for Squad man 8 (projected)");
    expect(screen.getByTestId("home-squad-8").textContent).toContain("off for Squad man 12 (projected)");
    expect(screen.getByTestId("live-subs").textContent).toContain("Squad man 12 on for Squad man 8");
    // A starter yet to play keeps his place and is not substituted.
    expect(screen.getByTestId("home-squad-6").textContent).toContain("yet to play");
  });

  it("keeps the next gameweek's xP beside the points, and every model's advice below", async () => {
    installFetchStub({ bodies: liveServed(liveGameweek("in_play")) });
    renderApp("/");

    await screen.findByTestId("home-live");
    expect(screen.getByRole("columnheader", { name: "xP next" })).toBeTruthy();
    expect(within(screen.getByTestId("home-squad-2")).getAllByRole("cell")[2].textContent).toBe("4.52");
    const card = screen.getByTestId("home-models");
    for (const m of modelsFixture.models) expect(within(card).getByTestId(`home-model-${m.id}`)).toBeTruthy();
  });

  it("renders a complete gameweek, still provisional until FPL data-checks it", async () => {
    installFetchStub({ bodies: liveServed(liveGameweek("complete")) });
    renderApp("/");

    expect((await screen.findByTestId("home-live-status")).textContent).toBe("Complete");
    expect(screen.getByTestId("home-live-provisional")).toBeTruthy();
    expect(screen.getByTestId("home-live-points").textContent).toContain("42");
  });

  it("renders a bonus-pending gameweek as such", async () => {
    installFetchStub({ bodies: liveServed(liveGameweek("bonus_pending")) });
    renderApp("/");

    expect((await screen.findByTestId("home-live-status")).textContent).toBe("Bonus pending");
    expect(screen.getByTestId("home-live-provisional")).toBeTruthy();
  });

  it("renders a final gameweek without the provisional mark", async () => {
    installFetchStub({ bodies: liveServed(liveGameweek("final")) });
    renderApp("/");

    expect((await screen.findByTestId("home-live-status")).textContent).toBe("Final");
    expect(screen.queryByTestId("home-live-provisional")).toBeNull();
  });

  it("is today's card, with last gameweek's points, when no live.json is published", async () => {
    installFetchStub({ bodies: served });
    renderApp("/");

    const raya = await screen.findByTestId("home-squad-1");
    await waitFor(() => expect(raya.textContent).toContain("8"));
    expect(screen.getByRole("columnheader", { name: "GW4 pts" })).toBeTruthy();
    expect(screen.queryByTestId("home-live")).toBeNull();
    expect(screen.queryByTestId("live-subs")).toBeNull();
  });

  it("keeps today's card, and says why, when the gameweek is in play but your team has no live figure", async () => {
    const live = liveGameweek("in_play");
    const owner = live.teams.find((t) => t.is_owner)!;
    const without = { ...live, teams: live.teams.map((t) => (t === owner ? { ...t, live: null, rank: null, reason: "no picks were read for this team" } : t)) };
    installFetchStub({ bodies: liveServed(without) });
    renderApp("/");

    expect((await screen.findByTestId("home-live-not-live")).textContent).toContain("no picks were read for this team");
    expect(screen.queryByTestId("home-live")).toBeNull();
    expect(screen.getByRole("columnheader", { name: "xP next" })).toBeTruthy();
  });

  it("falls back to today's card when live.json cannot be read", async () => {
    installFetchStub({ bodies: { ...served, players: liveRoster, live: { contract_version: 1, unrelated: true } } });
    renderApp("/");

    await screen.findByTestId("home-squad-1");
    await waitFor(() => expect(screen.queryByTestId("home-live")).toBeNull());
    // As the league does: the fallback is stated, not silent.
    expect(screen.getByTestId("home-live-unavailable").textContent).toContain("could not be read");
  });

  it("does not claim the live gameweek is unreadable when none is published", async () => {
    installFetchStub({ bodies: { ...served, players: liveRoster } });
    renderApp("/");

    await screen.findByTestId("home-squad-1");
    expect(screen.queryByTestId("home-live-unavailable")).toBeNull();
  });
});

/** The re-read on becoming visible (LIVE-06, R1.4.3 §5 Q5): no reload, no timer, nothing while hidden. */
describe("an open app that becomes visible again (LIVE-06)", () => {
  beforeEach(() => resetAppState());
  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(document, "visibilityState");
  });

  const setVisibility = (state: "visible" | "hidden") => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
  };
  const requests = (spy: ReturnType<typeof installFetchStub>, name: string) =>
    spy.mock.calls.filter(([url]) => String(url).endsWith(`/${name}.json`)).length;

  it("shows a new live.json after a deploy, in place, without a reload", async () => {
    installFetchStub({ bodies: { ...served, players: liveRoster, live: liveGameweek("in_play") } });
    renderApp("/");
    expect((await screen.findByTestId("home-live-status")).textContent).toBe("In play");
    const card = screen.getByTestId("home-squad");

    // A matchday refresh is published while the app sits hidden; the owner comes back to it.
    setVisibility("hidden");
    installFetchStub({ bodies: { ...served, players: liveRoster, live: liveGameweek("complete") } });
    setVisibility("visible");

    await waitFor(() => expect(screen.getByTestId("home-live-status").textContent).toBe("Complete"));
    expect(screen.getByTestId("home-live-points").textContent).toContain("42");
    // The same page, updated: the card was never swapped for a loading view.
    expect(screen.queryByTestId("app-loading")).toBeNull();
    expect(screen.getByTestId("home-squad")).toBe(card);
  });

  it("picks up a live.json that has appeared, and drops one that has gone", async () => {
    installFetchStub({ bodies: { ...served, players: liveRoster } });
    renderApp("/");
    await screen.findByTestId("home-squad-1");
    expect(screen.queryByTestId("home-live")).toBeNull();

    installFetchStub({ bodies: { ...served, players: liveRoster, live: liveGameweek("in_play") } });
    setVisibility("visible");
    expect((await screen.findByTestId("home-live")).textContent).toContain("Gameweek 4");

    // The next deadline moves the live tables on and the file goes: today's card again.
    installFetchStub({ bodies: { ...served, players: liveRoster } });
    setVisibility("visible");
    await waitFor(() => expect(screen.queryByTestId("home-live")).toBeNull());
    expect(screen.getByTestId("home-squad-1")).toBeTruthy();
  });

  it("fetches nothing while the document is hidden, and has no timer", async () => {
    const spy = installFetchStub({ bodies: { ...served, players: liveRoster, live: liveGameweek("in_play") } });
    renderApp("/");
    await screen.findByTestId("home-live");
    const before = spy.mock.calls.length;

    // Hiding the document, and a hidden document being told it changed, ask for nothing.
    setVisibility("hidden");
    setVisibility("hidden");
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(spy.mock.calls.length).toBe(before);

    // Becoming visible is the only trigger, and it asks for the live file again.
    setVisibility("visible");
    await waitFor(() => expect(requests(spy, "live")).toBe(2));
  });

  it("keeps what is on screen when the refresh cannot reach the network", async () => {
    installFetchStub({ bodies: { ...served, players: liveRoster, live: liveGameweek("in_play") } });
    renderApp("/");
    await screen.findByTestId("home-live");

    installFetchStub({ bodies: { ...served, players: liveRoster }, failing: ["live", "week"] });
    setVisibility("visible");
    await waitFor(() => expect(screen.getByTestId("home-squad")).toBeTruthy());
    expect(screen.getByTestId("home-live-status").textContent).toBe("In play");
    expect(screen.queryByTestId("app-error")).toBeNull();
  });
});
