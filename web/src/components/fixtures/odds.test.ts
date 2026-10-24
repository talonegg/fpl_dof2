import { describe, expect, it } from "vitest";
import { buildFixtureRun } from "../player/fixtureRun";
import { fixtures } from "../player/testFixtures";
import { oddsNotPosted, oddsSentence, oddsShort } from "./odds";

const odds = { win: 0.554, draw: 0.246, loss: 0.2, over_2_5: 0.63, as_of: "2026-08-18T09:00:00Z" };

describe("fixture odds wording (ORC-15)", () => {
  it("words the probabilities from the club's side", () => {
    expect(oddsShort(odds)).toBe("W 55% D 25% L 20%");
    expect(oddsSentence(odds)).toContain("win 55%, draw 25%, loss 20%, over 2.5 goals 63%");
  });

  it("says when the next check is, or that none is due", () => {
    expect(oddsNotPosted("2026-08-19T06:00:00Z")).toMatch(/^Odds not posted yet; next check at .+\.$/);
    expect(oddsNotPosted(null)).toMatch(/^Odds not posted yet; no further check/);
  });

  it("carries a fixture's odds, or null, into a player's run", () => {
    const priced = {
      ...fixtures,
      odds_next_check: "2026-08-19T06:00:00Z",
      teams: fixtures.teams.map((t) => ({
        ...t,
        gameweeks: t.gameweeks.map((g, i) =>
          i === 0 ? { ...g, fixtures: g.fixtures.map((f) => ({ ...f, odds })) } : g,
        ),
      })),
    };
    const run = buildFixtureRun(priced, { team_id: 1, position: "FWD" });
    expect(run?.gameweeks[0].fixtures[0].odds).toEqual(odds);
    expect(run?.gameweeks[1].fixtures[0].odds).toBeNull();
    expect(run?.oddsNextCheck).toBe("2026-08-19T06:00:00Z");
  });
});
