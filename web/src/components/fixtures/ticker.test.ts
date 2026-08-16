import { describe, expect, it } from "vitest";
import type { Fixtures } from "../../contract/types";
import { fixtureGrid } from "../../test/fixtures";
import {
  bandFor,
  bandRanges,
  buildRuns,
  difficultyOf,
  gameweeksOf,
  horizonOptions,
  runFor,
  sortRuns,
} from "./ticker";

const scale = fixtureGrid.scale;
const fullHorizon = gameweeksOf(fixtureGrid).length;

function runsBy(metric: Parameters<typeof buildRuns>[1] = "overall", horizon = fullHorizon) {
  return buildRuns(fixtureGrid, metric, horizon);
}

function run(team: string, metric: Parameters<typeof buildRuns>[1] = "overall", horizon = fullHorizon) {
  const found = runsBy(metric, horizon).find((r) => r.team === team);
  if (!found) throw new Error(`no run for ${team}`);
  return found;
}

describe("gameweeksOf", () => {
  it("covers the published window inclusively", () => {
    expect(gameweeksOf(fixtureGrid)).toEqual([1, 2, 3, 4]);
  });
});

describe("horizonOptions", () => {
  it("offers only horizons that fit inside the window, and always the whole window", () => {
    expect(horizonOptions(fixtureGrid)).toEqual([3, 4]);
  });

  it("collapses to the window itself when the window is shorter than the shortest offer", () => {
    const short: Fixtures = { ...fixtureGrid, to_gameweek: 2 };
    expect(horizonOptions(short)).toEqual([2]);
  });
});

describe("bandFor", () => {
  it("calls the published neutral score average, not a hardcoded midpoint", () => {
    expect(bandFor(scale.neutral, scale)).toEqual({ level: 3, label: "Average" });
  });

  it("bands the ends of the scale as the extremes", () => {
    expect(bandFor(scale.minimum, scale).level).toBe(1);
    expect(bandFor(scale.maximum, scale).level).toBe(5);
  });

  it("orders bands monotonically with difficulty", () => {
    const levels = [1.0, 2.2, 2.9, 3.6, 4.6].map((d) => bandFor(d, scale).level);
    expect(levels).toEqual([1, 2, 3, 4, 5]);
  });

  it("measures each side against its own half when the scale is asymmetric about neutral", () => {
    // Neutral sits well above the midpoint, so the same absolute gap means different things either
    // side of it: a point below neutral is a third of the way down a three-wide easy half and reads
    // as merely easy, while half a point above it is half of a one-wide hard half and reads as hard.
    const skewed = { ...scale, minimum: 0, neutral: 3, maximum: 4 };
    expect(bandFor(2.0, skewed).level).toBe(2);
    expect(bandFor(1.0, skewed).level).toBe(1);
    expect(bandFor(3.5, skewed).level).toBe(4);
    expect(bandFor(3.7, skewed).level).toBe(5);
  });

  it("treats a scale with no spread as average everywhere rather than dividing by zero", () => {
    const flat = { ...scale, minimum: 3, neutral: 3, maximum: 3 };
    expect(bandFor(3, flat).level).toBe(3);
  });
});

describe("bandRanges", () => {
  it("spans the whole published scale with no gaps, easiest first", () => {
    const ranges = bandRanges(scale);
    expect(ranges).toHaveLength(5);
    expect(ranges[0].from).toBe(scale.minimum);
    expect(ranges[4].to).toBe(scale.maximum);
    for (let i = 1; i < ranges.length; i += 1) expect(ranges[i].from).toBe(ranges[i - 1].to);
  });

  it("gives every band a range that `bandFor` actually puts scores into", () => {
    for (const range of bandRanges(scale)) {
      const middle = (range.from + range.to) / 2;
      expect(bandFor(middle, scale).level).toBe(range.level);
      expect(bandFor(middle, scale).label).toBe(range.label);
    }
  });
});

describe("difficultyOf", () => {
  it("reads the half of the scale asked for", () => {
    const entry = fixtureGrid.teams[0].gameweeks[0].fixtures[0];
    expect(difficultyOf(entry, "overall")).toBe(entry.difficulty);
    expect(difficultyOf(entry, "attack")).toBe(entry.attack_difficulty);
    expect(difficultyOf(entry, "defence")).toBe(entry.defence_difficulty);
  });
});

describe("runFor", () => {
  it("counts a double as two fixtures in one gameweek", () => {
    const arsenal = run("ARS");
    expect(arsenal.doubleCount).toBe(1);
    expect(arsenal.fixtureCount).toBe(5);
    expect(arsenal.gameweeks).toHaveLength(4);
    expect(arsenal.gameweeks[2].fixtures).toHaveLength(2);
  });

  it("keeps blank gameweeks in the row so the columns still line up", () => {
    const united = run("MUN");
    expect(united.gameweeks.map((gw) => gw.gameweek)).toEqual([1, 2, 3, 4]);
    expect(united.blankCount).toBe(2);
    expect(united.fixtureCount).toBe(2);
    expect(united.gameweeks[0].is_blank).toBe(true);
  });

  it("agrees with the published mean over the full window", () => {
    for (const team of fixtureGrid.teams) {
      const computed = run(team.team).mean;
      expect(computed).not.toBeNull();
      expect(computed as number).toBeCloseTo(team.mean_difficulty as number, 2);
    }
  });

  it("averages over the fixtures played, so a blank neither helps nor hurts the mean", () => {
    // City play twice in four, both easy. The mean is the mean of those two and nothing else — the
    // blanks are carried as a count instead, because a blank is not a 5 and is not a 1.
    const city = run("MCI");
    expect(city.mean).toBeCloseTo(1.5, 5);
    expect(city.blankCount).toBe(2);
  });

  it("recomputes over a trimmed window rather than reusing the full-window mean", () => {
    const overThree = run("ARS", "overall", 3);
    expect(overThree.gameweeks).toHaveLength(3);
    expect(overThree.fixtureCount).toBe(4);
    expect(overThree.mean).toBeCloseTo((1.6 + 3.4 + 1.9 + 3.0) / 4, 5);
    expect(overThree.mean).not.toBeCloseTo(fixtureGrid.teams[0].mean_difficulty as number, 3);
  });

  it("reads the attacking and defensive halves separately", () => {
    expect(run("ARS", "attack").mean).toBeCloseTo(2.4, 5);
    expect(run("ARS", "defence").mean).toBeCloseTo(2.52, 5);
  });

  it("treats a gameweek missing from the published row as a blank, not as a shorter row", () => {
    const gappy = { ...fixtureGrid.teams[4], gameweeks: [fixtureGrid.teams[4].gameweeks[1]] };
    const result = runFor(gappy, [1, 2, 3, 4], "overall");
    expect(result.gameweeks.map((gw) => gw.gameweek)).toEqual([1, 2, 3, 4]);
    expect(result.blankCount).toBe(3);
    expect(result.fixtureCount).toBe(1);
  });

  it("reports a null mean for a club with no fixture at all in the window", () => {
    const absent = { ...fixtureGrid.teams[0], gameweeks: [] };
    const result = runFor(absent, [1, 2], "overall");
    expect(result.mean).toBeNull();
    expect(result.blankCount).toBe(2);
  });
});

describe("sortRuns", () => {
  const runs = runsBy();

  it("puts the easiest run first", () => {
    expect(sortRuns(runs, "easiest").map((r) => r.team)).toEqual([
      "MCI",
      "ARS",
      "MUN",
      "AVL",
      "BUR",
    ]);
  });

  it("reverses cleanly for the hardest run", () => {
    expect(sortRuns(runs, "hardest").map((r) => r.team)).toEqual([
      "BUR",
      "AVL",
      "MUN",
      "ARS",
      "MCI",
    ]);
  });

  it("sorts by how many fixtures there are, which is the question a double gameweek asks", () => {
    // Arsenal's double puts them top on five; the two clubs on four break the tie on the easier
    // run, and the two clubs on two do the same.
    expect(sortRuns(runs, "fixtures").map((r) => r.team)).toEqual([
      "ARS",
      "AVL",
      "BUR",
      "MCI",
      "MUN",
    ]);
  });

  it("sorts by club name", () => {
    expect(sortRuns(runs, "team").map((r) => r.team)).toEqual(["ARS", "AVL", "BUR", "MCI", "MUN"]);
  });

  it("sorts a club with no fixtures last whichever direction the list runs", () => {
    const absent = { ...runs[0], team: "ZZZ", mean: null, fixtureCount: 0 };
    const withAbsent = [absent, ...runs];
    const last = (key: Parameters<typeof sortRuns>[1]) => {
      const sorted = sortRuns(withAbsent, key);
      return sorted[sorted.length - 1].team;
    };
    expect(last("easiest")).toBe("ZZZ");
    expect(last("hardest")).toBe("ZZZ");
  });

  it("breaks ties on the club name, so the same data always renders in the same order", () => {
    const a = { ...runs[0], team: "BBB", mean: 2.5, fixtureCount: 4 };
    const b = { ...runs[0], team: "AAA", mean: 2.5, fixtureCount: 4 };
    expect(sortRuns([a, b], "easiest").map((r) => r.team)).toEqual(["AAA", "BBB"]);
    expect(sortRuns([a, b], "hardest").map((r) => r.team)).toEqual(["AAA", "BBB"]);
    expect(sortRuns([a, b], "fixtures").map((r) => r.team)).toEqual(["AAA", "BBB"]);
  });

  it("does not mutate the array it was given", () => {
    const before = runs.map((r) => r.team);
    sortRuns(runs, "hardest");
    expect(runs.map((r) => r.team)).toEqual(before);
  });
});
