import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { WeekPanel } from "./WeekPanel";
import { skippedWeek, week } from "../test/fixtures";

describe("WeekPanel", () => {
  it("shows both the UK and the local deadline", () => {
    // The reason this exists at all: FPL publishes in UK time, the owner is on AEST, and the gap
    // between them changes twice a season on different dates. Doing that conversion in your head
    // at 03:00 is how a deadline gets missed.
    render(<WeekPanel week={week} />);
    const deadline = screen.getByTestId("week-deadline");

    expect(within(deadline).getByText("UK")).toBeTruthy();
    expect(within(deadline).getByText("Local")).toBeTruthy();
    expect(within(deadline).getByText("Decide by")).toBeTruthy();
  });

  it("renders the same instant as a Friday in the UK and a Saturday locally", () => {
    // 18:30 BST Friday is 03:30 Saturday in Sydney. If the panel ever renders one zone for both
    // rows, this is what catches it — a check on the labels alone would not.
    render(<WeekPanel week={week} />);
    const rows = screen.getByTestId("week-deadline").textContent ?? "";

    expect(rows).toContain("Fri");
    expect(rows).toContain("Sat");
  });

  it("lists every option including the roll, with its own gain", () => {
    // FR-24. Doing nothing is a decision with a number on it, not a blank space.
    render(<WeekPanel week={week} />);
    const options = screen.getByTestId("week-options");

    expect(within(options).getByText(/Roll \(no transfer\)/)).toBeTruthy();
    expect(screen.getByTestId("week-option-0")).toBeTruthy();
    expect(screen.getByTestId("week-option-1")).toBeTruthy();
    expect(screen.getByTestId("week-option-2")).toBeTruthy();
  });

  it("marks which option is recommended", () => {
    render(<WeekPanel week={week} />);
    const chosen = screen.getByTestId("week-option-1");
    expect(within(chosen).getByText(/recommended/)).toBeTruthy();

    const roll = screen.getByTestId("week-option-0");
    expect(within(roll).queryByText(/recommended/)).toBeNull();
  });

  it("shows a losing option's negative gain rather than hiding it", () => {
    // A panel that only showed the winner would be a recommendation engine. Showing the two-
    // transfer option at -0.90 is what lets the reader disagree with it (DP-10).
    render(<WeekPanel week={week} />);
    const losing = screen.getByTestId("week-option-2");

    expect(within(losing).getByText("-0.90")).toBeTruthy();
    expect(within(losing).getByText("-4")).toBeTruthy();
  });

  it("shows the transfer as a named swap with prices", () => {
    render(<WeekPanel week={week} />);
    const moves = screen.getByTestId("week-moves");

    expect(within(moves).getByText(/Salah/)).toBeTruthy();
    expect(within(moves).getByText(/Saka/)).toBeTruthy();
    expect(within(moves).getByText(/£14.8m/)).toBeTruthy();
  });

  it("says how the squad was established", () => {
    // Provenance is reported, never hidden: a declared squad and a reconstructed one deserve
    // different amounts of trust (DL-20).
    render(<WeekPanel week={week} />);
    expect(screen.getByTestId("week-state").textContent).toMatch(/squad declared/);
  });

  it("surfaces urgent alerts and stays quiet about the rest", () => {
    // Attention is the scarce resource. An availability alert changes what you do this week; a
    // price nudge does not, and putting both at the top means neither gets read by November.
    render(<WeekPanel week={week} />);
    const alerts = screen.getByTestId("week-alerts");

    expect(within(alerts).getByText(/Salah is unavailable/)).toBeTruthy();
    expect(within(alerts).queryByText(/pressure to rise/)).toBeNull();
  });

  it("explains itself when there is no squad yet", () => {
    // Preseason is the normal state before GW1 is scored, not an error (DL-20). The panel must
    // still render the deadline, because that is the part that is still true.
    render(<WeekPanel week={skippedWeek} />);

    expect(screen.getByTestId("week-skipped").textContent).toMatch(/no published picks/);
    expect(screen.getByTestId("week-deadline")).toBeTruthy();
    expect(screen.queryByTestId("week-options")).toBeNull();
  });
});
