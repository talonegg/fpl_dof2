import type { Models, SeasonReplay } from "../../contract/types";
import { MODEL_LABELS } from "../../data/model";
import type { ModelChoice } from "../../data/model";
import { COLOURS, DASHES } from "../models/modelStyle";
import { buildSeason } from "./season";
import type { Phase, Season } from "./season";

const pts = (v: number) => String(Math.round(v));

export const PHASE_LABELS: Record<Phase, string> = { replay: "Replay", prospective: "Prospective" };
const PHASE_HELP: Record<Phase, string> = {
  replay: "Retrospective: frozen models run after the gameweek was played",
  prospective: "Picks recorded before the deadline, scored afterwards",
};

export function PhaseBadge({ phase }: { phase: Phase }) {
  return (
    <span className={`season-phase season-phase-${phase}`} title={PHASE_HELP[phase]} data-testid={`phase-${phase}`}>
      {PHASE_LABELS[phase]}
    </span>
  );
}

/** Replay segment faint and thin over a shaded band; prospective segment solid with point markers. */
function SeasonChart({ season }: { season: Season }) {
  const { rows, models } = season;
  if (rows.length === 0) return null;
  const W = 720;
  const H = 260;
  const L = 44;
  const R = 12;
  const T = 12;
  const B = 28;
  const max = Math.max(1, ...models.map((m) => rows[rows.length - 1].cumulative[m] ?? 0));
  const x = (i: number) => L + ((W - L - R) * i) / Math.max(1, rows.length - 1);
  const y = (v: number) => H - B - ((H - T - B) * v) / max;
  const split = rows.findIndex((r) => r.phase === "prospective");
  const lastReplay = split === -1 ? rows.length - 1 : split - 1;
  const seg = (m: ModelChoice, from: number, to: number) =>
    rows
      .slice(from, to + 1)
      .map((r, k) => `${x(from + k)},${y(r.cumulative[m] ?? 0)}`)
      .join(" ");
  return (
    <figure className="history-chart" data-testid="season-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Cumulative points ${season.season}, replay then prospective`}>
        {lastReplay >= 0 && (
          <rect data-testid="season-replay-band" x={L} y={T} width={x(lastReplay) - L} height={H - T - B} fill="currentColor" opacity="0.06" />
        )}
        {split > 0 && <line x1={x(lastReplay)} x2={x(lastReplay)} y1={T} y2={H - B} stroke="currentColor" opacity="0.4" strokeDasharray="4 4" />}
        {rows.map((r, i) => (
          <text key={r.gameweek} x={x(i)} y={H - 8} textAnchor="middle" fontSize="11" fill="currentColor">
            {r.gameweek}
          </text>
        ))}
        {models.map((m) => (
          <g key={m} data-model={m}>
            {lastReplay >= 0 && (
              <polyline data-phase="replay" points={seg(m, 0, lastReplay)} fill="none" stroke={COLOURS[m]} strokeWidth={1.5} strokeDasharray={DASHES[m]} opacity={0.45} />
            )}
            {split !== -1 && (
              <polyline data-phase="prospective" points={seg(m, Math.max(0, lastReplay), rows.length - 1)} fill="none" stroke={COLOURS[m]} strokeWidth={3} strokeDasharray={DASHES[m]} />
            )}
            {split !== -1 &&
              rows.slice(split).map((r, k) => <circle key={r.gameweek} cx={x(split + k)} cy={y(r.cumulative[m] ?? 0)} r={3} fill={COLOURS[m]} />)}
          </g>
        ))}
      </svg>
      <figcaption className="models-legend">
        {models.map((m) => (
          <span key={m} className="models-legend-item">
            <svg width="24" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="24" y2="4" stroke={COLOURS[m]} strokeWidth="3" strokeDasharray={DASHES[m]} />
            </svg>
            {MODEL_LABELS[m]}
          </span>
        ))}
        <span className="history-axis-note" data-testid="season-line-legend">
          Shaded, faint thin line = replay · solid line with dots = prospective
        </span>
      </figcaption>
    </figure>
  );
}

/** The current season: GW1–n replay, then prospective frozen decisions as each GW is scored. */
export function SeasonView({ replay, models }: { replay: SeasonReplay | null; models: Models | null }) {
  const season = buildSeason(replay, models);
  if (season.rows.length === 0) return null;
  const { asOf } = season;
  const latest = Math.max(asOf.replay ?? 0, asOf.prospective ?? 0);
  const ranked = [...season.models].sort((a, b) => (season.totals[b]?.total ?? 0) - (season.totals[a]?.total ?? 0));
  return (
    <section className="history season" data-testid="season-history">
      <h2>Model comparison — {season.season} so far</h2>
      <p className="history-asof" data-testid="season-asof">
        As of GW{latest}
        {asOf.replay ? ` · GW1–${asOf.replay} replay` : ""}
        {asOf.prospective ? ` · GW${(asOf.replay ?? 0) + 1}–${asOf.prospective} prospective` : " · no prospective gameweek scored yet"}
      </p>
      <ul className="season-legend" data-testid="season-legend">
        <li>
          <PhaseBadge phase="replay" /> {PHASE_HELP.replay}. {replay?.caveat ?? ""}
        </li>
        <li>
          <PhaseBadge phase="prospective" /> {PHASE_HELP.prospective} by the frozen harness ({replay?.frozen_tag ?? models?.frozen.tag ?? "frozen tag"}).
        </li>
      </ul>
      {replay && Object.keys(replay.missing_models).length > 0 && (
        <p className="models-note">
          {Object.entries(replay.missing_models)
            .map(([m, why]) => `${MODEL_LABELS[m as ModelChoice] ?? m}: ${why}`)
            .join("; ")}
          .
        </p>
      )}

      <h3 id="season-summary-heading">Season to date</h3>
      <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="season-summary-heading">
        <table className="models-table" data-testid="season-summary">
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Replay</th>
              <th scope="col">Prospective</th>
              <th scope="col">Total</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((m) => {
              const t = season.totals[m]!;
              return (
                <tr key={m} data-testid={`season-row-${m}`}>
                  <th scope="row">{MODEL_LABELS[m]}</th>
                  <td>{asOf.replay ? pts(t.replay) : "—"}</td>
                  <td>{asOf.prospective ? pts(t.prospective) : "—"}</td>
                  <td data-testid={`season-total-${m}`}>
                    <strong>{pts(t.total)}</strong>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="models-note">Six-odd gameweeks is far too few to separate the models; the replay totals are not significant.</p>

      <h3>Cumulative points</h3>
      <SeasonChart season={season} />

      <h3 id="season-gw-heading">Per gameweek</h3>
      <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="season-gw-heading">
        <table className="models-table" data-testid="season-gw-table">
          <thead>
            <tr>
              <th scope="col">GW</th>
              <th scope="col">Type</th>
              {season.models.map((m) => (
                <th scope="col" key={m}>
                  {MODEL_LABELS[m]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {season.rows.map((r) => (
              <tr key={r.gameweek} className={`season-row-${r.phase}`} data-testid={`season-gw-${r.gameweek}`}>
                <th scope="row">{r.gameweek}</th>
                <td>
                  <PhaseBadge phase={r.phase} />
                </td>
                {season.models.map((m) => (
                  <td key={m}>{r.points[m] !== undefined ? pts(r.points[m]!) : "—"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Hook for Alchemy's per-player xP-vs-actual accuracy scoring. Schema not defined yet: do not guess it. */}
      <section className="season-accuracy" data-testid="season-accuracy-placeholder" aria-labelledby="season-accuracy-heading">
        <h3 id="season-accuracy-heading">Forecast accuracy (xP vs actual)</h3>
        <p className="models-note">Coming later: per-player expected-vs-actual points accuracy for each model.</p>
      </section>
    </section>
  );
}
