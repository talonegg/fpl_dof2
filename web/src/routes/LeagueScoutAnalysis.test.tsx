import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { history } from "../components/player/testFixtures";
import { installFetchStub, renderApp, resetAppState } from "../test/render";

/** WEB-09, WEB-13 and WEB-14: the league team page, the Scouting hand-offs and the Analysis paths. */
describe("League: a team's last gameweek (WEB-09)", () => {
  beforeEach(() => {
    resetAppState();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("opens a published team from the table with XI, bench, captain and each player's points", async () => {
    installFetchStub({ bodies: { history } });
    renderApp("/league");
    fireEvent.click(await screen.findByText("Roy Race XI"));

    const page = await screen.findByTestId("league-team");
    expect(page.textContent).toContain("68 in gameweek 3");
    const raya = within(page).getByTestId("league-team-player-1");
    // Raya's double gameweek 3 (3 + 5) sums to 8; he is the captain.
    expect(raya.textContent).toContain("Captain");
    expect(raya.textContent).toContain("8");
    expect(within(page).getByTestId("league-team-player-2").textContent).toContain("Vice-captain");
    // Watkins has no recorded fixture in the history: a dash, not a zero.
    expect(within(page).getByTestId("league-team-player-2").textContent).toContain("—");
    // Player 4 is on the bench and not in players.json: shown as an id, not dropped.
    const bench = within(page).getByRole("heading", { name: /Bench/ }).parentElement!;
    expect(within(bench).getByTestId("league-team-player-4").textContent).toContain("#4");
    expect(within(page).queryByTestId("league-team-no-points")).toBeNull();
  });

  it("shows the XI and the team total, and says so, when no per-player points are published", async () => {
    installFetchStub({ missing: [] });
    renderApp("/league/100");
    const page = await screen.findByTestId("league-team");
    expect(within(page).getByTestId("league-team-player-1")).toBeTruthy();
    expect(within(page).getByTestId("league-team-no-points").textContent).toContain("68");
  });

  it("says a malformed season history is malformed, not unpublished", async () => {
    installFetchStub({ bodies: { history: "not a history" } });
    renderApp("/league/100");
    const note = await screen.findByTestId("league-team-no-points");
    await waitFor(() => expect(note.textContent).toContain("malformed"));
    expect(note.textContent).not.toContain("not published");
  });

  it("shows a rival's transfers, hit, chip and differentials with the points each was worth (ORC-14)", async () => {
    const withThree = {
      ...history,
      players: [
        ...history.players,
        { id: 3, gameweeks: [{ gw: 3, pts: 7, mins: 90, goals: 0, assists: 0, price: 5 }], prices: [] },
      ],
    };
    installFetchStub({ bodies: { history: withThree } });
    renderApp("/league/100");
    const moves = await screen.findByTestId("league-team-moves");
    expect(moves.textContent).toContain("→ #4");
    expect(moves.textContent).toContain("−4 points");
    // The chip by its label, not the API's "3xc".
    expect(moves.textContent).toContain("Chip: Triple Captain");
    const diff = screen.getByTestId("league-team-diff");
    // Only the fielded XI scores: their #4 and your #3 (7 raw points) are both on the bench.
    await waitFor(() => expect(within(diff).getByTestId("diff-3").textContent).toContain("0"));
    expect(within(diff).getByTestId("diff-4").textContent).toContain("0");
    // Both hold Raya (8): their Triple Captain armband from rules.json makes him 24; you field him at 8.
    expect(within(diff).getByTestId("diff-1").textContent).toContain("24 for them, 8 for you");
    // 24 - 8, less their 4-point hit: 12 to them.
    expect(within(diff).getByTestId("diff-net").textContent).toContain("12 points");
    expect(within(diff).getByTestId("diff-net").textContent).toContain("their hit of 4 counted");
  });

  it("degrades only the team whose moves were not fetched (ORC-14, NFR-15)", async () => {
    installFetchStub({ bodies: { history } });
    renderApp("/league/400");
    expect((await screen.findByTestId("league-team-no-moves")).textContent).toContain("not available");
    // Its squad and differentials still render.
    expect(screen.getByTestId("league-team-player-2")).toBeTruthy();
    expect(screen.getByTestId("league-team-diff").textContent).toContain("They hold, you do not");
  });

  it("says a team's squad was not published", async () => {
    installFetchStub({ bodies: { history } });
    renderApp("/league/300");
    expect((await screen.findByTestId("league-team-unpublished")).textContent).toContain("not published");
  });

  it("says when the entry does not exist", async () => {
    installFetchStub();
    renderApp("/league/999");
    expect(await screen.findByTestId("league-team-not-found")).toBeTruthy();
  });
});

describe("Scouting and Analysis hand-offs (WEB-13, WEB-14)", () => {
  beforeEach(() => {
    resetAppState();
    installFetchStub({ bodies: { history } });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("opens a club's players in the scout table from the fixture ticker", async () => {
    renderApp("/scout/fixtures");
    fireEvent.click(await screen.findByTestId("ticker-players-ARS"));
    await screen.findByTestId("player-table");
    const rows = screen.getAllByTestId("player-row");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("Raya");
  });

  it("opens the player page from the scout table, which lists what the sources hold", async () => {
    renderApp("/scout");
    await screen.findByTestId("player-table");
    fireEvent.click(within(screen.getAllByTestId("player-row")[0]).getByRole("link"));
    const sources = await screen.findByTestId("player-sources");
    expect(sources.textContent).toContain("D-23");
    expect(sources.textContent).toContain("archive");
  });

  it("sends the players selected in Scouting to compare at the Analysis path", async () => {
    window.localStorage.clear();
    renderApp("/scout");
    await screen.findByTestId("player-table");
    fireEvent.click(screen.getByTestId("compare-1"));
    fireEvent.click(screen.getByTestId("compare-2"));
    const go = screen.getByTestId("scout-compare-go");
    expect(go.getAttribute("href")).toBe("/analysis/compare?compare=1,2");
    fireEvent.click(go);
    await waitFor(() => expect(screen.queryByTestId("compare-empty")).toBeNull());
    expect(screen.getByTestId("tab-analysis-compare").className).toContain("active");
  });

  it("serves the squad builder at /analysis and compare at /analysis/compare", async () => {
    renderApp("/analysis");
    expect(await screen.findByTestId("squad-builder")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tab-analysis-compare"));
    expect(await screen.findByTestId("compare-empty")).toBeTruthy();
  });
});
