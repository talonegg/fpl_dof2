import { NavLink, Outlet } from "react-router-dom";
import { useDataState } from "../data/DataProvider";
import { Header } from "../components/Header";
import { ThemeToggle } from "./ThemeToggle";
import { NAV_ITEMS } from "../routes/nav";

/**
 * The persistent shell: brand, navigation, theme control, then the active route.
 *
 * The loading and error states are rendered here, once, rather than in each view — so `useData()`
 * inside a route is unconditional and every view degrades the same way (DP-15). The nav stays on
 * screen in all three states: a failed data load must not strand the reader on a dead page.
 */
export function AppLayout() {
  const { state, reload } = useDataState();

  return (
    <div className="app-shell">
      {/* The brand is the page's `h1` and lives here, not in `Header`: one title per page, and the
          meta banner below is about the run rather than about the app. */}
      <header className="app-topbar" data-testid="app-nav">
        <div className="app-topbar-inner">
          <h1 className="app-nav-brand">FPL DOF</h1>
          <nav className="app-nav" aria-label="Main">
            <ul className="app-nav-links">
              {NAV_ITEMS.map((item) => (
                <li key={item.path}>
                  <NavLink
                    to={item.path}
                    end={item.path === "/"}
                    className={({ isActive }) => `app-nav-link${isActive ? " active" : ""}`}
                    data-testid={`nav-${item.label.toLowerCase()}`}
                  >
                    <span className="app-nav-link-full">{item.label}</span>
                    <span className="app-nav-link-short">{item.shortLabel}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <ThemeToggle />
        </div>
      </header>

      <div className="app">
        {state.status === "loading" && (
          <div className="app-loading" data-testid="app-loading">
            Loading…
          </div>
        )}

        {state.status === "error" && (
          <div className="app-error" role="alert" data-testid="app-error">
            <p>Could not load published data: {state.error}</p>
            <button type="button" onClick={reload} className="app-retry">
              Try again
            </button>
          </div>
        )}

        {state.status === "ready" && (
          <>
            <Header meta={state.data.meta} />
            <main>
              <Outlet />
            </main>
          </>
        )}
      </div>
    </div>
  );
}
