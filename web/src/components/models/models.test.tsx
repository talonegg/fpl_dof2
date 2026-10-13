import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { challengerWeek, players, week } from "../../test/fixtures";
import { diffModels } from "../../data/modelDiff";
import { MODEL_STORAGE_KEY } from "../../data/model";

describe("champion/challenger", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("defaults to the champion and labels the recommendation", async () => {
    installFetchStub({ bodies: { week_challenger: challengerWeek } });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    expect(screen.getByTestId("model-toggle-champion").getAttribute("aria-checked")).toBe("true");
    const card = screen.getByTestId("dashboard-recommendation");
    expect(within(card).getByTestId("model-badge").dataset.model).toBe("champion");
    expect(screen.getByTestId("week-rationale").textContent).toBe(week.recommendation!.rationale);
  });

  it("switches to the challenger, relabels, and remembers the choice", async () => {
    installFetchStub({ bodies: { week_challenger: challengerWeek } });
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    fireEvent.click(screen.getByTestId("model-toggle-challenger"));
    await waitFor(() =>
      expect(screen.getByTestId("week-rationale").textContent).toBe("Roll the free transfer"),
    );
    const card = screen.getByTestId("dashboard-recommendation");
    expect(within(card).getByTestId("model-badge").dataset.model).toBe("challenger");
    expect(window.localStorage.getItem(MODEL_STORAGE_KEY)).toBe("challenger");
  });

  it("honours a stored choice and a ?model= URL param", async () => {
    installFetchStub({ bodies: { week_challenger: challengerWeek } });
    window.localStorage.setItem(MODEL_STORAGE_KEY, "challenger");
    renderApp("/");
    await waitFor(() =>
      expect(screen.getByTestId("week-rationale").textContent).toBe("Roll the free transfer"),
    );
  });

  it("URL param overrides storage", async () => {
    installFetchStub({ bodies: { week_challenger: challengerWeek } });
    window.localStorage.setItem(MODEL_STORAGE_KEY, "challenger");
    window.history.replaceState(null, "", "/?model=champion");
    renderApp("/");
    await waitFor(() =>
      expect(screen.getByTestId("week-rationale").textContent).toBe(week.recommendation!.rationale),
    );
  });

  it("degrades to the champion when the challenger is missing", async () => {
    installFetchStub();
    window.localStorage.setItem(MODEL_STORAGE_KEY, "challenger");
    renderApp("/");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    expect((screen.getByTestId("model-toggle-challenger") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("model-toggle-note").textContent).toContain("not published");
    expect(screen.getByTestId("week-rationale").textContent).toBe(week.recommendation!.rationale);
  });

  it("shows the side-by-side diff", async () => {
    installFetchStub({ bodies: { week_challenger: challengerWeek } });
    renderApp("/models");
    await waitFor(() => expect(screen.getByTestId("model-diff")).toBeTruthy());
    expect(screen.getByTestId("model-diff-summary").textContent).toContain("transfers differ");
    expect(screen.getByTestId("model-diff-summary").textContent).toContain("captain differs");
    expect(screen.getByTestId("model-diff-challenger-transfers").textContent).toContain("Roll");
    expect(screen.getAllByTestId("model-diff-champion-only").length).toBe(1);
  });

  it("the diff view says so when the challenger is missing", async () => {
    installFetchStub();
    renderApp("/models");
    await waitFor(() => expect(screen.getByTestId("model-diff-missing")).toBeTruthy());
  });

  it("diffModels finds transfer, captain and XI differences", () => {
    const d = diffModels(week, challengerWeek, players);
    expect(d.transfersDiffer).toBe(true);
    expect(d.captainDiffers).toBe(true);
    expect(d.onlyChampionXI.map((p) => p.id)).toEqual([2]);
    expect(d.onlyChallengerXI.map((p) => p.id)).toEqual([3]);
    expect(diffModels(week, week, players).differenceCount).toBe(0);
  });
});
