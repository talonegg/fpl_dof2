import type { ReactElement } from "react";
import { HashRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ThemeProvider } from "./theme/ThemeProvider";
import { DataProvider } from "./data/DataProvider";
import { AppLayout } from "./layout/AppLayout";
import { DashboardRoute } from "./routes/DashboardRoute";
import { ScoutRoute } from "./routes/ScoutRoute";
import { PlayerRoute } from "./routes/PlayerRoute";
import { CompareRoute } from "./routes/CompareRoute";
import { SquadRoute } from "./routes/SquadRoute";
import { FixturesRoute } from "./routes/FixturesRoute";
import { LeagueRoute } from "./routes/LeagueRoute";
import { LogRoute } from "./routes/LogRoute";
import { SettingsRoute } from "./routes/SettingsRoute";
import { HealthRoute } from "./routes/HealthRoute";
import { GameweekRoute, PlanAheadRoute } from "./routes/GameweekRoute";
import { NotFoundRoute } from "./routes/NotFoundRoute";
import { HindsightPage, ModelsBacktestPage, ModelsPage, ModelsSeasonPage } from "./components/models/ModelsPage";
import { REDIRECTS } from "./routes/nav";
import type { ViewPath } from "./routes/nav";
import { PasswordGate } from "./gate/PasswordGate";
import { BUILD_PASSWORD_HASH } from "./gate/hash";
import "./App.css";

/**
 * The view behind every section and sub-tab in `routes/nav.ts`. Typed by `ViewPath`, so a path added
 * to the nav without a view here, or a view here with no nav entry, fails the type check.
 */
const VIEWS: Record<ViewPath, ReactElement> = {
  "/": <DashboardRoute />,
  "/league": <LeagueRoute />,
  "/models": <ModelsPage />,
  "/models/season": <ModelsSeasonPage />,
  "/models/2025-26": <ModelsBacktestPage />,
  "/review": <HindsightPage />,
  "/review/all": <LogRoute />,
  "/gameweek": <GameweekRoute />,
  "/gameweek/plan": <PlanAheadRoute />,
  "/scout": <ScoutRoute />,
  "/scout/fixtures": <FixturesRoute />,
  "/analysis": <SquadRoute />,
  "/analysis/compare": <CompareRoute />,
  "/health": <HealthRoute />,
};

/** An old path's new home, keeping its query (`?compare=`, `?model=`) and hash. */
function Redirect({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: to, search, hash }} replace />;
}

/**
 * The route table. Exported separately from `App` so tests (and any future story) can mount it
 * under a `MemoryRouter` at a chosen path without a real browser history.
 *
 * The sections' views come from `VIEWS`, the old paths from `REDIRECTS`; beyond those, only the
 * parameterised player route, Settings (the header's gear) and the catch-all.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {Object.entries(VIEWS).map(([path, element]) => (
          <Route key={path} path={path} element={element} />
        ))}
        {Object.entries(REDIRECTS).map(([path, to]) => (
          <Route key={path} path={path} element={<Redirect to={to} />} />
        ))}
        <Route path="player/:id" element={<PlayerRoute />} />
        <Route path="settings" element={<SettingsRoute />} />
        <Route path="*" element={<NotFoundRoute />} />
      </Route>
    </Routes>
  );
}

/**
 * Application root: theme, then data, then routing.
 *
 * `HashRouter`, not `BrowserRouter` — hosting is GitHub Pages under an unknown path prefix with no
 * server able to rewrite unknown paths onto `index.html`, so a deep-linked or refreshed path route
 * would 404 (DL-35). It also leaves E6-S9 with exactly one document to cache offline.
 *
 * `DataProvider` sits above the router so the published artefacts are loaded once for the whole
 * session and survive every navigation.
 */
export function App() {
  return (
    <ThemeProvider>
      {/* The gate sits above DataProvider: nothing under the data directory is fetched before unlock. */}
      <PasswordGate expectedHash={BUILD_PASSWORD_HASH}>
        <DataProvider>
          <HashRouter
            // Opt in to the v6→v7 behaviour changes. Both are behavioural, not cosmetic, and both are cheap to adopt here.
            future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
          >
            <AppRoutes />
          </HashRouter>
        </DataProvider>
      </PasswordGate>
    </ThemeProvider>
  );
}
