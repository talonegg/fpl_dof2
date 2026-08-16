/**
 * The builder as a reader meets it.
 *
 * The unit tests either side of this one prove the rules are applied correctly; what this checks is
 * that they are applied *live and visibly* — that an edit which breaks a rule says so on the page
 * before the reader can act on it, and that the re-optimisation never presents itself as more than
 * the heuristic it is.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { SquadBuilder } from "./SquadBuilder";
import { LOCKS_STORAGE_KEY, loadMarks } from "./locks";
import { builtSquad, pool, rules } from "./testFixtures";
import { week } from "../../test/fixtures";

function renderBuilder(overrides: { budget?: number } = {}) {
  const squadWeek = overrides.budget
    ? { ...week, squad_state: { ...week.squad_state!, budget: overrides.budget } }
    : null;
  return render(
    <SquadBuilder players={pool} squad={builtSquad} rules={rules} week={squadWeek} />,
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("the published squad, as loaded", () => {
  it("opens on the published squad and reports it legal", () => {
    renderBuilder();
    expect(screen.getByTestId("builder-legal")).toBeTruthy();
    expect(screen.queryByTestId("builder-violations")).toBeNull();
  });

  it("counts the squad against the published size rather than a remembered fifteen", () => {
    renderBuilder();
    const summary = screen.getByTestId("builder-summary");
    expect(summary.textContent).toContain(`${rules.squad.size} / ${rules.squad.size}`);
    expect(summary.textContent).toContain(
      `${rules.squad.starting_size} / ${rules.squad.starting_size} starting`,
    );
  });

  it("says what the budget it is spending against actually is", () => {
    renderBuilder();
    expect(screen.getByTestId("builder-basis").textContent).toContain("opening budget");
    cleanup();
    renderBuilder({ budget: 101.5 });
    expect(screen.getByTestId("builder-basis").textContent).toContain("sell value plus bank");
    expect(screen.getByTestId("builder-summary").textContent).toContain("£101.5m");
  });
});

describe("live legality checking", () => {
  it("shows a violation the moment a player is removed", () => {
    renderBuilder();
    const row = screen.getByTestId("builder-row-202");
    fireEvent.click(within(row).getByText("Ban"));

    const panel = screen.getByTestId("builder-violations");
    expect(panel.textContent).toContain("14 players");
    expect(panel.querySelector('[data-violation="composition"]')).toBeTruthy();
    expect(screen.queryByTestId("builder-legal")).toBeNull();
  });

  it("shows a formation violation when the XI is left short", () => {
    renderBuilder();
    const row = screen.getByTestId("builder-row-100");
    fireEvent.click(within(row).getByText("Starting"));

    const panel = screen.getByTestId("builder-violations");
    expect(panel.querySelector('[data-violation="starting_size"]')).toBeTruthy();
    expect(panel.querySelector('[data-violation="formation"]')).toBeTruthy();
  });

  it("clears the violation again when the edit is undone", () => {
    renderBuilder();
    const row = screen.getByTestId("builder-row-100");
    fireEvent.click(within(row).getByText("Starting"));
    expect(screen.getByTestId("builder-violations")).toBeTruthy();

    fireEvent.click(within(screen.getByTestId("builder-row-100")).getByText("Bench"));
    expect(screen.getByTestId("builder-legal")).toBeTruthy();
  });

  it("returns to the published squad on request", () => {
    renderBuilder();
    fireEvent.click(within(screen.getByTestId("builder-row-202")).getByText("Ban"));
    expect(screen.getByTestId("builder-violations")).toBeTruthy();

    fireEvent.click(screen.getByTestId("builder-reset"));
    expect(screen.getByTestId("builder-legal")).toBeTruthy();
  });
});

describe("swapping a player", () => {
  it("pins the picker to the outgoing player's position", () => {
    renderBuilder();
    fireEvent.click(within(screen.getByTestId("builder-row-202")).getByText("Replace"));

    const picker = screen.getByTestId("builder-picker");
    expect(picker.textContent).toContain("Replace");
    // Every candidate offered is a defender: a swap that changes the composition is never the move.
    const candidates = picker.querySelectorAll('[data-testid^="builder-candidate-"]');
    expect(candidates.length).toBeGreaterThan(0);
    for (const candidate of candidates) {
      expect(candidate.textContent).toContain("DEF");
    }
  });

  it("keeps the squad legal through a like-for-like swap", () => {
    renderBuilder();
    fireEvent.click(within(screen.getByTestId("builder-row-202")).getByText("Replace"));
    const picker = screen.getByTestId("builder-picker");
    const first = picker.querySelector('[data-testid^="builder-candidate-"]')!;
    fireEvent.click(within(first as HTMLElement).getByText("Add"));

    expect(screen.queryByTestId("builder-row-202")).toBeNull();
    expect(screen.getByTestId("builder-legal")).toBeTruthy();
  });

  it("filters the pool by a search term", () => {
    renderBuilder();
    fireEvent.change(screen.getByTestId("builder-search"), { target: { value: "MID310" } });
    const picker = screen.getByTestId("builder-picker");
    expect(picker.querySelectorAll('[data-testid^="builder-candidate-"]')).toHaveLength(1);
    expect(picker.textContent).toContain("MID310");
  });

  it("says so plainly when nothing matches", () => {
    renderBuilder();
    fireEvent.change(screen.getByTestId("builder-search"), { target: { value: "zzzz" } });
    expect(screen.getByTestId("builder-no-candidates")).toBeTruthy();
  });
});

describe("locks and bans", () => {
  it("persists a lock so it is still there next time", () => {
    renderBuilder();
    fireEvent.click(within(screen.getByTestId("builder-row-202")).getByText("Lock"));

    expect(loadMarks().locked).toContain(202);
    expect(window.localStorage.getItem(LOCKS_STORAGE_KEY)).toContain("202");

    cleanup();
    renderBuilder();
    expect(within(screen.getByTestId("builder-row-202")).getByText("Locked")).toBeTruthy();
  });

  it("banning a squad member removes them and records the ban", () => {
    renderBuilder();
    fireEvent.click(within(screen.getByTestId("builder-row-202")).getByText("Ban"));

    expect(screen.queryByTestId("builder-row-202")).toBeNull();
    expect(loadMarks().banned).toContain(202);
    expect(screen.getByTestId("builder-banned").textContent).toContain("DEF202");
  });

  it("never offers a banned player back in the picker", () => {
    renderBuilder();
    fireEvent.click(within(screen.getByTestId("builder-row-202")).getByText("Ban"));
    fireEvent.change(screen.getByTestId("builder-search"), { target: { value: "DEF202" } });
    expect(screen.getByTestId("builder-no-candidates")).toBeTruthy();
  });

  it("clears every mark on request", () => {
    renderBuilder();
    fireEvent.click(within(screen.getByTestId("builder-row-202")).getByText("Lock"));
    fireEvent.click(screen.getByTestId("builder-clear-marks"));
    expect(loadMarks()).toEqual({ locked: [], banned: [] });
  });
});

describe("re-optimising", () => {
  it("produces a legal squad and says it is a heuristic, not the optimiser", () => {
    renderBuilder();
    fireEvent.click(screen.getByTestId("builder-reoptimise"));

    expect(screen.getByTestId("builder-legal")).toBeTruthy();
    expect(screen.getByTestId("builder-run").textContent).toContain("Not proven optimal");

    const note = screen.getByTestId("builder-reoptimise-note").textContent ?? "";
    expect(note).toContain("heuristic");
    expect(note).toContain("ignores transfer costs");
  });

  it("keeps a locked player through a re-optimisation", () => {
    renderBuilder();
    // Lock the cheapest defender in the squad — one no value-ranking would keep by accident.
    fireEvent.click(within(screen.getByTestId("builder-row-206")).getByText("Lock"));
    fireEvent.click(screen.getByTestId("builder-reoptimise"));

    expect(screen.getByTestId("builder-row-206")).toBeTruthy();
    expect(screen.getByTestId("builder-legal")).toBeTruthy();
  });

  it("explains itself rather than failing silently when the constraints cannot be met", () => {
    renderBuilder({ budget: 30 });
    fireEvent.click(screen.getByTestId("builder-reoptimise"));

    const panel = screen.getByTestId("builder-infeasible");
    expect(panel.textContent).toContain("No legal squad");
    expect(screen.queryByTestId("builder-run")).toBeNull();
  });
});

describe("picking the XI", () => {
  it("restores a legal XI after the reader has broken it", () => {
    renderBuilder();
    fireEvent.click(within(screen.getByTestId("builder-row-100")).getByText("Starting"));
    expect(screen.getByTestId("builder-violations")).toBeTruthy();

    fireEvent.click(screen.getByTestId("builder-auto-xi"));
    expect(screen.getByTestId("builder-legal")).toBeTruthy();
  });

  it("marks the captain and vice-captain among the starters", () => {
    renderBuilder();
    const armbands = document.querySelectorAll(".builder-armband");
    expect(armbands).toHaveLength(2);
  });
});
