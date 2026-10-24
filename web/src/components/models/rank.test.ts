import { describe, expect, it } from "vitest";
import { rankBy } from "./rank";

describe("rankBy", () => {
  it("ranks highest first, shares a rank on a tie and lists the unscored last", () => {
    const scores: Record<string, number | null> = { a: 50, b: 70, c: 50, d: null, e: 40 };
    const ranked = rankBy(Object.keys(scores), (k) => scores[k]);
    expect(ranked.map((r) => [r.item, r.rank])).toEqual([
      ["b", 1],
      ["a", 2],
      ["c", 2],
      ["e", 4],
      ["d", null],
    ]);
  });
});
