import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import { meta, players, rules, squad } from "./test/fixtures";

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
