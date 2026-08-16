/**
 * The compared players' histories, turned into overlaid series (E6-S5, FR-29).
 *
 * Pure and DOM-free, like `verdict.ts` and `player/trends.ts`. The difference from the single-player
 * case is that everything here has to be made **commensurable** before it can share an axis, and each
 * of those alignments has a silent failure mode (DP-13):
 *
 * - **Cumulative, not per-gameweek.** Four spiky per-gameweek lines crossing each other is a picture
 *   nobody reads; four cumulative lines answer the question the view is actually for, which is who
 *   has delivered more and when the order changed. The double-gameweek and absent-value rules come
 *   from `player/trends.ts` rather than being restated here.
 * - **Price observations are per player and irregular.** Two players' price series have different
 *   dates and different lengths, so plotting each against its own index would put day 40 of one
 *   player above day 5 of another. They are aligned onto one shared date axis and **carried forward**
 *   — the gaps are days the price did not change, not days it was unknown.
 * - **Before a player's first observation there is no point at all**, not a zero and not the first
 *   value extended backwards. A line that starts flat at £8.0m before anything observed £8.0m is an
 *   invented measurement.
 * - **A player missing from the artefact is different from a player who has not featured**, and both
 *   are different from an absent artefact. All three are normal (DL-20, DP-15) and each is named.
 */

import type { History, Player, PlayerHistory } from "../../contract/types";
import type { Point } from "../charts/geometry";
import { cumulative } from "../player/trends";

/** One player's overlaid lines. Empty arrays are legitimate and mean "nothing measured yet". */
export interface PlayerTrendLines {
  playerId: number;
  name: string;
  /** This player has a row in the artefact at all. */
  present: boolean;
  /** Cumulative FPL points by gameweek. */
  points: Point[];
  /** Cumulative minutes by gameweek — the constraint under every other series here. */
  minutes: Point[];
  /** Cumulative Defensive Contribution actions. Empty when never measured for this player. */
  defensive: Point[];
  /** Price, x-indexed into the shared `priceDates` axis. */
  price: Point[];
}

export interface CompareTrends {
  lines: PlayerTrendLines[];
  /** The shared, ascending, de-duplicated price observation dates across every compared player. */
  priceDates: string[];
  /** Compared players with no row in the artefact. */
  absentNames: string[];
  /** Compared players present in the artefact but yet to feature in a scored gameweek. */
  notFeaturedNames: string[];
  /** Any player has a scored gameweek. False in preseason, and the gate on the performance charts. */
  anyGameweeks: boolean;
  /** Any player has a price observation. True in preseason once a price has been watched. */
  anyPrices: boolean;
  /** Defensive contribution was measured for at least one player. */
  anyDefensive: boolean;
  /** From the artefact, never inferred from an array length (DL-20). */
  gameweeksPlayed: number;
}

/**
 * Align one player's price observations onto a shared date axis, carrying the last value forward.
 *
 * Emits no point for a date before this player's first observation. `on` is an ISO date, so string
 * comparison is chronological comparison and no parsing is needed.
 */
export function alignToDates(
  observations: readonly { on: string; price: number; owned: number }[],
  dates: readonly string[],
  pick: (observation: { on: string; price: number; owned: number }) => number,
): Point[] {
  const out: Point[] = [];
  let cursor = 0;
  let current: number | null = null;

  dates.forEach((date, index) => {
    while (cursor < observations.length && observations[cursor].on <= date) {
      current = pick(observations[cursor]);
      cursor += 1;
    }
    if (current !== null) out.push({ x: index, y: current });
  });

  return out;
}

/** Every price observation date across the compared players, ascending and de-duplicated. */
export function sharedPriceDates(histories: readonly PlayerHistory[]): string[] {
  const dates = new Set<string>();
  for (const history of histories) {
    for (const observation of history.prices) dates.add(observation.on);
  }
  return [...dates].sort();
}

export function buildCompareTrends(
  history: History,
  players: readonly Player[],
): CompareTrends {
  const byId = new Map(history.players.map((entry) => [entry.id, entry]));
  const found = players
    .map((player) => byId.get(player.id))
    .filter((entry): entry is PlayerHistory => entry !== undefined);

  const priceDates = sharedPriceDates(found);

  const lines: PlayerTrendLines[] = [];
  const absentNames: string[] = [];
  const notFeaturedNames: string[] = [];

  for (const player of players) {
    const entry = byId.get(player.id);

    if (entry === undefined) {
      absentNames.push(player.name);
      lines.push({
        playerId: player.id,
        name: player.name,
        present: false,
        points: [],
        minutes: [],
        defensive: [],
        price: [],
      });
      continue;
    }

    if (entry.gameweeks.length === 0) notFeaturedNames.push(player.name);

    lines.push({
      playerId: player.id,
      name: player.name,
      present: true,
      points: cumulative(entry.gameweeks, (e) => e.pts).points,
      minutes: cumulative(entry.gameweeks, (e) => e.mins).points,
      defensive: cumulative(entry.gameweeks, (e) => e.dc).points,
      price: alignToDates(entry.prices, priceDates, (o) => o.price),
    });
  }

  return {
    lines,
    priceDates,
    absentNames,
    notFeaturedNames,
    anyGameweeks: lines.some((line) => line.points.length > 0),
    anyPrices: lines.some((line) => line.price.length > 0),
    anyDefensive: lines.some((line) => line.defensive.length > 0),
    gameweeksPlayed: history.gameweeks_played,
  };
}
