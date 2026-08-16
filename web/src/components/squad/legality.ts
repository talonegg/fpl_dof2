/**
 * Squad legality in the browser — the same rules the Python validator applies, read from the same
 * configuration (DL-14, Invariant 9, DP-05).
 *
 * **Nothing in this file knows what any FPL rule value is.** Squad size, starting size, budget, club
 * limit, per-position composition and the formation bounds all arrive as `rules.squad`, published
 * from the configuration `fpl_dof.rules` reads. A `3` for the club limit written here would be the
 * same defect as a `4` for a forward goal in a `.py` file, and would be right for exactly as long as
 * FPL left the rule alone.
 *
 * It is a deliberate mirror of `pipeline/src/fpl_dof/rules/legality.py`:
 *
 * - the **violation codes are the same strings** as that module's `ViolationCode`;
 * - the **`detail` keys are the same keys**, so the two can be compared structurally;
 * - every check **returns every violation** rather than stopping at the first, because a squad with
 *   three problems should say three things (a first-failure validator makes editing a game of
 *   whack-a-mole);
 * - the budget comparison is done **in tenths**, because 0.1 is not representable in binary and a
 *   squad costing exactly the budget must not be rejected for summing to 100.00000000000001.
 *
 * That alignment is the cheap half of the cross-language conformance test E6's definition of done
 * calls for: a harness need only feed both implementations the same squad and compare
 * `(code, detail)` pairs. Prose messages are deliberately *not* part of that contract — they are for
 * a reader, and the two languages phrase them for their own audiences.
 *
 * Pure by construction (DP-03): no I/O, no clock, no module state, configuration passed as an
 * argument.
 */

import type { Positionmap, Rules } from "../../contract/types";

export type Position = keyof Positionmap;

/**
 * The position codes, in the order a pitch reads.
 *
 * This is the contract's own key set — the four keys `Positionmap` declares — not a rule value. The
 * Python validator iterates its `Position` enum in exactly the same way. What each position
 * *requires* is read from the rules; only the identity of the positions is structural.
 */
export const POSITIONS: readonly Position[] = ["GKP", "DEF", "MID", "FWD"];

/** The same code set as `ViolationCode` in `fpl_dof.rules.legality`. */
export type ViolationCode =
  | "squad_size"
  | "duplicate_player"
  | "composition"
  | "budget"
  | "club_limit"
  | "starting_size"
  | "starter_not_in_squad"
  | "formation"
  | "captain_not_starting"
  | "vice_not_starting"
  | "captain_is_vice"
  | "bench_order";

export interface Violation {
  code: ViolationCode;
  /** For a reader. Not part of the cross-language contract. */
  message: string;
  /** For a machine. Keys match the Python validator's `detail` dictionary. */
  detail: Record<string, unknown>;
}

/** The minimum a squad member has to be, to be checkable. Everything else is presentation. */
export interface SquadMember {
  player_id: number;
  position: Position;
  team_id: number;
  /** The price at which this player counts against the budget. */
  price: number;
}

/** A squad, plus however much of a line-up has been decided so far. */
export interface ProposedSquad {
  players: readonly SquadMember[];
  /** Empty means "no line-up chosen yet" — squad-level checks only, as in the Python validator. */
  starting?: readonly number[];
  captain?: number | null;
  vice_captain?: number | null;
  bench_order?: readonly number[];
}

/** Prices summed in tenths, so a squad at exactly the budget is at exactly the budget. */
export function priceTenths(players: readonly SquadMember[]): number {
  return players.reduce((total, player) => total + Math.round(player.price * 10), 0);
}

export function totalPrice(players: readonly SquadMember[]): number {
  return priceTenths(players) / 10;
}

function countBy<T, K extends string | number>(items: readonly T[], key: (item: T) => K): Map<K, number> {
  const counts = new Map<K, number>();
  for (const item of items) {
    const k = key(item);
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  return counts;
}

/**
 * Every way this squad breaks the rules, in a stable order.
 *
 * `budget` overrides the rules' initial budget: once a season is under way the relevant figure is
 * squad sell value plus bank, not the opening £100.0m, and the caller has that from `week.json`.
 *
 * A squad with no starting XI is checked for squad-level legality only.
 */
export function validateSquad(
  squad: ProposedSquad,
  rules: Rules,
  options: { budget?: number } = {},
): Violation[] {
  const squadRules = rules.squad;
  const budget = options.budget ?? squadRules.budget;
  const violations = checkSquad(squad.players, squadRules, budget);
  if (squad.starting && squad.starting.length > 0) {
    violations.push(...checkLineup(squad, squadRules));
  }
  return violations;
}

export function isLegal(squad: ProposedSquad, rules: Rules, options: { budget?: number } = {}): boolean {
  return validateSquad(squad, rules, options).length === 0;
}

function checkSquad(
  players: readonly SquadMember[],
  rules: Rules["squad"],
  budget: number,
): Violation[] {
  const violations: Violation[] = [];

  if (players.length !== rules.size) {
    violations.push({
      code: "squad_size",
      message: `squad has ${players.length} players, expected ${rules.size}`,
      detail: { actual: players.length, expected: rules.size },
    });
  }

  const ids = countBy(players, (player) => player.player_id);
  const duplicates = [...ids.entries()]
    .filter(([, count]) => count > 1)
    .map(([id]) => id)
    .sort((a, b) => a - b);
  if (duplicates.length > 0) {
    violations.push({
      code: "duplicate_player",
      message: `player(s) selected more than once: ${duplicates.join(", ")}`,
      detail: { player_ids: duplicates },
    });
  }

  const byPosition = countBy(players, (player) => player.position);
  for (const position of POSITIONS) {
    const required = rules.composition[position];
    const actual = byPosition.get(position) ?? 0;
    if (actual !== required) {
      violations.push({
        code: "composition",
        message: `${position}: ${actual} selected, exactly ${required} required`,
        detail: { position, actual, expected: required },
      });
    }
  }

  const spendTenths = priceTenths(players);
  const budgetTenths = Math.round(budget * 10);
  if (spendTenths > budgetTenths) {
    violations.push({
      code: "budget",
      message: `squad costs £${(spendTenths / 10).toFixed(1)}m, budget is £${(budgetTenths / 10).toFixed(1)}m`,
      detail: { spend: spendTenths / 10, budget: budgetTenths / 10 },
    });
  }

  const perClub = [...countBy(players, (player) => player.team_id).entries()].sort(
    (a, b) => a[0] - b[0],
  );
  for (const [teamId, count] of perClub) {
    if (count > rules.club_limit) {
      violations.push({
        code: "club_limit",
        message: `${count} players from club ${teamId}, maximum is ${rules.club_limit}`,
        detail: { team_id: teamId, actual: count, limit: rules.club_limit },
      });
    }
  }

  return violations;
}

function checkLineup(squad: ProposedSquad, rules: Rules["squad"]): Violation[] {
  const violations: Violation[] = [];
  const members = new Map(squad.players.map((player) => [player.player_id, player]));
  const starting = squad.starting ?? [];

  if (starting.length !== rules.starting_size) {
    violations.push({
      code: "starting_size",
      message: `${starting.length} players starting, expected ${rules.starting_size}`,
      detail: { actual: starting.length, expected: rules.starting_size },
    });
  }

  const outside = [...new Set(starting.filter((id) => !members.has(id)))].sort((a, b) => a - b);
  if (outside.length > 0) {
    violations.push({
      code: "starter_not_in_squad",
      message: `starting player(s) not in the squad: ${outside.join(", ")}`,
      detail: { player_ids: outside },
    });
  }

  const startingPositions = countBy(
    starting.filter((id) => members.has(id)),
    (id) => members.get(id)!.position,
  );
  for (const position of POSITIONS) {
    const actual = startingPositions.get(position) ?? 0;
    const low = rules.formation_min[position];
    const high = rules.formation_max[position];
    if (actual < low || actual > high) {
      violations.push({
        code: "formation",
        message: `${position}: ${actual} starting, must be between ${low} and ${high}`,
        detail: { position, actual, min: low, max: high },
      });
    }
  }

  const startingSet = new Set(starting);
  const captain = squad.captain ?? null;
  const vice = squad.vice_captain ?? null;

  if (captain !== null && !startingSet.has(captain)) {
    violations.push({
      code: "captain_not_starting",
      message: `captain ${captain} is not in the starting XI`,
      detail: { player_id: captain },
    });
  }
  if (vice !== null && !startingSet.has(vice)) {
    violations.push({
      code: "vice_not_starting",
      message: `vice-captain ${vice} is not in the starting XI`,
      detail: { player_id: vice },
    });
  }
  if (captain !== null && vice !== null && captain === vice) {
    violations.push({
      code: "captain_is_vice",
      message: "captain and vice-captain are the same player",
      detail: { player_id: captain },
    });
  }

  if (squad.bench_order && squad.bench_order.length > 0) {
    // Compared as *sets*, which is what the Python validator does — a deliberate match, not a
    // convenience. Comparing sorted lists instead reports a violation for a bench order that names
    // one substitute twice, and the Python authority does not; the cross-language corpus caught the
    // disagreement and this is the side that changed (Invariant 9, DL-39). Both are therefore lax
    // about a repeated id, which is recorded rather than hidden: nothing can produce one, because
    // `draft.ts` derives the bench order from the squad rather than accepting one from a caller.
    const expectedSet = new Set(
      squad.players
        .filter((player) => !startingSet.has(player.player_id) && player.position !== "GKP")
        .map((player) => player.player_id),
    );
    const givenSet = new Set(squad.bench_order);
    const expected = [...expectedSet].sort((a, b) => a - b);
    const given = [...squad.bench_order].sort((a, b) => a - b);
    const same =
      givenSet.size === expectedSet.size && [...givenSet].every((id) => expectedSet.has(id));
    if (!same) {
      violations.push({
        code: "bench_order",
        message: "bench order must list exactly the outfield substitutes",
        detail: { given, expected },
      });
    }
  }

  return violations;
}

/**
 * Every starting XI shape the rules permit, in a stable order.
 *
 * Mirrors `SquadRules.legal_formations`: the goalkeeper, defender and midfielder counts are
 * enumerated within their published bounds and the forward count is whatever is left of the
 * starting size, kept only when it too falls within its bounds. Nothing here assumes 1-3-2-1 or
 * eleven starters — change the configuration and this changes with it.
 */
export function legalFormations(rules: Rules): Array<Record<Position, number>> {
  const squad = rules.squad;
  const formations: Array<Record<Position, number>> = [];
  for (let gkp = squad.formation_min.GKP; gkp <= squad.formation_max.GKP; gkp += 1) {
    for (let def = squad.formation_min.DEF; def <= squad.formation_max.DEF; def += 1) {
      for (let mid = squad.formation_min.MID; mid <= squad.formation_max.MID; mid += 1) {
        const fwd = squad.starting_size - gkp - def - mid;
        if (fwd >= squad.formation_min.FWD && fwd <= squad.formation_max.FWD) {
          formations.push({ GKP: gkp, DEF: def, MID: mid, FWD: fwd });
        }
      }
    }
  }
  return formations;
}

/**
 * What a player sells for — the mirror of `selling_price` in the Python rules module.
 *
 * Profit is shared with the game: the manager keeps `1 - sell_on_fee` of any rise, rounded **down**
 * to the nearest £0.1; a fall is borne in full. Both the fee and whether selling is at purchase
 * price at all come from the rules.
 *
 * Present and tested here, but **not yet applied by the builder**: the published contract carries no
 * per-player purchase price, so the browser cannot reconstruct what any individual player would
 * raise. `week.squad_state.budget` already nets the fee off in aggregate, which is what the builder
 * spends against; see the note in `SquadBuilder`. When a purchase price reaches the contract, this
 * is the function that consumes it.
 */
export function sellingPrice(purchasePrice: number, currentPrice: number, rules: Rules): number {
  if (rules.squad.sell_at_purchase_price) return purchasePrice;

  const purchaseTenths = Math.round(purchasePrice * 10);
  const currentTenths = Math.round(currentPrice * 10);
  if (currentTenths <= purchaseTenths) return currentTenths / 10;

  const profit = currentTenths - purchaseTenths;
  const kept = Math.floor(profit * (1 - rules.squad.sell_on_fee));
  return (purchaseTenths + kept) / 10;
}
