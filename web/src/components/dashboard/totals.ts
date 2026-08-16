import type { Squad } from "../../contract/types";

type SquadPlayer = Squad["players"][number];

/**
 * Squad-level expected points, added up in the browser.
 *
 * Two things this deliberately does **not** do.
 *
 * **It does not apply a captain multiplier.** The multiplier is an FPL rule and no rule value may
 * appear as a literal in any language (Invariant 2, Invariant 9, DP-05) — and `rules.json` does not
 * currently carry it. So these totals are stated as being *before captaincy*, and the pipeline's own
 * advised total (`week.advised.expected_points`), which does include it, is shown alongside rather
 * than recomputed here. A number that is honest about what it excludes beats a number that quietly
 * doubles the wrong player.
 *
 * **It does not pretend the uncertainty is small.** Standard deviations are combined in quadrature,
 * which assumes the fifteen forecasts are independent. They are not: players share fixtures, and a
 * clean sheet is one event for four defenders. The band this yields is therefore *too narrow*, and
 * the UI says so where it renders it — Invariant 6 asks for uncertainty, and DP-09 asks that an
 * estimated quantity never be dressed as a measured one, which includes not dressing an
 * optimistically narrow band as a calibrated one.
 */
export interface SquadTotals {
  /** How many players went into the starting total. */
  startingCount: number;
  startingXpNext: number;
  /** Undefined when any contributing player published no standard deviation. */
  startingSdNext?: number;
  startingXpHorizon: number;
  startingSdHorizon?: number;
  benchXpNext: number;
  /** All fifteen, which is what a Bench Boost week is worth before captaincy. */
  squadXpNext: number;
}

function sumMean(players: SquadPlayer[], pick: (p: SquadPlayer) => number): number {
  return players.reduce((total, player) => total + pick(player), 0);
}

/** Quadrature sum, or undefined if any player is missing its standard deviation. */
function sumSd(
  players: SquadPlayer[],
  pick: (p: SquadPlayer) => number | undefined,
): number | undefined {
  let variance = 0;
  for (const player of players) {
    const sd = pick(player);
    if (sd === undefined || sd === null) return undefined;
    variance += sd * sd;
  }
  return Math.sqrt(variance);
}

export function squadTotals(squad: Squad): SquadTotals {
  const starting = squad.players.filter((player) => player.starting);
  const bench = squad.players.filter((player) => !player.starting);

  return {
    startingCount: starting.length,
    startingXpNext: sumMean(starting, (p) => p.xp_next),
    startingSdNext: sumSd(starting, (p) => p.xp_next_sd),
    startingXpHorizon: sumMean(starting, (p) => p.xp_horizon),
    startingSdHorizon: sumSd(starting, (p) => p.xp_horizon_sd),
    benchXpNext: sumMean(bench, (p) => p.xp_next),
    squadXpNext: sumMean(squad.players, (p) => p.xp_next),
  };
}
