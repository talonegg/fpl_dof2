/**
 * Browser verification for E0-S7, extended by E6-S9.
 *
 * Drives real Chromium against the built site and checks the things that are only observable in a
 * browser. It runs in four phases:
 *
 *   1. **Layout and interaction**, at three viewports — no horizontal scroll, filtering and sorting
 *      without a reload, every route resolving, the theme toggle changing real colours.
 *   2. **Accessibility** — keyboard reachability and operability of every control, a visible focus
 *      ring on each, and charts that carry their meaning in text as well as in colour (NFR-14).
 *   3. **Progressive web app** — a valid manifest, a service worker that activates, and the check
 *      that actually matters: the app opening and rendering last-published data with the network
 *      switched off (FR-34).
 *   4. **Performance**, under emulated mobile hardware and throttled 4G — first contentful paint,
 *      initial payload, and the scout table's interaction latency, which is Q-06's measurement
 *      (NFR-04).
 *
 * Run against a served build:  node verify/browser-check.mjs http://127.0.0.1:4173
 */
import { chromium, devices } from "playwright";
import { mkdirSync, readFileSync } from "node:fs";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:4173";
const outputDir = new URL("./screenshots/", import.meta.url).pathname.replace(/^\//, "");
mkdirSync(outputDir, { recursive: true });

const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "tablet", width: 820, height: 1180 },
  { name: "desktop", width: 1440, height: 900 },
];

/**
 * The six artefacts the shell loads eagerly (DL-35). `history.json` and `fixtures.json` are
 * deliberately absent: they are fetched lazily by the routes that need them (DL-37), so a request
 * for one of those during a route sweep is correct behaviour and not a caching regression.
 */
const CORE_ARTEFACTS = ["meta", "rules", "players", "squad", "week", "plan"];

/**
 * Lighthouse's standard mobile throttling profile, which is what "simulated mobile 4G" in NFR-04
 * means in practice. Stated here rather than buried in the call so the numbers this script prints
 * can be read against a named profile.
 */
const MOBILE_4G = {
  offline: false,
  downloadThroughput: (1.6 * 1024 * 1024) / 8, // 1.6 Mbps
  uploadThroughput: (750 * 1024) / 8, // 750 kbps
  latency: 150, // ms RTT
};

/** NFR-04's three budgets. */
const BUDGET = { fcpMs: 2500, payloadBytes: 3 * 1024 * 1024, interactionMs: 150 };

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

/** A measured number worth printing whether or not it passed anything. */
function measure(message) {
  notes.push(`  ----  ${message}`);
}

/** The p-th percentile of a sample, nearest-rank. With ten samples, p95 is the highest. */
function percentile(values, p) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
}

const browser = await chromium.launch();

// Invariant 8: the browser reads published static artefacts and calls no external API.
const externalRequests = [];

for (const viewport of VIEWPORTS) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));
  // Counting requests is how the "load once, cache in memory" claim (DL-35) is checked in a real
  // browser rather than only in jsdom.
  let requestCount = 0;
  /** How many times each published artefact was asked for, by bare name. */
  const artefactRequests = {};
  page.on("request", (request) => {
    requestCount += 1;
    const url = request.url();
    if (!url.startsWith(baseUrl) && !url.startsWith("data:") && !url.startsWith("blob:")) {
      externalRequests.push(url);
    }
    const artefact = /\/data\/v1\/([^/?]+)\.json/.exec(url);
    if (artefact) artefactRequests[artefact[1]] = (artefactRequests[artefact[1]] ?? 0) + 1;
  });

  notes.push(`\n== ${viewport.name} ${viewport.width}x${viewport.height} ==`);
  // The app routes on the hash (DL-35), so the dashboard is the bare URL and every other view is a
  // fragment. Loading the bare URL also checks the default route resolves.
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="squad-pitch"]', { timeout: 15000 });

  check(consoleErrors.length === 0, `no console errors (${consoleErrors.slice(0, 3).join(" | ")})`);

  // --- the shell and the dashboard are present ---
  for (const id of ["app-nav", "header", "squad-pitch", "bench"]) {
    check(await page.locator(`[data-testid="${id}"]`).count() > 0, `${id} rendered`);
  }
  // The scout table lives on its own route now; finding it on the dashboard would mean the route
  // split had not actually happened.
  check(
    (await page.locator('[data-testid="player-table"]').count()) === 0,
    "the scout table is not on the dashboard",
  );

  // --- this week's decision (E1) ---
  // The panel is absent before the first gameweek is scored, which is a valid state (DL-20). What
  // must never happen is a panel that renders *one* deadline: FPL publishes in UK time, the owner
  // is on AEST, and the offset between them changes twice a season on different dates.
  const weekPanel = page.locator('[data-testid="week-deadline"]');
  if (await weekPanel.count() > 0) {
    const deadlineText = await weekPanel.innerText();
    check(/UK/.test(deadlineText), "the deadline is shown in UK time");
    check(/Local/.test(deadlineText), "the deadline is also shown in local time");
    check(/Decide by/.test(deadlineText), "a decide-by time is shown, earlier than the deadline");

    // The two zones must render different weekdays for a Friday-evening UK deadline. A panel that
    // formatted both rows in the same zone would pass a labels-only check and be useless.
    const times = await page.locator('[data-testid="week-deadline"] time').allInnerTexts();
    check(times.length >= 2, `both deadline instants are rendered (${times.length})`);

    // FR-24: doing nothing is a first-class option, not a fallback. Since E6-S6 the dashboard makes
    // that argument in the roll comparison — the recommended move and rolling shown side by side
    // with the margin between them — and the full ranked table sits inside a collapsed `<details>`
    // below it. `textContent` rather than `innerText`, because a collapsed `<details>` renders no
    // text and `innerText` would return "" for a table that is present and correct.
    const roll = page.locator(".dash-roll");
    if ((await roll.count()) > 0) {
      const rollText = await roll.first().evaluate((el) => el.textContent ?? "");
      check(/do nothing|roll/i.test(rollText), "rolling is presented as a first-class option (FR-24)");
      check(/against rolling/i.test(rollText), "the recommendation states its margin over rolling");
      // Which side won is carried by a class, not by the word "recommended" — that word only appears
      // when rolling *is* the recommendation. Exactly one side must be marked either way, or the
      // card shows two options and no answer.
      const chosen = await page.locator(".dash-roll-side-chosen").count();
      check(chosen === 1, `exactly one side of the roll comparison is marked as chosen (${chosen})`);
    }

    const options = page.locator('[data-testid="week-options"]');
    if ((await options.count()) > 0) {
      const rows = await page.locator('[data-testid="week-options"] tbody tr').count();
      const optionText = await options.first().evaluate((el) => el.textContent ?? "");
      check(rows > 0, `the ranked option table has rows (${rows})`);
      check(/roll/i.test(optionText), "rolling appears among the ranked options");
    }

    const state = page.locator('[data-testid="week-state"]');
    if (await state.count() > 0) {
      const stateText = await state.innerText();
      check(/squad (declared|reconstructed|from picks)/.test(stateText), "squad provenance is stated");
    }
  } else {
    notes.push("  (no weekly panel published; skipping its checks)");
  }

  // --- no horizontal page scroll, at any width ---
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }));
  check(
    overflow.scrollWidth <= overflow.clientWidth + 1,
    `page does not scroll horizontally (scrollWidth ${overflow.scrollWidth} vs clientWidth ${overflow.clientWidth})`,
  );

  // --- nothing overflows the viewport, unless it is deliberately inside a scroller ---
  // A wide table inside its own `overflow-x: auto` container is the intended pattern, so an
  // element with a horizontally scrollable ancestor is not an overflow bug. An element that
  // escapes the viewport with no scroller above it is.
  const widest = await page.evaluate((limit) => {
    const inScroller = (element) => {
      for (let node = element.parentElement; node; node = node.parentElement) {
        const overflowX = getComputedStyle(node).overflowX;
        if (overflowX === "auto" || overflowX === "scroll") return true;
      }
      return false;
    };
    let worst = { tag: "none", width: 0 };
    for (const element of document.querySelectorAll("body *")) {
      const rect = element.getBoundingClientRect();
      if (rect.right > limit + 1 && rect.width > worst.width && !inScroller(element)) {
        worst = {
          tag: `${element.tagName.toLowerCase()}.${element.className || "-"}`.slice(0, 60),
          width: Math.round(rect.right),
        };
      }
    }
    return worst;
  }, viewport.width);
  check(widest.width === 0, `nothing escapes the viewport outside a scroller (widest: ${widest.tag} @ ${widest.width}px)`);

  await page.screenshot({ path: `${outputDir}${viewport.name}.png`, fullPage: false });
  await page.screenshot({ path: `${outputDir}${viewport.name}-full.png`, fullPage: true });

  // --- the squad renders a full lineup and a bench ---
  const starters = await page.locator('[data-testid="squad-pitch"] [data-testid="squad-player-card"]').count();
  const bench = await page.locator('[data-testid="bench"] [data-testid="squad-player-card"]').count();
  check(starters === 11, `eleven starters on the pitch (found ${starters})`);
  check(bench === 4, `four substitutes on the bench (found ${bench})`);

  // --- uncertainty is always shown alongside a mean (Invariant 6) ---
  const pitchText = await page.locator('[data-testid="squad-pitch"]').innerText();
  check(pitchText.includes("±"), "expected points are shown with their uncertainty");

  // --- navigation is client-side and reaches the scout view (E6-S1) ---
  await page.locator('[data-testid="nav-scout"]').click();
  await page.waitForSelector('[data-testid="player-table"]', { timeout: 10000 });
  check(true, "the scout route is reachable from the nav");
  check(
    (await page.locator('[data-testid="squad-pitch"]').count()) === 0,
    "leaving the dashboard unmounts its content",
  );

  // --- the scout table filters, sorts and selects, all client-side (E6-S2) ---
  // The table is virtualised, so counting `player-row` elements counts what is *rendered*, not what
  // matched. Every assertion about filtering therefore reads the count line, and the DOM row count
  // is used for the one thing it does measure honestly: that virtualisation is actually happening.
  const matchedCount = async () =>
    Number(
      (await page.locator('[data-testid="scout-count"]').innerText()).match(/Showing ([\d,]+)/)?.[1]
        ?.replace(/,/g, "") ?? NaN,
    );

  const totalRows = await matchedCount();
  const renderedRows = await page.locator('[data-testid="player-row"]').count();
  check(totalRows > 100, `the scout table holds the full player set (${totalRows})`);
  check(renderedRows > 0, `the scout table renders rows (${renderedRows})`);
  // NFR-04: the epic makes virtualisation mandatory, so this is the check that it was not quietly
  // dropped. A naive render would put every matched row in the DOM and these two would be equal.
  check(
    renderedRows < totalRows / 3,
    `only the visible rows are in the DOM (${renderedRows} of ${totalRows})`,
  );

  await page.locator('[data-testid="position-filter-GKP"]').click();
  await page.waitForTimeout(150);
  const keepers = await matchedCount();
  check(keepers > 0 && keepers < totalRows, `position filter narrows the table (${totalRows} -> ${keepers})`);

  await page.locator('[data-testid="position-filter-ALL"]').click();
  await page.waitForTimeout(150);
  check((await matchedCount()) === totalRows, "clearing the position filter restores every row");

  await page.locator('[data-testid="player-search"]').fill("Haaland");
  await page.waitForTimeout(200);
  const searched = await matchedCount();
  check(searched > 0 && searched < totalRows, `search narrows the table (${searched} matched)`);
  await page.locator('[data-testid="player-search"]').fill("");
  await page.waitForTimeout(200);

  // Sorting lives on the header, which only the wide layout has: below 640px the rows are cards
  // (E6-S2), and a header that scrolled sideways off a 390px screen would be worse than none.
  const priceHeader = page.locator('[data-testid="sort-price"]');
  if ((await priceHeader.count()) > 0) {
    // Comparing only the first row after changing the sort *column* is a weak check: the most
    // expensive player is also the highest scoring, so the top row is the same either way.
    // Toggling one column's direction must genuinely invert the order.
    const priceOf = async (index) =>
      Number(
        (await page.locator('[data-testid="player-row"]').nth(index).innerText())
          .replace(/\n/g, " ")
          .match(/£([\d.]+)m/)?.[1] ?? NaN,
      );

    await priceHeader.click();
    await page.waitForTimeout(200);
    const [descFirst, descSecond] = [await priceOf(0), await priceOf(1)];
    check(descFirst >= descSecond, `descending price sort is ordered (${descFirst} >= ${descSecond})`);

    await priceHeader.click();
    await page.waitForTimeout(200);
    const [ascFirst, ascSecond] = [await priceOf(0), await priceOf(1)];
    check(ascFirst <= ascSecond, `ascending price sort is ordered (${ascFirst} <= ${ascSecond})`);
    check(ascFirst < descFirst, `toggling direction inverts the table (${descFirst} -> ${ascFirst})`);
  } else {
    // The card layout has no header, so sorting moves into the controls. It must still be reachable
    // — "sort by any column" is the requirement, not "sort by any column on a laptop".
    notes.push("  (card layout: sorting is a control rather than a header, as designed)");
    const nameOf = async (index) =>
      (await page.locator('[data-testid="player-row"]').nth(index).innerText()).split("\n")[0];
    await page.locator('[data-testid="scout-sort-key"]').selectOption("price");
    await page.waitForTimeout(200);
    const dearest = await nameOf(0);
    await page.locator('[data-testid="scout-sort-direction"]').click();
    await page.waitForTimeout(200);
    const cheapest = await nameOf(0);
    check(dearest !== cheapest, `sorting works from the controls (${dearest} -> ${cheapest})`);
    await page.locator('[data-testid="scout-sort-direction"]').click();
    await page.waitForTimeout(150);
  }

  // Invariant 6, on the surface that shows the forecast to the most players at once.
  const firstRowText = await page.locator('[data-testid="player-row"]').first().innerText();
  check(firstRowText.includes("±"), "scout rows show expected points with their uncertainty");

  // --- multi-select into the comparison view (E6-S2 → E6-S4), handed over in the URL (DL-36) ---
  const checkboxes = page.locator('[data-testid^="compare-"]');
  await checkboxes.nth(0).check();
  check(
    (await page.locator('[data-testid="scout-compare-hint"]').count()) > 0,
    "one player selected is not yet a comparison, and the tray says so",
  );
  await checkboxes.nth(1).check();
  const compareHref = await page.locator('[data-testid="scout-compare-go"]').getAttribute("href");
  check(/#\/compare\?compare=\d+,\d+$/.test(compareHref ?? ""), `the comparison link carries the ids (${compareHref})`);
  await page.locator('[data-testid="scout-compare-clear"]').click();
  await page.waitForTimeout(100);

  // --- saved filter presets survive a reload, because they are the point of saving one ---
  await page.locator('[data-testid="player-search"]').fill("Haaland");
  await page.waitForTimeout(200);
  await page.locator('[data-testid="scout-presets-toggle"]').click();
  await page.locator('[data-testid="scout-preset-name"]').fill("Verification");
  await page.locator('[data-testid="scout-preset-save"]').click();
  await page.waitForTimeout(100);
  await page.locator('[data-testid="player-search"]').fill("");
  await page.waitForTimeout(200);
  await page.locator('[data-testid="scout-preset-apply-Verification"]').click();
  await page.waitForTimeout(200);
  check((await matchedCount()) === searched, "applying a saved preset restores its filters");
  await page.locator('[data-testid="scout-preset-delete-Verification"]').click();
  await page.locator('[data-testid="scout-presets-toggle"]').click();
  await page.locator('[data-testid="player-search"]').fill("");
  await page.waitForTimeout(200);

  await page.locator('[data-testid="player-row"]').first().click();
  await page.waitForTimeout(200);
  const decomposition = page.locator('[data-testid="decomposition"]');
  check(await decomposition.count() > 0, "selecting a player reveals the xP decomposition");
  if (await decomposition.count() > 0) {
    const text = await decomposition.innerText();
    check(/defensive/i.test(text), "the decomposition includes Defensive Contribution");
  }

  // The property DL-35 actually claims is that *navigation* costs nothing, so the count is snapshot
  // here and compared after the sweep. A total count would now fail honestly: on a cold visit the
  // offline warm-up fetches each artefact a second time, by design (`data/offline.ts`).
  const artefactsBeforeSweep = { ...artefactRequests };

  // --- every route in the shell resolves to its real view ---
  // These named the placeholder each story would replace until E6-S4, S7 and S8 landed; they now
  // name the delivered views, so the sweep fails if a route regresses to rendering nothing.
  // `#/compare` with no `?compare=` is the empty state, which is a rendered view and not a fault.
  for (const [hash, testId] of [
    ["#/compare", "compare-empty"],
    ["#/squad", "squad-builder"],
    ["#/fixtures", "fixture-ticker"],
    ["#/player/1", "player-detail"],
    // The data health page (E7-S6). Its test id is asserted like any other view, and for the same
    // reason: it is the page a reader opens when something looks wrong, so a route that regressed
    // to rendering nothing would be discovered at the worst possible moment.
    ["#/health", "health-panel"],
    ["#/no-such-view", "not-found"],
  ]) {
    await page.evaluate((h) => {
      window.location.hash = h;
    }, hash);
    await page.waitForSelector(`[data-testid="${testId}"]`, { timeout: 10000 });
    check(true, `${hash} renders ${testId}`);
  }

  // The caching half of DL-35: a route change is a render, not a network event. Stated as "no core
  // artefact is requested again while sweeping every route", which is the claim. `fixtures.json` is
  // excluded because `#/fixtures` fetching it on arrival is the lazy design of DL-37, not a miss.
  const refetched = CORE_ARTEFACTS.filter(
    (name) => (artefactRequests[name] ?? 0) > (artefactsBeforeSweep[name] ?? 0),
  );
  check(
    refetched.length === 0,
    `visiting every route re-fetches no core artefact (${refetched.join(", ") || "none"})`,
  );

  // On a cold visit each artefact is fetched twice: once by the app, once by the offline warm-up
  // that puts it in the cache the service worker reads (`data/offline.ts`). Twice is the design;
  // more than twice would mean the memoised promise in `published.ts` had stopped working.
  const overFetched = CORE_ARTEFACTS.filter((name) => (artefactRequests[name] ?? 0) > 2);
  check(
    overFetched.length === 0,
    `no core artefact is fetched more than the load plus one cache warm (${overFetched.join(", ") || "none"})`,
  );
  measure(
    `artefact requests: ${Object.entries(artefactRequests)
      .map(([name, count]) => `${name}=${count}`)
      .join(" ")}`,
  );

  // --- theming (E6-S1) ---
  // With no stored preference the root carries no attribute, so the operating system decides.
  await page.evaluate(() => {
    window.location.hash = "#/";
  });
  await page.waitForSelector('[data-testid="squad-pitch"]', { timeout: 10000 });
  check(
    (await page.evaluate(() => document.documentElement.hasAttribute("data-theme"))) === false,
    "with no stored preference the theme follows the system",
  );

  const backgroundNow = () =>
    page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const firstBackground = await backgroundNow();
  await page.locator('[data-testid="theme-toggle"]').click();
  await page.waitForTimeout(100);
  const light = await backgroundNow();
  await page.locator('[data-testid="theme-toggle"]').click();
  await page.waitForTimeout(100);
  const dark = await backgroundNow();
  check(light !== dark, `the theme toggle changes real colours (${light} vs ${dark})`);
  check(
    (await page.evaluate(() => document.documentElement.getAttribute("data-theme"))) === "dark",
    "the manual choice is stamped on the root element",
  );
  check(
    firstBackground === light || firstBackground === dark,
    `the system default resolves to one of the two themes (${firstBackground})`,
  );

  const navigated = await page.evaluate(() => performance.getEntriesByType("navigation").length);
  check(navigated === 1, "no page reload occurred during interaction");

  await page.screenshot({ path: `${outputDir}${viewport.name}-selected.png`, fullPage: false });

  // The stored preference must survive a reload — which is the one place a real reload belongs,
  // and it happens after the no-reload check above.
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="squad-pitch"]', { timeout: 10000 });
  check(
    (await page.evaluate(() => document.documentElement.getAttribute("data-theme"))) === "dark",
    "the theme choice survives a reload",
  );

  await context.close();
}

// =================================================================================================
// Phase 2 — accessibility (NFR-14)
// =================================================================================================
//
// Keyboard operability is checked by actually pressing Tab and Enter, not by inspecting ARIA. A
// control can carry every attribute correctly and still be unreachable, and the only way to find
// that out is to try to reach it.

notes.push("\n== accessibility: keyboard and colour-independence ==");
{
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(baseUrl) && !url.startsWith("data:") && !url.startsWith("blob:")) {
      externalRequests.push(url);
    }
  });

  /**
   * Press Tab `limit` times, describing what holds focus at each step.
   *
   * `:focus-visible` is checked rather than `:focus` because that is the selector `index.css` hangs
   * the ring on, and it is the one that matches a keyboard tab and not a mouse click — so this
   * measures what a keyboard reader actually sees.
   */
  const tabThrough = async (limit) => {
    const seen = [];
    for (let i = 0; i < limit; i += 1) {
      await page.keyboard.press("Tab");
      const described = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const style = getComputedStyle(el);
        const width = Number.parseFloat(style.outlineWidth) || 0;
        return {
          tag: el.tagName.toLowerCase(),
          testId: el.getAttribute("data-testid") ?? "",
          label: (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 40),
          focusVisible: el.matches(":focus-visible"),
          ring: style.outlineStyle !== "none" && width > 0,
          tabIndex: el.tabIndex,
        };
      });
      if (described) seen.push(described);
    }
    return seen;
  };

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="squad-pitch"]', { timeout: 15000 });

  const dashboardStops = await tabThrough(25);
  check(dashboardStops.length > 0, `the dashboard has keyboard-reachable controls (${dashboardStops.length} stops)`);
  check(
    dashboardStops.some((s) => s.testId === "nav-scout"),
    "every nav destination is reachable by Tab",
  );
  check(
    dashboardStops.some((s) => s.testId === "theme-toggle"),
    "the theme toggle is reachable by Tab",
  );

  // The ring is the whole point: a control you can reach but cannot see you have reached is not
  // keyboard accessible. This is the check that catches an `outline: none` added for looks.
  const ringless = dashboardStops.filter((s) => s.focusVisible && !s.ring);
  check(
    ringless.length === 0,
    `every keyboard-focused control shows a focus ring (${ringless.map((s) => s.testId || s.tag).slice(0, 4).join(", ") || "none missing"})`,
  );

  // A positive tabindex takes an element out of document order and reorders the whole page around
  // it. It is almost always a mistake and is invisible until someone tabs.
  const positiveTabIndex = dashboardStops.filter((s) => s.tabIndex > 0);
  check(positiveTabIndex.length === 0, `no control overrides the tab order (${positiveTabIndex.length} with a positive tabindex)`);

  // --- controls must be *operable* from the keyboard, not merely focusable ---
  // The toggle cycles system → light → dark, so a single press can land on a theme that *looks*
  // identical to the one the system had already chosen. Comparing backgrounds after one press would
  // report a working control as broken; the attribute is what the control actually sets.
  await page.locator('[data-testid="theme-toggle"]').focus();
  const themeStops = [];
  for (let i = 0; i < 3; i += 1) {
    await page.keyboard.press("Enter");
    await page.waitForTimeout(120);
    themeStops.push(
      await page.evaluate(() => ({
        theme: document.documentElement.getAttribute("data-theme") ?? "system",
        background: getComputedStyle(document.body).backgroundColor,
      })),
    );
  }
  check(
    new Set(themeStops.map((s) => s.theme)).size > 1,
    `the theme toggle operates from the keyboard (${themeStops.map((s) => s.theme).join(" -> ")})`,
  );
  check(
    new Set(themeStops.map((s) => s.background)).size > 1,
    `keyboard operation changes real colours (${[...new Set(themeStops.map((s) => s.background))].join(" / ")})`,
  );

  // --- the scout view: its filters, search and sort must all be keyboard-driven ---
  await page.evaluate(() => {
    window.location.hash = "#/scout";
  });
  await page.waitForSelector('[data-testid="player-table"]', { timeout: 10000 });
  await page.waitForTimeout(200);

  const matched = async () =>
    Number(
      (await page.locator('[data-testid="scout-count"]').innerText()).match(/Showing ([\d,]+)/)?.[1]
        ?.replace(/,/g, "") ?? NaN,
    );

  const scoutTotal = await matched();
  await page.locator('[data-testid="player-search"]').focus();
  await page.keyboard.type("Salah");
  await page.waitForTimeout(250);
  check((await matched()) < scoutTotal, "the scout search filters from the keyboard");
  await page.locator('[data-testid="player-search"]').fill("");
  await page.waitForTimeout(250);

  const positionFilter = page.locator('[data-testid="position-filter-GKP"]');
  await positionFilter.focus();
  check(await positionFilter.evaluate((el) => el === document.activeElement), "a position filter can take focus");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(200);
  check((await matched()) < scoutTotal, "a position filter operates from the keyboard");
  await page.locator('[data-testid="position-filter-ALL"]').focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(200);

  // Sorting lives on the column header at this width. A header that sorts on click but not on Enter
  // is the single most common keyboard failure in a data table.
  const sortHeader = page.locator('[data-testid="sort-price"]');
  if ((await sortHeader.count()) > 0) {
    const topPrice = async () =>
      (await page.locator('[data-testid="player-row"]').first().innerText()).match(/£([\d.]+)m/)?.[1];
    await sortHeader.focus();
    const focusedHeader = await sortHeader.evaluate((el) => el === document.activeElement);
    check(focusedHeader, "a sort header can take focus");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(250);
    const descending = await topPrice();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(250);
    const ascending = await topPrice();
    check(descending !== ascending, `a sort header toggles from the keyboard (${descending} -> ${ascending})`);
  }

  // --- the squad builder's controls (E6-S7) ---
  await page.evaluate(() => {
    window.location.hash = "#/squad";
  });
  await page.waitForSelector('[data-testid="squad-builder"]', { timeout: 10000 });
  const builderStops = await tabThrough(40);
  check(builderStops.length > 5, `the squad builder is keyboard-navigable (${builderStops.length} stops)`);
  const builderRingless = builderStops.filter((s) => s.focusVisible && !s.ring);
  check(builderRingless.length === 0, `every squad-builder control shows a focus ring (${builderRingless.length} without)`);

  // --- charts carry their meaning in text, not only in colour (NFR-14) ---
  await page.evaluate(() => {
    window.location.hash = "#/player/1";
  });
  await page.waitForSelector('[data-testid="player-detail"]', { timeout: 10000 });
  await page.waitForTimeout(600);

  const chartAudit = await page.evaluate(() => {
    const figures = [...document.querySelectorAll("figure.chart")];
    return figures.map((figure) => {
      const svg = figure.querySelector("svg[role='img']");
      const prose = figure.querySelector(".chart-summary, .chart-readout, .chart-empty");
      return {
        title: figure.querySelector(".chart-title")?.textContent?.trim() ?? "(untitled)",
        named: Boolean(svg?.getAttribute("aria-label")?.trim()) || !svg,
        described: Boolean(prose?.textContent?.trim()),
      };
    });
  });
  check(chartAudit.length > 0, `the player page renders charts to audit (${chartAudit.length})`);
  check(
    chartAudit.every((c) => c.named),
    `every chart has an accessible name (${chartAudit.filter((c) => !c.named).map((c) => c.title).join(", ") || "all named"})`,
  );
  check(
    chartAudit.every((c) => c.described),
    `every chart states in words what it shows (${chartAudit.filter((c) => !c.described).map((c) => c.title).join(", ") || "all described"})`,
  );

  // --- the fixture grid, the one surface where colour is doing real work (E6-S8) ---
  await page.evaluate(() => {
    window.location.hash = "#/fixtures";
  });
  await page.waitForSelector('[data-testid="fixture-ticker"]', { timeout: 10000 });
  await page.waitForTimeout(400);

  // The grid is the one surface where colour does real work, so what matters is that colour is never
  // the *only* carrier. It is not: every cell prints its numeric difficulty (or names its band in
  // words, for a mean or a blank), the on-page legend maps each band to its numeric range, and the
  // full derivation is in the cell's tooltip. Read in greyscale the grid still says everything.
  // The legend's own chips are excluded from the tooltip check — they *are* the explanation.
  const ticker = await page.evaluate(() => {
    const chips = [...document.querySelectorAll(".ticker-chip")];
    const inLegend = (chip) => Boolean(chip.closest(".ticker-legend"));
    const carriesText = (chip) =>
      Boolean(
        chip.querySelector(".ticker-band-label")?.textContent?.trim() ||
          chip.querySelector(".ticker-score")?.textContent?.trim(),
      );
    return {
      total: chips.length,
      legend: chips.filter(inLegend).length,
      textless: chips.filter((chip) => !carriesText(chip)).length,
      untitled: chips.filter((chip) => !inLegend(chip) && !chip.getAttribute("title")?.trim()).length,
      legendBands: document.querySelectorAll(".ticker-legend-item").length,
    };
  });
  check(ticker.total > 0, `the fixture grid renders cells (${ticker.total})`);
  check(
    ticker.textless === 0,
    `every fixture cell carries its difficulty as text, not only as shading (${ticker.textless} with colour alone)`,
  );
  check(
    ticker.untitled === 0,
    `every data cell carries its derivation in a tooltip (${ticker.untitled} without)`,
  );
  check(ticker.legendBands > 0, `the shading is explained on the page by a legend (${ticker.legendBands} bands)`);

  await context.close();
}

// =================================================================================================
// Phase 3 — installable, and genuinely usable offline (FR-34)
// =================================================================================================

notes.push("\n== progressive web app ==");
{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const pwaExternal = [];
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(baseUrl) && !url.startsWith("data:") && !url.startsWith("blob:")) {
      pwaExternal.push(url);
    }
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="squad-pitch"]', { timeout: 15000 });

  // --- the manifest, read the way a browser reads it: from the document's own link ---
  const manifestHref = await page.getAttribute("link[rel='manifest']", "href");
  check(Boolean(manifestHref), `the document links a web app manifest (${manifestHref})`);

  const manifest = await page.evaluate(async (href) => {
    const response = await fetch(href);
    return response.ok ? response.json() : null;
  }, manifestHref);

  check(manifest !== null, "the manifest is fetchable");
  if (manifest) {
    // Chromium's installability criteria, checked one at a time so a failure says which.
    check(Boolean(manifest.name), `the manifest has a name (${manifest.name})`);
    check(Boolean(manifest.short_name), `the manifest has a short_name (${manifest.short_name})`);
    check(Boolean(manifest.start_url), `the manifest has a start_url (${manifest.start_url})`);
    check(
      ["standalone", "fullscreen", "minimal-ui"].includes(manifest.display),
      `the manifest requests an app display mode (${manifest.display})`,
    );
    check(Boolean(manifest.theme_color), `the manifest sets a theme colour (${manifest.theme_color})`);
    check(Boolean(manifest.background_color), `the manifest sets a background colour (${manifest.background_color})`);

    const icons = manifest.icons ?? [];
    const bigEnough = icons.filter((icon) =>
      String(icon.sizes ?? "")
        .split(" ")
        .some((size) => size === "any" || Number.parseInt(size, 10) >= 192),
    );
    check(bigEnough.length > 0, `the manifest has an icon of at least 192px (${icons.length} icons)`);
    check(
      icons.some((icon) => String(icon.purpose ?? "").includes("maskable")),
      "the manifest has a maskable icon, so Android does not frame it twice",
    );

    // Every icon must actually be there. A manifest naming a missing file is installable-looking
    // and produces a blank launcher tile.
    const missing = [];
    for (const icon of icons) {
      const ok = await page.evaluate(async (src) => (await fetch(src)).ok, new URL(icon.src, new URL(manifestHref, baseUrl)).href);
      if (!ok) missing.push(icon.src);
    }
    check(missing.length === 0, `every icon the manifest names exists (${missing.join(", ") || "all present"})`);

    // `index.html` restates two token values as `theme-color` metas because a meta tag cannot read a
    // custom property. This is the check that keeps the restatement honest.
    const tokensCss = readFileSync(new URL("../src/tokens.css", import.meta.url).pathname.replace(/^\//, ""), "utf8");
    const tokenValue = (block, name) => new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block)?.[1];
    const lightBlock = /^:root \{([\s\S]*?)\n\}/m.exec(tokensCss)[1];
    const darkBlock = /^:root\[data-theme="dark"\] \{([\s\S]*?)\n\}/m.exec(tokensCss)[1];
    const metas = await page.evaluate(() =>
      [...document.querySelectorAll("meta[name='theme-color']")].map((m) => ({
        media: m.getAttribute("media") ?? "",
        content: (m.getAttribute("content") ?? "").toLowerCase(),
      })),
    );
    const lightMeta = metas.find((m) => m.media.includes("light"))?.content;
    const darkMeta = metas.find((m) => m.media.includes("dark"))?.content;
    check(
      lightMeta === tokenValue(lightBlock, "--bg"),
      `the light theme-color meta matches --bg (${lightMeta} vs ${tokenValue(lightBlock, "--bg")})`,
    );
    check(
      darkMeta === tokenValue(darkBlock, "--bg"),
      `the dark theme-color meta matches the dark --bg (${darkMeta} vs ${tokenValue(darkBlock, "--bg")})`,
    );
    check(
      manifest.theme_color?.toLowerCase() === tokenValue(lightBlock, "--accent"),
      `the manifest theme colour is the accent token (${manifest.theme_color})`,
    );
  }

  // --- the service worker registers and takes control ---
  const swState = await page.evaluate(async () => {
    if (!("serviceWorker" in navigator)) return "unsupported";
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) return "unregistered";
    const worker = registration.active ?? registration.waiting ?? registration.installing;
    if (!worker) return "no worker";
    if (worker.state === "activated") return "activated";
    await new Promise((resolve) => {
      worker.addEventListener("statechange", () => {
        if (worker.state === "activated") resolve();
      });
      setTimeout(resolve, 8000);
    });
    return worker.state;
  });
  check(swState === "activated", `the service worker activates (${swState})`);

  // Give the runtime cache a moment to store the artefacts the page has already fetched.
  await page.waitForTimeout(1200);

  const cacheReport = await page.evaluate(async () => {
    const names = await caches.keys();
    const report = {};
    for (const name of names) {
      const cache = await caches.open(name);
      report[name] = (await cache.keys()).map((request) => new URL(request.url).pathname);
    }
    return report;
  });
  const allCached = Object.values(cacheReport).flat();
  const cachedArtefacts = CORE_ARTEFACTS.filter((name) =>
    allCached.some((path) => path.endsWith(`/data/v1/${name}.json`)),
  );
  measure(`caches: ${Object.keys(cacheReport).join(", ")}`);
  measure(`published artefacts cached: ${cachedArtefacts.join(", ") || "none"}`);
  // `week.json` and `plan.json` legitimately 404 before the season is scored (DL-20), and a 404 is
  // deliberately not cached — so the requirement is the artefacts that exist, not all six.
  check(cachedArtefacts.length >= 4, `the published artefacts are in the runtime cache (${cachedArtefacts.length})`);

  // --- the check the whole story is for: does it open with no network at all? ---
  await context.setOffline(true);
  const offlinePage = await context.newPage();
  const offlineErrors = [];
  offlinePage.on("pageerror", (error) => offlineErrors.push(String(error)));

  let offlineOpened = true;
  try {
    await offlinePage.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 20000 });
    await offlinePage.waitForSelector('[data-testid="squad-pitch"]', { timeout: 20000 });
  } catch (error) {
    offlineOpened = false;
    notes.push(`  (offline load failed: ${String(error).split("\n")[0]})`);
  }
  check(offlineOpened, "the app opens with the network switched off");

  if (offlineOpened) {
    // Opening is not enough — it has to render the *data*, or the shell has cached an empty app.
    const starters = await offlinePage.locator('[data-testid="squad-pitch"] [data-testid="squad-player-card"]').count();
    check(starters === 11, `offline, the last-published squad still renders (${starters} starters)`);
    check(
      (await offlinePage.locator('[data-testid="app-error"]').count()) === 0,
      "offline, no data-load error is shown",
    );

    const headerText = await offlinePage.locator('[data-testid="header"]').innerText();
    // DP-15: degraded state must be visible. The cached publication announces its own age on every
    // view, so a reader offline for a week is not shown week-old advice as though it were current.
    check(/As at/.test(headerText), "offline, the header still states when the data was published");

    // The scout table is the heaviest view, and the one most likely to have been left on the
    // network. It reads `players.json`, which must have come from the runtime cache.
    await offlinePage.evaluate(() => {
      window.location.hash = "#/scout";
    });
    await offlinePage.waitForSelector('[data-testid="player-table"]', { timeout: 15000 });
    const offlineRows = await offlinePage.locator('[data-testid="player-row"]').count();
    check(offlineRows > 0, `offline, the scout table renders from cache (${offlineRows} rows)`);
    check(offlineErrors.length === 0, `offline, no uncaught page error (${offlineErrors.slice(0, 2).join(" | ")})`);

    await offlinePage.screenshot({ path: `${outputDir}offline.png`, fullPage: false });
  }

  await context.setOffline(false);
  check(pwaExternal.length === 0, `the service worker introduces no external request (${pwaExternal.slice(0, 3).join(", ")})`);
  externalRequests.push(...pwaExternal);

  await context.close();
}

// =================================================================================================
// Phase 4 — performance under emulated mobile hardware and throttled 4G (NFR-04, Q-06)
// =================================================================================================

notes.push("\n== performance: emulated Pixel 5 on throttled 4G ==");
{
  const fcpSamples = [];
  const scoutReadySamples = [];
  let payload = null;

  // Ten cold loads. One sample is an anecdote; the budget is stated as a p95, so it needs a
  // distribution, and each load gets a fresh context so nothing is served from a warm cache.
  for (let run = 0; run < 10; run += 1) {
    const context = await browser.newContext({
      ...devices["Pixel 5"],
      // The service worker would serve the second run from cache and make the numbers a fiction.
      // First paint on a *cold* visit is what the budget is about.
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    const client = await context.newCDPSession(page);
    await client.send("Network.enable");
    await client.send("Network.emulateNetworkConditions", MOBILE_4G);
    // Lighthouse's mobile profile also slows the CPU; a phone is not a desktop with a small screen.
    await client.send("Emulation.setCPUThrottlingRate", { rate: 4 });

    await page.goto(baseUrl, { waitUntil: "load" });
    await page.waitForSelector('[data-testid="squad-pitch"]', { timeout: 60000 });

    const fcp = await page.evaluate(
      () => performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? null,
    );
    if (fcp !== null) fcpSamples.push(fcp);

    // The initial payload: everything the browser actually transferred to reach a usable dashboard.
    // Measured as transfer size, because that is what the connection pays for, and separated into
    // code and data so a miss says which half to fix.
    if (payload === null) {
      payload = await page.evaluate(() => {
        const navigation = performance.getEntriesByType("navigation")[0];
        const resources = performance.getEntriesByType("resource");
        const sum = (entries) => entries.reduce((total, entry) => total + (entry.transferSize || 0), 0);
        const isData = (entry) => entry.name.includes("/data/v1/");
        return {
          document: navigation?.transferSize ?? 0,
          code: sum(resources.filter((entry) => !isData(entry))),
          data: sum(resources.filter(isData)),
          resources: resources.length,
          largest: resources
            .map((entry) => ({ name: entry.name.split("/").pop(), bytes: entry.transferSize || 0 }))
            .sort((a, b) => b.bytes - a.bytes)
            .slice(0, 5),
        };
      });
    }

    // --- Q-06: the scout table, on the same throttled phone ---
    const scoutStart = Date.now();
    await page.evaluate(() => {
      window.location.hash = "#/scout";
    });
    await page.waitForSelector('[data-testid="player-row"]', { timeout: 60000 });
    scoutReadySamples.push(Date.now() - scoutStart);

    // Interaction latency is measured only once — it needs a settled page, and repeating it ten
    // times over a throttled connection buys precision on a number that is not close to its budget.
    if (run === 0) {
      const total = Number(
        (await page.locator('[data-testid="scout-count"]').innerText()).match(/Showing ([\d,]+)/)?.[1]
          ?.replace(/,/g, "") ?? NaN,
      );
      const rendered = await page.locator('[data-testid="player-row"]').count();
      measure(`Q-06: ${total} players published, ${rendered} rows in the DOM on an emulated phone`);
      check(
        rendered < total / 3,
        `Q-06: virtualisation holds on a phone (${rendered} of ${total} rows rendered)`,
      );

      // Filtering is pure client-side work over the whole player array (DL-36). This is the number
      // Q-06 turns on: if plain JSON plus `filter`/`sort` cannot keep an emulated phone under the
      // 150 ms interaction budget, the design bet is wrong and the epic says to record that.
      // Latency is measured in the page, not across the driver: `Date.now()` in Node includes
      // Playwright's own round trip, which on a throttled context is the same order as the thing
      // being measured. Typing a character and waiting for the count line to settle is the closest
      // honest analogue of what a reader feels.
      // `textContent`, not `innerText`, because that is what the in-page comparison below reads and
      // the two differ on whitespace — comparing one against the other would never match.
      const countText = () =>
        page.locator('[data-testid="scout-count"]').evaluate((el) => el.textContent);

      // Each step must be one the table genuinely responds to, or the wait below times out and
      // records the timeout as the latency. Alternating between a term and no term guarantees the
      // count line changes every time, so what is measured is always real work.
      const searchLatency = [];
      const searchSteps = ["salah", "", "sal", "", "s"];
      for (const term of searchSteps) {
        const before = await countText();
        const started = await page.evaluate(() => performance.now());
        await page.locator('[data-testid="player-search"]').fill(term);
        const settled = await page
          .waitForFunction(
            (previous) =>
              document.querySelector('[data-testid="scout-count"]')?.textContent !== previous,
            before,
            { timeout: 5000 },
          )
          .then(() => true)
          .catch(() => false);
        const elapsed = Math.round((await page.evaluate(() => performance.now())) - started);
        searchLatency.push(settled ? elapsed : NaN);
      }
      await page.locator('[data-testid="player-search"]').fill("");
      await page.waitForTimeout(200);

      // Below 640px the rows are cards and sorting is a control rather than a header (E6-S2). The
      // direction toggle is used in both layouts because inverting the order always changes the top
      // row, whereas re-selecting the column already sorted on changes nothing.
      const sortLatency = [];
      const sortHeader = page.locator('[data-testid="sort-price"]');
      const directionToggle = page.locator('[data-testid="scout-sort-direction"]');
      const useHeader = (await sortHeader.count()) > 0;
      measure(`Q-06: sorting via the ${useHeader ? "column header" : "card-layout control"}`);
      const topRow = () =>
        page.locator('[data-testid="player-row"]').first().evaluate((el) => el.textContent);
      for (let i = 0; i < 4; i += 1) {
        const before = await topRow();
        const started = await page.evaluate(() => performance.now());
        await (useHeader ? sortHeader : directionToggle).click();
        const settled = await page
          .waitForFunction(
            (previous) =>
              document.querySelector('[data-testid="player-row"]')?.textContent !== previous,
            before,
            { timeout: 5000 },
          )
          .then(() => true)
          .catch(() => false);
        const elapsed = Math.round((await page.evaluate(() => performance.now())) - started);
        sortLatency.push(settled ? elapsed : NaN);
      }

      // `NaN` marks a step the table never responded to. `Math.max` propagates it and the budget
      // comparison below is false, so an unresponsive table fails rather than quietly scoring well.
      const worstSearch = Math.max(...searchLatency);
      const worstSort = Math.max(...sortLatency);
      const render = (samples) =>
        samples.map((n) => (Number.isNaN(n) ? "no response" : `${n}ms`)).join(", ");
      measure(`Q-06: search latency over ${searchSteps.length} edits — ${render(searchLatency)}`);
      measure(`Q-06: sort latency over ${sortLatency.length} toggles — ${render(sortLatency)}`);
      check(
        worstSearch <= BUDGET.interactionMs,
        `Q-06: search stays inside the ${BUDGET.interactionMs}ms interaction budget (worst ${worstSearch}ms)`,
      );
      check(
        worstSort <= BUDGET.interactionMs,
        `Q-06: sorting stays inside the ${BUDGET.interactionMs}ms interaction budget (worst ${worstSort}ms)`,
      );
    }

    await context.close();
  }

  const p95 = percentile(fcpSamples, 95);
  const median = percentile(fcpSamples, 50);
  measure(`first contentful paint samples (ms): ${fcpSamples.map((n) => Math.round(n)).join(", ")}`);
  measure(`FCP median ${Math.round(median)}ms, p95 ${Math.round(p95)}ms, budget ${BUDGET.fcpMs}ms`);
  check(p95 < BUDGET.fcpMs, `p95 first contentful paint is under ${BUDGET.fcpMs}ms on mobile 4G (${Math.round(p95)}ms)`);

  measure(`scout route ready, p95 ${percentile(scoutReadySamples, 95)}ms (from hash change on a throttled phone)`);

  const kb = (bytes) => `${(bytes / 1024).toFixed(1)} KiB`;
  const initial = payload.document + payload.code + payload.data;
  measure(`initial payload: document ${kb(payload.document)}, code ${kb(payload.code)}, published data ${kb(payload.data)}`);
  measure(`largest resources: ${payload.largest.map((r) => `${r.name} ${kb(r.bytes)}`).join(", ")}`);
  measure(`initial payload total ${kb(initial)} against a ${kb(BUDGET.payloadBytes)} budget`);
  check(
    initial <= BUDGET.payloadBytes,
    `the initial payload is within ${kb(BUDGET.payloadBytes)} (${kb(initial)})`,
  );
}

check(externalRequests.length === 0, `no external network requests (${externalRequests.slice(0, 3).join(", ")})`);

await browser.close();

console.log(notes.join("\n"));
console.log(`\nScreenshots written to ${outputDir}`);
if (failures.length > 0) {
  console.error(`\n${failures.length} CHECK(S) FAILED:`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log("\nAll browser checks passed.");
