import { describe, expect, it } from "vitest";
import type { Components, Player } from "../../contract/types";
import { players as fixturePlayers } from "../../test/fixtures";
import { buildVerdict, separated } from "./verdict";

const [raya, watkins, mbeumo] = fixturePlayers.players;

interface Overrides extends Partial<Omit<Player, "components">> {
  id: number;
  components?: Partial<Components>;
}

/** A player built off the published fixture, so no test invents a shape the contract does not have. */
function player({ components, ...rest }: Overrides): Player {
  return {
    ...raya,
    ...rest,
    components: { ...raya.components, ...components },
  };
}

function line(verdict: ReturnType<typeof buildVerdict>, key: string) {
  const found = verdict.lines.find((entry) => entry.key === key);
  if (!found) throw new Error(`no verdict line ${key} in ${verdict.lines.map((l) => l.key).join(", ")}`);
  return found;
}

describe("separated", () => {
  it("is false when the gap is inside the combined uncertainty", () => {
    // The fixtures' own numbers: 4.20 ±1.89 against 4.52 ±2.03. A third of a point apart, with
    // bands nearly two points wide each. Nothing here is a difference.
    expect(separated(raya.xp_next, raya.xp_next_sd, watkins.xp_next, watkins.xp_next_sd)).toBe(false);
  });

  it("is true when the gap is wider than the combined uncertainty", () => {
    expect(separated(8.0, 1.0, 4.0, 1.0)).toBe(true);
  });

  it("does not separate two identical forecasts, however tight their bands", () => {
    expect(separated(5.0, 0, 5.0, 0)).toBe(false);
  });

  it("is symmetric", () => {
    expect(separated(4.0, 1.0, 8.0, 1.0)).toBe(separated(8.0, 1.0, 4.0, 1.0));
  });
});

describe("buildVerdict — the uncertainty discipline (Invariant 6, DP-09)", () => {
  it("refuses to name a leader when the forecasts overlap, and says so", () => {
    const verdict = buildVerdict([raya, watkins], { horizonGameweeks: 6 });

    expect(verdict.headline).toContain("does not separate");
    const next = line(verdict, "forecast_next");
    expect(next.decisive).toBe(false);
    expect(next.statement).toContain("Nothing separates them");
    // The claim it declines to make must not appear anywhere in the sentence that declines it.
    expect(next.statement).not.toContain("better forecast");
  });

  it("names a leader once the gap outruns the uncertainty", () => {
    const strong = player({ id: 10, name: "Strong", xp_next: 8.0, xp_next_sd: 1.0 });
    const weak = player({ id: 11, name: "Weak", xp_next: 4.0, xp_next_sd: 1.0 });

    const next = line(buildVerdict([weak, strong]), "forecast_next");
    expect(next.decisive).toBe(true);
    expect(next.statement).toContain("Strong has the better forecast");
    expect(next.statement).toContain("wider than the combined uncertainty");
  });

  it("quotes every expected-points figure with its band", () => {
    const verdict = buildVerdict([raya, watkins], { horizonGameweeks: 6 });
    for (const key of ["forecast_next", "forecast_horizon"]) {
      const statement = line(verdict, key).statement;
      expect(statement).toContain("±");
      // Both players' means, each immediately followed by an uncertainty.
      expect(statement).toMatch(/\d+\.\d{2} ±\d+\.\d.*\d+\.\d{2} ±\d+\.\d/);
    }
  });

  it("always carries its caveats, including that it adds no information", () => {
    const verdict = buildVerdict([raya, watkins]);
    expect(verdict.caveats.length).toBeGreaterThan(0);
    expect(verdict.caveats.join(" ")).toContain("forecast carrying an uncertainty band");
    expect(verdict.caveats.join(" ")).toContain("fixed set of rules");
  });

  it("names the positions when they differ, because they are not the same squad slot", () => {
    // Raya is a goalkeeper and Watkins a forward.
    expect(buildVerdict([raya, watkins]).caveats[0]).toContain("different positions");
    expect(buildVerdict([watkins, player({ id: 12, position: "FWD" })]).caveats[0]).not.toContain(
      "different positions",
    );
  });

  it("labels ownership as FPL's published figure, never as effective ownership (DL-24)", () => {
    const verdict = buildVerdict([raya, watkins]);
    expect(verdict.caveats.join(" ")).toContain("not effective ownership");
    expect(line(verdict, "ownership").statement).toContain("selected by");
  });
});

describe("buildVerdict — the dimensions", () => {
  it("says which is cheaper and what that buys per £m", () => {
    const value = line(buildVerdict([raya, watkins]), "value");
    // Raya £6.0m against Watkins £8.0m; horizon 19.255 and 22.214.
    expect(value.statement).toContain("Raya is £2.0m cheaper than Watkins");
    expect(value.statement).toContain("£6.0m against £8.0m");
    expect(value.statement).toContain("3.21"); // 19.255 / 6.0
    expect(value.statement).toContain("2.78"); // 22.214 / 8.0
    expect(value.decisive).toBe(true); // cheaper *and* the better rate
  });

  it("says plainly when price is not the deciding factor", () => {
    // Watkins and Mbeumo both cost £8.0m in the fixture.
    const value = line(buildVerdict([watkins, mbeumo]), "value");
    expect(value.statement).toContain("They all cost the same");
    expect(value.decisive).toBe(false);
  });

  it("puts an availability flag above any forecast gap", () => {
    const injured = player({
      id: 20,
      name: "Injured",
      status: "i",
      news: "Hamstring, expected back in two weeks",
    });
    const availability = line(buildVerdict([injured, watkins]), "availability");
    expect(availability.decisive).toBe(true);
    expect(availability.statement).toContain("Injured is injured");
    expect(availability.statement).toContain("Hamstring");
    expect(availability.statement).toContain("outranks any forecast gap");
  });

  it("names the surer starter only when the modelled gap is worth naming", () => {
    // 93.8% against 83.7% — ten points apart.
    const wide = line(buildVerdict([raya, watkins]), "availability");
    expect(wide.statement).toContain("Raya is the surer starter");
    expect(wide.statement).toContain("modelled rather than observed");

    const close = line(
      buildVerdict([player({ id: 30, name: "A", start_probability: 0.9 }), player({ id: 31, name: "B", start_probability: 0.88 })]),
      "availability",
    );
    expect(close.statement).toContain("about as often as each other");
  });

  it("reports differing model confidence rather than averaging over it", () => {
    const statement = line(buildVerdict([watkins, mbeumo]), "availability").statement;
    expect(statement).toContain("not equally confident");
    expect(statement).toContain("Mbeumo medium");
  });

  it("calls out the differential when ownership genuinely differs", () => {
    // Raya 31.0%, Watkins 12.5%.
    const ownership = line(buildVerdict([raya, watkins]), "ownership");
    expect(ownership.decisive).toBe(true);
    expect(ownership.statement).toContain("Watkins is the differential");
    expect(ownership.statement).toContain("12.5%");
    expect(ownership.statement).toContain("31.0%");
  });

  it("does not call two similar ownerships a differential", () => {
    const ownership = line(
      buildVerdict([
        player({ id: 40, name: "A", selected_by_percent: 31.0 }),
        player({ id: 41, name: "B", selected_by_percent: 29.0 }),
      ]),
      "ownership",
    );
    expect(ownership.decisive).toBe(false);
    expect(ownership.statement).toContain("barely separates them");
  });

  it("omits the ownership line when the figure is unpublished", () => {
    const verdict = buildVerdict([
      player({ id: 42, name: "A", selected_by_percent: undefined }),
      player({ id: 43, name: "B", selected_by_percent: undefined }),
    ]);
    expect(verdict.lines.find((entry) => entry.key === "ownership")).toBeUndefined();
  });

  it("separates an attacking forecast from a defensive one", () => {
    const striker = player({
      id: 50,
      name: "Striker",
      components: { goals: 2.0, assists: 0.5, clean_sheet: 0.1, saves: 0, defensive_contribution: 0.1 },
    });
    const stopper = player({
      id: 51,
      name: "Stopper",
      components: { goals: 0.1, assists: 0.1, clean_sheet: 1.5, saves: 1.0, defensive_contribution: 0.5 },
    });

    const components = line(buildVerdict([striker, stopper]), "components");
    expect(components.decisive).toBe(true);
    expect(components.statement).toContain("Striker 2.50 from goals and assists");
    expect(components.statement).toContain(
      "Stopper 0.20 from goals and assists against 3.00 from clean sheets",
    );
    expect(components.statement).toContain("different bets");
  });

  it("says so when the decomposition splits both players the same way", () => {
    // The fixtures share one component set, so nothing distinguishes them here.
    const components = line(buildVerdict([raya, watkins]), "components");
    expect(components.decisive).toBe(false);
    expect(components.statement).toContain("They all split the same way");
  });

  it("distinguishes a high floor from a high ceiling", () => {
    const safe = player({ id: 60, name: "Safe", xp_next: 2.5, xp_next_sd: 0.8 });
    const explosive = player({ id: 61, name: "Explosive", xp_next: 8.0, xp_next_sd: 3.5 });

    const floor = line(buildVerdict([safe, explosive]), "floor");
    expect(floor.decisive).toBe(true);
    expect(floor.statement).toContain("Safe is the safer of the two");
    expect(floor.statement).toContain("Explosive has to actually return");
  });

  it("flags when the single gameweek and the horizon disagree", () => {
    const shortTerm = player({ id: 70, name: "Short", xp_next: 8.0, xp_horizon: 10.0 });
    const longTerm = player({ id: 71, name: "Long", xp_next: 4.0, xp_horizon: 30.0 });

    const swap = line(buildVerdict([shortTerm, longTerm], { horizonGameweeks: 6 }), "order_swap");
    expect(swap.statement).toContain("Short leads for the single gameweek");
    expect(swap.statement).toContain("Long leads over the 6-gameweek horizon");
  });

  it("does not raise the order-swap line when the same player leads both", () => {
    const verdict = buildVerdict([
      player({ id: 72, name: "A", xp_next: 8.0, xp_horizon: 30.0 }),
      player({ id: 73, name: "B", xp_next: 4.0, xp_horizon: 10.0 }),
    ]);
    expect(verdict.lines.find((entry) => entry.key === "order_swap")).toBeUndefined();
  });
});

describe("buildVerdict — shape", () => {
  it("handles the full four, listing the ones behind the top two", () => {
    const four = [
      player({ id: 80, name: "One", xp_next: 8.0, xp_next_sd: 0.5 }),
      player({ id: 81, name: "Two", xp_next: 6.0, xp_next_sd: 0.5 }),
      player({ id: 82, name: "Three", xp_next: 4.0, xp_next_sd: 0.5 }),
      player({ id: 83, name: "Four", xp_next: 2.0, xp_next_sd: 0.5 }),
    ];
    const next = line(buildVerdict(four), "forecast_next");
    expect(next.statement).toContain("Behind them:");
    expect(next.statement).toContain("Three");
    expect(next.statement).toContain("Four");
  });

  it("is deterministic: the same players in any order produce the same verdict (DP-11)", () => {
    const a = buildVerdict([raya, watkins, mbeumo], { horizonGameweeks: 6 });
    const b = buildVerdict([mbeumo, watkins, raya], { horizonGameweeks: 6 });
    expect(b.headline).toBe(a.headline);
    expect(b.lines.map((l) => l.statement)).toEqual(a.lines.map((l) => l.statement));
  });

  it("returns nothing to argue about below two players", () => {
    const verdict = buildVerdict([raya]);
    expect(verdict.lines).toEqual([]);
    expect(verdict.headline).toContain("at least two players");
  });

  it("names the horizon in gameweeks when the publication says how long it is", () => {
    expect(line(buildVerdict([raya, watkins], { horizonGameweeks: 6 }), "forecast_horizon").heading).toBe(
      "Over the next 6 gameweeks",
    );
    expect(line(buildVerdict([raya, watkins]), "forecast_horizon").heading).toBe("Over the horizon");
  });
});
