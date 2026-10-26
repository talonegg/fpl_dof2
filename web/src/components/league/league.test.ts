import { describe, expect, it } from "vitest";
import type { League, LeagueSquad } from "../../contract/types";
import { leagueTable, players, preseasonLeague } from "../../test/fixtures";
import { liveGameweek } from "../../test/liveFixtures";
import {
  buildLeagueView,
  byOverlapDescending,
  compareSquads,
  fieldedPoints,
  nameList,
  playerNames,
} from "./league";

function squadOf(ids: number[], captain: number | null): LeagueSquad {
  return {
    player_ids: ids,
    starting_ids: ids.slice(0, 11),
    captain_id: captain,
    vice_captain_id: null,
  };
}

describe("fieldedPoints (ORC-14)", () => {
  const chips = { captain_multiplier: 2, captain_multiplier_by_chip: { "3xc": 3 }, bench_scores_with: [], transfers_free_with: [] };
  const squad: LeagueSquad = { player_ids: [1, 2, 3], starting_ids: [1, 2], captain_id: 1, vice_captain_id: 2 };
  const ten = () => 10;

  it("counts the fielded XI only, the captain at the configured multiplier", () => {
    expect([...fieldedPoints(squad, null, chips, ten)]).toEqual([[1, 20], [2, 10], [3, 0]]);
  });

  it("takes the chip's armband from the rules, and passes it to the vice when the captain was not fielded", () => {
    expect(fieldedPoints(squad, "3xc", chips, ten).get(1)).toBe(30);
    const subbed = { ...squad, starting_ids: [2, 3] };
    expect([...fieldedPoints(subbed, null, chips, ten)]).toEqual([[1, 0], [2, 20], [3, 10]]);
  });

  it("applies no multiplier when the rules publish none, and keeps unknown points unknown", () => {
    expect(fieldedPoints(squad, null, undefined, ten).get(1)).toBe(10);
    expect(fieldedPoints(squad, null, chips, () => null).get(1)).toBeNull();
  });
});

describe("compareSquads", () => {
  it("splits two squads into shared, theirs alone and yours alone", () => {
    const result = compareSquads(squadOf([1, 2, 3], 2), squadOf([2, 3, 4], 3));

    expect(result.overlapIds).toEqual([2, 3]);
    expect(result.ownerOnlyIds).toEqual([1]);
    expect(result.rivalOnlyIds).toEqual([4]);
  });

  it("keeps the two differential directions separate, never summed", () => {
    // Asymmetric on purpose: one player only the owner holds, three only the rival does. A single
    // "differentials" count would report four and say nothing about which way the risk runs.
    const result = compareSquads(squadOf([1, 2], 1), squadOf([2, 5, 6, 7], 5));

    expect(result.ownerOnlyIds).toEqual([1]);
    expect(result.rivalOnlyIds).toEqual([5, 6, 7]);
  });

  it("reports captain divergence, and agreement, as different answers", () => {
    expect(compareSquads(squadOf([1], 1), squadOf([1], 2)).captainDiverges).toBe(true);
    expect(compareSquads(squadOf([1], 1), squadOf([1], 1)).captainDiverges).toBe(false);
  });

  it("returns null divergence when either captain is unpublished, not false", () => {
    // The failure this guards: an unknown captain rendering identically to an agreeing one, which
    // would tell the reader they are covered when nobody measured it (DP-09).
    expect(compareSquads(squadOf([1], 1), squadOf([1], null)).captainDiverges).toBeNull();
    expect(compareSquads(squadOf([1], null), squadOf([1], 1)).captainDiverges).toBeNull();
  });
});

describe("buildLeagueView", () => {
  it("orders by rank and marks the owner's row", () => {
    const view = buildLeagueView(leagueTable);

    expect(view.rows.map((row) => row.entry.entry_id)).toEqual([100, 200, 300, 400]);
    expect(view.owner?.entry_id).toBe(200);
    expect(view.rows.filter((row) => row.isOwner)).toHaveLength(1);
  });

  it("anchors the comparison on the owner's own squad", () => {
    const view = buildLeagueView(leagueTable);
    const rival = view.rows.find((row) => row.entry.entry_id === 100);

    expect(view.anchor).toBe("anchored");
    // Owner holds 1,2,3; this rival holds 1,2,4.
    expect(rival?.comparison?.overlapIds).toEqual([1, 2]);
    expect(rival?.comparison?.ownerOnlyIds).toEqual([3]);
    expect(rival?.comparison?.rivalOnlyIds).toEqual([4]);
    expect(rival?.comparison?.captainDiverges).toBe(true);
  });

  it("leaves a rival with no published squad without a comparison, not with an empty one", () => {
    const view = buildLeagueView(leagueTable);
    const unfetched = view.rows.find((row) => row.entry.entry_id === 300);

    expect(unfetched?.comparison).toBeNull();
    expect(view.comparableCount).toBe(2);
  });

  it("never compares the owner against themselves", () => {
    const view = buildLeagueView(leagueTable);
    expect(view.rows.find((row) => row.isOwner)?.comparison).toBeNull();
  });

  it("refuses to anchor when no gameweek has been scored", () => {
    const view = buildLeagueView(preseasonLeague);

    expect(view.anchor).toBe("no_gameweek");
    expect(view.rows.every((row) => row.comparison === null)).toBe(true);
  });

  it("refuses to anchor when the owner is not in the league", () => {
    const withoutOwner: League = {
      ...leagueTable,
      entries: leagueTable.entries.map((entry) => ({ ...entry, is_owner: false })),
    };

    expect(buildLeagueView(withoutOwner).anchor).toBe("no_owner_row");
  });

  it("refuses to anchor when the owner has no squad published for the gameweek", () => {
    const ownerWithoutSquad: League = {
      ...leagueTable,
      entries: leagueTable.entries.map((entry) =>
        entry.is_owner ? { ...entry, squad: null } : entry,
      ),
    };

    const view = buildLeagueView(ownerWithoutSquad);
    expect(view.anchor).toBe("no_owner_squad");
    // And no rival gets a comparison off the back of a missing anchor.
    expect(view.rows.every((row) => row.comparison === null)).toBe(true);
  });

  it("reads rank movement, and treats a first-ever placing as unknown rather than static", () => {
    const view = buildLeagueView(leagueTable);
    const byId = new Map(view.rows.map((row) => [row.entry.entry_id, row]));

    expect(byId.get(100)?.rankChange).toBe(2); // 3rd to 1st
    expect(byId.get(200)?.rankChange).toBe(-1); // 1st to 2nd
    expect(byId.get(400)?.rankChange).toBeNull(); // last_rank 0: never placed
  });

  it("measures the gap to the leader, and never below zero", () => {
    const view = buildLeagueView(leagueTable);
    const byId = new Map(view.rows.map((row) => [row.entry.entry_id, row]));

    expect(byId.get(100)?.pointsBehindLeader).toBe(0);
    expect(byId.get(200)?.pointsBehindLeader).toBe(12);
    expect(view.rows.every((row) => (row.pointsBehindLeader ?? 0) >= 0)).toBe(true);
  });
});

describe("buildLeagueView with the gameweek in play (LIVE-05)", () => {
  const ids = (view: ReturnType<typeof buildLeagueView>) => view.rows.map((row) => row.entry.entry_id);

  it("is the plain table, in FPL's order, without live.json", () => {
    const view = buildLeagueView(leagueTable, null);
    expect(view.mode).toBe("table");
    expect(ids(view)).toEqual([100, 200, 300, 400]);
    expect(view.rows.every((row) => row.figures === null && row.liveTeam === null)).toBe(true);
    expect(view.rows.map((row) => row.shownRank)).toEqual([1, 2, 3, 4]);
  });

  it("orders by live total, with the live rank, and puts a team with no live figure last", () => {
    const view = buildLeagueView(leagueTable, liveGameweek());
    expect(view.mode).toBe("live");
    // The owner overtakes entry 100; entry 300 is not live, so it follows every live team even
    // though the league table has it third, and keeps the league table's own rank.
    expect(ids(view)).toEqual([200, 100, 400, 300]);
    expect(view.rows.map((row) => row.shownRank)).toEqual([1, 2, 3, 3]);
    expect(view.rows[3].figures).toBeNull();
    expect(view.rows[3].liveTeam?.reason).toContain("rival limit");
  });

  it("keeps the league table's own order among the teams that are not live", () => {
    const live = liveGameweek();
    const dark = { ...live, teams: live.teams.map((t) => (t.entry_id === 400 ? { ...t, live: null, rank: null, reason: "x" } : t)) };
    // 300 (league 3rd) before 400 (league 4th), both after the live teams.
    expect(ids(buildLeagueView(leagueTable, dark))).toEqual([200, 100, 300, 400]);
  });

  it("lets equal live totals share a rank, as published, and keeps the league's order within it", () => {
    const live = liveGameweek();
    const tied = {
      ...live,
      teams: live.teams.map((t) => (t.entry_id === 200 || t.entry_id === 100 ? { ...t, rank: 2 } : t)),
    };
    const view = buildLeagueView(leagueTable, tied);
    expect(view.rows.slice(0, 2).map((row) => row.shownRank)).toEqual([2, 2]);
    expect(ids(view).slice(0, 2)).toEqual([100, 200]); // league order: 100 is 1st, 200 is 2nd
  });

  it("reads movement as FPL's last rank less the live rank, and a first placing as unknown", () => {
    const byId = new Map(buildLeagueView(leagueTable, liveGameweek()).rows.map((row) => [row.entry.entry_id, row]));
    expect(byId.get(200)?.rankChange).toBe(0); // last rank 1, live 1st
    expect(byId.get(100)?.rankChange).toBe(1); // last rank 3, live 2nd
    expect(byId.get(400)?.rankChange).toBeNull(); // last_rank 0: never placed
    expect(byId.get(300)?.rankChange).toBe(-1); // not live: the league table's own, 2nd to 3rd
  });

  it("measures the gap on live totals, and leaves a team that is not live without one", () => {
    const byId = new Map(buildLeagueView(leagueTable, liveGameweek()).rows.map((row) => [row.entry.entry_id, row]));
    expect(byId.get(200)?.pointsBehindLeader).toBe(0);
    expect(byId.get(100)?.pointsBehindLeader).toBe(11); // 239 less 228
    expect(byId.get(300)?.pointsBehindLeader).toBeNull();
  });

  it("treats a league entry missing from live.json as not live", () => {
    const live = liveGameweek();
    const view = buildLeagueView(leagueTable, { ...live, teams: live.teams.filter((t) => t.entry_id !== 100) });
    expect(ids(view)).toEqual([200, 400, 100, 300]);
    expect(view.rows.find((row) => row.entry.entry_id === 100)?.liveTeam).toBeNull();
  });
});

describe("byOverlapDescending", () => {
  it("sorts the most alike first and puts unmeasured rows last", () => {
    const view = buildLeagueView(leagueTable);
    const ordered = byOverlapDescending(view.rows);

    // 100 and 400 share two each and tie-break on rank; the owner and the unfetched rival have no
    // comparison and sort last rather than as a zero overlap.
    expect(ordered.map((row) => row.entry.entry_id).slice(0, 2)).toEqual([100, 400]);
    expect(ordered.slice(2).every((row) => row.comparison === null)).toBe(true);
  });
});

describe("nameList", () => {
  it("names known players and keeps unknown ids visible rather than dropping them", () => {
    const names = playerNames(players);
    // A dropped id would turn an overlap of three into an overlap of two, silently.
    expect(nameList([1, 2, 99], names)).toEqual(["Raya", "Watkins", "#99"]);
  });
});
