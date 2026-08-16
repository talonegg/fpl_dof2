import { describe, expect, it } from "vitest";
import type { League, LeagueSquad } from "../../contract/types";
import { leagueTable, players, preseasonLeague } from "../../test/fixtures";
import {
  buildLeagueView,
  byOverlapDescending,
  compareSquads,
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
    expect(view.rows.every((row) => row.pointsBehindLeader >= 0)).toBe(true);
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
