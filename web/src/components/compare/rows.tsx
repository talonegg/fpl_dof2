/**
 * The comparison's rows, as data.
 *
 * Same shape of idea as `scout/columns.tsx`, transposed: the scout table puts players down the page
 * and attributes across it, a comparison puts attributes down the page and players across it. Both
 * are one array of definitions read by every layout, rather than JSX repeated per breakpoint.
 *
 * The interesting part is `leadingId`. Marking the best cell in a row is useful for price, ownership
 * and minutes, where the published number is what it is. It is **not** automatically safe for an
 * expected-points row: badging 4.52 as the leader over 4.20 ±1.9 asserts a difference the forecast
 * cannot support, which is the Invariant 6 failure this whole view is most likely to commit. So a
 * forecast row carries its standard deviation into the ranking, and only claims a lead when
 * `separated` from `verdict.ts` says the gap survives the uncertainty. One rule, read in two places.
 */

import type { ReactNode } from "react";
import type { Components, Player } from "../../contract/types";
import { formatPercent, formatPrice, formatXpRange } from "../../format";
import { statusLabel } from "../scout/columns";
import { separated } from "./verdict";

export type CompareGroup = "identity" | "value" | "forecast" | "components";

export const GROUP_LABELS: Record<CompareGroup, string> = {
  identity: "Identity",
  value: "Value and ownership",
  forecast: "Forecast",
  components: "Expected-points components",
};

export const GROUP_ORDER: CompareGroup[] = ["identity", "value", "forecast", "components"];

/** How a row is ranked across the compared players, when it can be ranked at all. */
export interface CompareRanking {
  value: (player: Player) => number | null;
  better: "higher" | "lower";
  /**
   * The uncertainty on `value`, for a row whose value is a forecast.
   *
   * Present means a lead is only claimed when the gap to the runner-up exceeds the combined
   * uncertainty. Absent means the number is published as-is and the best of it is simply the best.
   */
  sd?: (player: Player) => number;
}

export interface CompareRow {
  key: string;
  label: string;
  /** What the label abbreviates. Shown as the row's tooltip and its accessible description. */
  description: string;
  group: CompareGroup;
  render: (player: Player) => ReactNode;
  cellTitle?: (player: Player) => string | undefined;
  ranking?: CompareRanking;
}

/**
 * The forecast cell: mean and band, never the mean alone (Invariant 6). Two spans, as the scout
 * table does it, so the stylesheet can make the band part of the number rather than a footnote.
 */
function XpValue({ mean, sd }: { mean: number; sd: number }) {
  return (
    <span className="compare-xp">
      <span className="compare-xp-mean">{mean.toFixed(2)}</span>
      <span className="compare-xp-sd"> ±{sd.toFixed(1)}</span>
    </span>
  );
}

const COMPONENT_LABELS: Record<keyof Components, string> = {
  appearance: "Appearance",
  goals: "Goals",
  assists: "Assists",
  clean_sheet: "Clean sheet",
  goals_conceded: "Goals conceded",
  saves: "Saves",
  defensive_contribution: "Defensive contribution",
  bonus: "Bonus",
  cards: "Cards",
};

/**
 * The component rows.
 *
 * Every one ranks higher-is-better, deductions included: `goals_conceded` and `cards` are published
 * as negative expected points, so the player expected to lose the least already holds the highest
 * value. Inverting them here would badge the leakiest defender in the comparison as the winner.
 */
const componentRows: CompareRow[] = (Object.keys(COMPONENT_LABELS) as (keyof Components)[]).map(
  (key) => ({
    key: `component_${key}`,
    label: COMPONENT_LABELS[key],
    description: `Expected points from ${COMPONENT_LABELS[key].toLowerCase()}, part of the xP next decomposition`,
    group: "components" as const,
    render: (player: Player) => player.components[key].toFixed(2),
    ranking: { value: (player: Player) => player.components[key], better: "higher" as const },
  }),
);

export const COMPARE_ROWS: CompareRow[] = [
  {
    key: "position",
    label: "Position",
    description: "Playing position, which sets how the player is scored",
    group: "identity",
    render: (p) => p.position,
  },
  {
    key: "team",
    label: "Club",
    description: "Club",
    group: "identity",
    render: (p) => p.team,
  },
  {
    key: "price",
    label: "Price",
    description: "Current price, in £m. Cheaper is better, all else equal",
    group: "value",
    render: (p) => formatPrice(p.price),
    ranking: { value: (p) => p.price, better: "lower" },
  },
  {
    key: "value",
    label: "xP per £m",
    description:
      "Horizon expected points divided by price — a ratio of means, carrying none of the uncertainty",
    group: "value",
    render: (p) => (p.price > 0 ? (p.xp_horizon / p.price).toFixed(2) : "—"),
    ranking: { value: (p) => (p.price > 0 ? p.xp_horizon / p.price : null), better: "higher" },
  },
  {
    key: "selected_by_percent",
    label: "Selected by",
    description: "FPL's own published ownership figure. Never effective ownership (DL-24)",
    group: "value",
    render: (p) => formatPercent(p.selected_by_percent),
  },
  {
    key: "xp_next",
    label: "xP next gameweek",
    description: "Expected points next gameweek, with its uncertainty (Invariant 6)",
    group: "forecast",
    render: (p) => <XpValue mean={p.xp_next} sd={p.xp_next_sd} />,
    cellTitle: (p) => formatXpRange(p.xp_next, p.xp_next_sd),
    ranking: { value: (p) => p.xp_next, better: "higher", sd: (p) => p.xp_next_sd },
  },
  {
    key: "xp_horizon",
    label: "xP over the horizon",
    description: "Expected points over the planning horizon, with its uncertainty (Invariant 6)",
    group: "forecast",
    render: (p) => <XpValue mean={p.xp_horizon} sd={p.xp_horizon_sd} />,
    cellTitle: (p) => formatXpRange(p.xp_horizon, p.xp_horizon_sd),
    ranking: { value: (p) => p.xp_horizon, better: "higher", sd: (p) => p.xp_horizon_sd },
  },
  {
    key: "start_probability",
    label: "Chance of starting",
    description: "Modelled probability of starting the next gameweek — a forecast, not a record",
    group: "forecast",
    render: (p) => formatPercent(p.start_probability * 100),
    ranking: { value: (p) => p.start_probability, better: "higher" },
  },
  {
    key: "confidence",
    label: "Model confidence",
    description: "How much the model trusts this forecast",
    group: "forecast",
    render: (p) => <span className={`confidence-badge confidence-${p.confidence}`}>{p.confidence}</span>,
  },
  {
    key: "status",
    label: "Availability",
    description: "Availability, as the game reports it",
    group: "forecast",
    render: (p) => statusLabel(p.status),
    cellTitle: (p) => p.news || undefined,
  },
  ...componentRows,
];

/**
 * Which player, if any, leads this row.
 *
 * Returns null when the row is not ranked, when the leader ties with the runner-up, or when the row
 * is a forecast whose lead does not survive its own uncertainty. Pure, and tested directly: an
 * unearned badge on a forecast row is exactly the kind of wrong that looks fine on screen (DP-13).
 */
export function leadingId(row: CompareRow, players: readonly Player[]): number | null {
  const ranking = row.ranking;
  if (!ranking || players.length < 2) return null;

  const scored = players
    .map((player) => ({ player, value: ranking.value(player) }))
    .filter((entry): entry is { player: Player; value: number } => entry.value !== null);
  if (scored.length < 2) return null;

  const sign = ranking.better === "higher" ? -1 : 1;
  // Ties break on id so the badge never moves between renders of the same data (DP-11).
  scored.sort((a, b) => sign * (a.value - b.value) || a.player.id - b.player.id);

  const [leader, runnerUp] = scored;
  if (leader.value === runnerUp.value) return null;

  if (ranking.sd) {
    const leaderSd = ranking.sd(leader.player);
    const runnerUpSd = ranking.sd(runnerUp.player);
    if (!separated(leader.value, leaderSd, runnerUp.value, runnerUpSd)) return null;
  }

  return leader.player.id;
}
