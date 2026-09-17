import { describe, expect, it } from "vitest";
import type { Squad } from "../../contract/types";
import { players, skippedWeek, squad, week } from "../../test/fixtures";
import { effectiveSquad } from "./effective";

/**
 * DL-67: in-season the solve is skipped and the app starts from this week's advised squad.
 *
 * The property worth pinning is that nothing is invented: every member of the derived squad is a
 * published player with published numbers, the XI and captain are the advised ones, and when
 * there is no advice to fall back on the empty squad stays empty.
 */
const skippedSquad: Squad = {
  ...squad,
  status: "skipped",
  skipped: true,
  skipped_reason: "the season is under way",
  objective: 0,
  total_price: 0,
  formation: {},
  captain_id: null,
  vice_captain_id: null,
  bench_order: [],
  players: [],
};

describe("effectiveSquad", () => {
  it("returns a solved squad untouched", () => {
    expect(effectiveSquad(squad, week, players)).toBe(squad);
  });

  it("builds the squad from this week's advice when the solve was skipped", () => {
    const derived = effectiveSquad(skippedSquad, week, players);
    expect(derived.source).toBe("week_advice");
    expect(derived.players.map((p) => p.player_id)).toEqual(week.advised?.squad);
    expect(derived.players.filter((p) => p.starting).map((p) => p.player_id)).toEqual(
      week.advised?.starting,
    );
    expect(derived.captain_id).toBe(week.advised?.captain);
    expect(derived.vice_captain_id).toBe(week.advised?.vice_captain);
    expect(derived.bench_order).toEqual(week.advised?.bench_order);
    expect(derived.formation).toEqual({ GKP: 1, FWD: 1 });
    const raya = derived.players.find((p) => p.player_id === 1);
    expect(raya?.xp_next).toBe(players.players[0].xp_next);
    expect(raya?.web_name).toBe("Raya");
  });

  it("keeps the skipped squad empty when there is no advice to start from", () => {
    expect(effectiveSquad(skippedSquad, null, players)).toBe(skippedSquad);
    expect(effectiveSquad(skippedSquad, skippedWeek, players)).toBe(skippedSquad);
  });
});
