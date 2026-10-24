/**
 * The eight sections (R1.4.0 §1, WEB-07), declared once: the top nav, the bottom bar, the section
 * sub-tabs and the route table in `AppRoutes` all read this, so they cannot drift apart. A section's
 * first tab is the section's own path; a section with no tabs is a single view.
 *
 * `/player/:id` and `/settings` are deliberately absent: the player page is reached from Scouting and
 * the squad, Settings from the gear in the header.
 */
export interface NavTab {
  readonly path: string;
  readonly label: string;
}

export interface NavSection {
  readonly path: string;
  readonly label: string;
  /** Short label for narrow viewports, where the full one would wrap. */
  readonly shortLabel: string;
  readonly tabs: readonly NavTab[];
}

export const SECTIONS = [
  { path: "/", label: "Home", shortLabel: "Home", tabs: [] },
  { path: "/league", label: "League", shortLabel: "League", tabs: [] },
  {
    path: "/models",
    label: "Models",
    shortLabel: "Models",
    tabs: [
      { path: "/models", label: "Overview" },
      { path: "/models/season", label: "This season" },
      { path: "/models/2025-26", label: "2025/26" },
    ],
  },
  {
    path: "/review",
    label: "Last gameweek",
    shortLabel: "Last GW",
    tabs: [
      { path: "/review", label: "Latest" },
      { path: "/review/all", label: "All gameweeks" },
    ],
  },
  {
    path: "/gameweek",
    label: "This gameweek",
    shortLabel: "This GW",
    tabs: [
      { path: "/gameweek", label: "Decision" },
      { path: "/gameweek/plan", label: "Plan ahead" },
    ],
  },
  {
    path: "/scout",
    label: "Scouting",
    shortLabel: "Scout",
    tabs: [
      { path: "/scout", label: "Players" },
      { path: "/scout/fixtures", label: "Fixtures" },
    ],
  },
  {
    path: "/analysis",
    label: "Analysis",
    shortLabel: "Analysis",
    tabs: [
      { path: "/analysis", label: "Squad builder" },
      { path: "/analysis/compare", label: "Compare players" },
    ],
  },
  // Last on purpose: it is the page you open when something looks wrong, not one you navigate to in
  // the ordinary run of a gameweek (E7-S6). Home carries its summary.
  { path: "/health", label: "Data health", shortLabel: "Health", tabs: [] },
] as const satisfies readonly NavSection[];

type Section = (typeof SECTIONS)[number];

/** Every path that renders a view: each section, and each of its tabs. */
export type ViewPath = Section["path"] | Section["tabs"][number]["path"];

/** The narrow-screen bottom bar, in its own order (§5 Q3); every other section sits behind "More". */
export const BOTTOM_BAR: readonly Section["path"][] = ["/", "/gameweek", "/review", "/league", "/scout"];

export const BOTTOM_SECTIONS: readonly NavSection[] = BOTTOM_BAR.flatMap((p) => SECTIONS.filter((s) => s.path === p));
export const MORE_SECTIONS: readonly NavSection[] = SECTIONS.filter((s) => !BOTTOM_BAR.includes(s.path));

/** Paths from before the eight sections, kept so no saved link breaks. The query string is carried over. */
export const REDIRECTS: Readonly<Record<string, ViewPath>> = {
  "/log": "/review/all",
  "/squad": "/analysis",
  "/compare": "/analysis/compare",
  "/fixtures": "/scout/fixtures",
  "/history": "/models/2025-26",
};

/** The section a path belongs to: `/` only exactly, every other section by prefix. */
export function sectionOf(pathname: string): NavSection | undefined {
  return SECTIONS.find((s) =>
    s.path === "/" ? pathname === "/" : pathname === s.path || pathname.startsWith(`${s.path}/`),
  );
}

/** A label as a test id, e.g. "Last gameweek" → "last-gameweek". */
export const slug = (label: string) => label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
