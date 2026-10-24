import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { week } from "../../test/fixtures";
import { SquadBudget } from "./SquadBudget";

const state = week.squad_state!;
const recommendation = week.recommendation!;

function checkText(rec: typeof recommendation | undefined, bank = state.bank): string {
  render(<SquadBudget state={{ ...state, bank }} recommendation={rec} currentValue={100} advisedValue={100.3} />);
  return screen.getByTestId("squad-budget-check").textContent ?? "";
}

describe("SquadBudget", () => {
  it("shows the value, the budget and that the advised move fits it", () => {
    const text = checkText(recommendation);
    expect(text).toBe("Within budget: the advised moves cost £0.3m net, leaving £0.2m in the bank.");
    expect(screen.getByTestId("squad-budget-value").textContent).toContain("£100.0m");
    expect(screen.getByTestId("squad-budget-budget").textContent).toContain("£100.0m");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says a roll keeps the bank", () => {
    expect(checkText({ ...recommendation, moves: [], bank_after: state.bank })).toContain("no transfers");
  });

  it("flags advice the bank cannot pay for", () => {
    expect(checkText({ ...recommendation, bank_after: undefined }, 0.1)).toContain("£0.2m short");
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("flags a bank after the moves that disagrees with their prices", () => {
    expect(checkText({ ...recommendation, bank_after: 0.4 })).toContain("Check before acting");
  });
});
