import { describe, expect, it } from "vitest";
import { buildTrends, coverageStatement, findPlayerHistory } from "./trends";
import { history, preseasonHistory } from "./testFixtures";

function trendsFor(id: number) {
  const playerHistory = findPlayerHistory(history, id);
  if (playerHistory === null) throw new Error(`no history for ${id}`);
  return buildTrends(playerHistory, history.gameweeks_played);
}

describe("findPlayerHistory", () => {
  it("returns null for a player the artefact does not carry", () => {
    expect(findPlayerHistory(history, 999)).toBeNull();
  });
});

describe("buildTrends — double gameweeks", () => {
  it("sums a double into one bar rather than plotting two at the same x", () => {
    const trends = trendsFor(1);
    const gw3 = trends.points.find((bar) => bar.gameweek === 3);

    // GW3 is two fixtures, 3 points and 5 points.
    expect(gw3?.value).toBe(8);
    expect(trends.points.filter((bar) => bar.gameweek === 3)).toHaveLength(1);
  });

  it("sums minutes across a double as well", () => {
    expect(trendsFor(1).minutes.find((bar) => bar.gameweek === 3)?.value).toBe(90);
  });

  it("keeps the bars ascending by gameweek", () => {
    const gameweeks = trendsFor(1).points.map((bar) => bar.gameweek);
    expect(gameweeks).toEqual([...gameweeks].sort((a, b) => a - b));
  });
});

describe("buildTrends — absent is not zero", () => {
  it("omits an unmeasured gameweek from the expected-goals series rather than plotting a nil", () => {
    const trends = trendsFor(1);
    const xg = trends.attacking.series.find((s) => s.key === "xg");

    // Five entries over four gameweeks; GW2 has no `xg`, so it is not a point on the line.
    expect(xg).toBeDefined();
    expect(xg?.points.map((p) => p.x)).toEqual([1, 3, 4]);
  });

  it("reports coverage so the view can say how much of the season was measured", () => {
    const trends = trendsFor(1);
    expect(trends.attacking.coverage.total).toBe(4);
    expect(trends.attacking.coverage.measured).toBeLessThan(trends.attacking.coverage.total);
  });

  it("totals expected goals over the measured gameweeks only", () => {
    // 0.05 + (0.0 + 0.4) + 0.0 — GW2 contributes nothing because it measured nothing.
    expect(trendsFor(1).totals.expectedGoals).toBeCloseTo(0.45, 6);
  });

  it("accumulates actual goals cumulatively across every gameweek", () => {
    // Goals are always measured, so unlike xG this series has a point for all four gameweeks —
    // including GW2, where the expected series has a gap.
    const goals = trendsFor(1).attacking.series.find((s) => s.key === "goals");
    expect(goals?.points.map((p) => p.x)).toEqual([1, 2, 3, 4]);
    expect(goals?.points.map((p) => p.y)).toEqual([0, 0, 1, 1]);
  });

  it("counts coverage in gameweeks, so a double does not paper over a missing one", () => {
    // GW3 is a double with xG on both entries. Counting entries would give 4 measured against a
    // 4-gameweek season and hide the fact that GW2 has none.
    expect(trendsFor(1).attacking.coverage).toEqual({ measured: 3, total: 4 });
  });
});

describe("buildTrends — the empty cases", () => {
  it("reports no gameweeks for a player who has never featured, while keeping their prices", () => {
    const trends = trendsFor(2);

    expect(trends.hasGameweeks).toBe(false);
    expect(trends.points).toHaveLength(0);
    // The price series is the point: "no gameweeks" must not be read as "no data at all".
    expect(trends.hasPrices).toBe(true);
    expect(trends.price.points).toHaveLength(2);
  });

  it("carries gameweeks_played from the artefact rather than inferring it from an array", () => {
    // Watkins has played nothing, but four gameweeks have been scored in the season.
    expect(trendsFor(2).gameweeksPlayed).toBe(4);
  });

  it("handles a preseason artefact with nothing scored anywhere", () => {
    const playerHistory = findPlayerHistory(preseasonHistory, 1);
    const trends = buildTrends(playerHistory!, preseasonHistory.gameweeks_played);

    expect(trends.gameweeksPlayed).toBe(0);
    expect(trends.hasGameweeks).toBe(false);
    expect(trends.hasPrices).toBe(true);
    expect(trends.attacking.series.every((s) => s.points.length === 0)).toBe(true);
    expect(trends.defensive).toBeNull();
    expect(trends.totals.expectedGoals).toBeNull();
  });
});

describe("buildTrends — price and ownership", () => {
  it("indexes observations evenly and keeps the dates alongside", () => {
    const trends = trendsFor(1);

    expect(trends.price.points.map((p) => p.x)).toEqual([0, 1, 2]);
    expect(trends.price.points.map((p) => p.y)).toEqual([6.0, 6.1, 6.2]);
    expect(trends.priceDates).toEqual(["2026-08-01", "2026-09-02", "2026-09-12"]);
  });

  it("plots ownership as the published percentage", () => {
    expect(trendsFor(1).ownership.points.map((p) => p.y)).toEqual([28.4, 31.0, 33.7]);
  });
});

describe("coverageStatement", () => {
  it("says nothing when everything was measured", () => {
    expect(coverageStatement({ measured: 4, total: 4 }, "expected-goals")).toBeNull();
  });

  it("says nothing when there is no season yet", () => {
    expect(coverageStatement({ measured: 0, total: 0 }, "expected-goals")).toBeNull();
  });

  it("names the gap, and says absence is not a nil return", () => {
    const statement = coverageStatement({ measured: 3, total: 4 }, "expected-goals");
    expect(statement).toContain("3 of 4");
    expect(statement).toContain("not the same as a nil return");
  });

  it("is explicit when nothing was measured at all", () => {
    expect(coverageStatement({ measured: 0, total: 4 }, "expected-goals")).toContain(
      "No expected-goals data",
    );
  });
});
