import type { Live, LiveFigures, LiveTeam } from "../contract/types";

/**
 * Reading `live.json`, the gameweek in play (LIVE-05, LIVE-06, DL-99): pure functions, DOM-free.
 *
 * The views only **display, order and label** what the pipeline published. Every figure was scored
 * by the one realised scorer (ORC-04) and every rule-like number stays in `rules.json` (Invariant
 * 9), so nothing here scores a player, applies the armband or works out a substitution; the
 * product of a player's points and the multiplier *as the pipeline applied it* is the one sum, and
 * it is the displayed figure, not a second scorer.
 */

type Status = Live["status"];

/** A status in words. Status is always shown as text, never by colour alone (NFR-14). */
const STATUS_LABEL: Record<Status, string> = {
  in_play: "In play",
  bonus_pending: "Bonus pending",
  complete: "Complete",
  final: "Final",
};

export const statusLabel = (status: Status): string => STATUS_LABEL[status];

/** What a status means, for a tooltip and a screen reader (the contract's own definitions). */
const STATUS_MEANING: Record<Status, string> = {
  in_play: "a fixture is still to finish",
  bonus_pending: "every fixture is at full time but a bonus is not yet confirmed",
  complete: "every bonus is confirmed; FPL has not yet data-checked the gameweek",
  final: "FPL has data-checked the gameweek",
};

export const statusMeaning = (status: Status): string => STATUS_MEANING[status];

/** One team's published gameweek by entry id, or undefined. */
export function liveTeam(live: Live | null, entryId: number): LiveTeam | undefined {
  return live?.teams.find((team) => team.entry_id === entryId);
}

/** The owner's team, or undefined when `live.json` has none. */
export function liveOwner(live: Live | null): LiveTeam | undefined {
  return live?.teams.find((team) => team.is_owner);
}

/** A team's figures once the pipeline gave it a live one; a team without one is "not live". */
export function liveFigures(team: LiveTeam | undefined): LiveFigures | null {
  return team?.live ?? null;
}

/**
 * Whether a team's figures can still move: true until FPL has data-checked its gameweek. The
 * gameweek's own `provisional` flag is the same fact, but one team can be `final` first.
 */
export const isProvisional = (figures: LiveFigures): boolean => figures.status !== "final";

/** What a fielded player counts for so far: his points, times the multiplier as applied (the captain's armband). */
export const countedPoints = (player: { points: number; multiplier: number }): number =>
  player.points * player.multiplier;

export interface Substitution {
  on: number;
  off: number;
}

/**
 * The projected substitutions as pairs. The scorer appends the two ids together, so the n-th
 * substitute coming on is for the n-th starter going off (`rules/realised.py`).
 */
export function substitutions(figures: LiveFigures): Substitution[] {
  return figures.autosubs_in.flatMap((on, i) => {
    const off = figures.autosubs_out[i];
    return off === undefined ? [] : [{ on, off }];
  });
}

/** The fifteen split into those on the field (a multiplier above zero) and the bench, each in slot order. */
export function fieldedAndBench(figures: LiveFigures): { fielded: LiveFigures["players"]; bench: LiveFigures["players"] } {
  const bySlot = [...figures.players].sort((a, b) => a.slot - b.slot);
  return { fielded: bySlot.filter((p) => p.multiplier > 0), bench: bySlot.filter((p) => p.multiplier === 0) };
}

/**
 * A player's bonus in words, by how far his own fixtures have got. "Bonus pending" is only true once
 * his match is over (`complete`) and FPL has not yet confirmed the bonus; before that he is yet to
 * play, or his match is not over, and there is no bonus to be pending (LIVE-05, LIVE-06).
 */
export function bonusText(player: { bonus: number; bonus_confirmed: boolean; complete: boolean; minutes: number }): string {
  // First, whatever the bonus flag says: a player with no fixture started has no bonus of any kind
  // (the pipeline reads "no rows yet" as confirmed, which "no bonus" would misreport as a verdict).
  if (!player.complete && player.minutes === 0) return "yet to play";
  if (player.bonus_confirmed) return player.bonus > 0 ? `+${player.bonus} bonus, confirmed` : "no bonus";
  if (!player.complete) return player.bonus > 0 ? `+${player.bonus} bonus so far, match not over` : "match not over";
  return player.bonus > 0 ? `+${player.bonus} bonus, pending` : "bonus pending";
}
