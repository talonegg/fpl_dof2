/**
 * The plan timeline and the chip clock.
 *
 * What is worth protecting here is that the mechanics are named rather than counted — a reader
 * planning transfers needs "Raya out, Watkins in", not "1 transfer" — and that no chip expiry is
 * written into the component. The expiry test changes the *data* and requires the page to change
 * with it, which a hardcoded GW19 would fail (Invariant 2).
 */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Plan } from "../../contract/types";
import { PlanTimeline } from "./PlanTimeline";
import { indexPlayers } from "./draft";
import { plan, players, skippedPlan, squad } from "../../test/fixtures";

const index = indexPlayers(players.players, squad);

afterEach(cleanup);

function renderTimeline(value: Plan = plan) {
  return render(<PlanTimeline plan={value} index={index} />);
}

describe("the weeks", () => {
  it("renders a card per planned gameweek", () => {
    renderTimeline();
    expect(screen.getByTestId("timeline-week-2")).toBeTruthy();
    expect(screen.getByTestId("timeline-week-4")).toBeTruthy();
  });

  it("names the players moving rather than counting them", () => {
    renderTimeline();
    // GW2 brings in player 2 (Watkins) for player 4, who is not in the published pool.
    expect(screen.getByTestId("timeline-week-2").textContent).toContain("Watkins");
  });

  it("says plainly when a week makes no transfer", () => {
    renderTimeline();
    expect(screen.getByTestId("timeline-week-4").textContent).toContain("the squad rolls");
  });

  it("marks the chip on the week it is played", () => {
    renderTimeline();
    expect(screen.getByTestId("timeline-chip-4").textContent).toContain("Bench Boost");
  });

  it("shows the free, charged and hit arithmetic", () => {
    renderTimeline();
    const week = screen.getByTestId("timeline-week-2").textContent ?? "";
    expect(week).toContain("Free");
    expect(week).toContain("Charged");
    expect(week).toContain("Net xP");
  });
});

describe("the options", () => {
  it("offers no chooser when only one option was published", () => {
    renderTimeline();
    expect(screen.queryByTestId("timeline-option")).toBeNull();
  });

  it("lets the reader step through the alternatives, with the roll among them", () => {
    const withBaseline: Plan = {
      ...plan,
      baseline: {
        key: "roll",
        label: "roll everything",
        total_expected_points: 241.9,
        weeks: [{ ...plan.recommended!.weeks[0], transfers_in: [], transfers_out: [] }],
      },
    };
    renderTimeline(withBaseline);

    const chooser = screen.getByTestId("timeline-option") as HTMLSelectElement;
    expect(chooser.textContent).toContain("roll everything");

    fireEvent.change(chooser, { target: { value: "roll" } });
    expect(screen.getByTestId("timeline-week-2").textContent).toContain("the squad rolls");
  });
});

describe("the chip clock", () => {
  it("reads the expiry gameweek from the published calendar", () => {
    renderTimeline();
    expect(screen.getByTestId("timeline-expiry-bboost").textContent).toContain("GW19");
  });

  it("follows the data when the expiry changes, rather than remembering GW19", () => {
    const laterSet: Plan = {
      ...plan,
      chip_calendar: {
        ...plan.chip_calendar!,
        expiring: [{ chip: "bboost", chip_label: "Bench Boost", expires_gameweek: 33 }],
      },
    };
    renderTimeline(laterSet);
    const entry = screen.getByTestId("timeline-expiry-bboost").textContent ?? "";
    expect(entry).toContain("GW33");
    expect(entry).not.toContain("GW19");
  });

  it("marks an expiry that is close as urgent, in words as well as in style", () => {
    const soon: Plan = {
      ...plan,
      chip_calendar: {
        ...plan.chip_calendar!,
        from_gameweek: 18,
        expiring: [{ chip: "wildcard", chip_label: "Wildcard", expires_gameweek: 19 }],
      },
    };
    renderTimeline(soon);
    const entry = screen.getByTestId("timeline-expiry-wildcard");
    expect(entry.className).toContain("urgent");
    expect(entry.textContent).toContain("1 gameweek(s) away");
  });

  it("says when a chip is out of gameweeks entirely", () => {
    const gone: Plan = {
      ...plan,
      chip_calendar: {
        ...plan.chip_calendar!,
        from_gameweek: 19,
        expiring: [{ chip: "wildcard", chip_label: "Wildcard", expires_gameweek: 19 }],
      },
    };
    renderTimeline(gone);
    expect(screen.getByTestId("timeline-expiry-wildcard").textContent).toContain("last chance");
  });

  it("marks doubles and blanks on the chip windows", () => {
    renderTimeline();
    expect(screen.getByTestId("timeline-windows").textContent).toContain("double");
  });
});

describe("before there is anything to plan", () => {
  it("says so rather than rendering an empty timeline", () => {
    renderTimeline(skippedPlan);
    expect(screen.getByTestId("timeline-skipped")).toBeTruthy();
    expect(screen.queryByTestId("timeline-weeks")).toBeNull();
  });
});
