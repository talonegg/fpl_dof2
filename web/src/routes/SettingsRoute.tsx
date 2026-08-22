import { useLeague } from "../components/league/useLeague";
import { useOwnerIdentity } from "../components/settings/identity";
import { pipelineWorkflowUrl } from "../components/settings/dispatch";
import "../components/settings/settings.css";

/**
 * `/settings` — team and league ID entry (E13-S2, E13-S3, FR-40, DL-44).
 *
 * [Invariant 8](../../../CLAUDE.md) means this can never mean "fetch my picks from the browser": the
 * IDs entered here only ever do two things, both against artefacts the pipeline already published —
 * personalise the mini-league view, and compose the copyable inputs for an owner-triggered pipeline
 * run. Nothing entered here is transmitted anywhere; it lives in this browser's `localStorage` only.
 */
export function SettingsRoute() {
  const identity = useOwnerIdentity();
  const { state: league } = useLeague();

  function onTeamIdChange(value: string) {
    identity.setTeamId(value.trim() === "" ? null : Number(value));
  }

  function onLeagueIdChange(value: string) {
    identity.setLeagueId(value.trim() === "" ? null : Number(value));
  }

  const leagueMismatch =
    league.status === "ready" &&
    identity.leagueId !== null &&
    identity.leagueId !== league.league.league.id;

  return (
    <section className="settings" data-testid="settings-view">
      <header>
        <h2>Settings</h2>
        <p className="settings-lede">
          Your FPL team ID and mini-league ID, kept in this browser only. They are public identifiers,
          not secrets — but they are personal, so nothing typed here is ever sent anywhere or written
          to the repository (Invariant 8, Invariant 10).
        </p>
      </header>

      <fieldset className="settings-fieldset">
        <legend>Your identifiers</legend>

        <label className="settings-field">
          <span>FPL team ID</span>
          <input
            type="number"
            inputMode="numeric"
            min={1}
            step={1}
            value={identity.teamId ?? ""}
            placeholder="e.g. 1234567"
            onChange={(event) => onTeamIdChange(event.target.value)}
            data-testid="settings-team-id"
          />
          <span className="settings-hint">
            From the URL <code>/entry/&lt;id&gt;/event/1</code> on the FPL site.
          </span>
        </label>

        <label className="settings-field">
          <span>Mini-league ID</span>
          <input
            type="number"
            inputMode="numeric"
            min={1}
            step={1}
            value={identity.leagueId ?? ""}
            placeholder="e.g. 987654"
            onChange={(event) => onLeagueIdChange(event.target.value)}
            data-testid="settings-league-id"
          />
          <span className="settings-hint">
            From the URL <code>/leagues/&lt;id&gt;/standings/c</code>. Optional.
          </span>
        </label>

        <button
          type="button"
          className="settings-clear"
          onClick={identity.clear}
          disabled={identity.teamId === null && identity.leagueId === null}
          data-testid="settings-clear"
        >
          Clear
        </button>
      </fieldset>

      <section className="settings-fieldset" aria-label="What this personalises">
        <h3>What this changes</h3>
        <ul className="settings-effects">
          <li>
            The mini-league table highlights the row matching your team ID, if it is a member of the
            published league.
          </li>
          <li>The scout table can filter down to the players in the published squad.</li>
        </ul>

        {identity.leagueId !== null && league.status === "absent" && (
          <p className="settings-note" data-testid="settings-league-absent">
            No mini-league has been published yet, so there is nothing to match your league ID
            against.
          </p>
        )}

        {leagueMismatch && (
          <p className="settings-note settings-note-warn" data-testid="settings-league-mismatch">
            The published mini-league is <strong>{league.league.league.name}</strong> (ID{" "}
            {league.league.league.id}), not league {identity.leagueId}. This browser's league ID does
            not match what the pipeline last built — the highlighted rows and comparisons on{" "}
            <code>/league</code> belong to the published league, not the one entered here.
          </p>
        )}
      </section>

      <fieldset className="settings-fieldset">
        <legend>Trigger a run</legend>
        <p className="settings-hint">
          Dispatching a run needs your own GitHub sign-in — no token is stored in this app or ever
          leaves your device (Invariant 10, NFR-13). Open the workflow, choose "Run workflow", and
          paste these in if you want this run to use your IDs rather than the repository's default:
        </p>
        <dl className="settings-copy-list">
          <div>
            <dt>team_id</dt>
            <dd data-testid="settings-copy-team-id">{identity.teamId ?? "— not set —"}</dd>
          </div>
          <div>
            <dt>league_id</dt>
            <dd data-testid="settings-copy-league-id">{identity.leagueId ?? "— not set —"}</dd>
          </div>
        </dl>
        <a
          className="settings-dispatch-link"
          href={pipelineWorkflowUrl()}
          target="_blank"
          rel="noopener noreferrer"
          data-testid="settings-dispatch-link"
        >
          Open the Pipeline workflow on GitHub
        </a>
      </fieldset>
    </section>
  );
}
