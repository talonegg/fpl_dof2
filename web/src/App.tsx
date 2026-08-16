import { HashRouter, Route, Routes } from "react-router-dom";
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
import { HealthRoute } from "./routes/HealthRoute";
import { NotFoundRoute } from "./routes/NotFoundRoute";
import "./App.css";

/**
 * The route table. Exported separately from `App` so tests (and any future story) can mount it
 * under a `MemoryRouter` at a chosen path without a real browser history.
 *
 * Every path here has a matching entry in `routes/nav.ts`, except the parameterised player route
 * and the catch-all.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardRoute />} />
        <Route path="scout" element={<ScoutRoute />} />
        <Route path="player/:id" element={<PlayerRoute />} />
        <Route path="compare" element={<CompareRoute />} />
        <Route path="squad" element={<SquadRoute />} />
        <Route path="fixtures" element={<FixturesRoute />} />
        <Route path="league" element={<LeagueRoute />} />
        <Route path="health" element={<HealthRoute />} />
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
      <DataProvider>
        <HashRouter
          // Opt in to the v6→v7 behaviour changes now, while there are six routes rather than
          // twelve. Both are behavioural, not cosmetic, and both are cheap to adopt here.
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <AppRoutes />
        </HashRouter>
      </DataProvider>
    </ThemeProvider>
  );
}
