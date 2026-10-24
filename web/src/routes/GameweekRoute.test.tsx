/**
 * WEB-12 through the rendered routes: the decision follows the header's model, the roll is always
 * beside it, and Plan ahead counts the gameweeks to chip expiry from the published calendar.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import { challengerWeek, plan, strategiesFixture } from "../test/fixtures";

describe("This gameweek", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows the decision with its reasoning, rules and the roll beside it", async () => {
    installFetchStub();
    renderApp("/gameweek");
    await screen.findByTestId("decision-view");
    expect(screen.getByTestId("week-moves")).toBeTruthy();
    expect(screen.getByTestId("dashboard-roll-comparison")).toBeTruthy();
    expect(screen.getByTestId("squad-pitch")).toBeTruthy();
    expect(screen.getByTestId("bench")).toBeTruthy();
    expect(screen.getByText("Why this number")).toBeTruthy();
    expect(screen.getByTestId("decomposition")).toBeTruthy();
    expect(screen.getByText("What the rules say")).toBeTruthy();
    expect(screen.getByText("The bet you are making")).toBeTruthy();
  });

  it("changes the decision when the model changes, keeping the roll beside it", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture, week_c1: challengerWeek } });
    renderApp("/gameweek");
    await screen.findByTestId("decision-view");
    expect(screen.getByTestId("week-rationale").textContent).toContain("gain 2.40");

    fireEvent.click(screen.getByTestId("model-toggle-c1"));
    await waitFor(() =>
      expect(screen.getByTestId("week-rationale").textContent).toBe("Roll the free transfer"),
    );
    expect(screen.queryByTestId("week-moves")).toBeNull();
    expect(screen.getByTestId("dashboard-roll-comparison")).toBeTruthy();
    expect(screen.getByTestId("dashboard-roll-counterfactual")).toBeTruthy();
  });
});

describe("Plan ahead", () => {
  beforeEach(() => resetAppState());
  afterEach(() => vi.unstubAllGlobals());

  it("shows the chip calendar and the gameweeks left, from the published expiry", async () => {
    installFetchStub();
    renderApp("/gameweek/plan");
    await screen.findByTestId("plan-timeline");
    expect(screen.getByTestId("plan-calendar")).toBeTruthy();
    expect(screen.getByTestId("timeline-expiry-wildcard").textContent).toContain("GW19");
    expect(screen.getByTestId("timeline-expiry-wildcard").textContent).toContain("17 gameweek(s) away");
  });

  it("follows the data when the expiry moves (nothing is hardcoded)", async () => {
    const moved = {
      ...plan,
      chip_calendar: {
        ...plan.chip_calendar!,
        expiring: [{ chip: "wildcard", chip_label: "Wildcard", expires_gameweek: 7 }],
      },
    };
    installFetchStub({ bodies: { plan: moved } });
    renderApp("/gameweek/plan");
    await screen.findByTestId("plan-timeline");
    expect(screen.getByTestId("timeline-expiry-wildcard").textContent).toContain("GW7");
    expect(screen.getByTestId("timeline-expiry-wildcard").textContent).toContain("5 gameweek(s) away");
  });
});
