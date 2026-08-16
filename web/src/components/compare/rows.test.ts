import { describe, expect, it } from "vitest";
import type { Components, Player } from "../../contract/types";
import { players as fixturePlayers } from "../../test/fixtures";
import { COMPARE_ROWS, leadingId } from "./rows";

const [raya, watkins] = fixturePlayers.players;

interface Overrides extends Partial<Omit<Player, "components">> {
  id: number;
  components?: Partial<Components>;
}

function player({ components, ...rest }: Overrides): Player {
  return { ...raya, ...rest, components: { ...raya.components, ...components } };
}

function row(key: string) {
  const found = COMPARE_ROWS.find((entry) => entry.key === key);
  if (!found) throw new Error(`no compare row ${key}`);
  return found;
}

describe("leadingId", () => {
  it("marks the cheapest player on the price row, because lower is better there", () => {
    // Raya £6.0m, Watkins £8.0m.
    expect(leadingId(row("price"), [raya, watkins])).toBe(raya.id);
  });

  it("marks the highest value on a plain higher-is-better row", () => {
    expect(leadingId(row("start_probability"), [raya, watkins])).toBe(raya.id);
  });

  it("refuses to mark a forecast row when the gap is inside the uncertainty (Invariant 6)", () => {
    // Watkins has the higher mean, 4.52 against 4.20 — but with bands of ±2.0 and ±1.9 the lead is
    // not a lead, and badging it would assert a difference the forecast cannot support.
    expect(leadingId(row("xp_next"), [raya, watkins])).toBeNull();
    expect(leadingId(row("xp_horizon"), [raya, watkins])).toBeNull();
  });

  it("marks a forecast row once the gap outruns the uncertainty", () => {
    const strong = player({ id: 10, xp_next: 8.0, xp_next_sd: 1.0 });
    const weak = player({ id: 11, xp_next: 4.0, xp_next_sd: 1.0 });
    expect(leadingId(row("xp_next"), [weak, strong])).toBe(10);
  });

  it("marks nobody when the values tie", () => {
    const a = player({ id: 20, price: 7.0 });
    const b = player({ id: 21, price: 7.0 });
    expect(leadingId(row("price"), [a, b])).toBeNull();
  });

  it("marks nobody on an unranked row", () => {
    expect(leadingId(row("team"), [raya, watkins])).toBeNull();
    expect(leadingId(row("confidence"), [raya, watkins])).toBeNull();
  });

  it("treats a deduction component as higher-is-better, since it is published negative", () => {
    // Conceding less is a smaller deduction, which is the larger number.
    const leaky = player({ id: 30, components: { goals_conceded: -1.2 } });
    const tight = player({ id: 31, components: { goals_conceded: -0.1 } });
    expect(leadingId(row("component_goals_conceded"), [leaky, tight])).toBe(31);
  });

  it("ignores a player whose value is not published rather than ranking it as zero", () => {
    const free = player({ id: 40, price: 0 });
    expect(leadingId(row("value"), [free, watkins])).toBeNull();
  });
});

describe("COMPARE_ROWS", () => {
  it("renders every expected-points figure with its uncertainty (Invariant 6)", () => {
    for (const key of ["xp_next", "xp_horizon"]) {
      expect(row(key).cellTitle?.(watkins)).toContain("plausibly");
    }
  });

  it("has a unique key per row, so the leaders map cannot collide", () => {
    const keys = COMPARE_ROWS.map((entry) => entry.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("covers all nine expected-points components", () => {
    const componentRows = COMPARE_ROWS.filter((entry) => entry.group === "components");
    expect(componentRows.length).toBe(Object.keys(watkins.components).length);
  });
});
