import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dataStore, mergeAccuracy } from "./store";
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

describe("mergeAccuracy", () => {
  const season = (name: string, kind: "backtest" | "replay" | "prospective", mae: number) => ({
    season: name,
    kind,
    gameweeks: [{ gameweek: 1, phase: kind, mae: { c3: mae } }],
    pooled_mae: { c3: mae },
    missing_models: {},
  });
  const doc = (...seasons: ReturnType<typeof season>[]) => ({ contract_version: 1 as const, metric: "m", seasons });

  it("adds the live season to the checked-in ones, replacing a checked-in copy of it", () => {
    const checkedIn = doc(season("2025/26", "backtest", 1), season("2026/27", "prospective", 9));
    const live = doc(season("2026/27", "prospective", 2));
    expect(mergeAccuracy(checkedIn, live)?.seasons.map((s) => [s.season, s.kind, s.pooled_mae.c3])).toEqual([
      ["2025/26", "backtest", 1],
      ["2026/27", "prospective", 2],
    ]);
  });

  it("keeps whichever half exists", () => {
    const live = doc(season("2026/27", "prospective", 2));
    expect(mergeAccuracy(null, live)).toBe(live);
    expect(mergeAccuracy(live, null)).toBe(live);
    expect(mergeAccuracy(null, null)).toBeNull();
  });
});
