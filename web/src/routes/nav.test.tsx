import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import { BOTTOM_SECTIONS, MORE_SECTIONS, REDIRECTS, SECTIONS, slug } from "./nav";
import type { ViewPath } from "./nav";

/** The test id each view renders with the default fixtures: proof the route reached its real view. */
const VIEW_TEST_IDS: Record<ViewPath, string> = {
  "/": "squad-pitch",
  "/league": "league-table",
  "/models": "models-page",
  "/models/season": "models-season-empty", // the default fixtures publish no models.json
  "/models/2025-26": "models-backtest",
  "/review": "gw-selector",
  "/review/all": "log-table",
  "/gameweek": "week-deadline",
  "/gameweek/plan": "plan-timeline",
  "/scout": "player-table",
  "/scout/fixtures": "fixture-ticker",
  "/analysis": "squad-builder",
  "/analysis/compare": "compare-empty",
  "/health": "health-panel",
};

const VIEW_PATHS = SECTIONS.flatMap((s) => [s.path, ...s.tabs.map((t) => t.path)]).filter(
  (p, i, all) => all.indexOf(p) === i,
) as ViewPath[];

describe("the eight-section shell (WEB-07)", () => {
  beforeEach(() => {
    resetAppState();
    installFetchStub();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists the eight sections in the §1 order", () => {
    expect(SECTIONS.map((s) => s.label)).toEqual([
      "Home",
      "League",
      "Models",
      "Last gameweek",
      "This gameweek",
      "Scouting",
      "Analysis",
      "Data health",
    ]);
  });

  it.each(VIEW_PATHS)("renders %s, marked current in the nav and its tabs", async (path) => {
    renderApp(path);
    expect(await screen.findByTestId(VIEW_TEST_IDS[path])).toBeTruthy();
    expect(screen.queryByTestId("not-found")).toBeNull();
    const section = SECTIONS.find((s) => s.path === path || s.tabs.some((t) => t.path === path))!;
    expect(screen.getByTestId(`nav-${slug(section.label)}`).getAttribute("aria-current")).toBe("page");
    if (section.tabs.length > 0) {
      const tabs = screen.getByTestId("section-tabs");
      expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual(section.tabs.map((t) => t.label));
      expect(screen.getByTestId(`tab-${slug(path.slice(1))}`).getAttribute("aria-current")).toBe("page");
    } else {
      expect(screen.queryByTestId("section-tabs")).toBeNull();
    }
  });

  it("moves between a section's tabs by following the tab links", async () => {
    renderApp("/models");
    await screen.findByTestId("models-page");
    fireEvent.click(screen.getByTestId("tab-models-2025-26"));
    expect(await screen.findByTestId("models-backtest")).toBeTruthy();
    expect(screen.queryByTestId("models-page")).toBeNull();
  });

  it.each(Object.entries(REDIRECTS))("sends the old %s to %s", async (from, to) => {
    renderApp(from);
    expect(await screen.findByTestId(VIEW_TEST_IDS[to])).toBeTruthy();
  });

  it("keeps the query string through a redirect", async () => {
    renderApp("/compare?compare=1,2");
    expect(await screen.findByTestId("compare-table")).toBeTruthy();
  });

  it("opens Settings from the gear in the header", async () => {
    renderApp("/");
    await screen.findByTestId("squad-pitch");
    const gear = screen.getByTestId("nav-settings");
    expect(gear.getAttribute("aria-label")).toBe("Settings");
    fireEvent.click(gear);
    expect(await screen.findByTestId("settings-view")).toBeTruthy();
  });
});

describe("the narrow-screen bottom bar (§5 Q3)", () => {
  beforeEach(() => {
    resetAppState();
    installFetchStub();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("holds Home, This gameweek, Last gameweek, League and Scouting, then More", async () => {
    renderApp("/");
    const bar = await screen.findByTestId("bottom-bar");
    expect(BOTTOM_SECTIONS.map((s) => s.label)).toEqual(["Home", "This gameweek", "Last gameweek", "League", "Scouting"]);
    expect(within(bar).getAllByRole("link").slice(0, 5).map((a) => a.getAttribute("href"))).toEqual(
      BOTTOM_SECTIONS.map((s) => s.path),
    );
    expect(MORE_SECTIONS.map((s) => s.label)).toEqual(["Models", "Analysis", "Data health"]);
  });

  it("opens More as a disclosure, focuses its first entry, and closes on Escape back to the button", async () => {
    renderApp("/");
    await screen.findByTestId("bottom-bar");
    const more = screen.getByTestId("bottom-more");
    const menu = screen.getByTestId("bottom-more-menu");
    expect(more.getAttribute("aria-expanded")).toBe("false");
    expect(more.getAttribute("aria-controls")).toBe(menu.id);
    expect(menu.hidden).toBe(true);

    fireEvent.click(more);
    expect(more.getAttribute("aria-expanded")).toBe("true");
    expect(menu.hidden).toBe(false);
    expect(document.activeElement).toBe(screen.getByTestId("more-models"));

    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    expect(menu.hidden).toBe(true);
    expect(document.activeElement).toBe(more);
  });

  it("closes More once an entry is followed, and marks More current inside its sections", async () => {
    renderApp("/");
    await screen.findByTestId("bottom-bar");
    fireEvent.click(screen.getByTestId("bottom-more"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("more-data-health"));
    });
    expect(await screen.findByTestId("health-panel")).toBeTruthy();
    expect(screen.getByTestId("bottom-more-menu").hidden).toBe(true);
    expect(screen.getByTestId("bottom-more").className).toContain("active");
  });
});
