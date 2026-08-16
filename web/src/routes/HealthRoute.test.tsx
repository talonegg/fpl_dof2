import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import {
  blockedHealth,
  health,
  healthyHealth,
  ungatedHealth,
} from "../components/health/testFixtures";

/**
 * The data health page (E7-S6, FR-33, NFR-07, DL-41).
 *
 * This route carries an obligation the others do not: it is the page opened *because* something
 * looks wrong, so the states worth spending test effort on are the ones where being wrong is
 * invisible (DP-13). Two of them would be actively harmful rather than merely broken:
 *
 * * **an absent gate report rendering as a pass** — the reader concludes the data was checked, and
 *   nothing checked it;
 * * **a degraded or unseen source rendering as healthy** — a feed that quietly stopped being
 *   fetched goes unnoticed for as long as nobody happens to look at the raw manifest.
 *
 * Neither throws. Neither shows up in a type check. Both are asserted below.
 */
describe("HealthRoute", () => {
  beforeEach(() => {
    resetAppState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("populated", () => {
    it("renders the report when the artefact is published", async () => {
      installFetchStub();
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-panel")).toBeTruthy());
      expect(screen.getByTestId("health-sources")).toBeTruthy();
      expect(screen.getByTestId("health-gates")).toBeTruthy();
      expect(screen.getByTestId("health-stages")).toBeTruthy();
    });

    it("shows each stage with its outcome and how long it took", async () => {
      installFetchStub();
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-stage-optimise")).toBeTruthy());
      expect(screen.getByTestId("health-stage-optimise").textContent).toContain("succeeded");
    });

    it("reports the publishing run as published rather than claiming it succeeded", async () => {
      // The run writes this file before recording its own outcome, so its status is null. Reading
      // that as a failure would show a red tile on every successful publication; reading it as a
      // success would be a claim the manifest does not make.
      installFetchStub();
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-panel")).toBeTruthy());
      expect(screen.getByText("Published")).toBeTruthy();
    });

    it("charts the recent runs and names what the diagnostic actually is", async () => {
      installFetchStub();
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-chart-solve")).toBeTruthy());
      expect(screen.getByTestId("health-chart-volume")).toBeTruthy();

      // DP-09/DP-12: `r_squared_on_price` is R-15's price-dependence check, not a measure of skill.
      // Charting it as "model accuracy" would present an unvalidated model as a validated one.
      const dependence = screen.getByTestId("health-chart-dependence");
      expect(dependence.textContent).toContain("diagnostic, not a measure of accuracy");
      expect(dependence.textContent).toContain("model card");
    });

    it("says where the series came from, since the storage behind it is not the contract", async () => {
      installFetchStub();
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-history")).toBeTruthy());
      expect(screen.getByTestId("health-history").textContent).toContain("run-manifests");
    });

    it("shows no degraded banner when every source is reporting", async () => {
      installFetchStub({ bodies: { health: healthyHealth } });
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-panel")).toBeTruthy());
      expect(screen.queryByTestId("health-degraded-banner")).toBeNull();
    });
  });

  describe("degraded sources", () => {
    it("banners the degraded source with the reason and the stage that caught it", async () => {
      installFetchStub();
      renderApp("/health");
      const banner = await screen.findByTestId("health-degraded-banner");
      // The label is data from the artefact, never a name this layer knows (Invariant 1).
      expect(banner.textContent).toContain("beta-feed");
      // DP-09: the flag travels with its derivation. "Degraded" alone is a colour.
      expect(banner.textContent).toContain("HTTPError");
      expect(banner.textContent).toContain("ingest");
    });

    it("never renders a source the run said nothing about as healthy", async () => {
      // "No news" and "good news" are the same pixel if you let them be, and a feed that silently
      // stopped being fetched is exactly what that hides.
      installFetchStub();
      renderApp("/health");
      const row = await screen.findByTestId("health-source-gamma-feed");
      expect(row.textContent).toContain("Not seen");
      expect(row.textContent).not.toContain("OK");
    });

    it("says a degraded run still produced a recommendation, on less evidence", async () => {
      installFetchStub();
      renderApp("/health");
      const banner = await screen.findByTestId("health-degraded-banner");
      expect(banner.textContent).toContain("NFR-15");
    });

    it("shows freshness as an age rather than leaving the reader to subtract dates", async () => {
      installFetchStub();
      renderApp("/health");
      const row = await screen.findByTestId("health-source-alpha-feed");
      expect(row.textContent).toContain("24 min ago");
    });
  });

  describe("no health data, and gates that failed", () => {
    it("never renders a missing gate report as a pass", async () => {
      // The single most dangerous thing this page could get wrong: the reader concludes the data
      // was checked when nothing checked it (DP-13, Invariant 7).
      installFetchStub({ bodies: { health: ungatedHealth } });
      renderApp("/health");
      const gates = await screen.findByTestId("health-gates-absent");
      expect(gates.textContent).toContain("not the same as everything passing");
      expect(screen.getByText("Not reported")).toBeTruthy();
    });

    it("says a blocked publication means the site is serving an earlier run", async () => {
      installFetchStub({ bodies: { health: blockedHealth } });
      renderApp("/health");
      const blocked = await screen.findByTestId("health-gates-blocked");
      expect(blocked.textContent).toContain("player-volume");
      expect(blocked.textContent).toContain("earlier run");
      expect(screen.getByTestId("health-gate-player-volume").textContent).toContain(
        "far below the expected band",
      );
    });

    it("degrades to a stated reason when no history has been published", async () => {
      installFetchStub({ bodies: { health: ungatedHealth } });
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-history-absent")).toBeTruthy());
      expect(screen.queryByTestId("health-chart-solve")).toBeNull();
    });

    it("explains an absent report rather than showing a blank page", async () => {
      installFetchStub({ missing: ["health"] });
      renderApp("/health");
      const absent = await screen.findByTestId("health-absent");
      expect(absent.textContent).toContain("older published data directory");
      expect(screen.queryByTestId("health-panel")).toBeNull();
    });

    it("refuses to render a file that is not this artefact, and says so", async () => {
      // A payload that parses as JSON and is not `Health` would otherwise be handed to the
      // component as a shape the type system believes in, and the page would crash on the first
      // missing field. TypeScript cannot check what came off the network; the guard can (DP-15).
      installFetchStub({ bodies: { health: { hello: "world" } } });
      renderApp("/health");
      const malformed = await screen.findByTestId("health-malformed");
      expect(malformed.textContent).toContain("not the shape this app understands");
      expect(screen.queryByTestId("health-panel")).toBeNull();
    });

    it("survives a truncated report that is missing its source list", async () => {
      installFetchStub({
        bodies: { health: { ...health, sources: undefined } },
      });
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-malformed")).toBeTruthy());
    });

    it("reports a failed load and offers a retry that reaches the network again", async () => {
      installFetchStub({ failing: ["health"] });
      renderApp("/health");
      await waitFor(() => expect(screen.getByTestId("health-error")).toBeTruthy());

      installFetchStub();
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
      await waitFor(() => expect(screen.getByTestId("health-panel")).toBeTruthy());
    });
  });

  describe("provenance", () => {
    it("flags a run made from a dirty working tree as not reproducible", async () => {
      installFetchStub({
        bodies: { health: { ...health, run: { ...health.run, git_dirty: true } } },
      });
      renderApp("/health");
      const note = await screen.findByTestId("health-dirty");
      expect(note.textContent).toContain("cannot be reproduced");
    });
  });
});
