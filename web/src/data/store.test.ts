import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dataStore } from "./store";
import { challengerWeek, meta, players, rules, squad, strategiesFixture, week } from "../test/fixtures";
import { liveGameweek } from "../test/liveFixtures";

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

describe("dataStore.get for live.json (LIVE-04, LIVE-06)", () => {
  beforeEach(() => dataStore.reset());
  afterEach(() => vi.unstubAllGlobals());

  const stub = (response: Response) => vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));

  it("reads the gameweek in play", async () => {
    stub(json(liveGameweek("in_play")));
    await expect(dataStore.get("live")).resolves.toMatchObject({ status: "ready", data: { gameweek: 4, status: "in_play" } });
  });

  it("is absent between gameweeks and preseason, as a 404 or a single-page host's HTML", async () => {
    stub(new Response(null, { status: 404 }));
    await expect(dataStore.get("live")).resolves.toEqual({ status: "absent" });
    dataStore.reset();
    stub(new Response("<!doctype html>", { status: 200, headers: { "Content-Type": "text/html" } }));
    await expect(dataStore.get("live")).resolves.toEqual({ status: "absent" });
  });

  it("calls JSON without the fixtures and teams malformed", async () => {
    stub(json({ contract_version: 1, gameweek: 4 }));
    await expect(dataStore.get("live")).resolves.toEqual({ status: "malformed" });
  });
});

/** The refresh on becoming visible (LIVE-06): what the store does; the views' side is in HomeRoute.test.tsx. */
describe("dataStore.refresh", () => {
  beforeEach(() => dataStore.reset());
  afterEach(() => vi.unstubAllGlobals());

  it("drops what was loaded so the next read asks the network again, and counts the refresh", async () => {
    const fetcher = vi.fn(() => Promise.resolve(json(liveGameweek("in_play"))));
    vi.stubGlobal("fetch", fetcher);
    await dataStore.get("live");
    await dataStore.get("live");
    expect(fetcher).toHaveBeenCalledTimes(1); // cached, as ever

    const before = dataStore.generation();
    dataStore.refresh();
    expect(dataStore.generation()).toBe(before + 1);
    await dataStore.get("live");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("asks the origin to revalidate on a refresh's reads, and leaves first loads plain", async () => {
    const fetcher = vi.fn((..._args: unknown[]) => Promise.resolve(json(liveGameweek("in_play"))));
    vi.stubGlobal("fetch", fetcher);
    await dataStore.get("live");
    expect(fetcher.mock.calls[0][1]).toBeUndefined(); // a first load is a plain fetch

    dataStore.refresh();
    await dataStore.get("live");
    expect(fetcher.mock.calls[1][1]).toEqual({ cache: "no-cache" }); // GitHub Pages serves max-age=600

    dataStore.reset(); // a hard reset starts over: plain again
    await dataStore.get("live");
    expect(fetcher.mock.calls[2][1]).toBeUndefined();
  });

  it("tells subscribers, until they unsubscribe", () => {
    const heard = vi.fn();
    const unsubscribe = dataStore.subscribe(heard);
    dataStore.refresh();
    expect(heard).toHaveBeenCalledTimes(1);
    unsubscribe();
    dataStore.refresh();
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it("asks for nothing by itself: a refresh is a drop, and the reads that follow are the views'", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    dataStore.refresh();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
