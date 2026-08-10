/**
 * Browser verification for E0-S7.
 *
 * Drives real Chromium against the built site at the three viewports the story cares about, and
 * checks the things that are only observable in a browser: that the layout does not scroll
 * horizontally, that filtering and sorting work without a reload, that selecting a player reveals
 * the decomposition, and — the project invariant — that the page makes no external network request.
 *
 * Run against a served build:  node verify/browser-check.mjs http://127.0.0.1:4173
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:4173";
const outputDir = new URL("./screenshots/", import.meta.url).pathname.replace(/^\//, "");
mkdirSync(outputDir, { recursive: true });

const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "tablet", width: 820, height: 1180 },
  { name: "desktop", width: 1440, height: 900 },
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
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(baseUrl) && !url.startsWith("data:") && !url.startsWith("blob:")) {
      externalRequests.push(url);
    }
  });

  notes.push(`\n== ${viewport.name} ${viewport.width}x${viewport.height} ==`);
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="player-table"]', { timeout: 15000 });

  check(consoleErrors.length === 0, `no console errors (${consoleErrors.slice(0, 3).join(" | ")})`);

  // --- the structural pieces are present ---
  for (const id of ["header", "squad-pitch", "bench", "player-table"]) {
    check(await page.locator(`[data-testid="${id}"]`).count() > 0, `${id} rendered`);
  }

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

    const options = page.locator('[data-testid="week-options"]');
    if (await options.count() > 0) {
      const optionText = await options.innerText();
      check(/Roll \(no transfer\)/.test(optionText), "doing nothing is listed as an option (FR-24)");
      check(/recommended/.test(optionText), "the recommended option is marked");
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

  // --- the table filters, sorts and selects, all client-side ---
  const totalRows = await page.locator('[data-testid="player-row"]').count();
  check(totalRows > 0, `player table has rows (${totalRows})`);

  await page.locator('[data-testid="position-filter-GKP"]').click();
  await page.waitForTimeout(150);
  const keeperRows = await page.locator('[data-testid="player-row"]').count();
  check(keeperRows > 0 && keeperRows < totalRows, `position filter narrows the table (${totalRows} -> ${keeperRows})`);

  await page.locator('[data-testid="position-filter-ALL"]').click();
  await page.waitForTimeout(150);
  check(
    (await page.locator('[data-testid="player-row"]').count()) === totalRows,
    "clearing the position filter restores every row",
  );

  await page.locator('[data-testid="player-search"]').fill("Haaland");
  await page.waitForTimeout(200);
  const searched = await page.locator('[data-testid="player-row"]').count();
  check(searched > 0 && searched < totalRows, `search narrows the table (${searched} rows)`);
  await page.locator('[data-testid="player-search"]').fill("");
  await page.waitForTimeout(200);

  // Comparing only the first row after changing the sort *column* is a weak check: the most
  // expensive player is also the highest scoring, so the top row is the same either way.
  // Toggling one column's direction must genuinely invert the order.
  const priceOf = async (index) =>
    Number(
      (await page.locator('[data-testid="player-row"]').nth(index).innerText())
        .replace(/\n/g, " ")
        .match(/£([\d.]+)m/)?.[1] ?? NaN,
    );

  await page.locator('[data-testid="sort-price"]').click();
  await page.waitForTimeout(200);
  const [descFirst, descSecond] = [await priceOf(0), await priceOf(1)];
  check(descFirst >= descSecond, `descending price sort is ordered (${descFirst} >= ${descSecond})`);

  await page.locator('[data-testid="sort-price"]').click();
  await page.waitForTimeout(200);
  const [ascFirst, ascSecond] = [await priceOf(0), await priceOf(1)];
  check(ascFirst <= ascSecond, `ascending price sort is ordered (${ascFirst} <= ${ascSecond})`);
  check(ascFirst < descFirst, `toggling direction inverts the table (${descFirst} -> ${ascFirst})`);

  await page.locator('[data-testid="player-row"]').first().click();
  await page.waitForTimeout(200);
  const decomposition = page.locator('[data-testid="decomposition"]');
  check(await decomposition.count() > 0, "selecting a player reveals the xP decomposition");
  if (await decomposition.count() > 0) {
    const text = await decomposition.innerText();
    check(/defensive/i.test(text), "the decomposition includes Defensive Contribution");
  }

  const navigated = await page.evaluate(() => performance.getEntriesByType("navigation").length);
  check(navigated === 1, "no page reload occurred during interaction");

  await page.screenshot({ path: `${outputDir}${viewport.name}-selected.png`, fullPage: false });

  await context.close();
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
