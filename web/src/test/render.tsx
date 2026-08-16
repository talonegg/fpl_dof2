import { MemoryRouter } from "react-router-dom";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { AppRoutes } from "../App";
import { ThemeProvider } from "../theme/ThemeProvider";
import { DataProvider } from "../data/DataProvider";
import { resetPublishedDataCache } from "../data/published";
import { resetTrendCaches } from "../data/api";
import { fixtureGrid, leagueTable, meta, plan, players, rules, squad, week } from "./fixtures";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

export interface FetchStubOptions {
  /**
   * Absent artefacts are served as 404, which is the normal preseason answer (DL-20) — and, for
   * the lazily fetched ones, the answer a bundle deployed against older published data gets.
   */
  missing?: Array<"week" | "plan" | "fixtures" | "league">;
  /** Artefacts that should fail outright, for the error path. */
  failing?: Array<
    "meta" | "rules" | "players" | "squad" | "week" | "plan" | "fixtures" | "league"
  >;
  /** Override a body, for the variants a route needs (a preseason league, and so on). */
  bodies?: Record<string, unknown>;
}

/**
 * Stub `fetch` over the published contract and return the spy, so a test can assert how many
 * requests were made — which is how the caching claim in DL-35 is actually checked rather than
 * assumed.
 */
export function installFetchStub(options: FetchStubOptions = {}) {
  const missing = new Set(options.missing ?? []);
  const failing = new Set(options.failing ?? []);
  // `fixtures` is fetched lazily by the ticker rather than eagerly with the other six (DL-37), but
  // it is served from the same stub: a route that fetches it must not fall through to the
  // "unexpected fetch" rejection.
  const bodies: Record<string, unknown> = {
    meta,
    rules,
    players,
    squad,
    week,
    plan,
    fixtures: fixtureGrid,
    // `league.json` is the one artefact whose *absence* is the normal published state — it exists
    // only when a league is configured (E6-S10). It is served here so the populated view has
    // something to render; the absent case is the one a test asks for with `missing: ["league"]`.
    league: leagueTable,
    ...(options.bodies ?? {}),
  };

  const spy = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const name = url.split("/").pop()?.replace(".json", "") ?? "";
    if (failing.has(name as never)) return Promise.resolve(new Response(null, { status: 500 }));
    if (missing.has(name as never)) return Promise.resolve(new Response(null, { status: 404 }));
    if (name in bodies) return Promise.resolve(jsonResponse(bodies[name]));
    return Promise.reject(new Error(`Unexpected fetch: ${url}`));
  });

  vi.stubGlobal("fetch", spy);
  return spy;
}

/** Reset everything that outlives a single test: the data cache and the stored theme. */
export function resetAppState(): void {
  resetPublishedDataCache();
  resetTrendCaches();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
}

/** Render the whole shell at a given route, exactly as `App` does but on an in-memory history. */
export function renderApp(initialPath = "/") {
  return render(
    <ThemeProvider>
      <DataProvider>
        <MemoryRouter
          initialEntries={[initialPath]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <AppRoutes />
        </MemoryRouter>
      </DataProvider>
    </ThemeProvider>,
  );
}
