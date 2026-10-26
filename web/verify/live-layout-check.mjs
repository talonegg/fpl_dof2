/**
 * Browser check for the live gameweek's tables (LIVE-05, LIVE-06, NFR-03, NFR-14).
 *
 * jsdom has no layout, so "the live points are on screen at 375 px" can only be measured in a real
 * browser. At 320 px, 375 px and 1440 px it checks, for each live table (Home's squad card, a team's
 * page in the league, and the League table itself), that the page does not scroll sideways, that
 * the table needs no sideways scroll inside its own card, and that the cells a reader needs lie
 * inside the scroller's visible box: for a squad table every row's player name and live points
 * (`Pts`); for the League table every row's rank, team name and live total (and its gameweek
 * points and status). The League table is measured twice: with `live.json` (ordered by live total)
 * and with `live.json` withheld (the table's own Total column). It needs a built site published
 * with a `live.json` that holds a figure for the owner and for at least one other team.
 *
 * Run against a served build:  node verify/live-layout-check.mjs http://127.0.0.1:4173
 * Exits non-zero on a failure, so it can gate a workflow; prints every measurement either way.
 */
import { chromium } from "playwright";
import { CONTRACT_VERSION } from "./contract-version.mjs";

const baseUrl = (process.argv[2] ?? "http://127.0.0.1:4173").replace(/\/$/, "");
const UNLOCK_KEY = "fpl-dof:unlocked-hash";
const UNLOCK_HASH =
  process.env.VITE_FPL_PASSWORD_HASH ?? "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824";
const TOLERANCE = 1; // px: sub-pixel layout

const WIDTHS = [320, 375, 1440];

const response = await fetch(`${baseUrl}/data/v${CONTRACT_VERSION}/live.json`).catch(() => null);
const live = response && response.ok ? await response.json().catch(() => null) : null;
if (!live) {
  console.error(`No readable live.json is published at ${baseUrl}; there is no live table to measure.`);
  process.exit(1);
}
const other = live.teams.find((t) => !t.is_owner && t.live);
if (!other) {
  console.error("live.json holds no non-owner team with live figures; cannot measure a team page.");
  process.exit(1);
}

const VIEWS = [
  { name: "Home", hash: "#/", ready: '[data-testid="home-live"]', kind: "squad" },
  { name: "Team page", hash: `#/league/${other.entry_id}`, ready: '[data-testid="league-team-live"] table', kind: "squad" },
  { name: "League table", hash: "#/league", ready: '[data-testid="league-live"]', kind: "league" },
  // live.json withheld: the League table as it is outside a gameweek, with its own Total column.
  { name: "League table, no live.json", hash: "#/league", ready: '[data-testid="league-table"] table', kind: "league", withoutLive: true },
];

// PLAYWRIGHT_CHROMIUM_PATH points at a Chromium that is not in Playwright's own cache (a pre-installed one).
const browser = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {},
);
const failures = [];
const report = (ok, message) => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${message}`);
  if (!ok) failures.push(message);
};

/** Run in the page. Every box is [left, right]; the scroller is the table's own card. */
function measureSquad() {
  const scroller = document.querySelector(".live-scroll");
  const box = scroller.getBoundingClientRect();
  const el = document.documentElement;
  return {
    page: { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth },
    scroller: { left: box.left, right: box.right, scrollWidth: scroller.scrollWidth, clientWidth: scroller.clientWidth },
    rows: [...scroller.querySelectorAll("tbody tr")].map((tr) => {
      const name = tr.querySelector("th[scope=row]").getBoundingClientRect();
      const pts = tr.querySelector("td[data-testid$='-pts']").getBoundingClientRect();
      return { name: [name.left, name.right], pts: [pts.left, pts.right], hidden: pts.width === 0 };
    }),
  };
}

function measureLeague() {
  const scroller = document.querySelector(".league-scroll");
  const box = scroller.getBoundingClientRect();
  const el = document.documentElement;
  const cell = (tr, selector) => {
    const found = tr.querySelector(selector);
    if (!found) return null;
    const r = found.getBoundingClientRect();
    return { box: [r.left, r.right], hidden: r.width === 0 };
  };
  return {
    page: { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth },
    scroller: { left: box.left, right: box.right, scrollWidth: scroller.scrollWidth, clientWidth: scroller.clientWidth },
    headers: [...scroller.querySelectorAll("thead th")].map((th) => th.textContent.trim()),
    rows: [...scroller.querySelectorAll("tbody tr.league-row")].map((tr) => ({
      rank: cell(tr, ".league-rank"),
      team: cell(tr, "a.league-team"),
      total: cell(tr, "td[data-testid^='league-total-']"),
      gw: cell(tr, "td[data-testid^='league-gw-']"),
      status: cell(tr, "td[data-testid^='league-status-']"),
    })),
  };
}

for (const width of WIDTHS) {
  for (const view of VIEWS) {
    console.log(`\n== ${view.name} at ${width}px ==`);
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      deviceScaleFactor: 1,
      // A service worker would answer from its cache and bypass the route below.
      serviceWorkers: "block",
    });
    await context.addInitScript(
      ({ key, hash }) => {
        try {
          window.localStorage.setItem(key, hash);
        } catch {}
      },
      { key: UNLOCK_KEY, hash: UNLOCK_HASH },
    );
    if (view.withoutLive) await context.route("**/live.json", (route) => route.fulfill({ status: 404, body: "not found" }));
    const page = await context.newPage();
    await page.goto(`${baseUrl}/${view.hash}`, { waitUntil: "networkidle" });
    await page.waitForSelector(view.ready, { timeout: 15000 });

    const m = await page.evaluate(view.kind === "league" ? measureLeague : measureSquad);

    const inside = (range) => range[0] >= m.scroller.left - TOLERANCE && range[1] <= m.scroller.right + TOLERANCE;
    console.log(
      `  ----  scroller ${m.scroller.left.toFixed(0)}..${m.scroller.right.toFixed(0)} (content ${m.scroller.scrollWidth}px in ${m.scroller.clientWidth}px)`,
    );
    report(
      m.page.scrollWidth <= m.page.clientWidth + TOLERANCE,
      `the page does not scroll sideways (scrollWidth ${m.page.scrollWidth} vs clientWidth ${m.page.clientWidth})`,
    );
    report(
      m.scroller.scrollWidth <= m.scroller.clientWidth + TOLERANCE,
      `the table needs no sideways scroll inside its card (${m.scroller.scrollWidth} vs ${m.scroller.clientWidth})`,
    );
    if (view.kind === "league") {
      console.log(`  ----  columns: ${m.headers.join(" | ")}`);
      report(m.rows.length >= 2, `the table lists teams (found ${m.rows.length})`);
      for (const [key, label] of [
        ["rank", "rank"],
        ["team", "team name"],
        ["total", view.withoutLive ? "total" : "live total"],
        ["gw", "gameweek points"],
        ["status", "status"],
      ]) {
        const column = m.rows.map((r) => r[key]).filter(Boolean);
        if (column.length === 0) continue;
        const right = Math.max(...column.map((c) => c.box[1]));
        report(
          column.every((c) => !c.hidden && inside(c.box)),
          `every ${label} cell lies inside the card's visible box (rightmost edge ${right.toFixed(0)} vs ${m.scroller.right.toFixed(0)})`,
        );
      }
    } else {
      const worstPts = Math.max(...m.rows.map((r) => r.pts[1]));
      console.log(`  ----  widest Pts right edge ${worstPts.toFixed(0)}`);
      report(m.rows.length === 15, `fifteen players are listed (found ${m.rows.length})`);
      report(m.rows.every((r) => inside(r.name)), "every player name lies inside the scroller's visible box");
      report(m.rows.every((r) => !r.hidden && inside(r.pts)), "every live points cell lies inside the scroller's visible box");
    }
    await context.close();
  }
}

await browser.close();
if (failures.length > 0) {
  console.error(`\n${failures.length} check(s) failed.`);
  process.exit(1);
}
console.log("\nAll live-layout checks passed.");
