/**
 * WEB-12 through the rendered routes: the decision follows the header's model, the roll is always
 * beside it, and Plan ahead counts the gameweeks to chip expiry from the published calendar.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import { challengerWeek, plan, strategiesFixture, week } from "../test/fixtures";

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

  it("shows the selected model's roll, best single and best overall (ORC-11)", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture, week_c1: challengerWeek } });
    renderApp("/gameweek");
    const options = await screen.findByTestId("decision-options");
    expect(within(options).getAllByRole("row")).toHaveLength(4);
    expect(screen.getByTestId("decision-options-0").textContent).toContain("roll");
    expect(screen.getByTestId("decision-options-0").textContent).toContain("50.00");
    const single = screen.getByTestId("decision-options-1").textContent;
    expect(single).toContain("best single transfer");
    expect(single).toContain("Salah → Saka");
    expect(single).toContain("+2.40");
    const overall = screen.getByTestId("decision-options-2").textContent;
    expect(overall).toContain("best overall");
    expect(overall).toContain("−4");
    expect(overall).toContain("53.10");

    fireEvent.click(screen.getByTestId("model-toggle-c1"));
    await waitFor(() => expect(within(screen.getByTestId("decision-options")).getAllByRole("row")).toHaveLength(3));
    expect(screen.getByTestId("decision-options-0").textContent).toContain("roll, best overall");
    expect(screen.getByTestId("decision-options-1").textContent).toContain("−0.40");
  });

  it("shows the chip scenarios the model's plan enumerated, and says when a model has no plan (ORC-11)", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture, week_c1: challengerWeek } });
    renderApp("/gameweek");
    const scenario = await screen.findByTestId("decision-scenario-bboost@4");
    expect(scenario.textContent).toContain("Bench Boost in GW4");
    expect(scenario.textContent).toContain("recommended");
    expect(scenario.textContent).toContain("248.10");
    expect(scenario.textContent).toContain("−4");
    expect(screen.getByTestId("decision-scenarios").textContent).toContain("GW2–GW6");

    // C1 publishes a week but no plan here: said, not an empty table.
    fireEvent.click(screen.getByTestId("model-toggle-c1"));
    await waitFor(() => expect(screen.getByTestId("decision-no-scenarios").textContent).toContain("no multi-week plan"));
  });

  it("says so when the advice was published without its options", async () => {
    const { option_set: _gone, ...bare } = week.recommendation!;
    installFetchStub({ bodies: { week: { ...week, recommendation: bare } } });
    renderApp("/gameweek");
    expect((await screen.findByTestId("decision-no-options")).textContent).toContain("without its options");
    expect(screen.getByTestId("dashboard-roll-comparison")).toBeTruthy();
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
