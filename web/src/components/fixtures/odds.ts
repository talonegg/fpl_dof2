/**
 * Bookmaker odds on a fixture, as the margin-free probabilities `fixtures.json` publishes (ORC-15).
 * Always from the row's own club: win is this club winning. Shared by the ticker and the player's
 * fixture run so the two cannot word the same market differently.
 */
import type { FixtureOdds } from "../../contract/types";
import { formatLocalDateTime } from "../../format";

const pct = (p: number) => `${Math.round(p * 100)}%`;

/** Compact, never colour-only: letters carry the meaning. */
export const oddsShort = (o: FixtureOdds) => `W ${pct(o.win)} D ${pct(o.draw)} L ${pct(o.loss)}`;

/** The full sentence, for tooltips and screen readers. */
export const oddsSentence = (o: FixtureOdds) =>
  `Bookmaker odds, margin removed: win ${pct(o.win)}, draw ${pct(o.draw)}, loss ${pct(o.loss)}, over 2.5 goals ${pct(o.over_2_5)}`;

/** ORC-07's next-check information, worded for odds that are not posted yet. */
export const oddsNotPosted = (nextCheck: string | null | undefined) =>
  nextCheck
    ? `Odds not posted yet; next check at ${formatLocalDateTime(nextCheck)}.`
    : "Odds not posted yet; no further check is due before the deadline.";
