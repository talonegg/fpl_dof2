import { Link } from "react-router-dom";
import type { Health, Log, LogGameweek, Models } from "../../contract/types";
import { useData, useModel, useRegistry } from "../../data/DataProvider";
import { currentSquad } from "../../data/effective";
import { MODEL_PARAM } from "../../data/model";
import { modelLabel } from "../../data/registry";
import type { Registry } from "../../data/registry";
import { latestGameweek, pointsIn } from "../../data/season";
import { liveOwner } from "../../data/live";
import { unready, useArtefact } from "../../data/store";
import { formatPoints } from "../../format";
import { gateOutcome, runOutcome, sourceName, troubledSources } from "../health/health";
import { HomeLiveSquad } from "../live/HomeLiveSquad";
import { ProvisionalBadge } from "../models/ProvisionalBadge";
import { AlertsPanel } from "./AlertsPanel";
import { DeadlineCountdown } from "./DeadlineCountdown";
import { rollComparison } from "./roll";
import "./dashboard.css";

/**
 * Home (WEB-08): where am I and what should I do, in the order that changes a decision (E6-S6).
 *
 * The deadline and the alerts first, then the squad, then every model's advice, then the health of
 * the data behind it, then last gameweek's headline. Each part links to the section that owns the
 * detail (`/gameweek`, `/health`, `/review`); Home restates nothing those pages argue. Every part
 * degrades on its own when its artefact is absent (DP-15) and says why.
 */
export function Dashboard() {
  const { week, models } = useData();
  return (
    <div className="dashboard">
      {week && <DeadlineCountdown deadline={week.deadline} />}
      <AlertsPanel alerts={week?.alerts} tone="actionable" />
      <WaitingSources models={models} />
      <HomeSquad />
      <ModelAdvice />
      <HealthSummary />
      <LastGameweekCard />
      <AlertsPanel alerts={week?.alerts} tone="informational" />
    </div>
  );
}

/** Strategies waiting on a source (ORC-07): the reason is the pipeline's own words. */
function WaitingSources({ models }: { models: Models | null }) {
  const registry = useRegistry();
  const latest = latestGameweek(models);
  const waiting = Object.entries(latest?.availability ?? {}).filter(
    ([, a]) => !a.available && (a.sources?.length ?? 0) > 0,
  );
  if (waiting.length === 0) return null;
  return (
    <section
      className="dash-alerts dash-alerts-actionable"
      aria-labelledby="home-waiting-heading"
      data-testid="home-waiting"
    >
      <h2 id="home-waiting-heading" className="dash-alerts-heading">
        Waiting for a source
      </h2>
      <ul className="dash-alert-list">
        {waiting.map(([id, a]) => (
          <li key={id} className="dash-alert dash-alert-warning">
            <span className="dash-alert-tags">
              <span className="dash-alert-severity">warning</span>
              <span className="dash-alert-category">{modelLabel(registry, id)}</span>
            </span>
            <span className="dash-alert-message">
              {a.reason ?? "Waiting"} (waiting for {a.sources?.join(", ")})
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Your squad as it stands, before any model's advice (`currentSquad`): last gameweek's points
 * (history.json, measured) beside next gameweek's xP (a forecast).
 *
 * While a gameweek is in play and `live.json` holds a figure for the owner, the card is that
 * gameweek's instead (`HomeLiveSquad`, LIVE-06); a gameweek in play without one for the owner keeps
 * this card and says why.
 */
function HomeSquad() {
  const { publishedSquad, week, players } = useData();
  const squad = currentSquad(publishedSquad, week, players);
  const { state } = useArtefact("history");
  // The gameweek in play (LIVE-06): when it holds a figure for the owner, the card is the live one.
  const { state: liveState } = useArtefact("live");
  const live = liveState.status === "ready" ? liveState.data : null;
  const history = state.status === "ready" ? state.data : null;
  const lastGw = history && history.gameweeks_played > 0 ? history.gameweeks_played : null;
  const owner = liveOwner(live);
  if (live && owner?.live) return <HomeLiveSquad live={live} owner={owner} figures={owner.live} />;
  const pointsOf = (id: number): string => String(pointsIn(history, id, lastGw) ?? "—");
  // The bench is only named when the XI is known: an unknown lineup is not a bench of fifteen.
  const lineup = squad.players.some((p) => p.starting);
  const ordered = [...squad.players].sort((a, b) => Number(b.starting) - Number(a.starting));

  return (
    <section className="home-card" aria-labelledby="home-squad-heading" data-testid="home-squad">
      <h2 id="home-squad-heading">Your squad</h2>
      {ordered.length === 0 ? (
        <p>No squad is available yet. It appears once the first gameweek has been scored.</p>
      ) : (
        <table className="home-table" aria-labelledby="home-squad-heading">
          <thead>
            <tr>
              <th scope="col">Player</th>
              <th scope="col">{lastGw === null ? "Last GW" : `GW${lastGw}`} pts</th>
              <th scope="col">xP next</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((p) => (
              <tr key={p.player_id} data-testid={`home-squad-${p.player_id}`}>
                <th scope="row">
                  {p.web_name}{" "}
                  <span className="home-sub">
                    {p.team} {p.position}
                    {p.is_captain && " · captain"}
                    {p.is_vice_captain && " · vice"}
                    {lineup && !p.starting && " · bench"}
                  </span>
                </th>
                <td>{pointsOf(p.player_id)}</td>
                <td>{formatPoints(p.xp_next)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {live && owner && !owner.live && (
        <p className="home-sub" data-testid="home-live-not-live">
          Gameweek {live.gameweek} is in play, but there is no live figure for your team
          {owner.reason ? `: ${owner.reason}` : ""}. This is your squad as last published.
        </p>
      )}
      {(liveState.status === "error" || liveState.status === "malformed") && (
        <p className="home-sub" data-testid="home-live-unavailable">
          The live gameweek could not be read, so this is your squad as at the last finished gameweek.
        </p>
      )}
      {lastGw === null && (
        <p className="home-sub" data-testid="home-squad-no-points">
          {unready(state, "No player history is published yet") ?? "No gameweek has been scored yet"},
          so there are no points last gameweek to show.
        </p>
      )}
    </section>
  );
}

/** Each model's advice for the latest gameweek, expected points beside the roll, linked to This gameweek. */
function ModelAdvice() {
  const { models, weeks } = useData();
  const registry = useRegistry();
  const { available, setModel } = useModel();
  const latest = latestGameweek(models);
  const shown = (models?.models ?? []).filter((m) => m.role !== "retired");

  return (
    <section className="home-card" aria-labelledby="home-models-heading" data-testid="home-models">
      <h2 id="home-models-heading">What each model advises</h2>
      {!models || shown.length === 0 ? (
        <p>No model comparison is published yet. It appears once a model has recorded advice.</p>
      ) : (
        <ul className="home-list">
          {shown.map((m) => {
            const avail = latest?.availability?.[m.id];
            const advice = latest?.advice?.[m.id];
            const unavailable = avail ? !avail.available : !m.available;
            const rec = weeks[m.id]?.recommendation;
            const roll = rec ? rollComparison(rec).rollNet : undefined;
            const moves = advice?.transfers.map((t) => `${t.out_name} → ${t.in_name}`).join(", ");
            return (
              <li key={m.id} data-testid={`home-model-${m.id}`}>
                <h3>
                  {modelLabel(registry, m.id)}
                  {latest?.provisional && advice && (
                    <>
                      {" "}
                      <ProvisionalBadge testId={`home-provisional-${m.id}`} />
                    </>
                  )}
                </h3>
                {unavailable || !advice ? (
                  <p>
                    Unavailable:{" "}
                    {avail?.reason ?? m.unavailable_reason ?? "no advice recorded for this gameweek"}
                  </p>
                ) : (
                  <p>
                    {moves ? `Transfers: ${moves}` : "Roll the free transfer"}. Captain{" "}
                    {advice.captain_name}. <strong>{formatPoints(advice.expected_points)} xP</strong>
                    {roll !== undefined ? `, roll ${formatPoints(roll)} xP` : ", roll not published"}.
                  </p>
                )}
                {available.includes(m.id) ? (
                  // The query makes the link shareable; the click switches the model now, as the provider reads the query only on load.
                  <Link to={`/gameweek?${MODEL_PARAM}=${encodeURIComponent(m.id)}`} onClick={() => setModel(m.id)}>
                    {modelLabel(registry, m.id)} in This gameweek
                  </Link>
                ) : (
                  <p className="home-sub">Its full decision is not published for This gameweek.</p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** The run, the gates and the sources that need a look, in three lines. Detail lives on /health. */
function HealthSummary() {
  const { state } = useArtefact("health");
  const health: Health | null = state.status === "ready" ? state.data : null;
  const gates = health && gateOutcome(health);
  const troubled = health ? troubledSources(health) : [];
  return (
    <section
      className="home-card"
      aria-labelledby="home-health-heading"
      role={gates?.tone === "bad" ? "alert" : undefined}
      data-testid="home-health"
    >
      <h2 id="home-health-heading">Data health</h2>
      {health && gates ? (
        <ul className="home-list">
          <li>Run: {runOutcome(health).label}</li>
          <li data-testid="home-health-gates">Quality gates: {gates.label}</li>
          <li data-testid="home-health-sources">
            {troubled.length === 0
              ? "Every source reporting normally"
              : `Needs a look: ${troubled.map(sourceName).join(", ")}`}
          </li>
        </ul>
      ) : (
        <p>{unready(state, "No health report is published yet.") ?? "Loading the health report…"}</p>
      )}
      <Link to="/health">Open the data health page</Link>
    </section>
  );
}

const MISS_KIND = {
  model_blindspot: "a model blind spot",
  high_variance_outlier: "a high-variance outlier",
  captaincy_trap: "a captaincy trap",
} as const;

/** Last gameweek's headline from log.json (your points, hindsight). An absent log is said, not hidden. */
function LastGameweekCard() {
  const { state } = useArtefact("log");
  const registry = useRegistry();
  const log: Log | null = state.status === "ready" ? state.data : null;
  const last = log?.gameweeks.filter((g) => g.score).sort((a, b) => b.gameweek - a.gameweek)[0];

  return (
    <section className="home-card" aria-labelledby="home-last-heading" data-testid="home-last">
      <h2 id="home-last-heading">Last gameweek</h2>
      {last ? (
        <LastBody last={last} registry={registry} />
      ) : (
        <p data-testid="home-last-absent">
          {state.status === "loading"
            ? "Loading the season log…"
            : (unready(
                state,
                "No season log is published yet: it appears once a team is configured and a gameweek has been scored.",
              ) ?? "The season log has no scored gameweek yet.")}
        </p>
      )}
      <Link to="/review">Open last gameweek</Link>
    </section>
  );
}

function LastBody({ last, registry }: { last: LogGameweek; registry: Registry }) {
  const h = last.hindsight;
  const best = h?.rankings.slice().sort((a, b) => a.rank - b.rank)[0];
  const optimal = h?.optimal?.optimal_overall;
  const miss = h?.diagnostics.slice().sort((a, b) => b.actual_points - a.actual_points)[0];
  return (
    <>
      <h3>Gameweek {last.gameweek}</h3>
      <dl className="home-facts">
        <div>
          <dt>You scored</dt>
          <dd data-testid="home-last-yours">{last.score?.points}</dd>
        </div>
        <div>
          <dt>Best model</dt>
          <dd data-testid="home-last-best">
            {best ? `${modelLabel(registry, best.model_name)}, ${best.score.net_points}` : "not scored"}
          </dd>
        </div>
        <div>
          <dt>Hindsight optimum (net)</dt>
          <dd data-testid="home-last-optimal">{optimal ? optimal.net_points : "not available"}</dd>
        </div>
        <div>
          <dt>Biggest miss</dt>
          <dd data-testid="home-last-miss">
            {miss
              ? `${miss.player_name}, ${miss.actual_points} pts: ${MISS_KIND[miss.category]}`
              : "none flagged"}
          </dd>
        </div>
      </dl>
      {!h && (
        <p className="home-sub">
          Hindsight is not published for this gameweek, so only your points are shown.
        </p>
      )}
    </>
  );
}
