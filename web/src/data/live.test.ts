import { describe, expect, it } from "vitest";
import { liveGameweek } from "../test/liveFixtures";
import {
  bonusText,
  countedPoints,
  fieldedAndBench,
  isProvisional,
  liveFigures,
  liveOwner,
  liveTeam,
  statusLabel,
  statusMeaning,
  substitutions,
} from "./live";

describe("reading live.json (LIVE-05, LIVE-06)", () => {
  const live = liveGameweek("in_play");
  const owner = liveOwner(live)!;
  const figures = liveFigures(owner)!;

  it("finds the owner and a team by entry id, and nothing in no live.json", () => {
    expect(owner.entry_id).toBe(200);
    expect(liveTeam(live, 100)?.entry_name).toBe("Roy Race XI");
    expect(liveTeam(live, 999)).toBeUndefined();
    expect(liveTeam(null, 100)).toBeUndefined();
    expect(liveOwner(null)).toBeUndefined();
  });

  it("gives a team with no live figure no figures", () => {
    expect(liveFigures(liveTeam(live, 300))).toBeNull();
    expect(liveFigures(undefined)).toBeNull();
  });

  it("names every status in words, with its meaning", () => {
    expect((["in_play", "bonus_pending", "complete", "final"] as const).map(statusLabel)).toEqual([
      "In play",
      "Bonus pending",
      "Complete",
      "Final",
    ]);
    expect(statusMeaning("final")).toContain("data-checked");
  });

  it("is provisional until the team's own status is final", () => {
    expect(isProvisional(figures)).toBe(true);
    expect(isProvisional(liveFigures(liveOwner(liveGameweek("complete")))!)).toBe(true);
    expect(isProvisional(liveFigures(liveOwner(liveGameweek("final")))!)).toBe(false);
  });

  it("counts a player at his points times the multiplier as published", () => {
    expect(countedPoints({ points: 8, multiplier: 2 })).toBe(16);
    expect(countedPoints({ points: 8, multiplier: 0 })).toBe(0);
  });

  it("pairs each substitute with the starter he replaces, in the order the scorer made them", () => {
    expect(substitutions(figures)).toEqual([{ on: 12, off: 8 }]);
    expect(substitutions({ ...figures, autosubs_in: [12, 13], autosubs_out: [8, 4] })).toEqual([
      { on: 12, off: 8 },
      { on: 13, off: 4 },
    ]);
    expect(substitutions({ ...figures, autosubs_in: [], autosubs_out: [] })).toEqual([]);
  });

  it("splits the fifteen into those on the field and the bench, each in slot order", () => {
    const { fielded, bench } = fieldedAndBench(figures);
    expect(fielded.map((p) => p.player_id)).toEqual([1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12]);
    expect(bench.map((p) => p.player_id)).toEqual([8, 13, 14, 15]);
  });

  it("puts a bonus in words: confirmed, pending, or none", () => {
    const over = { complete: true, minutes: 90 };
    expect(bonusText({ bonus: 3, bonus_confirmed: true, ...over })).toBe("+3 bonus, confirmed");
    expect(bonusText({ bonus: 0, bonus_confirmed: true, ...over })).toBe("no bonus");
    // Pending is only said once his match is over and FPL has not confirmed the bonus.
    expect(bonusText({ bonus: 1, bonus_confirmed: false, ...over })).toBe("+1 bonus, pending");
    expect(bonusText({ bonus: 0, bonus_confirmed: false, ...over })).toBe("bonus pending");
  });

  it("does not call a bonus pending for a player whose match is not over", () => {
    // Yet to play: no fixture of his has finished, so there is nothing to be pending.
    expect(bonusText({ bonus: 0, bonus_confirmed: false, complete: false, minutes: 0 })).toBe("yet to play");
    // The pipeline reads a player with no fixture rows yet as "confirmed"; he is still yet to play.
    expect(bonusText({ bonus: 0, bonus_confirmed: true, complete: false, minutes: 0 })).toBe("yet to play");
    // Playing now: his match is not over, and FPL's bonus so far can still move.
    expect(bonusText({ bonus: 0, bonus_confirmed: false, complete: false, minutes: 67 })).toBe("match not over");
    expect(bonusText({ bonus: 2, bonus_confirmed: false, complete: false, minutes: 67 })).toBe(
      "+2 bonus so far, match not over",
    );
    for (const text of [
      bonusText({ bonus: 0, bonus_confirmed: false, complete: false, minutes: 0 }),
      bonusText({ bonus: 0, bonus_confirmed: false, complete: false, minutes: 67 }),
    ]) {
      expect(text).not.toContain("pending");
    }
  });
});
