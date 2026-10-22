import { describe, expect, it } from "vitest";
import type { Plan, Players, Week } from "../contract/types";
import { compareStrategies } from "./strategyCompare";

const players = {
  players: [1, 2, 3, 4, 5].map((id) => ({ id, name: `P${id}`, position: "MID" })),
} as unknown as Players;

function week(over: {
  starting: number[];
  bench?: number[];
  captain: number;
  vice?: number;
  moves?: { out: number; in: number; xpIn?: number; xpOut?: number }[];
  hit?: number;
}): Week {
  return {
    advised: {
      starting: over.starting,
      bench_order: over.bench ?? [],
      captain: over.captain,
      vice_captain: over.vice ?? over.starting[0],
    },
    recommendation: {
      hit_points: over.hit ?? 0,
      net_expected_points: 50,
      moves: (over.moves ?? []).map((m) => ({
        out: { player_id: m.out, web_name: `P${m.out}`, xp_next: m.xpOut },
        in: { player_id: m.in, web_name: `P${m.in}`, xp_next: m.xpIn },
      })),
    },
  } as unknown as Week;
}

const planWithChip = (chip: string | null) =>
  ({ recommended: { weeks: [{ gameweek: 9, chip: chip ? "x" : null, chip_label: chip }] } }) as unknown as Plan;

const base = week({ starting: [1, 2, 3], bench: [4], captain: 1, vice: 2 });

describe("compareStrategies", () => {
  it("reports no differences between identical advice", () => {
    const c = compareStrategies("a", ["a", "b"], { a: base, b: base }, {}, players);
    expect(c.diffs.b).toMatchObject({ transfersDiffer: false, captainDiffers: false, viceDiffers: false, xiIn: [], xiOut: [] });
    expect(c.disagreements).toEqual([]);
  });

  it("reports transfers, captain, vice, XI and bench against the baseline", () => {
    const other = week({
      starting: [1, 2, 5],
      bench: [3, 4],
      captain: 2,
      vice: 1,
      moves: [{ out: 3, in: 5, xpIn: 6.1, xpOut: 4.2 }],
      hit: -4,
    });
    const c = compareStrategies("a", ["a", "b"], { a: base, b: other }, {}, players);
    expect(c.diffs.b).toMatchObject({
      transfersDiffer: true,
      captainDiffers: true,
      viceDiffers: true,
      benchDiffers: true,
      xiIn: [5],
      xiOut: [3],
    });
    expect(c.advice.find((a) => a.id === "b")).toMatchObject({ transfers: ["P3 → P5"], hitPoints: -4 });
  });

  it("lists the players they disagree on with the xP the week artefacts carry", () => {
    const other = week({ starting: [1, 2, 5], captain: 1, moves: [{ out: 3, in: 5, xpIn: 6.1, xpOut: 4.2 }] });
    const c = compareStrategies("a", ["a", "b"], { a: base, b: other }, {}, players);
    expect(c.disagreements.map((d) => d.player.id)).toEqual([3, 5]);
    const p5 = c.disagreements.find((d) => d.player.id === 5)!;
    expect(p5.inXI).toEqual({ a: false, b: true });
    expect(p5.xp).toEqual({ b: 6.1 });
    expect(c.disagreements.find((d) => d.player.id === 3)!.xp).toEqual({ b: 4.2 });
  });

  it("includes players only the captaincy differs on", () => {
    const other = week({ starting: [1, 2, 3], captain: 2, vice: 1 });
    const c = compareStrategies("a", ["a", "b"], { a: base, b: other }, {}, players);
    expect(c.disagreements.map((d) => d.player.id)).toEqual([1, 2]);
    expect(c.disagreements[0].captainOf).toEqual(["a"]);
  });

  it("takes the chip from the strategy's plan and flags a difference", () => {
    const c = compareStrategies("a", ["a", "b"], { a: base, b: base }, { a: planWithChip(null), b: planWithChip("Wildcard") }, players);
    expect(c.advice.find((a) => a.id === "b")!.chip).toBe("Wildcard");
    expect(c.diffs.b.chipDiffers).toBe(true);
  });

  it("compares three to five strategies, each against the baseline, in the order given", () => {
    const ids = ["a", "b", "c", "d", "e"];
    const weeks = Object.fromEntries(ids.map((id, i) => [id, week({ starting: [1, 2, 3], captain: 1 + (i % 2) })]));
    const c = compareStrategies("a", ids, weeks, {}, players);
    expect(c.advice.map((a) => a.id)).toEqual(ids);
    expect(Object.keys(c.diffs)).toEqual(["b", "c", "d", "e"]);
    expect(c.diffs.c.captainDiffers).toBe(false);
    expect(c.diffs.b.captainDiffers).toBe(true);
  });

  it("leaves out a strategy with no week and says so", () => {
    const c = compareStrategies("a", ["a", "b"], { a: base }, {}, players);
    expect(c.advice.map((a) => a.id)).toEqual(["a"]);
    expect(c.missing).toEqual(["b"]);
  });

  it("takes the first strategy as baseline when the named one has no week", () => {
    const c = compareStrategies("z", ["a", "b"], { a: base, b: base }, {}, players);
    expect(c.baseline).toBe("a");
  });
});
