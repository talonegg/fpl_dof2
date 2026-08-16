import { describe, expect, it } from "vitest";
import { squadTotals } from "./totals";
import { squad } from "../../test/fixtures";

describe("squadTotals", () => {
  it("sums only starting players for the starting totals, and everyone for the squad total", () => {
    const totals = squadTotals(squad);
    // Fixture: Raya (starting, xp_next 4.199) + Watkins (starting, xp_next 4.517), Mbeumo benched.
    expect(totals.startingCount).toBe(2);
    expect(totals.startingXpNext).toBeCloseTo(4.199 + 4.517);
    expect(totals.benchXpNext).toBeCloseTo(3.2);
    expect(totals.squadXpNext).toBeCloseTo(4.199 + 4.517 + 3.2);
  });

  it("combines standard deviations in quadrature across the starting eleven", () => {
    const totals = squadTotals(squad);
    const expectedSd = Math.sqrt(1.89 ** 2 + 2.033 ** 2);
    expect(totals.startingSdNext).toBeCloseTo(expectedSd);
  });

  it("is undefined for the standard deviation when any starting player lacks one", () => {
    const missingSd = {
      ...squad,
      players: squad.players.map((player) =>
        player.player_id === 1 ? { ...player, xp_next_sd: undefined } : player,
      ),
    };
    const totals = squadTotals(missingSd);
    expect(totals.startingSdNext).toBeUndefined();
  });
});
