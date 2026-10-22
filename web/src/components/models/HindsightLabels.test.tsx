import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { buildRegistry } from "../../data/registry";
import { strategiesFixture } from "../../test/fixtures";
import { mockLog, mockPlayers } from "./HindsightSection.fixtures";

vi.mock("../../data/DataProvider", () => ({ useRegistry: () => buildRegistry(strategiesFixture) }));
const { HindsightSection } = await import("./HindsightSection");

describe("hindsight labels come from the registry", () => {
  it("labels rows by the registry's label, mapping a legacy key through its alias", () => {
    render(<HindsightSection log={mockLog} players={mockPlayers} status="ready" />);
    expect(screen.getByTestId("rank-row-c1").textContent).toContain("Challenger (C1)");
    expect(screen.getByTestId("rank-row-xp_v1").textContent).toContain("Champion (C3)");
  });
});
