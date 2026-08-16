/**
 * A player's upcoming fixture run, taken from the team-by-gameweek grid.
 *
 * Pure and DOM-free. Two things here are easy to get quietly wrong:
 *
 * - **The band thresholds are not FPL's FDR.** `fixtures.json` publishes its own `scale`, and the
 *   bands below are computed against that scale's `neutral`, `minimum` and `maximum` rather than
 *   against literals. A hardcoded "4 and above is hard" would be right only for whatever scale
 *   happened to be published the day it was written (DP-06).
 * - **Attack and defence difficulty are different numbers, and which one matters depends on the
 *   player's position.** A high-scoring game between two good sides is a good fixture for a forward
 *   and a bad one for a goalkeeper; collapsing that into one figure is most of what is wrong with a
 *   single FDR number, and the contract publishes both precisely so a view need not.
 */

import type {
  DifficultyScale,
  FixtureEntry,
  FixtureGameweek,
  Fixtures,
  Player,
  TeamFixtures,
} from "../../contract/types";

export type DifficultyBand = "very-easy" | "easy" | "neutral" | "hard" | "very-hard";

/**
 * Where the bands fall, as a fraction of the distance from neutral to the end of the scale.
 *
 * Presentation tunables, named rather than buried (DP-06). They are deliberately wide in the middle:
 * a model that has seen few matches produces scores clustered near neutral, and five equal bands
 * would paint confident colours onto differences the model cannot support.
 */
export const BAND_THRESHOLDS = { strong: 0.55, mild: 0.2 } as const;

export const BAND_LABELS: Record<DifficultyBand, string> = {
  "very-easy": "Very favourable",
  easy: "Favourable",
  neutral: "Neutral",
  hard: "Difficult",
  "very-hard": "Very difficult",
};

/** Band a difficulty score against the scale it was published with. Lower is easier. */
export function bandFor(difficulty: number, scale: DifficultyScale): DifficultyBand {
  const harderSpan = scale.maximum - scale.neutral;
  const easierSpan = scale.neutral - scale.minimum;

  if (difficulty > scale.neutral) {
    const fraction = harderSpan > 0 ? (difficulty - scale.neutral) / harderSpan : 0;
    if (fraction >= BAND_THRESHOLDS.strong) return "very-hard";
    if (fraction >= BAND_THRESHOLDS.mild) return "hard";
    return "neutral";
  }

  const fraction = easierSpan > 0 ? (scale.neutral - difficulty) / easierSpan : 0;
  if (fraction >= BAND_THRESHOLDS.strong) return "very-easy";
  if (fraction >= BAND_THRESHOLDS.mild) return "easy";
  return "neutral";
}

/**
 * The half of the scale that matters to this player.
 *
 * Goalkeepers and defenders are paid for clean sheets, so what their opponent is expected to score
 * is the number that decides their fixture. Forwards are paid for goals. Midfielders draw from both
 * and take the overall figure.
 */
export function relevantDifficulty(entry: FixtureEntry, position: Player["position"]): number {
  if (position === "GKP" || position === "DEF") return entry.defence_difficulty;
  if (position === "FWD") return entry.attack_difficulty;
  return entry.difficulty;
}

export function difficultyBasisLabel(position: Player["position"]): string {
  if (position === "GKP" || position === "DEF") return "what the opponent is expected to score";
  if (position === "FWD") return "what this club is expected to score";
  return "the overall balance of the fixture";
}

export interface RunFixture {
  gameweek: number;
  opponent: string;
  atHome: boolean;
  kickoffUtc: string | null;
  /** The figure this player is judged on, per `relevantDifficulty`. */
  difficulty: number;
  band: DifficultyBand;
  isDouble: boolean;
  /** Second and subsequent fixtures of a double, so the view can mark them. */
  indexInGameweek: number;
}

export interface RunGameweek {
  gameweek: number;
  isBlank: boolean;
  isDouble: boolean;
  fixtures: RunFixture[];
}

export interface FixtureRun {
  team: string;
  teamName: string;
  fromGameweek: number;
  toGameweek: number;
  gameweeks: RunGameweek[];
  /** Mean of the relevant difficulty across fixtures actually scheduled. Null when all blank. */
  meanDifficulty: number | null;
  meanBand: DifficultyBand | null;
  blanks: number;
  doubles: number;
  scale: DifficultyScale;
  /**
   * True when the difficulty model has no team ratings at all, so every fixture scores close to
   * neutral and the grid separates fixtures only by home advantage. Visible degradation, never
   * silent (DP-09, DP-15).
   */
  unrated: boolean;
}

function toRunGameweek(
  gameweek: FixtureGameweek,
  position: Player["position"],
  scale: DifficultyScale,
): RunGameweek {
  return {
    gameweek: gameweek.gameweek,
    isBlank: gameweek.is_blank,
    isDouble: gameweek.is_double,
    fixtures: gameweek.fixtures.map((entry, index) => {
      const difficulty = relevantDifficulty(entry, position);
      return {
        gameweek: gameweek.gameweek,
        opponent: entry.opponent,
        atHome: entry.at_home,
        kickoffUtc: entry.kickoff_utc ?? null,
        difficulty,
        band: bandFor(difficulty, scale),
        isDouble: gameweek.is_double,
        indexInGameweek: index,
      };
    }),
  };
}

/**
 * Build the run for a player, or null when the grid carries nothing for their club.
 *
 * Null is a normal answer, not a failure: a bundle deployed against an older published data
 * directory, or a club the grid does not cover, must leave the rest of the page intact (DP-15).
 * Matching is on `team_id` rather than the short name, because the short name is a display label and
 * the id is the key.
 */
export function buildFixtureRun(
  fixtures: Fixtures,
  player: Pick<Player, "team_id" | "position">,
): FixtureRun | null {
  const team: TeamFixtures | undefined = fixtures.teams.find((t) => t.team_id === player.team_id);
  if (!team) return null;

  const gameweeks = team.gameweeks.map((gw) => toRunGameweek(gw, player.position, fixtures.scale));
  const played = gameweeks.flatMap((gw) => gw.fixtures);

  const meanDifficulty =
    played.length === 0
      ? null
      : played.reduce((sum, f) => sum + f.difficulty, 0) / played.length;

  return {
    team: team.team,
    teamName: team.name,
    fromGameweek: fixtures.from_gameweek,
    toGameweek: fixtures.to_gameweek,
    gameweeks,
    meanDifficulty,
    meanBand: meanDifficulty === null ? null : bandFor(meanDifficulty, fixtures.scale),
    blanks: gameweeks.filter((gw) => gw.isBlank).length,
    doubles: gameweeks.filter((gw) => gw.isDouble).length,
    scale: fixtures.scale,
    unrated: fixtures.model.teams_rated === 0,
  };
}

/** The run in words, for readers who take a sentence faster than a strip of colours (DP-09). */
export function runStatement(run: FixtureRun, position: Player["position"]): string {
  if (run.meanDifficulty === null) {
    return `${run.teamName} has no fixture scheduled between GW${run.fromGameweek} and GW${run.toGameweek}.`;
  }

  const parts = [
    `${BAND_LABELS[run.meanBand ?? "neutral"].toLowerCase()} on average (${run.meanDifficulty.toFixed(2)} against a neutral ${run.scale.neutral.toFixed(2)}), rated on ${difficultyBasisLabel(position)}`,
  ];
  if (run.doubles > 0) parts.push(`${run.doubles} double gameweek${run.doubles === 1 ? "" : "s"}`);
  if (run.blanks > 0) parts.push(`${run.blanks} blank${run.blanks === 1 ? "" : "s"}`);

  return `GW${run.fromGameweek} to GW${run.toGameweek}: ${parts.join(", ")}.`;
}
