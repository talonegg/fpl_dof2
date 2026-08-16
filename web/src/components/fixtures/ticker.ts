/**
 * Fixture ticker logic: pure functions over `fixtures.json` (E6-S8, FR-30, DL-37).
 *
 * DOM-free on purpose, like `scout/filters.ts` — the interesting cases here are arithmetic and
 * ordering, and they should be checkable without rendering anything:
 *
 * - **A blank is not a hard fixture.** It contributes nothing to a run's mean, exactly as the
 *   published `mean_difficulty` does. A club with two blanks in six therefore looks *easy* on the
 *   mean alone, which is why every row also carries its fixture, double and blank counts and the
 *   view shows them. A mean that quietly rewards not playing is the one number on this page most
 *   able to mislead.
 * - **A club with no fixture at all in the window has a null mean**, and a null sorts last in both
 *   directions rather than pretending to be zero — the same rule the scout table follows.
 * - **Bands are derived from the published scale, never assumed.** `scale.minimum`, `.neutral` and
 *   `.maximum` come from configuration on the pipeline side (DP-06); reading a `3` here as "average"
 *   would be a literal standing in for a configured value.
 *
 * The window can be trimmed — "next three" is a different question from "next six" — so the means
 * are recomputed over whatever is visible rather than reusing `mean_difficulty`, which is always the
 * full-window figure. Over the full window the two agree, and a test asserts that they do.
 */

import type {
  DifficultyScale,
  FixtureEntry,
  FixtureGameweek,
  Fixtures,
  TeamFixtures,
} from "../../contract/types";

/**
 * Which half of the scale to read.
 *
 * Published separately because they genuinely disagree: a high-scoring game between two good sides
 * is a good fixture for forwards and a bad one for defenders, and collapsing that into a single
 * number is most of what is wrong with a single FDR figure (see `fixtures.schema.json`).
 */
export type Metric = "overall" | "attack" | "defence";

export const METRICS: ReadonlyArray<{ key: Metric; label: string; help: string }> = [
  {
    key: "overall",
    label: "Overall",
    help: "The mean of the attacking and defensive scores.",
  },
  {
    key: "attack",
    label: "Attack",
    help: "For this club's attackers: easier the more goals the model expects them to score.",
  },
  {
    key: "defence",
    label: "Defence",
    help: "For this club's defenders and keeper: harder the more goals it expects them to concede.",
  },
];

/** One fixture's score on the chosen half of the scale. Lower is easier, always. */
export function difficultyOf(entry: FixtureEntry, metric: Metric): number {
  if (metric === "attack") return entry.attack_difficulty;
  if (metric === "defence") return entry.defence_difficulty;
  return entry.difficulty;
}

export type BandLevel = 1 | 2 | 3 | 4 | 5;

export interface Band {
  level: BandLevel;
  /** Said in words, because colour is never the only carrier of meaning (E6-S9, DP-09). */
  label: string;
}

const BAND_LABELS: Record<BandLevel, string> = {
  1: "Very easy",
  2: "Easy",
  3: "Average",
  4: "Hard",
  5: "Very hard",
};

/**
 * How far from neutral a score must sit to leave the average band, and to reach the extreme one, as
 * a fraction of the distance from neutral to that end of the published scale.
 *
 * Presentation tunables, not model parameters: they decide how many cells get shaded strongly, and
 * nothing downstream depends on them. Set so that roughly the middle fifth of the range reads as
 * average — narrower and every fixture looks remarkable, wider and nothing does.
 */
const BAND_EDGE_NEAR = 0.2;
const BAND_EDGE_FAR = 0.6;

/**
 * Place a difficulty on a five-band scale, relative to the published neutral point.
 *
 * Measured outwards from `neutral` rather than across `[minimum, maximum]`, because neutral is a
 * real quantity — the score the arithmetic produces for a league-average fixture — and not a
 * midpoint by convention. Where the two ends of the scale are asymmetric about it, each side is
 * scaled by its own half.
 */
export function bandFor(difficulty: number, scale: DifficultyScale): Band {
  const half = difficulty < scale.neutral ? scale.neutral - scale.minimum : scale.maximum - scale.neutral;
  // A degenerate scale (no spread at all) is average everywhere rather than a division by zero.
  const offset = half > 0 ? (difficulty - scale.neutral) / half : 0;

  let level: BandLevel = 3;
  if (offset <= -BAND_EDGE_FAR) level = 1;
  else if (offset <= -BAND_EDGE_NEAR) level = 2;
  else if (offset >= BAND_EDGE_FAR) level = 5;
  else if (offset >= BAND_EDGE_NEAR) level = 4;

  return { level, label: BAND_LABELS[level] };
}

export interface BandRange extends Band {
  /** Inclusive lower bound on the published scale. */
  from: number;
  /** Upper bound. */
  to: number;
}

/**
 * The five bands with the score range each covers, for the legend.
 *
 * Derived here rather than written out in the view so the legend cannot drift from the shading: one
 * set of edges, used by both. A legend that disagrees with the grid it explains is worse than none,
 * because the reader has no way to tell which of the two is lying.
 */
export function bandRanges(scale: DifficultyScale): BandRange[] {
  const easy = scale.neutral - scale.minimum;
  const hard = scale.maximum - scale.neutral;
  const edges = [
    scale.minimum,
    scale.neutral - BAND_EDGE_FAR * easy,
    scale.neutral - BAND_EDGE_NEAR * easy,
    scale.neutral + BAND_EDGE_NEAR * hard,
    scale.neutral + BAND_EDGE_FAR * hard,
    scale.maximum,
  ];

  return ([1, 2, 3, 4, 5] as BandLevel[]).map((level, index) => ({
    level,
    label: BAND_LABELS[level],
    from: edges[index],
    to: edges[index + 1],
  }));
}

/** One club's row in the grid, over the visible window. */
export interface TeamRun {
  teamId: number;
  /** Short club name, e.g. ARS. */
  team: string;
  name: string;
  /** One entry per visible gameweek, ascending, blanks included. */
  gameweeks: FixtureGameweek[];
  /** Mean difficulty on the chosen metric over the fixtures actually scheduled. Null if none are. */
  mean: number | null;
  /** Fixtures scheduled in the window. A double gameweek contributes two. */
  fixtureCount: number;
  doubleCount: number;
  blankCount: number;
}

/** The gameweeks the grid covers, ascending, from the published window. */
export function gameweeksOf(fixtures: Fixtures): number[] {
  const gameweeks: number[] = [];
  for (let gw = fixtures.from_gameweek; gw <= fixtures.to_gameweek; gw += 1) gameweeks.push(gw);
  return gameweeks;
}

/**
 * The horizons offered, always including the full window and never exceeding it.
 *
 * Three and six because they are the horizons a transfer is actually argued over — "does he have a
 * good next three" — not because the data suggests them.
 */
export function horizonOptions(fixtures: Fixtures): number[] {
  const total = gameweeksOf(fixtures).length;
  const offered = [3, 6].filter((n) => n < total);
  return [...offered, total];
}

/**
 * A club's row over the first `horizon` gameweeks of the window.
 *
 * A gameweek missing from the published array is treated as a blank rather than skipped: the row
 * must line up with every other row's columns, and a hole that silently shortens one club's row is
 * a grid that lies about which gameweek a cell belongs to (DP-15).
 */
export function runFor(team: TeamFixtures, gameweeks: number[], metric: Metric): TeamRun {
  const byGameweek = new Map(team.gameweeks.map((entry) => [entry.gameweek, entry]));

  const visible: FixtureGameweek[] = gameweeks.map(
    (gameweek) =>
      byGameweek.get(gameweek) ?? { gameweek, is_double: false, is_blank: true, fixtures: [] },
  );

  const scores = visible.flatMap((entry) => entry.fixtures.map((f) => difficultyOf(f, metric)));

  return {
    teamId: team.team_id,
    team: team.team,
    name: team.name,
    gameweeks: visible,
    mean: scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null,
    fixtureCount: scores.length,
    doubleCount: visible.filter((entry) => entry.fixtures.length > 1).length,
    blankCount: visible.filter((entry) => entry.fixtures.length === 0).length,
  };
}

/** Every club's row, in published order. Sorting is a separate step, so it can be tested alone. */
export function buildRuns(fixtures: Fixtures, metric: Metric, horizon: number): TeamRun[] {
  const gameweeks = gameweeksOf(fixtures).slice(0, Math.max(1, horizon));
  return fixtures.teams.map((team) => runFor(team, gameweeks, metric));
}

export type SortKey = "easiest" | "hardest" | "fixtures" | "team";

export const SORTS: ReadonlyArray<{ key: SortKey; label: string }> = [
  { key: "easiest", label: "Easiest run first" },
  { key: "hardest", label: "Hardest run first" },
  { key: "fixtures", label: "Most fixtures first" },
  { key: "team", label: "Club name" },
];

/**
 * Order the rows.
 *
 * Every comparison falls through to the club's short name, so two clubs with identical runs always
 * come out in the same order — a stable, explicable ordering rather than whatever the engine's sort
 * happened to do that render (DP-11).
 */
export function sortRuns(runs: readonly TeamRun[], key: SortKey): TeamRun[] {
  const byName = (a: TeamRun, b: TeamRun) => a.team.localeCompare(b.team);

  return [...runs].sort((a, b) => {
    if (key === "team") return byName(a, b);

    if (key === "fixtures") {
      if (a.fixtureCount !== b.fixtureCount) return b.fixtureCount - a.fixtureCount;
      return compareMeans(a.mean, b.mean, "asc") || byName(a, b);
    }

    return compareMeans(a.mean, b.mean, key === "easiest" ? "asc" : "desc") || byName(a, b);
  });
}

/** Null means "no fixture in the window at all", and sorts last whichever way the list runs. */
function compareMeans(a: number | null, b: number | null, direction: "asc" | "desc"): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return direction === "asc" ? a - b : b - a;
}
