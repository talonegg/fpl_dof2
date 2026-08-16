import { describe, expect, it } from "vitest";
import type { History, PlayerHistory } from "../../contract/types";
import { players as fixturePlayers } from "../../test/fixtures";
import { history, preseasonHistory } from "../player/testFixtures";
import { alignToDates, buildCompareTrends, sharedPriceDates } from "./overlays";

const [raya, watkins, mbeumo] = fixturePlayers.players;

function observation(on: string, price: number, owned = 10) {
  return { on, price, owned };
}

describe("sharedPriceDates", () => {
  it("unions the dates across players and sorts them, so one axis serves all of them", () => {
    const a = { id: 1, gameweeks: [], prices: [observation("2026-09-02", 6.1)] } as PlayerHistory;
    const b = {
      id: 2,
      gameweeks: [],
      prices: [observation("2026-08-01", 8.0), observation("2026-09-02", 8.1)],
    } as PlayerHistory;

    expect(sharedPriceDates([a, b])).toEqual(["2026-08-01", "2026-09-02"]);
  });

  it("is empty when nothing has been observed", () => {
    expect(sharedPriceDates([])).toEqual([]);
  });
});

describe("alignToDates", () => {
  const dates = ["2026-08-01", "2026-08-15", "2026-09-02", "2026-09-12"];

  it("carries the last observed value forward across dates that observed nothing", () => {
    // A price series is emitted only on change, so a gap is an unchanged day, not a missing one.
    const points = alignToDates(
      [observation("2026-08-01", 6.0), observation("2026-09-02", 6.1)],
      dates,
      (o) => o.price,
    );
    expect(points).toEqual([
      { x: 0, y: 6.0 },
      { x: 1, y: 6.0 },
      { x: 2, y: 6.1 },
      { x: 3, y: 6.1 },
    ]);
  });

  it("emits nothing before the player's first observation, rather than back-filling it", () => {
    // The failure this guards: a flat line at £8.0m running back through weeks nothing observed.
    const points = alignToDates([observation("2026-09-02", 8.0)], dates, (o) => o.price);
    expect(points).toEqual([
      { x: 2, y: 8.0 },
      { x: 3, y: 8.0 },
    ]);
  });

  it("never emits a zero for an unobserved date, which would draw a free player", () => {
    const points = alignToDates([observation("2026-09-12", 8.0)], dates, (o) => o.price);
    expect(points.every((p) => p.y === 8.0)).toBe(true);
    expect(points).toHaveLength(1);
  });

  it("puts two players' observations of the same date at the same x", () => {
    const early = alignToDates([observation("2026-08-01", 6.0)], dates, (o) => o.price);
    const late = alignToDates([observation("2026-08-01", 8.0)], dates, (o) => o.price);
    expect(early.map((p) => p.x)).toEqual(late.map((p) => p.x));
  });

  it("takes the last observation when several share a date, not the first", () => {
    const points = alignToDates(
      [observation("2026-08-01", 6.0), observation("2026-08-01", 6.1)],
      ["2026-08-01"],
      (o) => o.price,
    );
    expect(points).toEqual([{ x: 0, y: 6.1 }]);
  });

  it("is empty when there is no shared axis at all", () => {
    expect(alignToDates([observation("2026-08-01", 6.0)], [], (o) => o.price)).toEqual([]);
  });
});

describe("buildCompareTrends", () => {
  it("sums a double gameweek into one cumulative point rather than two at the same x", () => {
    const trends = buildCompareTrends(history, [raya]);
    const line = trends.lines[0];
    // Raya's fixture: GW1 6, GW2 2, GW3 is a double of 3 and 5, GW4 8 — four points, not five.
    expect(line.points.map((p) => p.x)).toEqual([1, 2, 3, 4]);
    expect(line.points.map((p) => p.y)).toEqual([6, 8, 16, 24]);
  });

  it("accumulates minutes over the same gameweek axis", () => {
    const trends = buildCompareTrends(history, [raya]);
    // 90, 90, 45 + 45, 90.
    expect(trends.lines[0].minutes.map((p) => p.y)).toEqual([90, 180, 270, 360]);
  });

  it("names a player who is present but has never featured, rather than drawing a flat zero", () => {
    const trends = buildCompareTrends(history, [raya, watkins]);
    expect(trends.notFeaturedNames).toEqual(["Watkins"]);
    expect(trends.lines[1].present).toBe(true);
    expect(trends.lines[1].points).toEqual([]);
  });

  it("still plots the price of a player who has never featured", () => {
    // The state that breaks a view inferring "no data" from the wrong array.
    const trends = buildCompareTrends(history, [raya, watkins]);
    expect(trends.lines[1].price.length).toBeGreaterThan(0);
    expect(trends.anyPrices).toBe(true);
  });

  it("names a player the artefact does not carry, and keeps the others", () => {
    const trends = buildCompareTrends(history, [raya, mbeumo]);
    expect(trends.absentNames).toEqual(["Mbeumo"]);
    expect(trends.lines[1].present).toBe(false);
    expect(trends.lines[0].points.length).toBeGreaterThan(0);
  });

  it("keeps the lines in the order the players were compared in", () => {
    const trends = buildCompareTrends(history, [watkins, raya]);
    expect(trends.lines.map((line) => line.name)).toEqual(["Watkins", "Raya"]);
  });

  it("reads gameweeks played from the artefact, not from an array length (DL-20)", () => {
    const trends = buildCompareTrends(preseasonHistory, [raya]);
    expect(trends.gameweeksPlayed).toBe(0);
    expect(trends.anyGameweeks).toBe(false);
    // Preseason still has prices, so the price chart has something to draw.
    expect(trends.anyPrices).toBe(true);
  });

  it("reports no defensive data as absence, so no chart claims a nil return (DL-18)", () => {
    const noDc: History = {
      ...history,
      players: [
        {
          id: 1,
          gameweeks: [{ gw: 1, pts: 2, mins: 90, goals: 0, assists: 0, price: 6.0 }],
          prices: [],
        },
      ],
    };
    const trends = buildCompareTrends(noDc, [raya]);
    expect(trends.anyDefensive).toBe(false);
    expect(trends.lines[0].defensive).toEqual([]);
  });

  it("accumulates defensive actions where they were measured", () => {
    const trends = buildCompareTrends(history, [raya]);
    // 3, then GW2 unmeasured and dropped, then 2 + 1, then 4.
    expect(trends.lines[0].defensive.map((p) => p.y)).toEqual([3, 6, 10]);
    expect(trends.anyDefensive).toBe(true);
  });

  it("survives an artefact carrying none of the compared players", () => {
    const trends = buildCompareTrends({ ...history, players: [] }, [raya, watkins]);
    expect(trends.absentNames).toEqual(["Raya", "Watkins"]);
    expect(trends.anyGameweeks).toBe(false);
    expect(trends.priceDates).toEqual([]);
  });
});
