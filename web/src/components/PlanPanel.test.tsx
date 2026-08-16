import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PlanPanel } from "./PlanPanel";
import { plan, skippedPlan } from "../test/fixtures";

/**
 * The tests that carry real risk here are not "does it render the plan". They are the two
 * obligations E4 inherited, both of which fail silently: the D-13 caveat disappearing from a chip
 * recommendation, and an ownership figure being labelled as something it is not.
 */
describe("PlanPanel", () => {
  it("renders the D-13 caveat prominently whenever a chip is recommended", () => {
    render(<PlanPanel plan={plan} />);

    const caveats = screen.getByTestId("plan-caveats");
    expect(caveats.textContent).toContain("D-13");
    expect(caveats.textContent).toContain("unvalidated at the head of the ranking");

    // Before the recommendation, not after it: a caveat below the fold is a caveat nobody reads.
    const rationale = screen.getByTestId("plan-rationale");
    expect(
      caveats.compareDocumentPosition(rationale) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("states which ownership source is in use and never calls it effective ownership", () => {
    render(<PlanPanel plan={plan} />);

    const ownership = screen.getByTestId("plan-ownership");
    expect(ownership.textContent).toContain("selected by");
    expect(ownership.textContent).not.toContain("effective ownership");
    expect(screen.getByTestId("plan-ownership-source").textContent).toContain(
      "selected_by_percent",
    );
  });

  it("surfaces the most-captained callout separately, including when it is unknown", () => {
    render(<PlanPanel plan={plan} />);
    expect(screen.getByTestId("plan-most-captained").textContent).toContain(
      "not available in the published data",
    );
  });

  it("always shows rolling everything as a ranked option with a number on it", () => {
    render(<PlanPanel plan={plan} />);
    const runners = screen.getByTestId("plan-runners");
    expect(runners.textContent).toContain("roll everything");
    expect(runners.textContent).toContain("-6.2");
  });

  it("lists the chip calendar with the expiry read from the game, not written down", () => {
    render(<PlanPanel plan={plan} />);
    const expiry = screen.getByTestId("plan-chip-expiry");
    expect(expiry.textContent).toContain("Bench Boost");
    expect(expiry.textContent).toContain("gameweek 19");
  });

  it("degrades to a stated reason when there is nothing to plan around", () => {
    render(<PlanPanel plan={skippedPlan} />);
    expect(screen.getByTestId("plan-skipped").textContent).toContain(
      "no published picks are available",
    );
    expect(screen.queryByTestId("plan-weeks")).toBeNull();
  });
});
