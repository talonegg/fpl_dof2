/**
 * Client-side re-optimisation around locks and bans — a heuristic, and labelled as one (E6-S7, T2).
 *
 * **This is not the pipeline's optimiser and does not pretend to be.** The published squad comes
 * from a multi-gameweek MILP over a pruned pool with bench weighting, chip scenarios and a transfer
 * budget (E4, DL-15). What runs here is a greedy build plus a hill-climb, in the same spirit as the
 * greedy fallback in `fpl_dof.optimise.squad` — which exists there for exactly the reason it is
 * acceptable here: a legal answer now beats an optimal answer that needs a solver the browser does
 * not have (DP-15). Every caller must present the result as the heuristic it is; `SquadBuilder` says
 * so on the page, because a fallback presented indistinguishably from a full solve is the failure
 * DP-15 names outright.
 *
 * Known limitations, stated rather than discovered:
 *
 * - It maximises **squad-total** `xp_horizon`. The MILP weights the bench below the XI, so this will
 *   over-invest in a fifteenth player the real optimiser would leave cheap.
 * - It considers only **one-for-one swaps within a position**. Two-player moves that free up money
 *   for a premium — the shape of most good real transfers — are outside it.
 * - It ignores transfer cost entirely: it answers "what is a good legal squad?", never "is it worth
 *   the hits to get there?". `week.json` and `plan.json` answer that, and they are what the reader
 *   should act on.
 * - It optimises the coming horizon only, with no chip or fixture-swing reasoning.
 *
 * What it *is* guaranteed to do is never return an illegal squad: the result is put through
 * `validateSquad` before it is handed back, and a squad that fails is reported as infeasible rather
 * than returned. Being wrong about the best squad is a disappointment; being wrong about a legal one
 * is a defect (DP-13).
 *
 * Pure (DP-03): pool, rules, budget and constraints in; a result out.
 */

import type { Player, Rules } from "../../contract/types";
import { chooseLineup, type Lineup } from "./lineup";
import {
  POSITIONS,
  priceTenths,
  validateSquad,
  type Position,
  type SquadMember,
  type Violation,
} from "./legality";

/**
 * How many hill-climbing passes to make before stopping.
 *
 * DP-06: a named tunable with a reason, not a literal in a loop. Each pass is O(squad × pool) and a
 * pass that changes nothing ends the climb early, so this only bounds pathological cases. Six is
 * comfortably more than the two or three a fifteen-player squad converges in, and keeps the whole
 * re-optimisation inside a single frame's budget on the phone this has to run on (NFR-04).
 */
export const DEFAULT_PASSES = 6;

/**
 * The price floor used when ranking by points per pound.
 *
 * Guards the division only. A player cannot cost £0.0m under any published rules, but a pool row
 * with a missing price must not produce an infinite ratio and win every position.
 */
const PRICE_FLOOR = 0.1;

export interface ReoptimiseInput {
  pool: readonly Player[];
  rules: Rules;
  /** Squad value plus bank, from `week.json` where it exists. Never assumed to be the opening budget. */
  budget: number;
  /** Players that must be in the squad. */
  locked: readonly number[];
  /** Players that must not be. */
  banned: readonly number[];
  passes?: number;
}

export interface ReoptimiseSuccess {
  status: "heuristic";
  members: SquadMember[];
  lineup: Lineup | null;
  /** Squad-total `xp_horizon` — what the climb maximised, and nothing more than that. */
  objective: number;
  totalPrice: number;
  passes: number;
  swaps: number;
}

export interface ReoptimiseFailure {
  status: "infeasible";
  reasons: string[];
}

export type ReoptimiseResult = ReoptimiseSuccess | ReoptimiseFailure;

interface Candidate extends SquadMember {
  xp_horizon: number;
  xp_next: number;
}

function toCandidate(player: Player): Candidate {
  return {
    player_id: player.id,
    position: player.position,
    team_id: player.team_id,
    price: player.price,
    xp_horizon: player.xp_horizon,
    xp_next: player.xp_next,
  };
}

/** Points per pound over the horizon. The greedy build's ordering, as in the Python fallback. */
function valueRatio(candidate: Candidate): number {
  return candidate.xp_horizon / Math.max(candidate.price, PRICE_FLOOR);
}

function byValue(a: Candidate, b: Candidate): number {
  return valueRatio(b) - valueRatio(a) || a.player_id - b.player_id;
}

function byHorizon(a: Candidate, b: Candidate): number {
  return b.xp_horizon - a.xp_horizon || a.player_id - b.player_id;
}

/**
 * Why this cannot be done, in the reader's terms rather than as a status code.
 *
 * The same courtesy `_diagnose_infeasibility` extends on the Python side: "you have locked four
 * Arsenal players" is actionable, "infeasible" is not.
 */
function diagnose(
  locked: Candidate[],
  missing: number[],
  lockedAndBanned: number[],
  rules: Rules,
  budget: number,
): string[] {
  const reasons: string[] = [];
  const squad = rules.squad;

  if (missing.length > 0) {
    reasons.push(`locked player(s) are not in the published pool: ${missing.join(", ")}`);
  }
  if (lockedAndBanned.length > 0) {
    reasons.push(`player(s) both locked and banned: ${lockedAndBanned.join(", ")}`);
  }
  if (locked.length > squad.size) {
    reasons.push(`${locked.length} players locked, but the squad holds ${squad.size}`);
  }

  for (const position of POSITIONS) {
    const count = locked.filter((player) => player.position === position).length;
    const allowed = squad.composition[position];
    if (count > allowed) {
      reasons.push(`${count} ${position} locked, but the squad holds ${allowed}`);
    }
  }

  const perClub = new Map<number, number>();
  for (const player of locked) {
    perClub.set(player.team_id, (perClub.get(player.team_id) ?? 0) + 1);
  }
  for (const [teamId, count] of [...perClub.entries()].sort((a, b) => a[0] - b[0])) {
    if (count > squad.club_limit) {
      reasons.push(
        `${count} players locked from club ${teamId}, but at most ${squad.club_limit} may be selected`,
      );
    }
  }

  const lockedTenths = priceTenths(locked);
  if (lockedTenths > Math.round(budget * 10)) {
    reasons.push(
      `locked players alone cost £${(lockedTenths / 10).toFixed(1)}m, over the £${budget.toFixed(1)}m available`,
    );
  }

  return reasons;
}

/**
 * A lower bound on what filling the remaining slots must cost.
 *
 * Taking the cheapest available player per outstanding slot and ignoring the club limit gives a
 * bound that can only be optimistic, which is the safe direction: it never rejects a fill that would
 * have worked, and it stops the greedy build spending its last million on a fourth midfielder and
 * then finding it cannot afford a goalkeeper at all. The Python fallback has no such reservation and
 * raises instead; a reader clicking a button deserves the better-behaved version.
 */
function minimumRemainingCost(
  needs: Record<Position, number>,
  cheapestByPosition: Map<Position, Candidate[]>,
  chosen: Set<number>,
): number {
  let tenths = 0;
  for (const position of POSITIONS) {
    let wanted = needs[position];
    if (wanted <= 0) continue;
    for (const candidate of cheapestByPosition.get(position) ?? []) {
      if (wanted === 0) break;
      if (chosen.has(candidate.player_id)) continue;
      tenths += Math.round(candidate.price * 10);
      wanted -= 1;
    }
    if (wanted > 0) return Number.POSITIVE_INFINITY;
  }
  return tenths;
}

export function reoptimise(input: ReoptimiseInput): ReoptimiseResult {
  const { pool, rules, budget } = input;
  const squadRules = rules.squad;
  const passLimit = input.passes ?? DEFAULT_PASSES;
  const budgetTenths = Math.round(budget * 10);

  const banned = new Set(input.banned);
  const byId = new Map(pool.map((player) => [player.id, toCandidate(player)]));

  const lockedIds = [...new Set(input.locked)];
  const missing = lockedIds.filter((id) => !byId.has(id)).sort((a, b) => a - b);
  const lockedAndBanned = lockedIds.filter((id) => banned.has(id)).sort((a, b) => a - b);
  const lockedMembers = lockedIds
    .filter((id) => byId.has(id) && !banned.has(id))
    .map((id) => byId.get(id)!);

  const upFront = diagnose(lockedMembers, missing, lockedAndBanned, rules, budget);
  if (upFront.length > 0) return { status: "infeasible", reasons: upFront };

  const available = [...byId.values()].filter((candidate) => !banned.has(candidate.player_id));
  const byPositionValue = new Map<Position, Candidate[]>();
  const byPositionPrice = new Map<Position, Candidate[]>();
  for (const position of POSITIONS) {
    const members = available.filter((candidate) => candidate.position === position);
    byPositionValue.set(position, [...members].sort(byValue));
    byPositionPrice.set(
      position,
      [...members].sort((a, b) => a.price - b.price || a.player_id - b.player_id),
    );
  }

  // --- Greedy build -----------------------------------------------------------------------------
  const chosen = new Map<number, Candidate>();
  const perClub = new Map<number, number>();
  const lockedSet = new Set(lockedMembers.map((player) => player.player_id));
  let spentTenths = 0;

  const clubCount = (teamId: number) => perClub.get(teamId) ?? 0;

  const take = (candidate: Candidate) => {
    chosen.set(candidate.player_id, candidate);
    perClub.set(candidate.team_id, clubCount(candidate.team_id) + 1);
    spentTenths += Math.round(candidate.price * 10);
  };

  const drop = (candidate: Candidate) => {
    chosen.delete(candidate.player_id);
    perClub.set(candidate.team_id, clubCount(candidate.team_id) - 1);
    spentTenths -= Math.round(candidate.price * 10);
  };

  for (const member of lockedMembers) take(member);

  const needs = (): Record<Position, number> => {
    const remaining: Record<Position, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
    for (const position of POSITIONS) {
      const held = [...chosen.values()].filter((player) => player.position === position).length;
      remaining[position] = Math.max(0, squadRules.composition[position] - held);
    }
    return remaining;
  };

  /** Would taking this candidate still leave enough money to fill everything else? */
  const affordable = (candidate: Candidate) => {
    const after = needs();
    after[candidate.position] -= 1;
    const reserve = minimumRemainingCost(
      after,
      byPositionPrice,
      new Set([...chosen.keys(), candidate.player_id]),
    );
    return spentTenths + Math.round(candidate.price * 10) + reserve <= budgetTenths;
  };

  /**
   * Make room at a club that is full, so a blocked candidate can be taken.
   *
   * Greedy fills position by position, so the positions filled first can spend a club's whole
   * allowance and leave a later position with nowhere legal to go — a dead end the Python fallback
   * simply raises on. Here that dead end is reachable by a reader who bans enough players, so it is
   * worth one bounded repair: give up the least valuable player already chosen from the blocking
   * club, replace them with the best equivalent from a club with room, and try again. It gives up
   * value deliberately, which is exactly the trade a legal squad is worth.
   */
  const freeClubSlot = (teamId: number, incoming: Candidate): boolean => {
    const givingUp = [...chosen.values()]
      .filter((player) => player.team_id === teamId && !lockedSet.has(player.player_id))
      .sort((a, b) => -byHorizon(a, b));

    for (const outgoing of givingUp) {
      const outTenths = Math.round(outgoing.price * 10);
      for (const replacement of byPositionValue.get(outgoing.position) ?? []) {
        if (chosen.has(replacement.player_id)) continue;
        if (replacement.team_id === teamId) continue;
        if (clubCount(replacement.team_id) >= squadRules.club_limit) continue;

        const cost =
          Math.round(replacement.price * 10) - outTenths + Math.round(incoming.price * 10);
        const after = needs();
        after[incoming.position] -= 1;
        const reserve = minimumRemainingCost(
          after,
          byPositionPrice,
          new Set([...chosen.keys(), replacement.player_id, incoming.player_id]),
        );
        if (spentTenths + cost + reserve > budgetTenths) continue;

        drop(outgoing);
        take(replacement);
        return true;
      }
    }
    return false;
  };

  for (const position of POSITIONS) {
    let wanted = needs()[position];

    while (wanted > 0) {
      let taken = false;

      for (const candidate of byPositionValue.get(position) ?? []) {
        if (chosen.has(candidate.player_id)) continue;
        if (clubCount(candidate.team_id) >= squadRules.club_limit) continue;
        if (!affordable(candidate)) continue;
        take(candidate);
        taken = true;
        break;
      }

      if (!taken) {
        // Nobody is takeable as things stand. Try to unblock the best candidate whose only problem
        // is a full club.
        for (const candidate of byPositionValue.get(position) ?? []) {
          if (chosen.has(candidate.player_id)) continue;
          if (clubCount(candidate.team_id) < squadRules.club_limit) continue;
          if (!freeClubSlot(candidate.team_id, candidate)) continue;
          take(candidate);
          taken = true;
          break;
        }
      }

      if (!taken) {
        return {
          status: "infeasible",
          reasons: [
            `could not fill ${wanted} more ${position} within £${budget.toFixed(1)}m under the club limit`,
          ],
        };
      }

      wanted -= 1;
    }
  }

  // --- Hill climb -------------------------------------------------------------------------------
  //
  // One-for-one, same position, only when it raises the total. Same-position swaps keep the
  // composition legal by construction, so only budget and the club limit need re-checking.
  let swaps = 0;
  let passesUsed = 0;

  for (let pass = 0; pass < passLimit; pass += 1) {
    passesUsed = pass + 1;
    let changed = false;
    const weakestFirst = [...chosen.values()].sort((a, b) => -byHorizon(a, b));

    for (const outgoing of weakestFirst) {
      if (lockedSet.has(outgoing.player_id)) continue;
      const outTenths = Math.round(outgoing.price * 10);

      let best: Candidate | null = null;
      for (const candidate of byPositionValue.get(outgoing.position) ?? []) {
        if (chosen.has(candidate.player_id)) continue;
        if (candidate.xp_horizon <= outgoing.xp_horizon) continue;
        if (best !== null && byHorizon(candidate, best) >= 0) continue;

        const priceT = Math.round(candidate.price * 10);
        if (spentTenths - outTenths + priceT > budgetTenths) continue;

        const clubCount =
          (perClub.get(candidate.team_id) ?? 0) - (candidate.team_id === outgoing.team_id ? 1 : 0);
        if (clubCount >= squadRules.club_limit) continue;

        best = candidate;
      }

      if (best === null) continue;

      drop(outgoing);
      take(best);
      swaps += 1;
      changed = true;
    }

    if (!changed) break;
  }

  // --- Line-up, then prove it legal --------------------------------------------------------------
  const members = [...chosen.values()].sort(
    (a, b) => POSITIONS.indexOf(a.position) - POSITIONS.indexOf(b.position) || byHorizon(a, b),
  );
  const lineup = chooseLineup(members, rules);

  const violations: Violation[] = validateSquad(
    {
      players: members,
      starting: lineup?.starting ?? [],
      captain: lineup?.captain ?? null,
      vice_captain: lineup?.vice_captain ?? null,
      bench_order: lineup?.bench_order ?? [],
    },
    rules,
    { budget },
  );

  if (violations.length > 0) {
    return {
      status: "infeasible",
      reasons: [
        "the heuristic produced a squad that breaks the rules, so it has been discarded:",
        ...violations.map((violation) => violation.message),
      ],
    };
  }

  return {
    status: "heuristic",
    members,
    lineup,
    objective: members.reduce((total, member) => {
      return total + (byId.get(member.player_id)?.xp_horizon ?? 0);
    }, 0),
    totalPrice: spentTenths / 10,
    passes: passesUsed,
    swaps,
  };
}
