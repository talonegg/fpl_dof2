// vitest + jsdom setup. No jest-dom (not an approved dependency) — assertions
// use plain DOM/vitest matchers only.

// This jsdom build exposes a `window.localStorage` that is not a `Storage` — it has no `getItem`,
// `setItem` or `clear`. The theme preference is persisted through that API (E6-S1), so tests need a
// working one. A ten-line in-memory implementation is preferable to mocking the browser API the
// code under test actually calls: the persistence path stays exercised rather than stubbed out.
const storage = window.localStorage as unknown as Partial<Storage> | undefined;
if (typeof storage?.getItem !== "function") {
  const store = new Map<string, string>();
  const memoryStorage: Storage = {
    get length() {
      return store.size;
    },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
  };
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: memoryStorage,
  });
}

// jsdom has no layout engine: every element reports `offsetWidth`/`offsetHeight` of zero. The scout
// table's virtualiser (E6-S2) sizes its window from exactly those two properties, so under jsdom it
// would conclude the viewport is zero pixels tall and render no rows at all — and every assertion
// about the table would then be testing an empty list rather than the component.
//
// Giving the prototype a notional viewport is the smallest honest fix. It says "assume a laptop-sized
// window", which is the same assumption `useMediaQuery` makes when `matchMedia` is absent, so the
// tests exercise the wide layout coherently. Anything genuinely depending on real geometry belongs in
// the Playwright pass (DL-30), not here.
const NOTIONAL_VIEWPORT = { width: 1200, height: 800 };

for (const [property, value] of Object.entries({
  offsetWidth: NOTIONAL_VIEWPORT.width,
  offsetHeight: NOTIONAL_VIEWPORT.height,
})) {
  Object.defineProperty(HTMLElement.prototype, property, {
    configurable: true,
    get() {
      return value;
    },
  });
}

export {};
