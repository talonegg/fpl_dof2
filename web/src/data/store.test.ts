import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dataStore } from "./store";
import { challengerWeek, meta, players, rules, squad, strategiesFixture, week } from "../test/fixtures";

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

describe("loadPublished", () => {
  beforeEach(() => dataStore.reset());
  afterEach(() => vi.unstubAllGlobals());

  it("fetches a challenger's week and plan before the base artefacts have resolved", async () => {
    const held = new Map<string, (r: Response) => void>();
    const requested: string[] = [];
    const bodies: Record<string, unknown> = {
      strategies: strategiesFixture,
      week,
      week_c1: challengerWeek,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const name = String(input).split("/").pop()!.replace(".json", "");
        requested.push(name);
        if (["meta", "rules", "players", "squad"].includes(name)) {
          return new Promise<Response>((resolve) => held.set(name, resolve));
        }
        return Promise.resolve(name in bodies ? json(bodies[name]) : new Response(null, { status: 404 }));
      }),
    );

    const loaded = dataStore.loadPublished();
    await vi.waitFor(() => expect(requested).toContain("week_c1"));
    expect(requested).toContain("plan_c1");
    expect(held.size).toBe(4); // the base artefacts are still pending

    held.get("meta")!(json(meta));
    held.get("rules")!(json(rules));
    held.get("players")!(json(players));
    held.get("squad")!(json(squad));
    const data = await loaded;
    expect(data.weeks.c1).toEqual(challengerWeek);
    expect(data.weeks.c3).toEqual(week);
    expect(data.plans.c1).toBeUndefined(); // 404 means none (DP-15)
  });
});

/**
 * One spelling of each state, for every artefact (WEB-04). The case a 404 does not cover: a
 * single-page host answers a missing path with `index.html` and a **200** (`vite dev`, `vite
 * preview`, any SPA fallback), and `league.json` is absent by default — so without the content-type
 * check local development would see a parse error on a page that is working perfectly (DP-15).
 */
describe("dataStore.get", () => {
  beforeEach(() => dataStore.reset());
  afterEach(() => vi.unstubAllGlobals());

  const stub = (response: Response) => vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));

  it("treats a 404 as absent", async () => {
    stub(new Response(null, { status: 404 }));
    await expect(dataStore.get("league")).resolves.toEqual({ status: "absent" });
  });

  it("treats an SPA fallback served as HTML with a 200 as absent, not as a parse failure", async () => {
    stub(new Response("<!doctype html><html></html>", { status: 200, headers: { "Content-Type": "text/html" } }));
    await expect(dataStore.get("league")).resolves.toEqual({ status: "absent" });
  });

  it("parses a real published artefact", async () => {
    stub(json({ contract_version: 1, league: {}, gameweek: null, entries: [] }));
    await expect(dataStore.get("league")).resolves.toMatchObject({ status: "ready", data: { contract_version: 1 } });
  });

  it("calls JSON that is not the artefact malformed", async () => {
    stub(json({ contract_version: 1, unrelated: true }));
    await expect(dataStore.get("health")).resolves.toEqual({ status: "malformed" });
  });

  it("reports a genuine server failure as an error rather than calling it absent", async () => {
    stub(new Response("upstream exploded", { status: 500, headers: { "Content-Type": "text/html" } }));
    await expect(dataStore.get("fixtures")).resolves.toMatchObject({ status: "error", message: expect.stringMatching(/500/) });
  });

  it("asks again after anything but ready", async () => {
    stub(new Response(null, { status: 404 }));
    await dataStore.get("log");
    stub(json({ contract_version: 1 }));
    await expect(dataStore.get("log")).resolves.toMatchObject({ status: "ready" });
  });
});
