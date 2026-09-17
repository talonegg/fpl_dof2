import { LogTable } from "../components/log/LogTable";
import { useLog } from "../components/log/useLog";
import "../components/log/log.css";

/**
 * `/log` — the season log (DL-69, E8 §3): what was played, what it scored, what was advised.
 *
 * `log.json` is fetched here rather than by the shell, like `league.json` (DL-40), and for the
 * same reason its absence is a first-class state: it is written only when a team ID is configured
 * and the game has recorded picks for it, so "absent" means "nothing to log yet" (DP-15).
 */
export function LogRoute() {
  const { state, retry } = useLog();

  if (state.status === "loading") {
    return (
      <section className="log-status" data-testid="log-loading">
        <p>Loading the season log…</p>
      </section>
    );
  }

  if (state.status === "absent") {
    return (
      <section className="log-status" data-testid="log-absent">
        <h2>No season log yet</h2>
        <p>
          The log is published once the pipeline knows which team is yours and the game has
          recorded at least one gameweek of picks for it. Until then there is nothing to reconcile.
        </p>
        <p>
          The team ID is a repository variable in CI and a local setting on a workstation; it is
          never committed (DL-44). Once it is set, the first finished gameweek appears here on the
          next run.
        </p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="log-status" data-testid="log-error">
        <h2>The season log could not be loaded</h2>
        <p>{state.message}</p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  }

  return <LogTable log={state.log} />;
}
