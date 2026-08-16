import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { History } from "../../contract/types";
import { players as fixturePlayers } from "../../test/fixtures";
import { resetTrendCaches } from "../../data/api";
import { history, preseasonHistory } from "../player/testFixtures";
import { CompareTrends } from "./CompareTrends";

const [raya, watkins, mbeumo] = fixturePlayers.players;

function installStub(options: { body?: History; missing?: boolean; failing?: boolean } = {}) {
  const spy = vi.fn((input: RequestInfo | URL) => {
    const name = String(input).split("/").pop()?.replace(".json", "") ?? "";
    if (name !== "history") return Promise.reject(new Error(`Unexpected fetch: ${String(input)}`));
    if (options.failing) return Promise.resolve(new Response(null, { status: 500 }));
    if (options.missing) return Promise.resolve(new Response(null, { status: 404 }));
    return Promise.resolve(
      new Response(JSON.stringify(options.body ?? history), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

function renderTrends(players = [raya, watkins]) {
  return render(<CompareTrends players={players} horizonGameweeks={6} />);
}

describe("CompareTrends forecast charts (E6-S5)", () => {
  beforeEach(() => {
    resetTrendCaches();
    installStub();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("charts both forecast horizons with an uncertainty band on every one", async () => {
    renderTrends();
    for (const id of ["compare-chart-xp-next", "compare-chart-xp-horizon"]) {
      const chart = screen.getByTestId(id);
      // Two players, two bands. A forecast chart with no band is the failure E6-S5 names.
      expect(chart.querySelectorAll(".chart-band")).toHaveLength(2);
      expect(chart.querySelectorAll(".chart-band-mean")).toHaveLength(2);
    }
    await waitFor(() => expect(screen.getByTestId("compare-trend-charts")).toBeTruthy());
  });

  it("states the plausible range in words beside every forecast (Invariant 6)", async () => {
    renderTrends();
    const readout = screen.getByTestId("compare-chart-xp-next-readout").textContent ?? "";
    expect(readout).toContain("Raya");
    expect(readout).toContain("plausibly");
    expect(readout).toContain("Watkins");
    await waitFor(() => expect(screen.getByTestId("compare-trend-charts")).toBeTruthy());
  });

  it("names the horizon in the chart title rather than saying 'the horizon'", async () => {
    renderTrends();
    expect(screen.getByTestId("compare-chart-xp-horizon").textContent).toContain(
      "over the next 6 gameweeks",
    );
    await waitFor(() => expect(screen.getByTestId("compare-trend-charts")).toBeTruthy());
  });

  it("separates the forecast from the measured charts in as many words", async () => {
    renderTrends();
    expect(screen.getByTestId("compare-forecast-caveat").textContent).toContain(
      "forecasts, not measurements",
    );
    await waitFor(() => expect(screen.getByTestId("compare-trend-charts")).toBeTruthy());
  });

  it("keeps the forecast charts when the history artefact is absent entirely (DP-15)", async () => {
    installStub({ missing: true });
    renderTrends();
    await waitFor(() => expect(screen.getByTestId("compare-trends-unavailable")).toBeTruthy());
    // The half of the section that needs no fetch must survive the half that does.
    expect(screen.getByTestId("compare-chart-xp-next")).toBeTruthy();
  });

  it("reports a failed history load without taking the section down", async () => {
    installStub({ failing: true });
    renderTrends();
    await waitFor(() =>
      expect(screen.getByTestId("compare-trends-unavailable").textContent).toContain("500"),
    );
    expect(screen.getByTestId("compare-chart-xp-horizon")).toBeTruthy();
  });
});

describe("CompareTrends history overlays", () => {
  beforeEach(() => {
    resetTrendCaches();
    installStub();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("overlays one line per player on the points and minutes charts", async () => {
    renderTrends();
    await waitFor(() => expect(screen.getByTestId("compare-chart-points")).toBeTruthy());

    // Watkins has never featured, so only Raya has a performance line — and that is stated,
    // not silently dropped.
    const points = screen.getByTestId("compare-chart-points");
    expect(points.querySelectorAll("[data-series]")).toHaveLength(1);
    expect(screen.getByTestId("compare-trends-not-featured").textContent).toContain("Watkins");
    expect(screen.getByTestId("compare-chart-minutes")).toBeTruthy();
  });

  it("charts defensive contributions where they were measured", async () => {
    renderTrends();
    await waitFor(() => expect(screen.getByTestId("compare-chart-defensive")).toBeTruthy());
  });

  it("overlays price on a shared date axis, including a player yet to feature", async () => {
    renderTrends();
    await waitFor(() => expect(screen.getByTestId("compare-chart-price")).toBeTruthy());
    // Both players have observed prices even though only one has played.
    expect(screen.getByTestId("compare-chart-price").querySelectorAll("[data-series]")).toHaveLength(
      2,
    );
  });

  it("names a player the published history does not carry", async () => {
    renderTrends([raya, mbeumo]);
    await waitFor(() => expect(screen.getByTestId("compare-trends-absent")).toBeTruthy());
    expect(screen.getByTestId("compare-trends-absent").textContent).toContain("Mbeumo");
  });

  it("treats preseason as a normal state, not an error (DL-20)", async () => {
    installStub({ body: preseasonHistory });
    renderTrends([raya, watkins]);
    await waitFor(() => expect(screen.getByTestId("compare-trends-no-gameweeks")).toBeTruthy());

    expect(screen.getByTestId("compare-trends-no-gameweeks").textContent).toContain(
      "No gameweek has been scored",
    );
    expect(screen.queryByTestId("compare-chart-points")).toBeNull();
    // Prices are observed before the season starts, so that chart still has something to draw.
    expect(screen.getByTestId("compare-chart-price")).toBeTruthy();
  });

  it("says so when nothing has recorded a price yet", async () => {
    installStub({ body: { ...preseasonHistory, players: [{ id: 1, gameweeks: [], prices: [] }] } });
    renderTrends([raya, watkins]);
    await waitFor(() => expect(screen.getByTestId("compare-trends-no-prices")).toBeTruthy());
  });
});
