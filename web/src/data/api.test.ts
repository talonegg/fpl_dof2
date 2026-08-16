import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchFixtures, fetchLeague, resetTrendCaches } from "./api";

/**
 * How the lazily fetched artefacts decide that something is *absent* rather than *broken*.
 *
 * The case that matters is the one a 404 does not cover: a single-page host answers a missing path
 * with `index.html` and a **200**. `vite dev` and `vite preview` both do it, as does any static host
 * with an SPA fallback configured. Since `league.json` is absent whenever no mini-league is
 * configured — the default — this is the response local development gets every single time, and
 * without the content-type check it surfaces as a JSON parse error on a page that is working
 * perfectly (DP-15).
 */
describe("lazily fetched artefacts", () => {
  afterEach(() => {
    resetTrendCaches();
    vi.unstubAllGlobals();
  });

  function stub(response: Response) {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));
  }

  it("treats a 404 as absent", async () => {
    stub(new Response(null, { status: 404 }));
    await expect(fetchLeague()).resolves.toBeNull();
  });

  it("treats an SPA fallback served as HTML with a 200 as absent, not as a parse failure", async () => {
    stub(
      new Response("<!doctype html><html><body>app shell</body></html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );
    await expect(fetchLeague()).resolves.toBeNull();
  });

  it("still parses a real published artefact", async () => {
    const payload = { contract_version: 1, league: {}, gameweek: null, entries: [] };
    stub(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(fetchLeague()).resolves.toMatchObject({ contract_version: 1 });
  });

  it("still raises a genuine server failure rather than calling it absent", async () => {
    // The check must not turn every non-JSON response into "nothing here" — a 500 is a fault and
    // has to reach the retry path.
    stub(new Response("upstream exploded", { status: 500, headers: { "Content-Type": "text/html" } }));
    await expect(fetchFixtures()).rejects.toThrow(/500/);
  });
});
