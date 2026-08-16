/**
 * Fixtures for the squad builder's tests.
 *
 * A pool big enough to build a legal fifteen from several ways over, with prices and forecasts that
 * are deterministic functions of the id — so a failing test points at the logic rather than at a
 * hand-tuned number somebody has to reverse-engineer.
 *
 * The rules object is imported from the shared contract fixture rather than restated, because a
 * second copy of the squad rules in a test directory is the same drift risk the whole of DL-14
 * exists to close.
 */

import type { Player, Squad } from "../../contract/types";
import { rules } from "../../test/fixtures";
import type { Position, SquadMember } from "./legality";

export { rules };

/** How many clubs the pool spans. Small enough that the club limit actually binds. */
const CLUBS = 8;

const SHORT_NAMES = ["ARS", "AVL", "BOU", "BRE", "BHA", "CHE", "CRY", "EVE"];

function makePlayer(id: number, position: Position, seed: number): Player {
  const price = 4.0 + (seed % 6);
  const teamId = 1 + (seed % CLUBS);
  // Forecast rises with price, with a deterministic wobble so the ranking is not simply the price
  // ranking — a re-optimiser that only ever picked the most expensive player would pass otherwise.
  const xpNext = 2.0 + price * 0.4 + ((seed * 7) % 5) * 0.3;
  return {
    id,
    name: `${position}${id}`,
    full_name: `Player ${id}`,
    position,
    team: SHORT_NAMES[teamId - 1],
    team_id: teamId,
    price,
    xp_next: Number(xpNext.toFixed(3)),
    xp_next_sd: 1.5,
    xp_horizon: Number((xpNext * 5).toFixed(3)),
    xp_horizon_sd: 6.0,
    start_probability: 0.9,
    confidence: "high",
    selected_by_percent: 10,
    status: "a",
    news: "",
    components: {
      appearance: 1.8,
      goals: 0.5,
      assists: 0.2,
      clean_sheet: 1.0,
      goals_conceded: -0.3,
      saves: 0.0,
      defensive_contribution: 0.1,
      bonus: 0.2,
      cards: -0.1,
    },
  };
}

/**
 * Roughly two and a half squads' worth of players in every position.
 *
 * Ids are blocked by position (100s goalkeepers, 200s defenders, and so on) so a failure message
 * naming an id says which position it was without a lookup.
 */
export const pool: Player[] = [
  ...Array.from({ length: 8 }, (_, i) => makePlayer(100 + i, "GKP", i)),
  ...Array.from({ length: 16 }, (_, i) => makePlayer(200 + i, "DEF", i)),
  ...Array.from({ length: 16 }, (_, i) => makePlayer(300 + i, "MID", i)),
  ...Array.from({ length: 10 }, (_, i) => makePlayer(400 + i, "FWD", i)),
];

export const poolById = new Map(pool.map((player) => [player.id, player]));

export function member(id: number): SquadMember {
  const player = poolById.get(id);
  if (!player) throw new Error(`no fixture player ${id}`);
  return {
    player_id: player.id,
    position: player.position,
    team_id: player.team_id,
    price: player.price,
  };
}

/**
 * A legal fifteen, chosen by hand rather than by the code under test.
 *
 * Picked to keep every club at or under the limit and the total comfortably inside the budget, so a
 * test that sees a violation has found one rather than tripped over the fixture.
 */
export const LEGAL_IDS = [
  100, 101, // GKP — clubs 1, 2
  202, 203, 204, 205, 206, // DEF — clubs 3, 4, 5, 6, 7
  300, 301, 302, 306, 307, // MID — clubs 1, 2, 3, 7, 8
  403, 404, 405, // FWD — clubs 4, 5, 6
];

export const legalMembers: SquadMember[] = LEGAL_IDS.map(member);

/** Eleven of them in a shape the published bounds permit: 1 GKP, 4 DEF, 4 MID, 2 FWD. */
export const LEGAL_XI = [100, 202, 203, 204, 205, 300, 301, 302, 307, 403, 404];

/** The published squad artefact, built from the same fifteen. */
export const builtSquad: Squad = {
  contract_version: 1,
  run_id: "test-run",
  status: "optimal",
  objective: 100,
  total_price: legalMembers.reduce((total, m) => total + m.price, 0),
  budget: rules.squad.budget,
  formation: { GKP: 1, DEF: 4, MID: 4, FWD: 2 },
  captain_id: 404,
  vice_captain_id: 302,
  bench_order: [206, 306, 405],
  players: LEGAL_IDS.map((id) => {
    const player = poolById.get(id)!;
    return {
      player_id: player.id,
      web_name: player.name,
      position: player.position,
      team: player.team,
      team_id: player.team_id,
      price: player.price,
      xp_next: player.xp_next,
      xp_next_sd: player.xp_next_sd,
      xp_horizon: player.xp_horizon,
      xp_horizon_sd: player.xp_horizon_sd,
      starting: LEGAL_XI.includes(id),
      is_captain: id === 404,
      is_vice_captain: id === 302,
    };
  }),
};
