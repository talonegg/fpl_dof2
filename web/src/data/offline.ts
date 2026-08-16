/**
 * Warming the offline cache for the published artefacts (E6-S9, FR-34).
 *
 * **The problem this solves.** The service worker caches `data/v1/*.json` with a network-first
 * strategy, so a reader who has loaded the app once has last-published data available offline. But
 * a service worker does not control the page that registered it until it has activated and claimed
 * it, which happens *after* that page's own fetches have already gone out. On a genuinely first
 * visit the six artefacts are therefore fetched without ever passing through the worker, nothing is
 * written to the runtime cache, and a reader who installs the app and then loses signal gets an
 * empty shell. The failure is invisible in every test that reloads before checking, which is most
 * of them.
 *
 * **The fix.** After the first load resolves, put whatever is missing into the same cache the worker
 * reads. The Cache Storage API is available to the page directly, so this needs no worker to be in
 * control and no message passing — the two sides agree on a cache name and nothing else.
 *
 * **It costs one extra fetch per artefact, once, ever.** Only on a visit where the cache is cold;
 * every later visit finds the entries present and does nothing, and once the worker is in control it
 * keeps them fresh itself. Paying ~50 KiB once to make the first install work offline is the right
 * trade against a reader opening the app on a train and seeing nothing.
 *
 * **Everything here is best-effort.** Cache Storage is absent in some private-browsing modes and the
 * whole API is unavailable outside a secure context; `week.json` and `plan.json` legitimately 404
 * before the season is scored (DL-20). None of that may take the app down, so every failure is
 * swallowed and reported in the return value rather than thrown (DP-15).
 */

/**
 * The runtime cache the service worker writes published artefacts into.
 *
 * `vite.config.ts` imports this constant for its `runtimeCaching` rule, so the name is written once
 * rather than agreed by two files that look nothing alike.
 */
export const PUBLISHED_CACHE = "fpl-dof-published-v1";

/**
 * The artefacts worth having offline: the six the shell loads eagerly (DL-35).
 *
 * `history.json` and `fixtures.json` are deliberately absent. They are lazy by route (DL-37) and
 * `history.json` fully populated is larger than the other six together; warming them would spend the
 * first visit's bandwidth on views the reader may never open. They still cache through the worker
 * once fetched, so a reader who has visited the player page has them offline too.
 */
export const WARMED_ARTEFACTS = ["meta", "rules", "players", "squad", "week", "plan"] as const;

export interface WarmResult {
  /** Artefacts newly written to the cache. */
  added: string[];
  /** Artefacts already present, so not re-fetched. */
  present: string[];
  /** Artefacts that could not be cached — a 404 before the season starts, or a failed request. */
  failed: string[];
  /** Set when the environment has no Cache Storage at all, which is not an error. */
  unsupported?: boolean;
}

export interface WarmOptions {
  /** Base for the published files, e.g. `/data/v1`. Same value `api.ts` fetches from. */
  dataBase: string;
  /** Injected so the unit tests need neither a browser nor a service worker. */
  cacheStorage?: CacheStorage;
  names?: readonly string[];
}

/**
 * Ensure every named artefact is in the published cache, fetching only what is missing.
 *
 * Never rejects. The result says what happened, which is what a caller can act on; a thrown error
 * here would propagate into the data-loading path this is deliberately kept out of.
 */
export async function warmPublishedCache({
  dataBase,
  cacheStorage = typeof caches === "undefined" ? undefined : caches,
  names = WARMED_ARTEFACTS,
}: WarmOptions): Promise<WarmResult> {
  const result: WarmResult = { added: [], present: [], failed: [] };
  if (!cacheStorage) return { ...result, unsupported: true };

  let cache: Cache;
  try {
    cache = await cacheStorage.open(PUBLISHED_CACHE);
  } catch {
    return { ...result, unsupported: true };
  }

  for (const name of names) {
    const url = `${dataBase}/${name}.json`;
    try {
      if (await cache.match(url)) {
        result.present.push(name);
        continue;
      }
      // `add` fetches and stores in one step, and rejects on a non-2xx response — which is exactly
      // the behaviour wanted for a `week.json` that is not published yet. A 404 must not be cached:
      // it would outlive the publication that fixes it.
      await cache.add(url);
      result.added.push(name);
    } catch {
      result.failed.push(name);
    }
  }

  return result;
}
