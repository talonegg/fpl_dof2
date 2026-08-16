import { describe, expect, it, vi } from "vitest";
import { PUBLISHED_CACHE, WARMED_ARTEFACTS, warmPublishedCache } from "./offline";

/**
 * A minimal Cache Storage double.
 *
 * `add` is the interesting method: the real one fetches and rejects on a non-2xx response, which is
 * how a `week.json` that is not published yet must behave (DL-20). `missing` is the set of names it
 * should reject for.
 */
function fakeCaches({ existing = [], missing = [] }: { existing?: string[]; missing?: string[] } = {}) {
  const stored = new Set(existing);
  const added: string[] = [];
  const opened: string[] = [];
  const cache = {
    match: vi.fn(async (url: string) => (stored.has(url) ? { ok: true } : undefined)),
    add: vi.fn(async (url: string) => {
      if (missing.some((name) => url.endsWith(`/${name}.json`))) {
        throw new TypeError(`Request failed: ${url}`);
      }
      stored.add(url);
      added.push(url);
    }),
  };
  return {
    storage: {
      open: vi.fn(async (name: string) => {
        opened.push(name);
        return cache;
      }),
    } as unknown as CacheStorage,
    cache,
    added,
    opened,
  };
}

const dataBase = "/data/v1";

describe("warmPublishedCache", () => {
  it("caches every eagerly-loaded artefact on a cold cache", async () => {
    const { storage, added, opened } = fakeCaches();

    const result = await warmPublishedCache({ dataBase, cacheStorage: storage });

    expect(opened).toEqual([PUBLISHED_CACHE]);
    expect(result.added).toEqual([...WARMED_ARTEFACTS]);
    expect(result.failed).toEqual([]);
    expect(added).toEqual(WARMED_ARTEFACTS.map((name) => `/data/v1/${name}.json`));
  });

  it("fetches nothing when the cache is already warm", async () => {
    // The second visit must be free. A warm-up that re-fetched every time would add a redundant
    // round of requests to every single load, which is the opposite of the point.
    const { storage, cache } = fakeCaches({
      existing: WARMED_ARTEFACTS.map((name) => `/data/v1/${name}.json`),
    });

    const result = await warmPublishedCache({ dataBase, cacheStorage: storage });

    expect(result.present).toEqual([...WARMED_ARTEFACTS]);
    expect(result.added).toEqual([]);
    expect(cache.add).not.toHaveBeenCalled();
  });

  it("keeps going when an artefact is not published, and does not cache the failure", async () => {
    // Before the first gameweek is scored there is no `week.json` or `plan.json` (DL-20). That must
    // cost those two entries and nothing else — an early return here would leave `players.json`,
    // the largest and most useful artefact, out of the offline cache entirely.
    const { storage } = fakeCaches({ missing: ["week", "plan"] });

    const result = await warmPublishedCache({ dataBase, cacheStorage: storage });

    expect(result.failed).toEqual(["week", "plan"]);
    expect(result.added).toEqual(["meta", "rules", "players", "squad"]);
  });

  it("reports an unsupported environment rather than throwing", async () => {
    // Cache Storage is absent in some private-browsing modes and outside a secure context. The app
    // must load normally there, just without offline support.
    const result = await warmPublishedCache({ dataBase, cacheStorage: undefined });

    expect(result.unsupported).toBe(true);
    expect(result.added).toEqual([]);
  });

  it("survives a Cache Storage that refuses to open", async () => {
    const storage = { open: vi.fn(async () => { throw new Error("denied"); }) } as unknown as CacheStorage;

    await expect(warmPublishedCache({ dataBase, cacheStorage: storage })).resolves.toMatchObject({
      unsupported: true,
    });
  });

  it("honours the base it is given, so a hosted sub-path still caches the right URLs", async () => {
    // The app is served from an unknown path prefix on GitHub Pages (DL-35). Caching absolute
    // `/data/v1/...` URLs there would warm a cache the app never reads from.
    const { storage, added } = fakeCaches();

    await warmPublishedCache({ dataBase: "/fpl-dof/data/v1", cacheStorage: storage, names: ["meta"] });

    expect(added).toEqual(["/fpl-dof/data/v1/meta.json"]);
  });

  it("warms the six eager artefacts and not the lazy ones", () => {
    // `history.json` fully populated is larger than the other six combined (DL-37). If it ever ends
    // up in this list, a first visit pays for it whether or not the reader opens a player page.
    expect([...WARMED_ARTEFACTS]).toEqual(["meta", "rules", "players", "squad", "week", "plan"]);
    expect(WARMED_ARTEFACTS).not.toContain("history");
    expect(WARMED_ARTEFACTS).not.toContain("fixtures");
  });
});
