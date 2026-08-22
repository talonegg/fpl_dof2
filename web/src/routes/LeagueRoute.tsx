import { LeagueTable } from "../components/league/LeagueTable";
import { useLeague } from "../components/league/useLeague";
import { useOwnerIdentity } from "../components/settings/identity";
import "../components/league/league.css";

/**
 * `/league` — the mini-league view (E6-S10, FR-32).
 *
 * `league.json` is fetched here rather than by the shell, like `fixtures.json` (DL-37). The
 * difference is what its absence means: every other artefact is written on every run, so a 404 is
 * an older published directory. This one is written **only when a league is configured**, and none
 * is by default — so "absent" is the ordinary state of a working installation, and it gets a real
 * page explaining what configuring one would unlock rather than an apology (DP-15).
 *
 * The team/league ID typed into Settings (E13-S2) is a client-side lens on top of this, not a
 * different fetch — Invariant 8 means the browser still only ever reads what the pipeline already
 * published. When it names a league other than the one published here, that is said plainly rather
 * than silently ignored (DP-09, DP-15, consistent with DL-40's treatment of the absent league).
 */
export function LeagueRoute() {
  const { state, retry } = useLeague();
  const identity = useOwnerIdentity();
  const leagueMismatch =
    state.status === "ready" &&
    identity.leagueId !== null &&
    identity.leagueId !== state.league.league.id;

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

  return (
    <>
      {leagueMismatch && (
        <p className="league-note league-note-warn" data-testid="league-id-mismatch">
          The league ID entered in Settings ({identity.leagueId}) does not match this published
          league, <strong>{state.league.league.name}</strong> (ID {state.league.league.id}). This
          page shows the published league regardless.
        </p>
      )}
      <LeagueTable league={state.league} enteredTeamId={identity.teamId} />
    </>
  );
}
