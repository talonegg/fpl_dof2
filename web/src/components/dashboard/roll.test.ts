import { describe, expect, it } from "vitest";
import { rollComparison, formatSignedPoints, formatTransferLabel } from "./roll";
import { week } from "../../test/fixtures";

type Recommendation = NonNullable<typeof week.recommendation>;

function withRecommendation(overrides: Partial<Recommendation>): Recommendation {
  return { ...week.recommendation!, ...overrides };
}

describe("rollComparison", () => {
  it("states the gain over rolling when the recommendation is a transfer", () => {
    const result = rollComparison(week.recommendation!);
    expect(result.isRoll).toBe(false);
    expect(result.recommendedNet).toBe(52.4);
    expect(result.rollNet).toBe(50.0);
    expect(result.gainOverRoll).toBeCloseTo(2.4);
    expect(result.statement).toContain("nets");
    expect(result.counterfactual).toEqual({ label: "Roll (no transfer)", net: 50.0, gainOverRoll: 0 });
  });

  it("still names the best transfer available when the recommendation is to roll", () => {
    const recommendation = withRecommendation({
      is_roll: true,
      transfers: 0,
      net_expected_points: 50.0,
      gain_over_roll: 0,
    });
    const result = rollComparison(recommendation);
    expect(result.isRoll).toBe(true);
    expect(result.counterfactual?.label).toBe("1 transfer");
    expect(result.counterfactual?.net).toBe(52.4);
    expect(result.statement).toContain("Rolling");
  });

  it("falls back to gain_over_roll alone when no options are published", () => {
    const recommendation = withRecommendation({ options: undefined });
    const result = rollComparison(recommendation);
    expect(result.rollNet).toBeUndefined();
    expect(result.gainOverRoll).toBeCloseTo(2.4);
    expect(result.counterfactual).toBeUndefined();
  });

  it("says the gain is not published when neither options nor gain_over_roll exist", () => {
    const recommendation = withRecommendation({ options: undefined, gain_over_roll: undefined });
    const result = rollComparison(recommendation);
    expect(result.gainOverRoll).toBeUndefined();
    expect(result.statement).toContain("not published");
  });

  it("says rolling beats every transfer when the best option still loses", () => {
    const recommendation = withRecommendation({
      is_roll: true,
      transfers: 0,
      net_expected_points: 50.0,
      gain_over_roll: 0,
      options: [
        { transfers: 0, hit_points: 0, net_expected_points: 50.0, gain_over_roll: 0, moves: [] },
        { transfers: 1, hit_points: -4, net_expected_points: 47.0, gain_over_roll: -3.0, moves: [] },
      ],
    });
    const result = rollComparison(recommendation);
    expect(result.statement).toContain("fewer points than holding");
  });
});

describe("formatSignedPoints", () => {
  it("prefixes a plus sign for a positive value", () => {
    expect(formatSignedPoints(2.4)).toBe("+2.40");
  });

  it("keeps the minus sign for a negative value and adds none for zero", () => {
    expect(formatSignedPoints(-0.9)).toBe("-0.90");
    expect(formatSignedPoints(0)).toBe("0.00");
  });
});

describe("formatTransferLabel", () => {
  it("names a roll and pluralises transfers correctly", () => {
    expect(formatTransferLabel(0)).toBe("Roll (no transfer)");
    expect(formatTransferLabel(1)).toBe("1 transfer");
    expect(formatTransferLabel(2)).toBe("2 transfers");
  });
});
