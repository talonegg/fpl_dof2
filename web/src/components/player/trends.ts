/**
 * One player's history, turned into the series the charts plot.
 *
 * Pure and DOM-free (the `scout/filters.ts` pattern). The dangerous mistakes here are all silent
 * (DP-13):
 *
 * - **Absent is not zero.** `xg`, `xa`, `dc` and `dc_pts` are optional in the contract and their
 *   absence means *not measured*, which is a different claim from *nil return* (DL-18). Plotting an
 *   absent xG as 0 draws a player who created nothing, from data that never said so. Absent points
 *   are dropped from the series and counted into a coverage figure the view states outright.
 * - **A double gameweek is two entries with the same `gw`.** Summing per gameweek is required, or a
 *   double silently plots as two bars at one x and the second overwrites the first.
 * - **Price and ownership are step functions**, emitted only on change. The gaps are days the value
 *   was unchanged, so the series is carried forward, not interpolated.
 *
 * Nothing here is a forecast, so nothing here carries an uncertainty band — these are measurements,
 * and inventing an error bar for something that was counted would be worse than having none (DL-37).
 */

import type { History, HistoryGameweek, PlayerHistory } from "../../contract/types";
import type { Point } from "../charts/geometry";

export interface TrendSeries {
  key: string;
  label: string;
  points: Point[];
}

/** How much of a series was actually measured, so the view can say so rather than imply totality. */
export interface Coverage {
  measured: number;
  total: number;
}

export interface TrendBar {
  gameweek: number;
  value: number;
}

export interface PlayerTrends {
  /** From the artefact, not from an array length: zero is a normal preseason state (DL-20). */
  gameweeksPlayed: number;
  /** This player has scored gameweeks. False in preseason, and for a player yet to feature. */
  hasGameweeks: boolean;
  /** Price observations exist. True in preseason as soon as the pipeline has watched a price. */
  hasPrices: boolean;
  /** Total FPL points per gameweek, doubles summed. */
  points: TrendBar[];
  /** Minutes per gameweek, doubles summed. */
  minutes: TrendBar[];
  /** Cumulative expected versus actual goals, and the same for assists. */
  attacking: { series: TrendSeries[]; coverage: Coverage };
  /** Defensive Contribution actions and the points they earned. Null when never measured. */
  defensive: { series: TrendSeries[]; coverage: Coverage } | null;
  price: TrendSeries;
  ownership: TrendSeries;
  /** Price observation dates, indexed as the price and ownership series are. */
  priceDates: string[];
  totals: {
    points: number;
    minutes: number;
    goals: number;
    assists: number;
    /** Null when expected goals were never measured for this player. */
    expectedGoals: number | null;
    expectedAssists: number | null;
  };
}

/** Sum the entries of a double gameweek into one, keyed by gameweek and ascending. */
function byGameweek(
  entries: readonly HistoryGameweek[],
  pick: (entry: HistoryGameweek) => number,
): TrendBar[] {
  const totals = new Map<number, number>();
  for (const entry of entries) {
    totals.set(entry.gw, (totals.get(entry.gw) ?? 0) + pick(entry));
  }
  return [...totals.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([gameweek, value]) => ({ gameweek, value }));
}

/**
 * A cumulative series over the gameweeks where the field was measured.
 *
 * Unmeasured gameweeks contribute nothing and are not plotted, so the running total is honestly "the
 * total of what we measured" rather than a total silently deflated by missing weeks.
 *
 * **Exported for `compare/compareTrends.ts`**, which overlays the same quantity across two to four
 * players. Shared rather than restated because the two rules it encodes — sum a double gameweek into
 * one point, and drop an unmeasured value instead of treating it as zero — are exactly the ones whose
 * violation is silent (DP-13). Two copies is two chances to get one of them wrong in one view only,
 * and a comparison drawn under different rules from the player page is worse than either alone.
 */
export function cumulative(
  entries: readonly HistoryGameweek[],
  pick: (entry: HistoryGameweek) => number | undefined,
): { points: Point[]; measured: number; total: number | null } {
  const totals = new Map<number, number>();

  for (const entry of entries) {
    const value = pick(entry);
    if (value === undefined || value === null) continue;
    totals.set(entry.gw, (totals.get(entry.gw) ?? 0) + value);
  }

  let running = 0;
  const points = [...totals.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([gw, value]) => {
      running += value;
      return { x: gw, y: running };
    });

  // Measured is a count of *gameweeks*, not of entries. Counting entries would let a double
  // gameweek report two measurements against a one-gameweek denominator, and coverage would read
  // as complete precisely when a gameweek was missing — the coverage figure exists to catch that.
  return { points, measured: totals.size, total: totals.size === 0 ? null : running };
}

/** Distinct gameweeks in the series — the denominator for a coverage figure. */
function distinctGameweeks(entries: readonly HistoryGameweek[]): number {
  return new Set(entries.map((entry) => entry.gw)).size;
}

export function buildTrends(playerHistory: PlayerHistory, gameweeksPlayed: number): PlayerTrends {
  const entries = playerHistory.gameweeks;
  const total = distinctGameweeks(entries);

  const goals = cumulative(entries, (e) => e.goals);
  const assists = cumulative(entries, (e) => e.assists);
  const xg = cumulative(entries, (e) => e.xg);
  const xa = cumulative(entries, (e) => e.xa);
  const dc = cumulative(entries, (e) => e.dc);
  const dcPoints = cumulative(entries, (e) => e.dc_pts);

  const attackingSeries: TrendSeries[] = [
    { key: "goals", label: "Goals scored", points: goals.points },
    { key: "assists", label: "Assists made", points: assists.points },
  ];
  // Expected series only when something measured them. An empty line labelled "expected goals" reads
  // as "expected nothing", which is the wrong claim entirely.
  if (xg.points.length > 0) {
    attackingSeries.push({ key: "xg", label: "Expected goals", points: xg.points });
  }
  if (xa.points.length > 0) {
    attackingSeries.push({ key: "xa", label: "Expected assists", points: xa.points });
  }

  const defensiveSeries: TrendSeries[] = [];
  if (dc.points.length > 0) {
    defensiveSeries.push({ key: "dc", label: "Defensive actions", points: dc.points });
  }
  if (dcPoints.points.length > 0) {
    defensiveSeries.push({ key: "dc_pts", label: "Points awarded", points: dcPoints.points });
  }

  const prices = playerHistory.prices;

  return {
    gameweeksPlayed,
    hasGameweeks: entries.length > 0,
    hasPrices: prices.length > 0,
    points: byGameweek(entries, (e) => e.pts),
    minutes: byGameweek(entries, (e) => e.mins),
    attacking: {
      series: attackingSeries,
      coverage: { measured: xg.measured, total },
    },
    defensive:
      defensiveSeries.length === 0
        ? null
        : { series: defensiveSeries, coverage: { measured: dc.measured, total } },
    // x is the observation index, not a date: the observations are irregular, and spacing them
    // evenly is what makes a step function readable. The date labels come from `priceDates`.
    price: {
      key: "price",
      label: "Price",
      points: prices.map((observation, index) => ({ x: index, y: observation.price })),
    },
    ownership: {
      key: "owned",
      label: "Selected by",
      points: prices.map((observation, index) => ({ x: index, y: observation.owned })),
    },
    priceDates: prices.map((observation) => observation.on),
    totals: {
      points: entries.reduce((sum, e) => sum + e.pts, 0),
      minutes: entries.reduce((sum, e) => sum + e.mins, 0),
      goals: goals.total ?? 0,
      assists: assists.total ?? 0,
      expectedGoals: xg.total,
      expectedAssists: xa.total,
    },
  };
}

/** Find one player's history in the artefact. Null when the artefact does not carry them. */
export function findPlayerHistory(history: History, playerId: number): PlayerHistory | null {
  return history.players.find((p) => p.id === playerId) ?? null;
}

/**
 * How much of the season has expected-goals data, as a sentence.
 *
 * Stated rather than implied: a chart drawn from four of eleven gameweeks is a different object from
 * one drawn from eleven, and the reader cannot tell them apart by looking (DP-09).
 */
export function coverageStatement(coverage: Coverage, what: string): string | null {
  if (coverage.total === 0) return null;
  if (coverage.measured === 0) return `No ${what} data has been measured this season.`;
  if (coverage.measured >= coverage.total) return null;
  return `Measured in ${coverage.measured} of ${coverage.total} gameweeks — the rest have no ${what} data, which is not the same as a nil return.`;
}
