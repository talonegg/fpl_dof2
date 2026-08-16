import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderApp, resetAppState } from "../../test/render";
import { meta, plan, players, rules, squad, week } from "../../test/fixtures";
import { resetTrendCaches } from "../../data/api";
import { fixtures, history, preseasonHistory, unratedFixtures } from "./testFixtures";

interface StubOptions {
  /** Artefacts served as 404 — a normal answer for the lazy pair (DL-37). */
  missing?: string[];
  /** Artefacts that fail outright. */
  failing?: string[];
  history?: typeof history;
  fixtures?: typeof fixtures;
}

/**
 * A fetch stub that also serves the two lazy artefacts.
 *
 * Local rather than an extension of `src/test/render.tsx`: the shared stub covers the shell's eager
 * load and deliberately rejects anything else, which is a useful assertion for every other suite.
 */
function installStub(options: StubOptions = {}) {
  const missing = new Set(options.missing ?? []);
  const failing = new Set(options.failing ?? []);
  const bodies: Record<string, unknown> = {
    meta,
    rules,
    players,
    squad,
    week,
    plan,
    history: options.history ?? history,
    fixtures: options.fixtures ?? fixtures,
  };

  const spy = vi.fn((input: RequestInfo | URL) => {
    const name = String(input).split("/").pop()?.replace(".json", "") ?? "";
    if (failing.has(name)) return Promise.resolve(new Response(null, { status: 500 }));
    if (missing.has(name)) return Promise.resolve(new Response(null, { status: 404 }));
    if (name in bodies) {
      return Promise.resolve(
        new Response(JSON.stringify(bodies[name]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.reject(new Error(`Unexpected fetch: ${String(input)}`));
  });

  vi.stubGlobal("fetch", spy);
  return spy;
}

/** Raya, id 1: a goalkeeper at Arsenal, the club the fixture grid carries. */
const RAYA = "/player/1";
/** Watkins, id 2: a forward whose club is absent from the grid and who has never featured. */
const WATKINS = "/player/2";

describe("Player detail (E6-S3)", () => {
  beforeEach(() => {
    resetAppState();
    resetTrendCaches();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("the forecast, and its uncertainty", () => {
    it("never shows an expected-points mean without its plausible range (Invariant 6)", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("player-detail")).toBeTruthy());

      // 4.199 ±1.89 → plausibly 0.4 to 8.0.
      const next = screen.getByTestId("xp-next");
      expect(next.textContent).toContain("4.20");
      expect(next.textContent).toContain("plausibly");

      const horizon = screen.getByTestId("xp-horizon");
      expect(horizon.textContent).toContain("plausibly");
    });

    it("leads with the decomposition, because that is the question the page answers", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("decomposition-panel")).toBeTruthy());
      expect(screen.getByTestId("decomposition")).toBeTruthy();
      expect(screen.getByText("Why this number")).toBeTruthy();
    });

    it("frames the start probability in words, not as a bare number", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("minutes-probability")).toBeTruthy());
      const panel = screen.getByTestId("minutes-probability");

      expect(panel.textContent).toContain("93.8%");
      expect(panel.textContent).toContain("19 of every 20");
      // It is a forecast, and says so.
      expect(panel.textContent).toContain("not a team sheet");
    });
  });

  describe("availability", () => {
    it("renders the status through the shared mapping rather than a second one", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("availability")).toBeTruthy());
      expect(screen.getByTestId("availability").textContent).toContain("Available");
    });

    it("says set-piece role is unpublished rather than inventing it", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("set-piece-unpublished")).toBeTruthy());
      expect(screen.getByTestId("set-piece-unpublished").textContent).toContain("not published");
    });
  });

  describe("fixture run", () => {
    it("renders the run, marking the blank and both halves of the double", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("fixture-run")).toBeTruthy());
      const run = screen.getByTestId("fixture-run");

      expect(run.textContent).toContain("BUR");
      expect(run.textContent).toContain("MCI");
      expect(run.textContent).toContain("Blank");
      // The double: both opponents present.
      expect(run.textContent).toContain("EVE");
      expect(run.textContent).toContain("WOL");
    });

    it("bands a favourable fixture and a difficult one differently", async () => {
      installStub();
      const { container } = renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("fixture-run")).toBeTruthy());

      expect(container.querySelector(".fixture-band-very-easy")).toBeTruthy();
      expect(container.querySelector(".fixture-band-very-hard")).toBeTruthy();
    });

    it("says the run in words as well as in colour", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("fixture-run")).toBeTruthy());
      const text = screen.getByTestId("fixture-run").textContent ?? "";

      expect(text).toContain("GW5 to GW8");
      expect(text).toContain("1 double gameweek");
      expect(text).toContain("1 blank");
    });

    it("warns when the difficulty model has rated nothing, rather than showing a rated grid", async () => {
      installStub({ fixtures: unratedFixtures });
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("fixture-run-unrated")).toBeTruthy());
      expect(screen.getByTestId("fixture-run-unrated").textContent).toContain("home advantage");
    });

    it("degrades when the grid does not carry the player's club", async () => {
      installStub();
      renderApp(WATKINS);

      await waitFor(() => expect(screen.getByTestId("fixture-run-missing")).toBeTruthy());
      // The rest of the page is intact.
      expect(screen.getByTestId("decomposition")).toBeTruthy();
    });

    it("degrades when fixtures.json is absent from the published data (DP-15)", async () => {
      installStub({ missing: ["fixtures"] });
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("fixture-run-unavailable")).toBeTruthy());
      expect(screen.getByTestId("decomposition")).toBeTruthy();
      expect(screen.getByTestId("trend-charts")).toBeTruthy();
    });

    it("degrades when fixtures.json fails to load", async () => {
      installStub({ failing: ["fixtures"] });
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("fixture-run-unavailable")).toBeTruthy());
      expect(screen.getByTestId("player-detail")).toBeTruthy();
    });
  });

  describe("trend charts", () => {
    it("charts points, minutes, expected returns, price and ownership", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("trend-charts")).toBeTruthy());

      expect(screen.getByTestId("chart-points")).toBeTruthy();
      expect(screen.getByTestId("chart-minutes")).toBeTruthy();
      expect(screen.getByTestId("chart-attacking")).toBeTruthy();
      expect(screen.getByTestId("chart-defensive")).toBeTruthy();
      expect(screen.getByTestId("chart-price")).toBeTruthy();
      expect(screen.getByTestId("chart-ownership")).toBeTruthy();
    });

    it("states how much of the season has expected-goals data", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("trends-xg-coverage")).toBeTruthy());
      expect(screen.getByTestId("trends-xg-coverage").textContent).toContain(
        "not the same as a nil return",
      );
    });

    it("labels ownership as 'selected by', never as effective ownership (DL-24)", async () => {
      installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("chart-ownership")).toBeTruthy());
      const text = screen.getByTestId("chart-ownership").textContent ?? "";

      expect(text).toContain("Selected by");
      expect(text).toContain("never effective ownership");
    });

    it("gives every chart an accessible name and a written summary", async () => {
      installStub();
      const { container } = renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("chart-points")).toBeTruthy());

      for (const svg of Array.from(container.querySelectorAll(".chart-svg"))) {
        expect(svg.getAttribute("role")).toBe("img");
        expect(svg.getAttribute("aria-label")).toBeTruthy();
      }
    });

    it("says so plainly in preseason, and still charts the price that has been observed", async () => {
      installStub({ history: preseasonHistory });
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("trends-no-gameweeks")).toBeTruthy());

      expect(screen.getByTestId("trends-no-gameweeks").textContent).toContain(
        "No gameweek has been scored",
      );
      // Nothing to plot for returns...
      expect(screen.queryByTestId("chart-points")).toBeNull();
      // ...but the price series exists from the first day the pipeline watched a price.
      expect(screen.getByTestId("chart-price")).toBeTruthy();
      expect(screen.getByTestId("chart-ownership")).toBeTruthy();
    });

    it("distinguishes a player who has not featured from a season that has not started", async () => {
      installStub();
      renderApp(WATKINS);

      await waitFor(() => expect(screen.getByTestId("trends-no-gameweeks")).toBeTruthy());
      expect(screen.getByTestId("trends-no-gameweeks").textContent).toContain("has not featured");
      expect(screen.getByTestId("chart-price")).toBeTruthy();
    });

    it("degrades when history.json is absent from the published data (DP-15)", async () => {
      installStub({ missing: ["history"] });
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("trends-unavailable")).toBeTruthy());
      // The fixture run and the decomposition survive it.
      expect(screen.getByTestId("fixture-run")).toBeTruthy();
      expect(screen.getByTestId("decomposition")).toBeTruthy();
    });

    it("degrades when history.json fails to load", async () => {
      installStub({ failing: ["history"] });
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("trends-unavailable")).toBeTruthy());
      expect(screen.getByTestId("player-detail")).toBeTruthy();
    });

    it("says so when the artefact carries no history for this player", async () => {
      installStub({ history: { ...history, players: [] } });
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("trends-missing")).toBeTruthy());
    });
  });

  describe("caching", () => {
    it("fetches each lazy artefact once, however many panels want it", async () => {
      const spy = installStub();
      renderApp(RAYA);

      await waitFor(() => expect(screen.getByTestId("trend-charts")).toBeTruthy());
      await waitFor(() => expect(screen.getByTestId("fixture-run")).toBeTruthy());

      const urls = spy.mock.calls.map(([input]) => String(input));
      expect(urls.filter((u) => u.endsWith("history.json"))).toHaveLength(1);
      expect(urls.filter((u) => u.endsWith("fixtures.json"))).toHaveLength(1);
    });
  });
});
