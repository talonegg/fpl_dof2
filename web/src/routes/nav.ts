/**
 * The navigation model, declared once so the nav bar and the route table cannot drift apart.
 * Adding a view means adding an entry here and a `<Route>` with the same path in `AppRoutes`.
 *
 * `/player/:id` and any other parameterised route is deliberately absent: it is reachable from the
 * scout table and the squad, not from the top-level nav.
 */
export interface NavItem {
  path: string;
  label: string;
  /** Short label for narrow viewports, where the full one would wrap. */
  shortLabel: string;
}

export const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Dashboard", shortLabel: "Home" },
  { path: "/scout", label: "Scout", shortLabel: "Scout" },
  { path: "/compare", label: "Compare", shortLabel: "Compare" },
  { path: "/squad", label: "Squad", shortLabel: "Squad" },
  { path: "/fixtures", label: "Fixtures", shortLabel: "Fixtures" },
  { path: "/league", label: "Mini-league", shortLabel: "League" },
];
