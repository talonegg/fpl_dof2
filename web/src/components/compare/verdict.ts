/**
 * The plain-language verdict on a comparison (E6-S4, FR-28).
 *
 * This is what makes `/compare` worth more than reading two rows of the scout table: the table shows
 * the numbers, this says what the numbers mean. It is a **fixed set of rules over the published
 * figures**, not generated prose — there is no model here, no external call (Invariant 8) and no
 * paid service (Invariant 3). Every sentence is derived from a field in `players.json`, and the
 * function is pure so the wording can be tested without a DOM (DP-03, DP-13).
 *
 * The hard constraint is Invariant 6 and DP-09: **a verdict must not claim a difference the
 * uncertainty does not support.** "Watkins is better next week" is an unearned sentence when the two
 * forecasts are 4.20 ±1.9 and 4.52 ±2.0, and it is exactly the kind of unearned sentence a
 * comparison view invites. So every forecast claim goes through `separated`, and when the gap is
 * inside the noise the verdict says so in as many words rather than quietly picking a winner.
 */

import type { Components, Player } from "../../contract/types";
import { formatPercent, formatPrice, formatXp } from "../../format";
import { AVAILABLE_STATUS, statusLabel } from "../scout/columns";

/**
 * How many combined standard deviations two forecasts must differ by before the verdict is willing
 * to name a leader.
 *
 * Presentation thresholds, like `COMPARE_MIN`/`COMPARE_MAX` in `data/comparison.ts`: they set how
 * this view *talks*, not how the game scores, so Invariant 2 is not engaged and they belong beside
 * the code that reads them rather than in `rules.json`.
 *
 * **Why one sigma, and not two.** The band shown elsewhere in the app is two standard deviations,
 * because that is the honest width of a *single* forecast. This is a different question: whether two
 * forecasts differ. At the top of the ranking a single-gameweek forecast carries a standard
 * deviation around half its own mean, so a two-sigma bar on the *difference* would declare every
 * pair of players indistinguishable and the verdict would never say anything at all. One sigma on
 * the difference is a deliberately modest bar, and the wording that goes with it claims no more than
 * that — "wider than the combined uncertainty", never "clearly better".
 */
export const SEPARATION_SIGMAS = 1;

/**
 * Percentage points of modelled start probability that count as a real difference.
 *
 * Below this the two are the same claim rendered to different decimal places; a verdict that calls
 * 91% against 89% "the surer starter" is reading noise aloud.
 */
export const START_PROBABILITY_MARGIN = 5;

/** Percentage points of ownership that count as a real difference, for the same reason. */
export const OWNERSHIP_MARGIN = 5;

/** Share of the forecast that must come from appearance points before it is called a high floor. */
export const HIGH_FLOOR_SHARE = 0.5;

export interface VerdictLine {
  /** Stable key: the dimension this line is about. */
  key: string;
  /** Short heading for the dimension, e.g. "Next gameweek". */
  heading: string;
  /** The sentence, or two, in plain British English. */
  statement: string;
  /**
   * True when the published numbers actually separate the players on this dimension.
   *
   * False is not a missing answer — it is the answer, and the view renders it differently rather
   * than hiding it. "These are too close to call" is decision-relevant information (DP-09).
   */
  decisive: boolean;
}

export interface Verdict {
  headline: string;
  lines: VerdictLine[];
  /** What the reader must hold in mind while reading the lines above. Never optional. */
  caveats: string[];
}

export interface VerdictOptions {
  /** How many gameweeks the horizon forecast covers, from `meta.horizon_gameweeks`. */
  horizonGameweeks?: number;
}

/**
 * Do two forecasts differ by more than their own uncertainty?
 *
 * The two means are treated as independent, so the standard deviation of the difference is the root
 * sum of squares. Exported because the table marks a leading forecast cell on exactly the same test
 * — one rule for when a lead may be claimed, read in two places rather than stated twice.
 */
export function separated(aMean: number, aSd: number, bMean: number, bSd: number): boolean {
  const gap = Math.abs(aMean - bMean);
  const noise = Math.sqrt(aSd * aSd + bSd * bSd) * SEPARATION_SIGMAS;
  return gap > noise;
}

function points(value: number): string {
  return value.toFixed(2);
}

/**
 * "A, B and C" — an Oxford-comma-free list, as British English prefers.
 *
 * Ordered by id rather than by the order the ids happened to appear in the URL, so the same three
 * players produce the same sentence however they were ticked (DP-11).
 */
function names(list: readonly Player[]): string {
  const all = [...list].sort((a, b) => a.id - b.id).map((player) => player.name);
  if (all.length <= 1) return all.join("");
  return `${all.slice(0, -1).join(", ")} and ${all[all.length - 1]}`;
}

function rankBy(players: readonly Player[], value: (player: Player) => number): Player[] {
  // Ties break on id, so the same input always produces the same sentence (DP-11).
  return [...players].sort((a, b) => value(b) - value(a) || a.id - b.id);
}

/** Points a player is forecast to earn simply by appearing. The floor under everything else. */
function floor(player: Player): number {
  return player.components.appearance;
}

function sumComponents(player: Player, keys: readonly (keyof Components)[]): number {
  return keys.reduce((total, key) => total + player.components[key], 0);
}

/** Goals and assists: the returns that arrive in lumps. */
function attacking(player: Player): number {
  return sumComponents(player, ["goals", "assists"]);
}

/**
 * Clean sheets, saves and defensive contribution: the returns that accrue.
 *
 * `goals_conceded` is deliberately excluded — it is a deduction, and folding a negative into a
 * "where the points come from" total would understate a defender who is expected to earn a lot and
 * concede a lot, which is precisely the player this line exists to describe.
 */
function defensive(player: Player): number {
  return sumComponents(player, ["clean_sheet", "saves", "defensive_contribution"]);
}

function forecastLine(
  players: readonly Player[],
  key: "next" | "horizon",
  options: VerdictOptions,
): VerdictLine {
  const mean = (p: Player) => (key === "next" ? p.xp_next : p.xp_horizon);
  const sd = (p: Player) => (key === "next" ? p.xp_next_sd : p.xp_horizon_sd);
  const ranked = rankBy(players, mean);
  const [leader, runnerUp] = ranked;

  const horizonWeeks = options.horizonGameweeks;
  const heading =
    key === "next"
      ? "Next gameweek"
      : horizonWeeks === undefined
        ? "Over the horizon"
        : `Over the next ${horizonWeeks} gameweeks`;
  const period = key === "next" ? "next gameweek" : "over the horizon";

  const shown = `${leader.name} ${formatXp(mean(leader), sd(leader))} against ${runnerUp.name} ${formatXp(mean(runnerUp), sd(runnerUp))}`;
  const gap = mean(leader) - mean(runnerUp);
  const rest =
    ranked.length > 2
      ? ` Behind them: ${ranked
          .slice(2)
          .map((p) => `${p.name} ${formatXp(mean(p), sd(p))}`)
          .join(", ")}.`
      : "";

  if (separated(mean(leader), sd(leader), mean(runnerUp), sd(runnerUp))) {
    return {
      key: `forecast_${key}`,
      heading,
      statement: `${leader.name} has the better forecast ${period} — ${shown}. The ${points(gap)}-point gap is wider than the combined uncertainty in the two forecasts, so it is a difference worth acting on.${rest}`,
      decisive: true,
    };
  }

  return {
    key: `forecast_${key}`,
    heading,
    statement: `Nothing separates them ${period}: ${shown}, a gap of ${points(gap)} points against uncertainty bands far wider than that. Treat them as level here and decide on something else.${rest}`,
    decisive: false,
  };
}

/** The order swapping between the single gameweek and the horizon is worth saying out loud. */
function orderSwapLine(players: readonly Player[], options: VerdictOptions): VerdictLine | null {
  const nextLeader = rankBy(players, (p) => p.xp_next)[0];
  const horizonLeader = rankBy(players, (p) => p.xp_horizon)[0];
  if (nextLeader.id === horizonLeader.id) return null;

  const weeks =
    options.horizonGameweeks === undefined
      ? "the horizon"
      : `the ${options.horizonGameweeks}-gameweek horizon`;
  return {
    key: "order_swap",
    heading: "The order changes",
    statement: `${nextLeader.name} leads for the single gameweek but ${horizonLeader.name} leads over ${weeks}. If this is a transfer you intend to keep, the horizon is the number that matters; if it is a one-week punt, it is not.`,
    decisive: true,
  };
}

function valueLine(players: readonly Player[]): VerdictLine {
  const byPrice = [...players].sort((a, b) => a.price - b.price || a.id - b.id);
  const cheapest = byPrice[0];
  const dearest = byPrice[byPrice.length - 1];

  const rate = (p: Player) => (p.price > 0 ? p.xp_horizon / p.price : 0);
  const bestRate = rankBy(players, rate)[0];

  if (cheapest.price === dearest.price) {
    return {
      key: "value",
      heading: "Price",
      statement: `They all cost the same, ${formatPrice(cheapest.price)}, so this is not a budget decision — whatever you pick frees the same money for the rest of the squad.`,
      decisive: false,
    };
  }

  const saving = dearest.price - cheapest.price;
  const elsewhere = ` That ${formatPrice(saving)} has to earn its keep somewhere else in the squad.`;
  const rateSentence = `Per £m of price the horizon forecast is ${points(rate(cheapest))} for ${cheapest.name} against ${points(rate(dearest))} for ${dearest.name}${
    bestRate.id !== cheapest.id && bestRate.id !== dearest.id
      ? `, and ${points(rate(bestRate))} for ${bestRate.name}, the best rate of the ${players.length}`
      : ""
  }.`;

  return {
    key: "value",
    heading: "Price",
    statement: `${cheapest.name} is ${formatPrice(saving)} cheaper than ${dearest.name} (${formatPrice(cheapest.price)} against ${formatPrice(dearest.price)}). ${rateSentence}${elsewhere}`,
    // A ratio of two means, carrying none of the uncertainty above — said plainly in the caveats.
    decisive: bestRate.id === cheapest.id,
  };
}

function availabilityLine(players: readonly Player[]): VerdictLine {
  const flagged = players.filter((player) => player.status !== AVAILABLE_STATUS);
  if (flagged.length > 0) {
    const detail = flagged
      .map((player) => {
        const news = player.news ? ` — ${player.news}` : "";
        return `${player.name} is ${statusLabel(player.status).toLowerCase()}${news}`;
      })
      .join("; ");
    return {
      key: "availability",
      heading: "Availability",
      statement: `${detail}. An availability flag outranks any forecast gap on this page: the model prices the risk in, but it cannot know what the manager knows.`,
      decisive: true,
    };
  }

  const ranked = rankBy(players, (p) => p.start_probability);
  const [surest, next] = ranked;
  const spread = (surest.start_probability - next.start_probability) * 100;
  const shownStarts = ranked
    .map((p) => `${p.name} ${formatPercent(p.start_probability * 100)}`)
    .join(", ");

  const confidences = new Set(players.map((p) => p.confidence));
  const confidenceNote =
    confidences.size === 1
      ? ` The model rates its own confidence ${ranked[0].confidence} for all of them.`
      : ` The model is not equally confident in these forecasts: ${ranked.map((p) => `${p.name} ${p.confidence}`).join(", ")}.`;

  if (spread >= START_PROBABILITY_MARGIN) {
    return {
      key: "availability",
      heading: "Minutes and confidence",
      statement: `${surest.name} is the surer starter: ${shownStarts}, all modelled rather than observed.${confidenceNote}`,
      decisive: true,
    };
  }

  return {
    key: "availability",
    heading: "Minutes and confidence",
    statement: `All are modelled to start about as often as each other — ${shownStarts}.${confidenceNote}`,
    decisive: confidences.size > 1,
  };
}

function ownershipLine(players: readonly Player[]): VerdictLine | null {
  const known = players.filter((player) => player.selected_by_percent !== undefined);
  if (known.length < 2) return null;

  const ranked = rankBy(known, (p) => p.selected_by_percent ?? 0);
  const most = ranked[0];
  const least = ranked[ranked.length - 1];
  const spread = (most.selected_by_percent ?? 0) - (least.selected_by_percent ?? 0);
  const shown = ranked
    .map((p) => `${p.name} ${formatPercent(p.selected_by_percent)}`)
    .join(", ");

  if (spread >= OWNERSHIP_MARGIN) {
    return {
      key: "ownership",
      heading: "Ownership",
      statement: `${least.name} is the differential of the ${known.length}: selected by ${formatPercent(least.selected_by_percent)} against ${most.name}'s ${formatPercent(most.selected_by_percent)}. Owning the crowd's pick loses you nothing when it hauls; owning the differential is where a rank moves, in either direction.`,
      decisive: true,
    };
  }

  return {
    key: "ownership",
    heading: "Ownership",
    statement: `Ownership barely separates them — ${shown}. Neither is a rank-moving differential against the other.`,
    decisive: false,
  };
}

function componentsLine(players: readonly Player[]): VerdictLine {
  const lean = (p: Player) => attacking(p) - defensive(p);
  const ranked = rankBy(players, lean);
  const mostAttacking = ranked[0];
  const mostDefensive = ranked[ranked.length - 1];

  const describe = (p: Player) =>
    `${p.name} ${points(attacking(p))} from goals and assists against ${points(defensive(p))} from clean sheets, saves and defensive contribution`;

  // Equal leans, not equal players: a decomposition that splits everyone the same way says nothing,
  // and pretending otherwise would badge a rounding difference as a difference of kind.
  if (lean(mostAttacking) === lean(mostDefensive)) {
    return {
      key: "components",
      heading: "Where the points come from",
      statement: `They all split the same way: ${points(attacking(mostAttacking))} from goals and assists against ${points(defensive(mostAttacking))} from clean sheets, saves and defensive contribution. Picking between them is not a choice between two kinds of return.`,
      decisive: false,
    };
  }

  const leansAttacking = attacking(mostAttacking) > defensive(mostAttacking);
  const leansDefensive = defensive(mostDefensive) > attacking(mostDefensive);
  const contrast =
    leansAttacking && leansDefensive
      ? " These are different bets, not two routes to the same points: attacking returns arrive in lumps and defensive ones accrue, so they fail on different weeks."
      : " The lean is a matter of degree rather than of kind here.";

  return {
    key: "components",
    heading: "Where the points come from",
    statement: `${describe(mostAttacking)}. ${describe(mostDefensive)}.${contrast}`,
    decisive: true,
  };
}

function floorLine(players: readonly Player[]): VerdictLine | null {
  const share = (p: Player) => (p.xp_next > 0 ? floor(p) / p.xp_next : 0);
  const ranked = rankBy(players, share);
  const highest = ranked[0];
  const lowest = ranked[ranked.length - 1];
  // Identical floors are not a difference in safety, so there is nothing to say.
  if (share(highest) === share(lowest)) return null;

  const shown = `${formatPercent(share(highest) * 100)} of ${highest.name}'s forecast is appearance points against ${formatPercent(share(lowest) * 100)} of ${lowest.name}'s`;

  if (share(highest) >= HIGH_FLOOR_SHARE && share(lowest) < HIGH_FLOOR_SHARE) {
    return {
      key: "floor",
      heading: "Floor against ceiling",
      statement: `${highest.name} is the safer of the two: ${shown}, so most of the forecast arrives simply for playing. ${lowest.name} has to actually return to beat it, which is the higher ceiling and the worse blank.`,
      decisive: true,
    };
  }

  return {
    key: "floor",
    heading: "Floor against ceiling",
    statement: `${shown} — a difference in how safe the forecast is, though not a large one.`,
    decisive: false,
  };
}

function headline(players: readonly Player[], options: VerdictOptions): string {
  const byHorizon = rankBy(players, (p) => p.xp_horizon);
  const [horizonLeader, horizonNext] = byHorizon;
  const byNext = rankBy(players, (p) => p.xp_next);
  const [nextLeader, nextRunnerUp] = byNext;

  const horizonSeparated = separated(
    horizonLeader.xp_horizon,
    horizonLeader.xp_horizon_sd,
    horizonNext.xp_horizon,
    horizonNext.xp_horizon_sd,
  );
  const nextSeparated = separated(
    nextLeader.xp_next,
    nextLeader.xp_next_sd,
    nextRunnerUp.xp_next,
    nextRunnerUp.xp_next_sd,
  );

  const weeks =
    options.horizonGameweeks === undefined
      ? "the horizon"
      : `the next ${options.horizonGameweeks} gameweeks`;

  if (horizonSeparated) {
    return `${horizonLeader.name} is the stronger forecast over ${weeks}, by more than the uncertainty in the two numbers.`;
  }
  if (nextSeparated) {
    return `${nextLeader.name} has the better single-gameweek forecast, but nothing separates these ${players.length} over ${weeks}.`;
  }
  return `The forecast does not separate ${names(players)} — the gaps are smaller than their own uncertainty, so decide on price, minutes and how the points are earned.`;
}

function caveats(players: readonly Player[]): string[] {
  const out = [
    "Every figure here is a forecast carrying an uncertainty band, not a measurement. Where this verdict declines to name a leader, that is the finding rather than a missing answer.",
    "Points per £m is a ratio of two means and carries none of the uncertainty above; read it alongside the bands, not instead of them.",
    "Ownership is FPL's own published 'selected by' figure. It is not effective ownership, which this project does not observe (DL-24).",
    "This verdict is assembled from the published numbers by a fixed set of rules. It adds no information the table above does not already contain — it only says which differences are large enough to matter.",
  ];

  // Canonical order, not the order the ids arrived in, so the sentence is stable (DP-11).
  const order: Player["position"][] = ["GKP", "DEF", "MID", "FWD"];
  const present = new Set(players.map((player) => player.position));
  const positions = order.filter((position) => present.has(position));
  if (positions.length > 1) {
    out.unshift(
      `These are ${positions.join(", ")} — different positions, scored differently, and usually not alternatives for the same squad slot. Compare them knowing that.`,
    );
  }
  return out;
}

/**
 * The verdict for a resolved comparison of two to four players.
 *
 * Callers resolve the ids first: this takes players, not ids, and expects at least two. Fewer than
 * two is a route-level state with its own view, not something to render an apologetic verdict for.
 */
export function buildVerdict(players: readonly Player[], options: VerdictOptions = {}): Verdict {
  if (players.length < 2) {
    return {
      headline: "A comparison needs at least two players.",
      lines: [],
      caveats: [],
    };
  }

  const lines: (VerdictLine | null)[] = [
    forecastLine(players, "next", options),
    forecastLine(players, "horizon", options),
    orderSwapLine(players, options),
    valueLine(players),
    availabilityLine(players),
    ownershipLine(players),
    componentsLine(players),
    floorLine(players),
  ];

  return {
    headline: headline(players, options),
    lines: lines.filter((line): line is VerdictLine => line !== null),
    caveats: caveats(players),
  };
}
