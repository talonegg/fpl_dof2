import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { Live } from "../../contract/types";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { liveGameweek, liveRoster } from "../../test/liveFixtures";
import { preseasonLeague } from "../../test/fixtures";
import { formatLocalDateTime } from "../../format";

/**
 * The league during the gameweek (LIVE-05, FR-32): the table ordered by live total, and a team's
 * drill-down down to each player. The properties worth holding are the ones that would otherwise
 * be wrong quietly: a team with no live figure must not be ranked as though it scored nothing, a
 * provisional figure must say so, and a scorer that disagrees with FPL must be visible (DP-13).
 */
describe("LeagueTable with the gameweek in play (LIVE-05)", () => {
  beforeEach(() => resetAppState());
  afterEach(() => vi.unstubAllGlobals());

  async function renderLeague(live: Live | null = liveGameweek("in_play")) {
    installFetchStub({ bodies: { players: liveRoster, ...(live ? { live } : {}) } });
    renderApp("/league");
    await waitFor(() => expect(screen.getByTestId("league-table")).toBeTruthy());
    // The table waits for live.json too, so the order below is the live one from the first paint.
  }
  const order = () => screen.getAllByTestId(/^league-row-\d+$/).map((r) => r.getAttribute("data-testid"));
  const row = (id: number) => within(screen.getByTestId(`league-row-${id}`));

  it("orders the table by live total, with the live rank and the movement since FPL's last rank", async () => {
    await renderLeague();

    // The league table has 100, 200, 300, 400. Live, the owner has overtaken 100, and 300, which
    // has no live figure, follows every team that has one.
    expect(order()).toEqual(["league-row-200", "league-row-100", "league-row-400", "league-row-300"]);
    expect(screen.getByTestId("league-total-200").textContent).toBe("239");
    expect(screen.getByTestId("league-total-100").textContent).toBe("228");
    expect(screen.getByRole("columnheader", { name: "Live total" })).toBeTruthy();
    // 100 was 3rd at FPL's last rank and is 2nd live: one place gained, said in words as well.
    expect(screen.getByTestId("league-row-100").querySelector(".league-rank")?.textContent).toContain("2▲1 places gained");
    // The owner was and is first: no movement is claimed.
    expect(screen.getByTestId("league-row-200").querySelector(".league-rank")?.textContent).toBe("1");
  });

  it("shows each team's gameweek points, its hit and chip, and its status in words", async () => {
    await renderLeague();

    expect(screen.getByTestId("league-gw-200").textContent).toContain("41");
    expect(screen.getByTestId("league-gw-200").textContent).toContain("after a 4-point hit");
    expect(screen.getByTestId("league-gw-100").textContent).toContain("18");
    expect(screen.getByTestId("league-gw-100").textContent).toContain("Triple Captain");
    expect(screen.getByTestId("league-status-200").textContent).toContain("In play");
    expect(screen.getByTestId("league-status-100").textContent).toContain("In play");
  });

  it("marks every row provisional, and the table, until the gameweek is final", async () => {
    await renderLeague();

    for (const id of [200, 100, 400]) expect(screen.getByTestId(`league-provisional-${id}`).textContent).toBe("Provisional");
    const summary = screen.getByTestId("league-live");
    expect(summary.textContent).toContain("Gameweek 4, ordered by live total");
    expect(within(summary).getByTestId("league-live-status").textContent).toBe("In play");
    expect(within(summary).getByTestId("league-live-provisional")).toBeTruthy();
    expect(screen.getByTestId("league-live-as-of").textContent).toBe(`Updated ${formatLocalDateTime("2026-09-19T21:30:00Z")}`);
  });

  it("drops the provisional marks once every team is final", async () => {
    await renderLeague(liveGameweek("final"));

    expect(screen.getByTestId("league-live-status").textContent).toBe("Final");
    expect(screen.queryByTestId("league-live-provisional")).toBeNull();
    expect(screen.queryByText("Provisional")).toBeNull();
    expect(screen.getByTestId("league-status-200").textContent).toContain("Final");
  });

  it("shows a team without a live figure as not live, on the league table's own figures", async () => {
    await renderLeague();

    const status = screen.getByTestId("league-not-live-300");
    expect(status.textContent).toBe("not live");
    // The reason is on the mark for anyone who asks for it.
    expect(status.getAttribute("title")).toContain("past the rival limit");
    // The league table's own total and last scored gameweek, the latter labelled as such.
    expect(screen.getByTestId("league-total-300").textContent).toBe("175");
    expect(screen.getByTestId("league-gw-300").textContent).toContain("41");
    expect(screen.getByTestId("league-gw-300").textContent).toContain("GW3, last scored");
    // Its total is a gameweek behind everyone else's, so no gap to the live leader is claimed.
    expect(row(300).getAllByRole("cell")[5].textContent).toBe("—");
    // It is not provisional: it carries no live figure to move.
    expect(screen.queryByTestId("league-provisional-300")).toBeNull();
    expect(row(300).getByText(/league table rank, not live/)).toBeTruthy();
  });

  it("makes a mismatch with FPL visible on the row", async () => {
    const live = liveGameweek("final");
    const mismatched: Live = {
      ...live,
      teams: live.teams.map((t) =>
        t.entry_id === 100 && t.game ? { ...t, matches_game: false, game: { ...t.game, points: 19 } } : t,
      ),
    };
    await renderLeague(mismatched);

    const note = screen.getByTestId("league-mismatch-100");
    expect(note.textContent).toContain("Differs from FPL");
    expect(note.textContent).toContain("its own figure is 19 before a 0-point hit");
    expect(note.textContent).toContain("this table has 18");
    // Agreement says nothing.
    expect(screen.queryByTestId("league-mismatch-200")).toBeNull();
  });

  it("keeps the comparison columns, and the names and expand control stay operable by keyboard", async () => {
    await renderLeague();

    // Team names are links and the overlap is a button: the native controls a keyboard reaches.
    expect(row(300).getByRole("link", { name: "Beyond The Budget" }).getAttribute("href")).toBe("/league/300");
    const expand = row(100).getByRole("button", { name: /players shared/ });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(expand);
    const detail = screen.getByTestId("league-detail-100");
    expect(expand.getAttribute("aria-expanded")).toBe("true");
    // The detail spans every column, the live ones included.
    expect(detail.querySelector("td")?.getAttribute("colspan")).toBe("10");
    expect(within(detail).getByText(/Raya, Watkins/)).toBeTruthy();
    // Status is text in its own column, not a colour.
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeTruthy();
  });

  it("does not say no gameweek has been scored beside a live table in the first gameweek", async () => {
    installFetchStub({ bodies: { league: preseasonLeague, players: liveRoster, live: liveGameweek("in_play") } });
    renderApp("/league");

    await waitFor(() => expect(screen.getByTestId("league-table")).toBeTruthy());
    expect(screen.getByTestId("league-live")).toBeTruthy();
    expect(screen.queryByTestId("league-anchor")).toBeNull();
    expect(screen.getByTestId("league-table").textContent).not.toContain("No gameweek has been scored");
    expect(screen.getByTestId("league-table").textContent).not.toContain("before any gameweek has been scored");
  });

  it("still says it before a gameweek is scored when there is no live.json", async () => {
    installFetchStub({ bodies: { league: preseasonLeague } });
    renderApp("/league");

    await waitFor(() => expect(screen.getByTestId("league-table")).toBeTruthy());
    expect(screen.getByTestId("league-anchor").textContent).toContain("No gameweek has been scored");
  });

  it("is today's table when live.json is absent", async () => {
    await renderLeague(null);

    expect(order()).toEqual(["league-row-100", "league-row-200", "league-row-300", "league-row-400"]);
    expect(screen.queryByTestId("league-live")).toBeNull();
    expect(screen.queryByText("not live")).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Status" })).toBeNull();
  });

  it("falls back to the league table, and says so, when live.json is unreadable", async () => {
    installFetchStub({ bodies: { live: { contract_version: 1, unrelated: true } } });
    renderApp("/league");

    await waitFor(() => expect(screen.getByTestId("league-table")).toBeTruthy());
    expect(screen.getByTestId("league-live-unavailable").textContent).toContain("could not be read");
    expect(screen.queryByTestId("league-live")).toBeNull();
    expect(order()[0]).toBe("league-row-100");
  });

  it("re-orders in place when the app is next looked at and a refresh has moved the totals", async () => {
    await renderLeague();
    const table = screen.getByTestId("league-table");

    // The next matchday: entry 100 scores big and takes the lead.
    const live = liveGameweek("bonus_pending");
    const moved: Live = {
      ...live,
      teams: live.teams.map((t) => {
        if (t.entry_id === 100 && t.live) return { ...t, rank: 1, live: { ...t.live, live_total: 250 } };
        if (t.entry_id === 200) return { ...t, rank: 2 };
        return t;
      }),
    };
    installFetchStub({ bodies: { players: liveRoster, live: moved } });
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() => expect(order()[0]).toBe("league-row-100"));
    expect(screen.getByTestId("league-total-100").textContent).toBe("250");
    expect(screen.getByTestId("league-live-status").textContent).toBe("Bonus pending");
    expect(screen.getByTestId("league-table")).toBe(table);
    Reflect.deleteProperty(document, "visibilityState");
  });
});

/** A team's drill-down (WEB-09) with the gameweek in play: every player's live points, minutes and bonus. */
describe("LeagueTeam with the gameweek in play (LIVE-05)", () => {
  beforeEach(() => resetAppState());
  afterEach(() => vi.unstubAllGlobals());

  const open = async (entryId: number, live: Live | null = liveGameweek("in_play")) => {
    installFetchStub({ bodies: { players: liveRoster, ...(live ? { live } : {}) } });
    renderApp(`/league/${entryId}`);
    await screen.findByTestId("league-team");
  };
  const player = (id: number) => within(screen.getByTestId(`live-player-${id}`));
  const cells = (id: number) => player(id).getAllByRole("cell").map((c) => c.textContent);

  it("shows each player's minutes, points so far and bonus, confirmed or pending", async () => {
    await open(200);

    const live = within(screen.getByTestId("league-team-live"));
    expect(live.getByRole("heading", { name: "Gameweek 4, live" })).toBeTruthy();
    // Raya: ninety minutes, six points, no bonus to come.
    expect(cells(1)).toEqual(["90", "6", "no bonus"]);
    // Watkins, the captain: 8 points doubled, with his bonus confirmed.
    expect(cells(2)[1]).toContain("16");
    expect(cells(2)[1]).toContain("8 × 2");
    expect(cells(2)[2]).toBe("+2 bonus, confirmed");
    // Mbeumo is still playing: his bonus is pending, not zero.
    expect(cells(3)).toEqual(["67", "5", "bonus pending"]);
    // Squad man 10 earned three bonus points, confirmed.
    expect(cells(10)[2]).toBe("+3 bonus, confirmed");
    expect(live.getAllByTestId(/^live-player-\d+$/)).toHaveLength(15);
  });

  it("names the projected substitutions, and leaves a starter yet to play where he is", async () => {
    await open(200);

    expect(screen.getByTestId("live-player-12").textContent).toContain("on for Squad man 8 (projected)");
    expect(screen.getByTestId("live-player-8").textContent).toContain("off for Squad man 12 (projected)");
    expect(screen.getByTestId("live-subs").textContent).toContain("Squad man 12 on for Squad man 8");
    expect(screen.getByTestId("live-player-6").textContent).toContain("yet to play");
    expect(screen.getByTestId("live-player-6").textContent).not.toContain("projected");
    // The bench player who stays on the bench is labelled so.
    expect(screen.getByTestId("live-player-13").textContent).toContain("bench");
  });

  it("states the team's status, points, hit, live total and rank, provisional until final", async () => {
    await open(200);

    expect(screen.getByTestId("league-team-live-status").textContent).toBe("In play");
    expect(screen.getByTestId("league-team-live-provisional").textContent).toBe("Provisional");
    expect(screen.getByTestId("league-team-live-points").textContent).toBe("41 points after a 4-point hit");
    expect(screen.getByTestId("league-team-live-total").textContent).toBe("239 in total, rank 1 by live total");
  });

  it("applies the chip's multiplier as published, and links players to their pages", async () => {
    await open(100);

    // Triple Captain: 3 points times three, from the published multiplier.
    expect(cells(2)[1]).toContain("9");
    expect(cells(2)[1]).toContain("3 × 3");
    expect(within(screen.getByTestId("live-player-2")).getByRole("link", { name: "Watkins" }).getAttribute("href")).toBe("/player/2");
    expect(screen.getByTestId("league-team-live-points").textContent).toContain("Triple Captain played");
  });

  it("is not provisional once final, and shows a mismatch with FPL where there is one", async () => {
    const live = liveGameweek("final");
    const mismatched: Live = {
      ...live,
      teams: live.teams.map((t) => (t.entry_id === 100 && t.game ? { ...t, matches_game: false, game: { ...t.game, points: 19 } } : t)),
    };
    await open(100, mismatched);

    expect(screen.getByTestId("league-team-live-status").textContent).toBe("Final");
    expect(screen.queryByTestId("league-team-live-provisional")).toBeNull();
    expect(screen.getByTestId("league-team-live-mismatch").textContent).toContain("its own figure is 19");
  });

  it("says a team is not live, and why, instead of inventing a gameweek for it", async () => {
    await open(300);

    const note = screen.getByTestId("league-team-not-live");
    expect(note.textContent).toContain("not live");
    expect(note.textContent).toContain("past the rival limit, so its picks were not read");
    expect(screen.queryByTestId("league-team-live-points")).toBeNull();
    expect(screen.queryByTestId("live-subs")).toBeNull();
  });

  it("has no live section without live.json", async () => {
    await open(200, null);

    expect(screen.queryByTestId("league-team-live")).toBeNull();
    expect(screen.getByTestId("league-team-moves")).toBeTruthy();
  });
});
