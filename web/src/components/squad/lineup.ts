/**
 * Choosing a starting XI from a squad, by enumerating the legal shapes.
 *
 * The formation space is tiny — the published bounds admit a handful of shapes — so this enumerates
 * every legal one and picks the best rather than searching (DP-10: prefer the formulation you can
 * argue with). "3-4-3 beats 3-5-2 by 1.4 expected points" is a sentence a reader can disagree with;
 * a shape falling out of a solver is not.
 *
 * The shapes themselves come from `legalFormations`, which reads the bounds from `rules.json`. No
 * formation is named here.
 */

import type { Rules } from "../../contract/types";
import { legalFormations, POSITIONS, type Position } from "./legality";

/** What choosing a line-up needs to know about a player: where they play and what they are worth. */
export interface LineupCandidate {
  player_id: number;
  position: Position;
  /** Expected points for the coming gameweek. The XI is picked for the next deadline, not the horizon. */
  xp_next: number;
}

export interface Lineup {
  starting: number[];
  bench_order: number[];
  captain: number | null;
  vice_captain: number | null;
  formation: Record<Position, number>;
  /** Summed `xp_next` of the XI, before any captain multiplier. What the shapes were ranked on. */
  expected_points: number;
}

/**
 * Rank by expected points, then by id.
 *
 * The id tie-break is not decoration: without it two players on identical forecasts would order by
 * whatever the input happened to be, and the same squad could produce different line-ups on
 * successive renders. Deterministic tie-breaks are the cheapest kind of reproducibility (DP-11).
 */
function byExpectedPoints(a: LineupCandidate, b: LineupCandidate): number {
  return b.xp_next - a.xp_next || a.player_id - b.player_id;
}

/**
 * The best legal XI for this squad, or `null` when no legal shape can be filled.
 *
 * Returning null rather than a best-effort XI is deliberate: an incomplete squad has no line-up, and
 * inventing one would hide the composition violation the validator is already reporting.
 */
export function chooseLineup(players: readonly LineupCandidate[], rules: Rules): Lineup | null {
  const byPosition = new Map<Position, LineupCandidate[]>();
  for (const position of POSITIONS) {
    byPosition.set(
      position,
      players.filter((player) => player.position === position).sort(byExpectedPoints),
    );
  }

  let best: Lineup | null = null;

  for (const formation of legalFormations(rules)) {
    const starters: LineupCandidate[] = [];
    let feasible = true;
    let value = 0;

    for (const position of POSITIONS) {
      const wanted = formation[position];
      const available = byPosition.get(position) ?? [];
      if (available.length < wanted) {
        feasible = false;
        break;
      }
      for (const player of available.slice(0, wanted)) {
        starters.push(player);
        value += player.xp_next;
      }
    }

    if (!feasible) continue;
    if (best !== null && value <= best.expected_points) continue;

    const startingIds = new Set(starters.map((player) => player.player_id));
    const ranked = [...starters].sort(byExpectedPoints);
    const bench = players
      .filter((player) => !startingIds.has(player.player_id) && player.position !== "GKP")
      .sort(byExpectedPoints);

    best = {
      starting: starters.map((player) => player.player_id),
      bench_order: bench.map((player) => player.player_id),
      captain: ranked[0]?.player_id ?? null,
      vice_captain: ranked[1]?.player_id ?? null,
      formation,
      expected_points: value,
    };
  }

  return best;
}

/** The formation a chosen XI actually is, for display: counts per position in pitch order. */
export function formationOf(
  players: readonly LineupCandidate[],
  starting: readonly number[],
): Record<Position, number> {
  const startingSet = new Set(starting);
  const counts: Record<Position, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
  for (const player of players) {
    if (startingSet.has(player.player_id)) counts[player.position] += 1;
  }
  return counts;
}
