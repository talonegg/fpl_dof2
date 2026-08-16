import type { Health, HealthMetricsPoint } from "../../contract/types";
import { LineChart } from "../charts/LineChart";
import { formatLocalDateTime } from "../../format";
import {
  formatAge,
  formatDuration,
  gateOutcome,
  runOutcome,
  seriesOf,
  sourceStatus,
  troubledSources,
  type StatusReading,
} from "./health";
import "./health.css";

/**
 * The data health page (E7-S6, FR-33, NFR-07, DL-41).
 *
 * The monitoring dashboard is part of the product rather than a separate tool, and with no budget
 * for observability tooling that is not a compromise — it is the only version that stays free and
 * actually gets looked at.
 *
 * Four things it does that a status page usually does not, each because leaving them out would
 * mislead:
 *
 * **Every badge carries its reason.** "Degraded" on its own is a colour; "degraded, `HTTPError`,
 * reported by the ingest stage" is something a reader can act on at 03:00 without opening a log
 * (DP-09). The same goes for a gate: its message and the requirement it protects sit in the row.
 *
 * **It never renders "not known" as "fine".** An absent gate report reads as *not reported*, not as
 * a pass; a source this run said nothing about reads as *not seen*, not as OK. Those two
 * substitutions are the only way this page can be actively harmful, because a reader who trusts it
 * stops looking (DP-13, DP-15).
 *
 * **It names no data source.** Every label on the page is a string that arrived in the artefact.
 * There is no per-source branch, no per-source styling and no list of expected sources anywhere in
 * `web/` (Invariant 1, DP-01).
 *
 * **It does not call the diagnostic an accuracy.** `r_squared_on_price` is R-15's check that the
 * forecast is not a repricing of the price list — high is bad. Charting it under a heading like
 * "model accuracy" would present an unvalidated model as a validated one, which is the exact failure
 * DP-09 exists to prevent. Skill is measured against a baseline in the backtest and reported in the
 * model card (DP-12), and this page points there rather than pretending to answer it.
 */
export function HealthPanel({ health }: { health: Health }) {
  const troubled = troubledSources(health);
  const run = runOutcome(health);
  const gates = gateOutcome(health);
  const okCount = health.sources.filter((source) => source.status === "ok").length;

  return (
    <section className="health" data-testid="health-panel">
      <header className="health-head">
        <h2>Data health</h2>
        <p className="health-asat">
          Published {formatLocalDateTime(health.generated_at)} · run{" "}
          <code>{health.run.run_id}</code>
          {health.run.git_sha ? (
            <>
              {" "}
              · commit <code>{health.run.git_sha.slice(0, 10)}</code>
            </>
          ) : null}
        </p>
        {health.run.git_dirty ? (
          <p className="health-note" data-testid="health-dirty">
            This run was made from a working tree with uncommitted changes, so it cannot be
            reproduced from its recorded inputs alone.
          </p>
        ) : null}
      </header>

      {troubled.length > 0 ? (
        <div className="health-banner" role="status" data-testid="health-degraded-banner">
          <h3>
            {troubled.length} of {health.sources.length} sources are not reporting normally
          </h3>
          <p>
            Losing a source removes the fields it contributes and nothing else — the recommendation
            is still produced, on less evidence (NFR-15).
          </p>
          <ul>
            {troubled.map((source) => (
              <li key={source.source} data-testid={`health-banner-${source.source}`}>
                <strong>{source.source}</strong> — {sourceStatus(source).detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="health-strip">
        <Tile title="Last run" reading={run} />
        <Tile title="Quality gates" reading={gates} />
        <Tile
          title="Sources"
          reading={{
            label: `${okCount} of ${health.sources.length} OK`,
            tone: troubled.length > 0 ? "warn" : "good",
            detail:
              health.sources.length === 0
                ? "This run recorded no sources at all."
                : "Counted from what this run recorded, not from a list of expected sources.",
          }}
        />
      </div>

      <Sources health={health} />
      <Gates health={health} />
      <Stages health={health} />
      <MetricsHistory health={health} />
    </section>
  );
}

function Tile({ title, reading }: { title: string; reading: StatusReading }) {
  return (
    <div className={`health-tile health-tone-${reading.tone}`}>
      <h3>{title}</h3>
      {/* The tone is carried by a word as well as by a colour, so the tile reads in greyscale
          and to a screen reader (NFR-14). */}
      <p className="health-tile-value">{reading.label}</p>
      <p className="health-tile-detail">{reading.detail}</p>
    </div>
  );
}

function Sources({ health }: { health: Health }) {
  return (
    <section className="health-section" data-testid="health-sources">
      <h3>Sources</h3>
      {health.sources.length === 0 ? (
        <p className="health-empty">
          This run recorded no sources. That is a state of the run, not of the page.
        </p>
      ) : (
        <>
          {/* Outside the scroller on purpose. As a <caption> it inherited the table's width, which
              is wider than a phone, so the sentence was clipped by the scroller rather than
              wrapping — and this is the sentence that stops the freshness column being misread.
              `aria-describedby` keeps it associated with the table for a screen reader. */}
          <p className="health-caption" id="health-freshness-note">
            Freshness is the age of each source&rsquo;s newest captured snapshot at the moment this
            file was published, not at the moment you are reading it.
          </p>
          <div className="health-scroller">
            <table className="health-table" aria-describedby="health-freshness-note">
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Status</th>
                  <th scope="col">Freshness</th>
                  <th scope="col">Captured</th>
                  <th scope="col">Requests</th>
                  <th scope="col">Why</th>
                </tr>
              </thead>
              <tbody>
                {health.sources.map((source) => {
                  const reading = sourceStatus(source);
                  return (
                    <tr key={source.source} data-testid={`health-source-${source.source}`}>
                      <th scope="row">{source.source}</th>
                      <td>
                        <span className={`health-pill health-tone-${reading.tone}`}>
                          {reading.label}
                        </span>
                      </td>
                      <td>{formatAge(source.age_seconds)}</td>
                      <td>
                        {source.observed_at ? formatLocalDateTime(source.observed_at) : "never"}
                      </td>
                      <td>
                        {source.network_calls ?? "—"} live / {source.cache_hits ?? "—"} cached
                      </td>
                      <td className="health-why">{reading.detail}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Gates({ health }: { health: Health }) {
  const gates = health.gates;
  return (
    <section className="health-section" data-testid="health-gates">
      <h3>Quality gates</h3>
      {!gates ? (
        <p className="health-empty" data-testid="health-gates-absent">
          No gate report was published with this run, so none of the data behind this site has been
          checked by it. This is not the same as everything passing — a gate that never ran has
          proved nothing.
        </p>
      ) : (
        <>
          {!gates.passed ? (
            <p className="health-banner-inline" data-testid="health-gates-blocked">
              Publication was blocked by {gates.blocking.join(", ")}. Nothing new was published, and
              the artefacts this site is serving come from an earlier run — stale and honest, rather
              than fresh and wrong.
            </p>
          ) : null}
          <div className="health-scroller">
            <table className="health-table">
              <thead>
                <tr>
                  <th scope="col">Gate</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Protects</th>
                  <th scope="col">What it found</th>
                </tr>
              </thead>
              <tbody>
                {gates.results.map((gate) => (
                  <tr key={gate.gate} data-testid={`health-gate-${gate.gate}`}>
                    <th scope="row">{gate.gate}</th>
                    <td>
                      <span
                        className={`health-pill health-tone-${
                          gate.outcome === "failed"
                            ? gate.severity === "error"
                              ? "bad"
                              : "warn"
                            : gate.outcome === "skipped"
                              ? "neutral"
                              : "good"
                        }`}
                      >
                        {gate.outcome}
                      </span>
                    </td>
                    <td>{gate.severity}</td>
                    <td>{gate.requirement}</td>
                    <td className="health-why">{gate.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Stages({ health }: { health: Health }) {
  if (health.run.stages.length === 0) {
    return (
      <section className="health-section" data-testid="health-stages">
        <h3>Stages</h3>
        <p className="health-empty">This run recorded no stages.</p>
      </section>
    );
  }
  return (
    <section className="health-section" data-testid="health-stages">
      <h3>Stages</h3>
      <ul className="health-stages">
        {health.run.stages.map((stage) => (
          <li key={stage.name} data-testid={`health-stage-${stage.name}`}>
            <span
              className={`health-pill health-tone-${
                stage.status === "failed" ? "bad" : stage.status === "skipped" ? "neutral" : "good"
              }`}
            >
              {stage.status}
            </span>
            <span className="health-stage-name">{stage.name}</span>
            <span className="health-stage-time">{formatDuration(stage.duration_seconds)}</span>
            {stage.error ? <span className="health-stage-error">{stage.error}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function MetricsHistory({ health }: { health: Health }) {
  const history = health.metrics_history;
  if (!history || history.runs.length === 0) {
    return (
      <section className="health-section" data-testid="health-history">
        <h3>Recent runs</h3>
        <p className="health-empty" data-testid="health-history-absent">
          No run history has been published yet. It appears once more than one run has been
          recorded.
        </p>
      </section>
    );
  }

  const runs = history.runs;
  const label = (x: number) => {
    const point: HealthMetricsPoint | undefined = runs[x - 1];
    if (!point?.finished_at) return `#${x}`;
    return new Date(point.finished_at).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
    });
  };

  const solve = seriesOf(runs, (point) => point.solve_seconds);
  const volume = seriesOf(runs, (point) => point.rows_total);
  const dependence = seriesOf(runs, (point) => point.r_squared_on_price);

  return (
    <section className="health-section" data-testid="health-history">
      <h3>Recent runs</h3>
      <p className="health-note">
        {runs.length} run{runs.length === 1 ? "" : "s"}, oldest first, derived from{" "}
        <code>{history.derived_from}</code>. A run that never reached a stage draws a gap on that
        stage&rsquo;s chart rather than a zero.
      </p>

      <div className="health-charts">
        <LineChart
          testId="health-chart-solve"
          title="Solve time"
          summary={`How long the squad optimiser took on each of the last ${runs.length} runs, in seconds. What matters is that it stays comfortably inside the pre-deadline window, not the absolute figure.`}
          series={[{ key: "solve", label: "Seconds", points: solve, variant: 0 }]}
          xTickLabel={label}
          emptyMessage="No run in this window reached the optimiser."
        />
        <LineChart
          testId="health-chart-volume"
          title="Conformed rows"
          summary={`Total rows in the conformed model on each of the last ${runs.length} runs. A source returning a fraction of its usual records produces a perfectly valid, perfectly wrong model, and a step down here is the first place that shows.`}
          series={[{ key: "rows", label: "Rows", points: volume, variant: 1 }]}
          xTickLabel={label}
          emptyMessage="No run in this window recorded row counts."
        />
        <LineChart
          testId="health-chart-dependence"
          title="Price dependence of the forecast"
          summary={`How much of the forecast is explained by price and position alone (R-15), on each of the last ${runs.length} runs. This is a diagnostic, not a measure of accuracy, and a HIGH value is the bad one: it means the forecast is largely a repricing of the price list. Skill is measured against a baseline in the backtest and reported in the model card, not here.`}
          series={[{ key: "r2", label: "R² on price", points: dependence, variant: 2 }]}
          xTickLabel={label}
          includeZero
          minSpan={0.2}
          emptyMessage="No run in this window recorded the diagnostic."
        />
      </div>
    </section>
  );
}
