import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import { meta, plan, players, rules, squad, week } from "./test/fixtures";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("meta.json")) return Promise.resolve(jsonResponse(meta));
        if (url.endsWith("rules.json")) return Promise.resolve(jsonResponse(rules));
        if (url.endsWith("players.json")) return Promise.resolve(jsonResponse(players));
        if (url.endsWith("squad.json")) return Promise.resolve(jsonResponse(squad));
        if (url.endsWith("week.json")) return Promise.resolve(jsonResponse(week));
        if (url.endsWith("plan.json")) return Promise.resolve(jsonResponse(plan));
        return Promise.reject(new Error(`Unexpected fetch: ${url}`));
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads published data and renders header, squad pitch and player table", async () => {
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("header")).toBeTruthy());

    expect(screen.getByTestId("squad-pitch")).toBeTruthy();
    expect(screen.getByTestId("bench")).toBeTruthy();
    expect(screen.getByTestId("player-table")).toBeTruthy();

    // Quiet model warning for an "informative" price dependence.
    const warning = screen.getByTestId("model-warning");
    expect(warning.className).toContain("model-warning-quiet");
  });
});

describe("App without a weekly recommendation", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("meta.json")) return Promise.resolve(jsonResponse(meta));
        if (url.endsWith("rules.json")) return Promise.resolve(jsonResponse(rules));
        if (url.endsWith("players.json")) return Promise.resolve(jsonResponse(players));
        if (url.endsWith("squad.json")) return Promise.resolve(jsonResponse(squad));
        // 404 is the normal preseason answer, not a failure (DL-20).
        if (url.endsWith("week.json")) return Promise.resolve(new Response(null, { status: 404 }));
        if (url.endsWith("plan.json")) return Promise.resolve(new Response(null, { status: 404 }));
        return Promise.reject(new Error(`Unexpected fetch: ${url}`));
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("still renders the squad when week.json is absent", async () => {
    // DP-15. A missing weekly panel must degrade to no panel, not to an error page — the forecast
    // and the squad are still worth looking at.
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("header")).toBeTruthy());
    expect(screen.getByTestId("squad-pitch")).toBeTruthy();
    expect(screen.queryByTestId("week-deadline")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
