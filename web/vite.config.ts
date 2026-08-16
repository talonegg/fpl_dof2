import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
// The one name the worker and the app must agree on. Imported rather than restated, because two
// files disagreeing about a cache name fails silently: the app warms a cache nothing ever reads.
import { PUBLISHED_CACHE } from "./src/data/offline";

/**
 * Read a colour from `tokens.css`'s light palette.
 *
 * The manifest needs a theme and a background colour, and writing them here as hex literals would
 * put two colours outside the one file allowed to hold them — the exact defect `tokens.css` opens by
 * naming. They are read instead, so a palette change carries the install banner and splash screen
 * with it.
 */
function token(name: string): string {
  const css = readFileSync(resolve(import.meta.dirname, "src/tokens.css"), "utf8");
  const lightRoot = /^:root \{([\s\S]*?)\n\}/m.exec(css);
  if (!lightRoot) throw new Error("tokens.css has no :root block");
  const found = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`).exec(lightRoot[1]);
  if (!found) throw new Error(`tokens.css has no ${name}`);
  return found[1];
}

export default defineConfig({
  base: "./",
  plugins: [
    react(),
    /**
     * The offline half of E6-S9 (FR-34, NFR-14).
     *
     * **Two caches, on purpose, because the shell and the data have opposite obligations.**
     *
     * The *shell* — the HTML document, the hashed JS and CSS, the icons — is precached. Its
     * filenames carry content hashes, so a precached shell is never stale: a new build produces new
     * names and the old entries are evicted on activation.
     *
     * The *published data* is not precached, and must not be. It lives at stable URLs under
     * `data/v1/`, so a precache entry would pin one publication for as long as the bundle lived and
     * the app would confidently show last month's prices. It is `NetworkFirst` instead: online, the
     * reader always gets the newest publication; offline, they get the last one that reached them,
     * which is precisely "offline access to last-published data" and nothing more. The staleness is
     * never silent either — the header renders `meta.generated_at` as "As at …" on every view, so a
     * cached publication announces its own age (DP-15: degraded state is visible).
     *
     * **Invariant 8 is not weakened here.** Every route below matches this origin's own published
     * artefacts; the service worker introduces no request the app was not already making, and no
     * pattern here can match another host.
     */
    VitePWA({
      // A decision-support app must never serve last week's bundle to someone at a deadline, so a
      // new build takes over as soon as it is available rather than waiting for every tab to close.
      registerType: "autoUpdate",
      injectRegister: "auto",
      // No `includeAssets`: the icons live in `public/` and the glob below already precaches every
      // png and svg, so naming them again only puts duplicate entries in the precache manifest.
      manifest: {
        name: "FPL DOF — Fantasy Premier League decision support",
        short_name: "FPL DOF",
        description:
          "Expected points, squad decisions and fixture difficulty for the 2026/27 season, " +
          "from published static artefacts.",
        lang: "en-GB",
        // Relative, because hosting is GitHub Pages under an unknown path prefix (DL-35) and an
        // absolute "/" would scope the worker to the domain root the app does not own.
        start_url: "./",
        scope: "./",
        display: "standalone",
        orientation: "any",
        theme_color: token("--accent"),
        background_color: token("--bg"),
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          {
            src: "icons/icon-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
          { src: "icons/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
        ],
      },
      workbox: {
        // Note the absence of `json`: the published artefacts are handled at runtime below, and
        // precaching them is the failure this configuration exists to avoid.
        globPatterns: ["**/*.{js,css,html,svg,png,ico,woff2}"],
        // One document to serve, because the app routes on the hash (DL-35). Every route is that
        // same document, so an offline deep link resolves without a server rewrite.
        navigateFallback: "index.html",
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            urlPattern: /\/data\/v1\/[^/]+\.json$/,
            handler: "NetworkFirst",
            options: {
              cacheName: PUBLISHED_CACHE,
              // Long enough for a slow mobile connection to win, short enough that a reader with no
              // connection is not staring at a spinner before the cache answers.
              networkTimeoutSeconds: 4,
              // Eight artefacts today; the headroom is for the contract growing, not for versions.
              expiration: { maxEntries: 16 },
              // A 404 is a real answer for `week.json` before the season starts (DL-20), but it is
              // not one worth keeping — caching it would outlive the publication that fixes it.
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
      // The worker is a build-time concern only. Enabling it in dev puts a caching layer between the
      // editor and the browser, which is how an afternoon disappears.
      devOptions: { enabled: false },
    }),
  ],
  server: {
    host: true,
    port: 5173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
