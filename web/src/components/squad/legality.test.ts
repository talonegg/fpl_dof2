/**
 * The legality validator, rule by rule.
 *
 * DP-13 says test hardest where being wrong is invisible, and this is that place: a validator that
 * silently permits an illegal squad produces a page that looks completely normal and is wrong about
 * the only thing it exists to be right about.
 *
 * The last block is the one that matters most. It does not check that the validator gets FPL's 2026/27
 * rules right — it checks that the validator has no opinion about them at all, by handing it
 * *different* rules and requiring the answers to change. A hardcoded 3 for the club limit would pass
 * every other test in this file and fail those.
 */

import { describe, expect, it } from "vitest";
import type { Rules } from "../../contract/types";
import {
  isLegal,
  legalFormations,
  sellingPrice,
  totalPrice,
  validateSquad,
  type SquadMember,
  type ViolationCode,
} from "./legality";
import { LEGAL_XI, legalMembers, member, rules } from "./testFixtures";

function codes(violations: ReturnType<typeof validateSquad>): ViolationCode[] {
  return violations.map((violation) => violation.code);
}

const fullSquad = {
  players: legalMembers,
  starting: LEGAL_XI,
  captain: LEGAL_XI[0],
  vice_captain: LEGAL_XI[1],
};

describe("validateSquad — a legal squad", () => {
  it("finds nothing wrong with a legal fifteen and a legal XI", () => {
    expect(validateSquad(fullSquad, rules)).toEqual([]);
    expect(isLegal(fullSquad, rules)).toBe(true);
  });

  it("checks squad-level rules only when no XI has been chosen", () => {
    // The E0 case: the optimiser picks fifteen and the line-up comes later. A squad with no XI must
    // not be told it has the wrong number of starters.
    expect(validateSquad({ players: legalMembers }, rules)).toEqual([]);
  });

  it("reports every violation rather than stopping at the first", () => {
    const broken: SquadMember[] = [
      ...legalMembers.slice(0, 13),
      { ...member(403), player_id: 900, team_id: 1, price: 60 },
    ];
    const violations = validateSquad({ players: broken }, rules);
    expect(violations.length).toBeGreaterThan(2);
    expect(new Set(codes(violations)).size).toBeGreaterThan(2);
  });
});

describe("validateSquad — squad size and duplicates", () => {
  it("flags a squad short of the published size", () => {
    const violations = validateSquad({ players: legalMembers.slice(0, 14) }, rules);
    expect(codes(violations)).toContain("squad_size");
    expect(violations.find((v) => v.code === "squad_size")?.detail).toEqual({
      actual: 14,
      expected: rules.squad.size,
    });
  });

  it("flags the same player selected twice", () => {
    const doubled = [...legalMembers.slice(0, 14), legalMembers[0]];
    const violations = validateSquad({ players: doubled }, rules);
    expect(codes(violations)).toContain("duplicate_player");
    expect(violations.find((v) => v.code === "duplicate_player")?.detail).toEqual({
      player_ids: [legalMembers[0].player_id],
    });
  });
});

describe("validateSquad — composition", () => {
  it("flags a position over its published count", () => {
    // One midfielder swapped for a sixth defender: two violations, not one, because both positions
    // are now wrong.
    const swapped = legalMembers.map((m) => (m.player_id === 307 ? member(207) : m));
    const violations = validateSquad({ players: swapped }, rules);
    const composition = violations.filter((v) => v.code === "composition");
    expect(composition.map((v) => v.detail.position).sort()).toEqual(["DEF", "MID"]);
    expect(composition.find((v) => v.detail.position === "DEF")?.detail).toEqual({
      position: "DEF",
      actual: rules.squad.composition.DEF + 1,
      expected: rules.squad.composition.DEF,
    });
  });

  it("names every position that is short", () => {
    const violations = validateSquad({ players: [] }, rules);
    expect(violations.filter((v) => v.code === "composition")).toHaveLength(4);
  });
});

describe("validateSquad — budget", () => {
  it("accepts a squad costing exactly the budget", () => {
    // The float trap: 0.1 is not representable in binary, and fifteen prices summed in floating
    // point can exceed their own total. Summing in tenths is what makes this pass.
    const priced = legalMembers.map((m, index) => ({ ...m, price: index === 0 ? 5.1 : 6.5 }));
    const budget = totalPrice(priced);
    expect(validateSquad({ players: priced }, rules, { budget })).toEqual([]);
  });

  it("flags a squad a tenth over the budget", () => {
    const priced = legalMembers.map((m) => ({ ...m, price: 6.7 }));
    const budget = totalPrice(priced) - 0.1;
    const violations = validateSquad({ players: priced }, rules, { budget });
    expect(codes(violations)).toContain("budget");
    expect(violations.find((v) => v.code === "budget")?.detail).toEqual({
      spend: totalPrice(priced),
      budget,
    });
  });

  it("spends against the rules' budget when no override is given", () => {
    const priced = legalMembers.map((m) => ({ ...m, price: rules.squad.budget / 10 }));
    expect(codes(validateSquad({ players: priced }, rules))).toContain("budget");
  });

  it("spends against the override when one is given, which is the in-season case", () => {
    // From E1 onward the figure is squad sell value plus bank, not the opening budget.
    const cheap = legalMembers.map((m) => ({ ...m, price: 4.0 }));
    expect(validateSquad({ players: cheap }, rules, { budget: 60 })).toEqual([]);
    expect(codes(validateSquad({ players: cheap }, rules, { budget: 59.9 }))).toContain("budget");
  });
});

describe("validateSquad — club limit", () => {
  it("flags one club over the published limit", () => {
    // Everyone outside the overloaded club is given a club of their own, so the count under test is
    // exactly the five put there and not five plus whatever the fixture already had.
    const overloaded = legalMembers.map((m, index) =>
      index < 5 ? { ...m, team_id: 1 } : { ...m, team_id: 100 + index },
    );
    const violations = validateSquad({ players: overloaded }, rules);
    expect(codes(violations)).toContain("club_limit");
    expect(violations.find((v) => v.code === "club_limit")?.detail).toEqual({
      team_id: 1,
      actual: 5,
      limit: rules.squad.club_limit,
    });
  });

  it("accepts a club exactly at the limit", () => {
    const atLimit = legalMembers.map((m, index) =>
      index < rules.squad.club_limit ? { ...m, team_id: 1 } : { ...m, team_id: 20 - index },
    );
    expect(codes(validateSquad({ players: atLimit }, rules))).not.toContain("club_limit");
  });
});

describe("validateSquad — the line-up", () => {
  it("flags the wrong number of starters", () => {
    const violations = validateSquad({ ...fullSquad, starting: LEGAL_XI.slice(0, 10) }, rules);
    expect(codes(violations)).toContain("starting_size");
  });

  it("flags a starter who is not in the squad", () => {
    const violations = validateSquad({ ...fullSquad, starting: [...LEGAL_XI.slice(1), 999] }, rules);
    expect(codes(violations)).toContain("starter_not_in_squad");
    expect(violations.find((v) => v.code === "starter_not_in_squad")?.detail).toEqual({
      player_ids: [999],
    });
  });

  it("flags a formation below a position's minimum", () => {
    // Both goalkeepers benched and two extra defenders in: GKP falls under its floor.
    const starting = [202, 203, 204, 205, 206, 300, 301, 302, 306, 403, 404];
    const violations = validateSquad({ ...fullSquad, starting, captain: 403, vice_captain: 404 }, rules);
    const formation = violations.filter((v) => v.code === "formation");
    expect(formation.map((v) => v.detail.position)).toContain("GKP");
    expect(formation.find((v) => v.detail.position === "GKP")?.detail).toEqual({
      position: "GKP",
      actual: 0,
      min: rules.squad.formation_min.GKP,
      max: rules.squad.formation_max.GKP,
    });
  });

  it("flags a formation above a position's maximum", () => {
    // Every defender starting plus both keepers: DEF is at its max but GKP is over its own.
    const starting = [100, 101, 202, 203, 204, 205, 206, 300, 301, 302, 306];
    const violations = validateSquad({ ...fullSquad, starting, captain: 100, vice_captain: 101 }, rules);
    expect(
      violations.filter((v) => v.code === "formation").map((v) => v.detail.position),
    ).toContain("GKP");
  });

  it("flags a captain who is not starting", () => {
    const violations = validateSquad({ ...fullSquad, captain: 101 }, rules);
    expect(codes(violations)).toContain("captain_not_starting");
  });

  it("flags a vice-captain who is not starting", () => {
    const violations = validateSquad({ ...fullSquad, vice_captain: 206 }, rules);
    expect(codes(violations)).toContain("vice_not_starting");
  });

  it("flags a captain who is also the vice-captain", () => {
    const violations = validateSquad({ ...fullSquad, vice_captain: LEGAL_XI[0] }, rules);
    expect(codes(violations)).toContain("captain_is_vice");
  });

  it("accepts a bench order listing exactly the outfield substitutes", () => {
    expect(validateSquad({ ...fullSquad, bench_order: [206, 306, 405] }, rules)).toEqual([]);
  });

  it("flags a bench order containing the reserve goalkeeper", () => {
    const violations = validateSquad({ ...fullSquad, bench_order: [101, 206, 306, 405] }, rules);
    expect(codes(violations)).toContain("bench_order");
  });

  it("flags a bench order missing a substitute", () => {
    const violations = validateSquad({ ...fullSquad, bench_order: [206, 306] }, rules);
    expect(codes(violations)).toContain("bench_order");
  });
});

/**
 * Invariant 9, tested directly.
 *
 * Every case here changes the *rules* and requires the validator's answer to change with them. A
 * literal anywhere in `legality.ts` would survive every test above and die here — which is the whole
 * point, because the day FPL changes a rule is the day the literal becomes wrong and nobody thinks
 * to look for it.
 */
describe("the rules are read, never known", () => {
  function withSquadRules(overrides: Partial<Rules["squad"]>): Rules {
    return { ...rules, squad: { ...rules.squad, ...overrides } };
  }

  it("follows a changed squad size", () => {
    const smaller = withSquadRules({ size: 14 });
    expect(codes(validateSquad({ players: legalMembers }, smaller))).toContain("squad_size");
    expect(validateSquad({ players: legalMembers.slice(0, 14) }, smaller).map((v) => v.code)).not.toContain(
      "squad_size",
    );
  });

  it("follows a changed club limit", () => {
    const twoPerClub = withSquadRules({ club_limit: 2 });
    const threeFromOne = legalMembers.map((m, index) =>
      index < 3 ? { ...m, team_id: 1 } : { ...m, team_id: 100 + index },
    );
    expect(codes(validateSquad({ players: threeFromOne }, rules))).not.toContain("club_limit");
    expect(codes(validateSquad({ players: threeFromOne }, twoPerClub))).toContain("club_limit");
  });

  it("follows a changed budget", () => {
    const halfBudget = withSquadRules({ budget: rules.squad.budget / 2 });
    expect(codes(validateSquad({ players: legalMembers }, rules))).not.toContain("budget");
    expect(codes(validateSquad({ players: legalMembers }, halfBudget))).toContain("budget");
  });

  it("follows a changed composition", () => {
    const fourDefenders = withSquadRules({
      composition: { ...rules.squad.composition, DEF: 4, MID: 6 },
    });
    const violations = validateSquad({ players: legalMembers }, fourDefenders);
    expect(violations.filter((v) => v.code === "composition").map((v) => v.detail.position)).toEqual([
      "DEF",
      "MID",
    ]);
  });

  it("follows changed formation bounds", () => {
    const threeAtTheBack = withSquadRules({
      formation_min: { ...rules.squad.formation_min, DEF: 5 },
    });
    expect(codes(validateSquad(fullSquad, rules))).not.toContain("formation");
    expect(codes(validateSquad(fullSquad, threeAtTheBack))).toContain("formation");
  });

  it("follows a changed starting size", () => {
    const tenASide = withSquadRules({ starting_size: 10 });
    expect(codes(validateSquad(fullSquad, tenASide))).toContain("starting_size");
  });
});

describe("legalFormations", () => {
  it("enumerates only shapes that add up to the starting size and sit inside the bounds", () => {
    const formations = legalFormations(rules);
    expect(formations.length).toBeGreaterThan(0);
    for (const formation of formations) {
      const total = formation.GKP + formation.DEF + formation.MID + formation.FWD;
      expect(total).toBe(rules.squad.starting_size);
      expect(formation.DEF).toBeGreaterThanOrEqual(rules.squad.formation_min.DEF);
      expect(formation.FWD).toBeLessThanOrEqual(rules.squad.formation_max.FWD);
    }
  });

  it("contains the shapes a reader would name, without naming them in the code", () => {
    const shapes = legalFormations(rules).map((f) => `${f.DEF}-${f.MID}-${f.FWD}`);
    expect(shapes).toContain("4-4-2");
    expect(shapes).toContain("3-5-2");
    expect(shapes).toContain("5-3-2");
  });

  it("shrinks when the rules tighten", () => {
    const tight: Rules = {
      ...rules,
      squad: {
        ...rules.squad,
        formation_min: { GKP: 1, DEF: 4, MID: 4, FWD: 2 },
        formation_max: { GKP: 1, DEF: 4, MID: 4, FWD: 2 },
      },
    };
    expect(legalFormations(tight)).toEqual([{ GKP: 1, DEF: 4, MID: 4, FWD: 2 }]);
  });
});

describe("sellingPrice", () => {
  it("returns the current price when the player has not risen", () => {
    expect(sellingPrice(7.5, 7.2, rules)).toBeCloseTo(7.2, 5);
    expect(sellingPrice(7.5, 7.5, rules)).toBeCloseTo(7.5, 5);
  });

  it("shares the rise with the game, rounding the manager's share down", () => {
    // A £0.3m rise at a 50% fee: the manager keeps £0.1m, not £0.15m.
    expect(sellingPrice(7.5, 7.8, rules)).toBeCloseTo(7.6, 5);
    expect(sellingPrice(7.5, 7.6, rules)).toBeCloseTo(7.5, 5);
    expect(sellingPrice(7.5, 7.7, rules)).toBeCloseTo(7.6, 5);
  });

  it("reads the fee from the rules rather than assuming one", () => {
    const noFee: Rules = { ...rules, squad: { ...rules.squad, sell_on_fee: 0 } };
    expect(sellingPrice(7.5, 7.9, noFee)).toBeCloseTo(7.9, 5);
  });

  it("honours a rules configuration that sells at purchase price", () => {
    const atPurchase: Rules = {
      ...rules,
      squad: { ...rules.squad, sell_at_purchase_price: true },
    };
    expect(sellingPrice(7.5, 9.0, atPurchase)).toBeCloseTo(7.5, 5);
  });
});
