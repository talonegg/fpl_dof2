import { LeagueTable } from "../components/league/LeagueTable";
import { useLeague } from "../components/league/useLeague";
import "../components/league/league.css";

/**
 * `/league` — the mini-league view (E6-S10, FR-32).
 *
 * `league.json` is fetched here rather than by the shell, like `fixtures.json` (DL-37). The
 * difference is what its absence means: every other artefact is written on every run, so a 404 is
 * an older published directory. This one is written **only when a league is configured**, and none
 * is by default — so "absent" is the ordinary state of a working installation, and it gets a real
 * page explaining what configuring one would unlock rather than an apology (DP-15).
 */
export function LeagueRoute() {
  const { state, retry } = useLeague();

  if (state.status === "loading") {
    return (
      <section className="league-status" data-testid="league-loading">
        <p>Loading the mini-league…</p>
      </section>
    );
  }

  if (state.status === "absent") {
    return (
      <section className="league-status" data-testid="league-absent">
        <h2>No mini-league configured</h2>
        <p>
          Nothing is broken: no classic mini-league has been set up, so the pipeline has no
          standings to fetch and publishes no league data at all.
        </p>
        <p>Configuring one adds a view of:</p>
        <ul>
          <li>the league table, and how far behind the leader you are;</li>
          <li>how much of your squad each rival shares;</li>
          <li>
            the players only they hold — what you are exposed to — and the players only you hold;
          </li>
          <li>whether each rival captained someone other than your captain.</li>
        </ul>
        <ol>
          <li>
            Open the league on the FPL site. Its ID is the number in the URL:{" "}
            <code>/leagues/&lt;id&gt;/standings/c</code>.
          </li>
          <li>
            Set <code>entry.league_id</code> in <code>config/local.yaml</code>, alongside your{" "}
            <code>entry.team_id</code> — the comparison is anchored on your own team, so both are
            needed for the overlap columns.
          </li>
          <li>
            Run <code>fpl-dof run</code>. The league appears here on the next publish.
          </li>
        </ol>
        <p>
          Squads can only be read once a gameweek has been scored, so before the first deadline this
          view shows the table alone even with a league configured.
        </p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="league-status" data-testid="league-error">
        <h2>Mini-league</h2>
        <p>The mini-league could not be loaded: {state.message}</p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  }

  return <LeagueTable league={state.league} />;
}
