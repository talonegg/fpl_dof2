/**
 * The draft squad the reader is editing, and the pure transitions that change it.
 *
 * State is deliberately thin: fifteen player ids and whichever of them are starting. Everything else
 * — the members themselves, the price, the formation, the captaincy, the bench order and the
 * violations — is *derived* on every render by `resolveDraft`. Derived state cannot drift from the
 * thing it describes, and it is what makes "live legality checking" live rather than a check that
 * has to remember to re-run.
 *
 * All of this is pure and DOM-free (DP-03); the React binding is in `SquadBuilder`.
 */

import type { Player, Rules, Squad } from "../../contract/types";
import { chooseLineup, formationOf, type LineupCandidate } from "./lineup";
import {
  totalPrice,
  validateSquad,
  type Position,
  type SquadMember,
  type Violation,
} from "./legality";

/** A player as the builder needs them: legality fields, plus enough to render a row. */
export interface BuilderPlayer extends SquadMember {
  name: string;
  team: string;
  xp_next: number;
  xp_next_sd?: number;
  xp_horizon: number;
  xp_horizon_sd?: number;
  /** FPL availability flag, where the pool carries one. */
  status?: string;
  news?: string;
  /** False when the player is only known from `squad.json` and not from the published pool. */
  in_pool: boolean;
}

export interface SquadDraft {
  memberIds: number[];
  starting: number[];
}

export type PlayerIndex = Map<number, BuilderPlayer>;

/**
 * Everyone the builder can talk about, keyed by id.
 *
 * The pool is the source of record. Squad members absent from it are still indexed from the squad
 * artefact so a squad can always be *rendered*, flagged with `in_pool: false` so the re-optimiser's
 * refusal to reason about them can be explained rather than looking like a bug.
 */
export function indexPlayers(pool: readonly Player[], squad: Squad): PlayerIndex {
  const index: PlayerIndex = new Map();

  for (const player of pool) {
    index.set(player.id, {
      player_id: player.id,
      position: player.position,
      team_id: player.team_id,
      price: player.price,
      name: player.name,
      team: player.team,
      xp_next: player.xp_next,
      xp_next_sd: player.xp_next_sd,
      xp_horizon: player.xp_horizon,
      xp_horizon_sd: player.xp_horizon_sd,
      status: player.status,
      news: player.news,
      in_pool: true,
    });
  }

  for (const member of squad.players) {
    if (index.has(member.player_id)) continue;
    index.set(member.player_id, {
      player_id: member.player_id,
      position: member.position,
      team_id: member.team_id,
      price: member.price,
      name: member.web_name,
      team: member.team,
      xp_next: member.xp_next,
      xp_next_sd: member.xp_next_sd,
      xp_horizon: member.xp_horizon,
      xp_horizon_sd: member.xp_horizon_sd,
      in_pool: false,
    });
  }

  return index;
}

/** The published squad, as a draft to start editing from. */
export function draftFromSquad(squad: Squad): SquadDraft {
  return {
    memberIds: squad.players.map((player) => player.player_id),
    starting: squad.players.filter((player) => player.starting).map((player) => player.player_id),
  };
}

export function removeFromDraft(draft: SquadDraft, id: number): SquadDraft {
  return {
    memberIds: draft.memberIds.filter((memberId) => memberId !== id),
    starting: draft.starting.filter((memberId) => memberId !== id),
  };
}

/** Adding an id already present is a no-op rather than a duplicate the validator then complains about. */
export function addToDraft(draft: SquadDraft, id: number): SquadDraft {
  if (draft.memberIds.includes(id)) return draft;
  return { ...draft, memberIds: [...draft.memberIds, id] };
}

/**
 * Swap one player for another in place, keeping the outgoing player's place in the XI.
 *
 * Position order is preserved so the list does not reshuffle under the reader's cursor mid-edit.
 */
export function replaceInDraft(draft: SquadDraft, outgoing: number, incoming: number): SquadDraft {
  if (!draft.memberIds.includes(outgoing)) return addToDraft(draft, incoming);
  if (draft.memberIds.includes(incoming)) return removeFromDraft(draft, outgoing);
  return {
    memberIds: draft.memberIds.map((id) => (id === outgoing ? incoming : id)),
    starting: draft.starting.map((id) => (id === outgoing ? incoming : id)),
  };
}

/**
 * Start or bench a player.
 *
 * No bounds are enforced here on purpose. A reader mid-edit will pass through twelve starters on
 * their way to a different shape, and a control that silently refuses is far more confusing than a
 * violation panel that says "MID: 6 starting, must be between 2 and 5". The validator is the
 * authority; the buttons are not.
 */
export function toggleStarter(draft: SquadDraft, id: number): SquadDraft {
  if (!draft.memberIds.includes(id)) return draft;
  return draft.starting.includes(id)
    ? { ...draft, starting: draft.starting.filter((memberId) => memberId !== id) }
    : { ...draft, starting: [...draft.starting, id] };
}

/** The best legal XI for the current fifteen, when one exists. */
export function autoLineup(draft: SquadDraft, index: PlayerIndex, rules: Rules): SquadDraft {
  const members = resolveMembers(draft, index);
  const lineup = chooseLineup(members, rules);
  if (!lineup) return draft;
  return { ...draft, starting: lineup.starting };
}

export function resolveMembers(draft: SquadDraft, index: PlayerIndex): BuilderPlayer[] {
  return draft.memberIds
    .map((id) => index.get(id))
    .filter((player): player is BuilderPlayer => player !== undefined);
}

export interface ResolvedDraft {
  members: BuilderPlayer[];
  starters: BuilderPlayer[];
  bench: BuilderPlayer[];
  starting: number[];
  bench_order: number[];
  captain: number | null;
  vice_captain: number | null;
  formation: Record<Position, number>;
  totalPrice: number;
  /** Budget minus what the fifteen cost. Negative is over budget, and the validator will say so. */
  remaining: number;
  violations: Violation[];
  /** Members whose ids are not in the index at all — a stale draft pointing at a departed player. */
  unknownIds: number[];
}

/**
 * Everything derived from a draft, including its violations. One call, every render.
 *
 * Captaincy is derived rather than edited: the two highest-forecast starters take the armbands. That
 * is a scope decision, not a rules simplification — the validator checks the captaincy rules in full
 * and is tested against them, so wiring a manual choice in later changes this function and nothing
 * else.
 */
export function resolveDraft(
  draft: SquadDraft,
  index: PlayerIndex,
  rules: Rules,
  budget: number,
): ResolvedDraft {
  const members = resolveMembers(draft, index);
  const unknownIds = draft.memberIds.filter((id) => !index.has(id));
  const memberIds = new Set(members.map((member) => member.player_id));
  const starting = draft.starting.filter((id) => memberIds.has(id));

  const startingSet = new Set(starting);
  const starters = members.filter((member) => startingSet.has(member.player_id));
  const bench = members
    .filter((member) => !startingSet.has(member.player_id))
    .sort(benchOrder);

  const ranked = [...starters].sort(
    (a, b) => b.xp_next - a.xp_next || a.player_id - b.player_id,
  );
  const captain = ranked[0]?.player_id ?? null;
  const vice = ranked[1]?.player_id ?? null;

  const benchOrderIds = bench
    .filter((member) => member.position !== "GKP")
    .map((member) => member.player_id);

  const violations = validateSquad(
    {
      players: members,
      starting,
      captain,
      vice_captain: vice,
      bench_order: benchOrderIds,
    },
    rules,
    { budget },
  );

  const spend = totalPrice(members);

  return {
    members,
    starters,
    bench,
    starting,
    bench_order: benchOrderIds,
    captain,
    vice_captain: vice,
    formation: formationOf(members, starting),
    totalPrice: spend,
    remaining: Math.round((budget - spend) * 10) / 10,
    violations,
    unknownIds,
  };
}

/** The reserve keeper first, then the outfield substitutes best-forecast first. */
function benchOrder(a: LineupCandidate & { position: Position }, b: LineupCandidate & { position: Position }): number {
  if (a.position === "GKP" && b.position !== "GKP") return -1;
  if (b.position === "GKP" && a.position !== "GKP") return 1;
  return b.xp_next - a.xp_next || a.player_id - b.player_id;
}

/** How many more of each position the draft still needs, for the replacement picker. */
export function shortfall(draft: SquadDraft, index: PlayerIndex, rules: Rules): Record<Position, number> {
  const members = resolveMembers(draft, index);
  const counts: Record<Position, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
  for (const member of members) counts[member.position] += 1;
  return {
    GKP: rules.squad.composition.GKP - counts.GKP,
    DEF: rules.squad.composition.DEF - counts.DEF,
    MID: rules.squad.composition.MID - counts.MID,
    FWD: rules.squad.composition.FWD - counts.FWD,
  };
}
