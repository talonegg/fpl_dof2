/**
 * The scout table's columns, as data.
 *
 * A column knows four things: how to sort by it, how to render it, how wide it wants to be, and
 * whether it is on by default. Keeping that in one array rather than spread through JSX is what
 * makes the column picker, the sort headers and the phone layout three readers of one definition
 * instead of three places to forget a column (DL-36). E6-S3 and E6-S4 reuse the accessors rather
 * than restating how a component is rendered.
 *
 * Groups exist so the picker can be skimmed: identity, value, forecast, underlying.
 */

import type { ReactNode } from "react";
import type { Components, Player } from "../../contract/types";
import { formatPercent, formatPrice, formatXpRange } from "../../format";

export type ColumnGroup = "identity" | "value" | "forecast" | "underlying";

export interface ScoutColumn {
  key: string;
  /** Header text. Kept short — the header row is the first thing that overflows. */
  label: string;
  /** What the header abbreviates, for the `title` and the accessible name. */
  description: string;
  group: ColumnGroup;
  /** Track width in the CSS grid that lays the rows out. */
  width: string;
  numeric: boolean;
  /** Sort key. Strings sort lexically, numbers numerically; missing values sort last either way. */
  sortValue: (player: Player) => number | string | null;
  render: (player: Player) => ReactNode;
  /** Cell tooltip, where the rendered value abbreviates something longer. */
  cellTitle?: (player: Player) => string | undefined;
  /** In the default column set. The rest are one click away in the picker. */
  defaultVisible: boolean;
}

export const GROUP_LABELS: Record<ColumnGroup, string> = {
  identity: "Identity",
  value: "Value and ownership",
  forecast: "Forecast",
  underlying: "Expected-points components",
};

export const GROUP_ORDER: ColumnGroup[] = ["identity", "value", "forecast", "underlying"];

/**
 * FPL's availability codes, as published on the player.
 *
 * These are enum values from the source data, not rule values — no scoring, price or squad number
 * appears here — so Invariant 2 is not engaged. An unrecognised code renders as itself rather than
 * as "unknown", because a new code is information and hiding it would be the bug.
 */
const STATUS_LABELS: Record<string, string> = {
  a: "Available",
  d: "Doubtful",
  i: "Injured",
  s: "Suspended",
  u: "Unavailable",
  n: "On loan or ineligible",
};

export const AVAILABLE_STATUS = "a";

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

/** Rank a status for sorting: available first, then the codes that reduce it, worst last. */
const STATUS_SORT_ORDER = ["a", "d", "s", "i", "u", "n"];

function statusRank(status: string): number {
  const index = STATUS_SORT_ORDER.indexOf(status);
  return index === -1 ? STATUS_SORT_ORDER.length : index;
}

const CONFIDENCE_SORT_ORDER: Player["confidence"][] = ["high", "medium", "low", "none"];

const COMPONENT_LABELS: Record<keyof Components, { label: string; description: string }> = {
  appearance: { label: "App", description: "Expected points from appearances" },
  goals: { label: "Gls", description: "Expected points from goals" },
  assists: { label: "Ast", description: "Expected points from assists" },
  clean_sheet: { label: "CS", description: "Expected points from clean sheets" },
  goals_conceded: { label: "GC", description: "Expected points lost to goals conceded" },
  saves: { label: "Sv", description: "Expected points from saves" },
  defensive_contribution: {
    label: "DC",
    description: "Expected points from defensive contribution",
  },
  bonus: { label: "Bns", description: "Expected bonus points" },
  cards: { label: "Cds", description: "Expected points lost to cards" },
};

/** The underlying-stats columns, in the order xP decomposes. All off by default — there are nine. */
const componentColumns: ScoutColumn[] = (Object.keys(COMPONENT_LABELS) as (keyof Components)[]).map(
  (key) => ({
    key: `component_${key}`,
    label: COMPONENT_LABELS[key].label,
    description: COMPONENT_LABELS[key].description,
    group: "underlying" as const,
    width: "4.4rem",
    numeric: true,
    sortValue: (p: Player) => p.components[key],
    render: (p: Player) => p.components[key].toFixed(2),
    defaultVisible: false,
  }),
);

/**
 * A forecast cell. Invariant 6 and DP-09: the mean never appears without its band, and the two are
 * separate spans so the stylesheet can make the uncertainty visibly part of the number rather than
 * a footnote beside it.
 */
function XpCell({ mean, sd }: { mean: number; sd: number }) {
  return (
    <span className="scout-xp">
      <span className="scout-xp-mean">{mean.toFixed(2)}</span>
      <span className="scout-xp-sd"> ±{sd.toFixed(1)}</span>
    </span>
  );
}

export const SCOUT_COLUMNS: ScoutColumn[] = [
  {
    key: "name",
    label: "Player",
    description: "Player name",
    group: "identity",
    width: "minmax(7rem, 1.6fr)",
    numeric: false,
    sortValue: (p) => p.name.toLowerCase(),
    render: (p) => p.name,
    cellTitle: (p) => p.full_name ?? p.name,
    defaultVisible: true,
  },
  {
    key: "position",
    label: "Pos",
    description: "Position",
    group: "identity",
    width: "3.6rem",
    numeric: false,
    sortValue: (p) => p.position,
    render: (p) => p.position,
    defaultVisible: true,
  },
  {
    key: "team",
    label: "Club",
    description: "Club",
    group: "identity",
    width: "3.8rem",
    numeric: false,
    sortValue: (p) => p.team.toLowerCase(),
    render: (p) => p.team,
    defaultVisible: true,
  },
  {
    key: "price",
    label: "Price",
    description: "Price, in £m",
    group: "value",
    width: "4.8rem",
    numeric: true,
    sortValue: (p) => p.price,
    render: (p) => formatPrice(p.price),
    defaultVisible: true,
  },
  {
    key: "value",
    label: "xP/£m",
    description: "Expected points next gameweek per £m of price",
    group: "value",
    width: "4.8rem",
    numeric: true,
    sortValue: (p) => (p.price > 0 ? p.xp_next / p.price : null),
    render: (p) => (p.price > 0 ? (p.xp_next / p.price).toFixed(2) : "—"),
    defaultVisible: false,
  },
  {
    key: "selected_by_percent",
    label: "Sel %",
    description:
      "Selected by — FPL's own published ownership figure, never effective ownership (DL-24)",
    group: "value",
    width: "4.6rem",
    numeric: true,
    sortValue: (p) => p.selected_by_percent ?? null,
    render: (p) => formatPercent(p.selected_by_percent),
    defaultVisible: true,
  },
  {
    key: "start_probability",
    label: "Start %",
    description: "Modelled probability of starting the next gameweek — a forecast, not a record",
    group: "forecast",
    width: "5rem",
    numeric: true,
    sortValue: (p) => p.start_probability,
    render: (p) => formatPercent(p.start_probability * 100),
    defaultVisible: true,
  },
  // TODO(E6-S2): minutes played, form and the fixture run are named in the E6-S2 story but are not
  // in the published `players.json` contract. They arrive with `history.json` and `fixtures.json`
  // (E6-S1b); each is one entry in this array once they do. `start_probability` stands in for
  // minutes meanwhile, and is labelled as the forecast it is rather than as a record of anything.
  {
    key: "xp_next",
    label: "xP next",
    description: "Expected points next gameweek, with its uncertainty (Invariant 6)",
    group: "forecast",
    width: "6.6rem",
    numeric: true,
    sortValue: (p) => p.xp_next,
    render: (p) => <XpCell mean={p.xp_next} sd={p.xp_next_sd} />,
    cellTitle: (p) => formatXpRange(p.xp_next, p.xp_next_sd),
    defaultVisible: true,
  },
  {
    key: "xp_horizon",
    label: "xP run",
    description: "Expected points over the planning horizon, with its uncertainty (Invariant 6)",
    group: "forecast",
    width: "7rem",
    numeric: true,
    sortValue: (p) => p.xp_horizon,
    render: (p) => <XpCell mean={p.xp_horizon} sd={p.xp_horizon_sd} />,
    cellTitle: (p) => formatXpRange(p.xp_horizon, p.xp_horizon_sd),
    defaultVisible: true,
  },
  {
    key: "confidence",
    label: "Conf",
    description: "How much the model trusts this forecast",
    group: "forecast",
    width: "5.6rem",
    numeric: false,
    sortValue: (p) => CONFIDENCE_SORT_ORDER.indexOf(p.confidence),
    render: (p) => (
      <span className={`confidence-badge confidence-${p.confidence}`}>{p.confidence}</span>
    ),
    defaultVisible: true,
  },
  {
    key: "status",
    label: "Avail",
    description: "Availability, as the game reports it",
    group: "forecast",
    width: "6rem",
    numeric: false,
    sortValue: (p) => statusRank(p.status),
    render: (p) => statusLabel(p.status),
    cellTitle: (p) => p.news || undefined,
    defaultVisible: false,
  },
  ...componentColumns,
];

export const COLUMNS_BY_KEY: Record<string, ScoutColumn> = Object.fromEntries(
  SCOUT_COLUMNS.map((column) => [column.key, column]),
);

export const DEFAULT_VISIBLE_COLUMNS: string[] = SCOUT_COLUMNS.filter(
  (column) => column.defaultVisible,
).map((column) => column.key);

/**
 * The columns a phone gets.
 *
 * Deliberately not "the default set, narrower". At 390px there is room for the player, what they
 * cost and what they are forecast to return; everything else is noise you scroll past to reach the
 * next name. The rest stay one tap away on the row's detail panel.
 */
export const PHONE_COLUMNS: string[] = ["name", "position", "team", "price", "xp_next"];

/** Name is how you know which row you are on, so it may not be switched off. */
export const PINNED_COLUMN = "name";

/** Column keys in canonical order, whatever order the caller's set is in. */
export function orderColumns(keys: readonly string[]): ScoutColumn[] {
  const wanted = new Set(keys);
  return SCOUT_COLUMNS.filter((column) => wanted.has(column.key));
}
