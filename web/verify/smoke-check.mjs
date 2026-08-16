/**
 * Deployed smoke test — E7-S7.
 *
 * Phase 5 of the browser verification, and the only one that runs against a site this project did
 * not serve itself. `browser-check.mjs` answers "is this build correct?" against a local preview;
 * this answers a narrower and different question: **did the thing that is actually deployed come up,
 * and is it serving real data?**
 *
 * It is deliberately a separate script rather than a fifth phase inside `browser-check.mjs`, for
 * two reasons. It runs at a different time — after a deploy, from a workflow that has no build
 * directory — and it must stay fast and dependency-light, because a post-deploy check that takes
 * four minutes is one that gets skipped. It shares the harness's conventions (the same Playwright
 * Chromium of DL-30, the same `check`/`measure` reporting, the same non-zero exit on failure) so the
 * output reads the same and there is one way to run a browser against this app, not two.
 *
 * WHAT IT DOES NOT DO, ON PURPOSE
 *
 * No layout, accessibility, PWA or performance checking — those are phases 1 to 4 and they belong on
 * a build, before it ships. Repeating them here would double the cost of every deploy to re-answer
 * a question that was already answered. This checks liveness and data integrity, which are the only
 * things that can be true locally and false in production.
 *
 * Run against a deployed site:
 *
 *   npm run verify:smoke -- https://<user>.github.io/<repo>/
 *
 * The trailing path matters: GitHub Pages serves a project site under a path prefix, and the app is
 * built with that prefix as its base. Passing the bare origin would check a 404 page.
 */
import { chromium } from "playwright";

const baseUrl = (process.argv[2] ?? "http://127.0.0.1:4173").replace(/\/+$/, "");

/** The contract version this bundle of checks understands. Mirrors `CONTRACT_VERSION` (DP-04). */
const EXPECTED_CONTRACT_VERSION = 1;

/**
 * Artefacts every successful publication writes, so any one of them missing is a real fault.
 *
 * `week.json`, `plan.json` and `league.json` are deliberately absent from this list: each is legitimately
 * missing in a normal published state (DL-20, DL-40), and a smoke test that failed on them would
 * fail every deploy made before the first gameweek is scored.
 */
const REQUIRED_ARTEFACTS = ["meta", "rules", "players", "squad", "fixtures", "history", "health"];

/**
 * Routes that must render their real view, named by the `data-testid` of the component that fills
 * them — the same discriminator phase 1 uses. Checking for "a non-empty body" would pass on an
 * error page, which is exactly the failure a smoke test exists to catch.
 */
const ROUTES = [
  // The dashboard is named by the squad pitch rather than by a wrapper: a pitch that rendered means
  // the shell mounted, the contract loaded, and the artefacts parsed. A wrapper would have rendered
  // regardless of all three.
  ["#/", "squad-pitch", "the dashboard's squad"],
  ["#/scout", "player-table", "the scout table"],
  ["#/squad", "squad-builder", "the squad builder"],
  ["#/fixtures", "fixture-ticker", "the fixture ticker"],
  ["#/health", "health-panel", "the data health page"],
];

const failures = [];
const notes = [];

function check(condition, message) {
  if (condition) {
    notes.push(`  PASS  ${message}`);
  } else {
    failures.push(message);
    notes.push(`  FAIL  ${message}`);
  }
}

function measure(message) {
  notes.push(`  ----  ${message}`);
}

console.log(`\nDeployed smoke test (E7-S7) against ${baseUrl}\n`);

const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();

// Invariant 8: the browser reads published static artefacts and calls no external API. Worth
// re-checking here specifically, because this is the only run against a real host — a stray origin
// that a local preview never exercised would show up here and nowhere else.
const externalRequests = [];
const origin = new URL(baseUrl).origin;
page.on("request", (request) => {
  const url = request.url();
  if (url.startsWith("data:") || url.startsWith("blob:")) return;
  if (!url.startsWith(origin)) externalRequests.push(url);
});

const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(String(error)));

// --- the app shell -----------------------------------------------------------------------------

const started = Date.now();
const response = await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded", timeout: 30000 });
check(response !== null && response.status() < 400, `the site responds (${response?.status()})`);
measure(`shell responded in ${Date.now() - started}ms`);

// The shell is the app, not merely a document: a deploy that serves `index.html` with a broken
// asset path returns 200 and renders nothing, which is the single most likely deploy failure.
let shellRendered = true;
try {
  await page.waitForSelector("#root > *", { timeout: 20000 });
} catch {
  shellRendered = false;
}
check(shellRendered, "the app shell mounts something into #root");

// --- the published data contract ---------------------------------------------------------------

for (const name of REQUIRED_ARTEFACTS) {
  const url = `${baseUrl}/data/v${EXPECTED_CONTRACT_VERSION}/${name}.json`;
  const result = await page.evaluate(async (target) => {
    try {
      const res = await fetch(target);
      const contentType = res.headers.get("content-type") ?? "";
      const text = await res.text();
      let parsed = null;
      let parseError = null;
      try {
        parsed = JSON.parse(text);
      } catch (error) {
        parseError = String(error);
      }
      return {
        status: res.status,
        contentType,
        bytes: text.length,
        version: parsed?.contract_version ?? null,
        parseError,
      };
    } catch (error) {
      return { status: 0, contentType: "", bytes: 0, version: null, parseError: String(error) };
    }
  }, url);

  check(result.status === 200, `${name}.json is served (${result.status})`);
  // A single-page host answers a missing path with `index.html` and a 200 (DL-37's note on
  // `fetchLazy`). Status alone would therefore pass on an artefact that is not deployed at all, so
  // the content type and a successful parse are what actually prove the file is there.
  check(
    result.parseError === null,
    `${name}.json parses as JSON${result.parseError ? ` (${result.parseError})` : ""}`,
  );
  check(
    result.version === EXPECTED_CONTRACT_VERSION,
    `${name}.json declares contract_version ${EXPECTED_CONTRACT_VERSION} (got ${result.version})`,
  );
  measure(`${name}.json ${result.bytes} bytes, ${result.contentType || "no content-type"}`);
}

// --- the routes --------------------------------------------------------------------------------

for (const [hash, testId, description] of ROUTES) {
  await page.evaluate((h) => {
    window.location.hash = h;
  }, hash);
  let rendered = true;
  try {
    await page.waitForSelector(`[data-testid="${testId}"]`, { timeout: 20000 });
  } catch {
    rendered = false;
  }
  check(rendered, `${hash} renders ${description}`);
}

// --- invariants that only a real host can falsify ------------------------------------------------

check(
  externalRequests.length === 0,
  `no external network requests (${externalRequests.slice(0, 3).join(", ") || "none"})`,
);
check(
  pageErrors.length === 0,
  `no uncaught page errors (${pageErrors.slice(0, 2).join(" | ") || "none"})`,
);

await browser.close();

console.log(notes.join("\n"));
if (failures.length > 0) {
  console.log(`\n${failures.length} check(s) FAILED:`);
  for (const failure of failures) console.log(`  - ${failure}`);
  process.exit(1);
}
console.log(`\nAll ${notes.filter((n) => n.includes("PASS")).length} checks passed.\n`);
