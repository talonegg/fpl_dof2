import { describe, expect, it } from "vitest";
import {
  bandFor,
  buildFixtureRun,
  difficultyBasisLabel,
  relevantDifficulty,
  runStatement,
} from "./fixtureRun";
import { fixtures, unratedFixtures } from "./testFixtures";

const scale = fixtures.scale; // minimum 1, neutral 3, maximum 5

describe("bandFor", () => {
  it("bands against the published scale, not against a hardcoded FDR", () => {
    expect(bandFor(1.0, scale)).toBe("very-easy");
    expect(bandFor(3.0, scale)).toBe("neutral");
    expect(bandFor(5.0, scale)).toBe("very-hard");
  });

  it("treats scores near neutral as neutral rather than colouring in noise", () => {
    expect(bandFor(2.8, scale)).toBe("neutral");
    expect(bandFor(3.2, scale)).toBe("neutral");
  });

  it("moves with the scale: the same score bands differently on a wider one", () => {
    // 4.0 sits above neutral on the published scale and below it on a wider one. A hardcoded
    // "4 and above is hard" would be right only for whichever scale it was written against.
    const wide = { ...scale, minimum: 0, neutral: 5, maximum: 10 };
    expect(bandFor(4.0, scale)).toBe("hard");
    expect(bandFor(4.0, wide)).toBe("easy");
  });

  it("degrades to neutral on a scale with no span rather than dividing by zero", () => {
    const flat = { ...scale, minimum: 3, neutral: 3, maximum: 3 };
    expect(bandFor(3, flat)).toBe("neutral");
  });
});

describe("relevantDifficulty", () => {
  const entry = fixtures.teams[0].gameweeks[0].fixtures[0]; // attack 1.4, defence 1.6

  it("judges a goalkeeper and a defender on what the opponent is expected to score", () => {
    expect(relevantDifficulty(entry, "GKP")).toBe(1.6);
    expect(relevantDifficulty(entry, "DEF")).toBe(1.6);
  });

  it("judges a forward on what their own club is expected to score", () => {
    expect(relevantDifficulty(entry, "FWD")).toBe(1.4);
  });

  it("gives a midfielder the overall balance, since they draw on both", () => {
    expect(relevantDifficulty(entry, "MID")).toBe(entry.difficulty);
  });

  it("names the basis in words, so the strip is arguable", () => {
    expect(difficultyBasisLabel("DEF")).toContain("opponent");
    expect(difficultyBasisLabel("FWD")).toContain("this club");
  });
});

describe("buildFixtureRun", () => {
  it("returns null when the grid does not carry the player's club, rather than throwing", () => {
    // Watkins's club (team_id 2) is absent from this grid. The panel must degrade, not crash.
    expect(buildFixtureRun(fixtures, { team_id: 2, position: "FWD" })).toBeNull();
  });

  it("builds the run for a club the grid does carry", () => {
    const run = buildFixtureRun(fixtures, { team_id: 1, position: "DEF" });
    expect(run?.team).toBe("ARS");
    expect(run?.fromGameweek).toBe(5);
    expect(run?.toGameweek).toBe(8);
    expect(run?.gameweeks).toHaveLength(4);
  });

  it("keeps the blank gameweek as an entry, because it is the one that would be invisible", () => {
    const run = buildFixtureRun(fixtures, { team_id: 1, position: "DEF" });
    const blank = run?.gameweeks.find((gw) => gw.gameweek === 7);

    expect(blank?.isBlank).toBe(true);
    expect(blank?.fixtures).toHaveLength(0);
    expect(run?.blanks).toBe(1);
  });

  it("keeps both fixtures of a double", () => {
    const run = buildFixtureRun(fixtures, { team_id: 1, position: "DEF" });
    const double = run?.gameweeks.find((gw) => gw.gameweek === 8);

    expect(double?.isDouble).toBe(true);
    expect(double?.fixtures).toHaveLength(2);
    expect(double?.fixtures.map((f) => f.indexInGameweek)).toEqual([0, 1]);
    expect(run?.doubles).toBe(1);
  });

  it("means only over the fixtures actually scheduled, so a blank does not count as hard", () => {
    const run = buildFixtureRun(fixtures, { team_id: 1, position: "DEF" });
    // Four scheduled fixtures: defence difficulties 1.6, 4.8, 2.9, 3.1.
    expect(run?.meanDifficulty).toBeCloseTo((1.6 + 4.8 + 2.9 + 3.1) / 4, 6);
  });

  it("bands the same run differently for a forward, because it rates a different number", () => {
    const defender = buildFixtureRun(fixtures, { team_id: 1, position: "DEF" });
    const forward = buildFixtureRun(fixtures, { team_id: 1, position: "FWD" });
    expect(forward?.meanDifficulty).not.toBeCloseTo(defender!.meanDifficulty!, 6);
  });

  it("flags an unrated model, so a placeholder grid is not read as a rating", () => {
    expect(buildFixtureRun(fixtures, { team_id: 1, position: "MID" })?.unrated).toBe(false);
    expect(buildFixtureRun(unratedFixtures, { team_id: 1, position: "MID" })?.unrated).toBe(true);
  });
});

describe("runStatement", () => {
  it("names the doubles, the blanks and the basis of the rating", () => {
    const run = buildFixtureRun(fixtures, { team_id: 1, position: "DEF" })!;
    const statement = runStatement(run, "DEF");

    expect(statement).toContain("GW5 to GW8");
    expect(statement).toContain("1 double gameweek");
    expect(statement).toContain("1 blank");
    expect(statement).toContain("opponent");
  });

  it("says so plainly when a club has no fixture in the window at all", () => {
    const allBlank = {
      ...fixtures,
      teams: [
        {
          ...fixtures.teams[0],
          gameweeks: fixtures.teams[0].gameweeks.map((gw) => ({
            ...gw,
            is_blank: true,
            is_double: false,
            fixtures: [],
          })),
        },
      ],
    };
    const run = buildFixtureRun(allBlank, { team_id: 1, position: "MID" })!;

    expect(run.meanDifficulty).toBeNull();
    expect(runStatement(run, "MID")).toContain("no fixture scheduled");
  });
});
