import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../../test/render";
import { challengerWeek, strategiesFixture, week } from "../../test/fixtures";
import { MODEL_STORAGE_KEY } from "../../data/model";

const registry = { strategies: strategiesFixture, week_c1: challengerWeek };
const championRationale = week.recommendation!.rationale;

describe("champion and challenger from the registry", () => {
  beforeEach(() => {
    resetAppState();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("defaults to the champion and labels the recommendation", async () => {
    installFetchStub({ bodies: registry });
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    expect(screen.getByTestId("model-toggle-c3").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("week-rationale").textContent).toBe(championRationale);
  });

  it("switches to the challenger, relabels, and remembers the choice", async () => {
    installFetchStub({ bodies: registry });
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    fireEvent.click(screen.getByTestId("model-toggle-c1"));
    await waitFor(() => expect(screen.getByTestId("week-rationale").textContent).toBe("Roll the free transfer"));
    expect(window.localStorage.getItem(MODEL_STORAGE_KEY)).toBe("c1");
  });

  it("opens the challenger from a saved legacy 'challenger' preference, and saves the id instead", async () => {
    installFetchStub({ bodies: registry });
    window.localStorage.setItem(MODEL_STORAGE_KEY, "challenger");
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("week-rationale").textContent).toBe("Roll the free transfer"));
    expect(screen.getByTestId("model-toggle-c1").getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect(window.localStorage.getItem(MODEL_STORAGE_KEY)).toBe("c1"));
  });

  it("opens the challenger from an old ?model=challenger link", async () => {
    installFetchStub({ bodies: registry });
    window.history.replaceState(null, "", "/?model=challenger");
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("week-rationale").textContent).toBe("Roll the free transfer"));
  });

  it("an old ?model=champion link overrides the saved choice and opens the champion", async () => {
    installFetchStub({ bodies: registry });
    window.localStorage.setItem(MODEL_STORAGE_KEY, "c1");
    window.history.replaceState(null, "", "/?model=champion");
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("week-rationale").textContent).toBe(championRationale));
    expect(screen.getByTestId("model-toggle-c3").getAttribute("aria-checked")).toBe("true");
  });

  it("an unknown model opens the champion", async () => {
    installFetchStub({ bodies: registry });
    window.history.replaceState(null, "", "/?model=nonsense");
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("week-rationale").textContent).toBe(championRationale));
  });

  it("degrades to the champion when the challenger's week is missing", async () => {
    installFetchStub({ bodies: { strategies: strategiesFixture } });
    window.localStorage.setItem(MODEL_STORAGE_KEY, "challenger");
    renderApp("/gameweek");
    await waitFor(() => expect(screen.getByTestId("model-toggle")).toBeTruthy());
    expect(screen.queryByTestId("model-toggle-c1")).toBeNull();
    expect(screen.getByTestId("model-toggle-note").textContent).toContain("not published");
    expect(screen.getByTestId("week-rationale").textContent).toBe(championRationale);
  });
});
