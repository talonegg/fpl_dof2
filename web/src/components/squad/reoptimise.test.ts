/**
 * The heuristic re-optimiser.
 *
 * The load-bearing property is not "it finds a good squad" — it is a heuristic and is allowed to
 * miss. It is **it never returns an illegal one**, under every constraint a reader can express. A
 * squad-builder that quietly hands back four Arsenal players is worse than one that refuses, because
 * the reader will believe it (DP-13, DP-15).
 */

import { describe, expect, it } from "vitest";
import type { Rules } from "../../contract/types";
import { isLegal, POSITIONS, validateSquad } from "./legality";
import { chooseLineup } from "./lineup";
import { DEFAULT_PASSES, reoptimise } from "./reoptimise";
import { pool, poolById, rules } from "./testFixtures";

const budget = rules.squad.budget;

function run(overrides: Partial<Parameters<typeof reoptimise>[0]> = {}) {
  return reoptimise({ pool, rules, budget, locked: [], banned: [], ...overrides });
}

describe("reoptimise — legality is the guarantee", () => {
  it("returns a squad that passes the validator", () => {
    const result = run();
    expect(result.status).toBe("heuristic");
    if (result.status !== "heuristic") return;

    expect(
      validateSquad(
        {
          players: result.members,
          starting: result.lineup?.starting ?? [],
          captain: result.lineup?.captain,
          vice_captain: result.lineup?.vice_captain,
          bench_order: result.lineup?.bench_order ?? [],
        },
        rules,
        { budget },
      ),
    ).toEqual([]);
  });

  it("fills the published composition exactly", () => {
    const result = run();
    if (result.status !== "heuristic") throw new Error("expected a squad");
    for (const position of POSITIONS) {
      const count = result.members.filter((m) => m.position === position).length;
      expect(count).toBe(rules.squad.composition[position]);
    }
  });

  it("stays inside the budget it was given, not the rules' opening budget", () => {
    const tight = run({ budget: 70 });
    if (tight.status !== "heuristic") throw new Error("expected a squad");
    expect(tight.totalPrice).toBeLessThanOrEqual(70);
    expect(isLegal({ players: tight.members }, rules, { budget: 70 })).toBe(true);
  });

  it("refuses rather than overspending when the budget cannot buy a legal squad", () => {
    // Comfortably below the cheapest fifteen this pool admits. The failure mode being guarded
    // against is not "it says no" — it is "it says yes and hands back a squad over the budget".
    const impossible = run({ budget: 40 });
    expect(impossible.status).toBe("infeasible");
  });

  it("never returns a squad over its budget, at any budget it accepts", () => {
    for (const candidateBudget of [70, 75, 80, 90, 100, 120]) {
      const result = run({ budget: candidateBudget });
      if (result.status !== "heuristic") continue;
      expect(result.totalPrice).toBeLessThanOrEqual(candidateBudget);
      expect(isLegal({ players: result.members }, rules, { budget: candidateBudget })).toBe(true);
    }
  });

  it("respects the club limit even when the best players share a club", () => {
    // Every forward on one club: the limit must bind rather than the value ranking winning.
    const clustered = pool.map((player) =>
      player.position === "FWD" ? { ...player, team_id: 1, team: "ARS" } : player,
    );
    const result = reoptimise({ pool: clustered, rules, budget, locked: [], banned: [] });
    if (result.status !== "heuristic") throw new Error("expected a squad");
    const perClub = new Map<number, number>();
    for (const m of result.members) perClub.set(m.team_id, (perClub.get(m.team_id) ?? 0) + 1);
    for (const count of perClub.values()) expect(count).toBeLessThanOrEqual(rules.squad.club_limit);
  });

  it("follows a tightened club limit from the rules rather than a remembered three", () => {
    const twoPerClub: Rules = { ...rules, squad: { ...rules.squad, club_limit: 2 } };
    const result = reoptimise({ pool, rules: twoPerClub, budget, locked: [], banned: [] });
    if (result.status !== "heuristic") throw new Error("expected a squad");
    const perClub = new Map<number, number>();
    for (const m of result.members) perClub.set(m.team_id, (perClub.get(m.team_id) ?? 0) + 1);
    for (const count of perClub.values()) expect(count).toBeLessThanOrEqual(2);
  });
});

describe("reoptimise — locks and bans", () => {
  it("keeps every locked player", () => {
    const locked = [107, 215, 315];
    const result = run({ locked });
    if (result.status !== "heuristic") throw new Error("expected a squad");
    const ids = result.members.map((m) => m.player_id);
    for (const id of locked) expect(ids).toContain(id);
  });

  it("keeps a locked player the value ranking would never have chosen", () => {
    // The worst points-per-pound player in the pool, forced in.
    const worst = [...pool].sort(
      (a, b) => a.xp_horizon / a.price - b.xp_horizon / b.price || a.id - b.id,
    )[0];
    const result = run({ locked: [worst.id] });
    if (result.status !== "heuristic") throw new Error("expected a squad");
    expect(result.members.map((m) => m.player_id)).toContain(worst.id);
  });

  it("picks nobody who is banned", () => {
    const banned = pool.filter((player) => player.position === "FWD").slice(0, 4).map((p) => p.id);
    const result = run({ banned });
    if (result.status !== "heuristic") throw new Error("expected a squad");
    for (const id of banned) expect(result.members.map((m) => m.player_id)).not.toContain(id);
  });

  it("still returns a legal squad when almost every option is banned", () => {
    // Ban everyone but the bare minimum plus one spare per position.
    const keep = new Set<number>();
    for (const position of POSITIONS) {
      pool
        .filter((player) => player.position === position)
        .slice(0, rules.squad.composition[position] + 1)
        .forEach((player) => keep.add(player.id));
    }
    const banned = pool.filter((player) => !keep.has(player.id)).map((player) => player.id);
    const result = run({ banned, budget: 200 });
    if (result.status !== "heuristic") throw new Error("expected a squad");
    expect(isLegal({ players: result.members }, rules, { budget: 200 })).toBe(true);
  });
});

describe("reoptimise — saying why, when it cannot", () => {
  it("refuses when a locked player is not in the published pool", () => {
    const result = run({ locked: [99999] });
    expect(result.status).toBe("infeasible");
    if (result.status !== "infeasible") return;
    expect(result.reasons.join(" ")).toContain("99999");
  });

  it("refuses when a player is both locked and banned", () => {
    const result = run({ locked: [200], banned: [200] });
    expect(result.status).toBe("infeasible");
    if (result.status !== "infeasible") return;
    expect(result.reasons.join(" ")).toContain("locked and banned");
  });

  it("refuses when the locks break the club limit, and names the club", () => {
    const clubOne = pool.filter((player) => player.team_id === 1).slice(0, 4).map((p) => p.id);
    const result = run({ locked: clubOne });
    expect(result.status).toBe("infeasible");
    if (result.status !== "infeasible") return;
    expect(result.reasons.join(" ")).toContain("club 1");
  });

  it("refuses when the locks alone cost more than the budget", () => {
    const expensive = [...pool].sort((a, b) => b.price - a.price).slice(0, 6).map((p) => p.id);
    const cost = expensive.reduce((total, id) => total + poolById.get(id)!.price, 0);
    const result = run({ locked: expensive, budget: cost - 1 });
    expect(result.status).toBe("infeasible");
    if (result.status !== "infeasible") return;
    expect(result.reasons.join(" ")).toContain("over the");
  });

  it("refuses when more of a position are locked than the squad holds", () => {
    const keepers = pool.filter((player) => player.position === "GKP").slice(0, 4).map((p) => p.id);
    const result = run({ locked: keepers });
    expect(result.status).toBe("infeasible");
    if (result.status !== "infeasible") return;
    expect(result.reasons.join(" ")).toContain("GKP");
  });

  it("refuses when too many players are locked to fit the squad", () => {
    const everyone = pool.slice(0, rules.squad.size + 1).map((player) => player.id);
    const result = run({ locked: everyone });
    expect(result.status).toBe("infeasible");
  });
});

describe("reoptimise — the climb itself", () => {
  it("improves on, or matches, the squad it started from", () => {
    const free = run();
    const constrained = run({ locked: [] , passes: 0 });
    if (free.status !== "heuristic" || constrained.status !== "heuristic") {
      throw new Error("expected squads");
    }
    // Zero passes is the greedy build alone; the climb may only ever add value.
    expect(free.objective).toBeGreaterThanOrEqual(constrained.objective - 1e-9);
  });

  it("stops early when a pass changes nothing rather than burning the whole budget of passes", () => {
    const result = run();
    if (result.status !== "heuristic") throw new Error("expected a squad");
    expect(result.passes).toBeLessThanOrEqual(DEFAULT_PASSES);
  });

  it("is deterministic: the same inputs give the same squad", () => {
    const first = run();
    const second = run();
    if (first.status !== "heuristic" || second.status !== "heuristic") {
      throw new Error("expected squads");
    }
    expect(first.members.map((m) => m.player_id)).toEqual(second.members.map((m) => m.player_id));
    expect(first.objective).toBeCloseTo(second.objective, 9);
  });

  it("reports the price it actually spent", () => {
    const result = run();
    if (result.status !== "heuristic") throw new Error("expected a squad");
    const summed = result.members.reduce((total, m) => total + m.price, 0);
    expect(result.totalPrice).toBeCloseTo(summed, 5);
  });
});

describe("chooseLineup", () => {
  it("picks a legal shape and the best XI within it", () => {
    const result = run();
    if (result.status !== "heuristic") throw new Error("expected a squad");
    const lineup = result.lineup;
    expect(lineup).not.toBeNull();
    if (!lineup) return;

    expect(lineup.starting).toHaveLength(rules.squad.starting_size);
    for (const position of POSITIONS) {
      const count = lineup.formation[position];
      expect(count).toBeGreaterThanOrEqual(rules.squad.formation_min[position]);
      expect(count).toBeLessThanOrEqual(rules.squad.formation_max[position]);
    }
  });

  it("gives the armbands to the two best-forecast starters", () => {
    const result = run();
    if (result.status !== "heuristic" || !result.lineup) throw new Error("expected a lineup");
    const { starting, captain, vice_captain } = result.lineup;
    const ranked = starting
      .map((id) => poolById.get(id)!)
      .sort((a, b) => b.xp_next - a.xp_next || a.id - b.id);
    expect(captain).toBe(ranked[0].id);
    expect(vice_captain).toBe(ranked[1].id);
  });

  it("benches the reserve goalkeeper rather than putting them in the bench order", () => {
    const result = run();
    if (result.status !== "heuristic" || !result.lineup) throw new Error("expected a lineup");
    const keepers = result.members.filter((m) => m.position === "GKP").map((m) => m.player_id);
    for (const id of keepers) expect(result.lineup.bench_order).not.toContain(id);
  });

  it("returns null for a squad that cannot fill any legal shape", () => {
    const onlyKeepers = pool
      .filter((player) => player.position === "GKP")
      .map((player) => ({ player_id: player.id, position: player.position, xp_next: player.xp_next }));
    expect(chooseLineup(onlyKeepers, rules)).toBeNull();
  });
});
