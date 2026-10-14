import { useState } from "react";
import type { ModelsHistory } from "../../contract/types";
import { MODEL_LABELS, parseModel } from "../../data/model";
import type { ModelChoice } from "../../data/model";
import { ModelBadge } from "../models/ModelBadge";
import { ModelSelector } from "../models/ModelSelector";
import { COLOURS, DASHES } from "../models/modelStyle";
import "../models/models.css";
import "./history.css";

const pts = (v: number) => String(Math.round(v));
const signed = (v: number, dp = 2) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(dp)}`;

/** Cumulative points over the season, one line per model; the highlighted model is drawn on top. */
function CumulativeChart({ history, ids, highlight }: { history: ModelsHistory; ids: ModelChoice[]; highlight: ModelChoice }) {
  const gws = history.gameweeks.map((g) => g.gameweek);
  if (gws.length === 0) return null;
  const max = Math.max(1, ...ids.map((m) => history.gameweeks[gws.length - 1].models[m]?.cumulative ?? 0));
  const W = 720;
  const H = 280;
  const L = 44;
  const R = 12;
  const T = 12;
  const B = 28;
  const x = (i: number) => L + ((W - L - R) * i) / Math.max(1, gws.length - 1);
  const y = (v: number) => H - B - ((H - T - B) * v) / max;
  const ticks = Array.from(new Set([0, 0.25, 0.5, 0.75, 1].map((f) => Math.round((max * f) / 100) * 100)));
  const order = [...ids.filter((m) => m !== highlight), highlight];
  const summary = ids
    .map((m) => `${MODEL_LABELS[m]} ${pts(history.gameweeks[gws.length - 1].models[m]?.cumulative ?? 0)}`)
    .join(", ");
  return (
    <figure className="history-chart" data-testid="history-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Cumulative points after GW${gws[gws.length - 1]}: ${summary}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="currentColor" opacity="0.12" />
            <text x={L - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill="currentColor">
              {t}
            </text>
          </g>
        ))}
        {gws.map((gw, i) =>
          gw === 1 || gw % 5 === 0 ? (
            <text key={gw} x={x(i)} y={H - 8} textAnchor="middle" fontSize="11" fill="currentColor">
              {gw}
            </text>
          ) : null,
        )}
        {order.map((m) => (
          <polyline
            key={m}
            data-model={m}
            points={history.gameweeks.map((g, i) => `${x(i)},${y(g.models[m]?.cumulative ?? 0)}`).join(" ")}
            fill="none"
            stroke={COLOURS[m]}
            strokeWidth={m === highlight ? 3.5 : 1.75}
            strokeDasharray={DASHES[m]}
            opacity={m === highlight ? 1 : 0.7}
          />
        ))}
      </svg>
      <figcaption className="models-legend">
        {ids.map((m) => (
          <span key={m} className={`models-legend-item${m === highlight ? " is-highlight" : ""}`}>
            <svg width="24" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="24" y2="4" stroke={COLOURS[m]} strokeWidth="3" strokeDasharray={DASHES[m]} />
            </svg>
            {MODEL_LABELS[m]}
          </span>
        ))}
        <span className="history-axis-note">x: gameweek · y: cumulative points</span>
      </figcaption>
    </figure>
  );
}

/** `/history` — how the five frozen models would have played 2025/26 (a backtest). */
export function ModelHistoryView({ history }: { history: ModelsHistory }) {
  const ids = history.models
    .filter((m) => m.available)
    .map((m) => parseModel(m.id))
    .filter((m): m is ModelChoice => m !== null);
  const unavailable = history.models.filter((m) => !m.available);
  const [highlight, setHighlight] = useState<ModelChoice>(ids.includes("champion") ? "champion" : ids[0]);
  const summary = new Map(history.summary.map((s) => [s.model, s]));
  const ranked = [...history.summary].sort((a, b) => a.final_rank - b.final_rank);
  const sel = summary.get(highlight);

  return (
    <section className="history" data-testid="model-history">
      <h2>Model history — {history.season}</h2>
      <p className="history-caveat" role="note" data-testid="history-caveat">
        {history.caveat}
      </p>

      <ModelSelector
        available={ids}
        value={highlight}
        onChange={setHighlight}
        label="Highlight model"
        showCompareLink={false}
        testId="history-model"
        note={
          sel
            ? `${MODEL_LABELS[highlight]}: ${pts(sel.total)} pts, ranked ${sel.final_rank} of ${ids.length}.`
            : undefined
        }
      />

      <h3 id="history-summary-heading">Relative performance</h3>
      <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="history-summary-heading">
        <table className="models-table history-summary" data-testid="history-summary">
          <thead>
            <tr>
              <th scope="col">Rank</th>
              <th scope="col">Model</th>
              <th scope="col">Total</th>
              <th scope="col">Per GW</th>
              <th scope="col">Δ vs champion / GW (95% CI)</th>
              <th scope="col">GWs won</th>
              <th scope="col">Hits</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((s) => {
              const m = parseModel(s.model) ?? "champion";
              const d = s.delta_vs_champion;
              return (
                <tr key={s.model} className={m === highlight ? "is-highlight" : ""} data-testid={`history-row-${m}`}>
                  <td>{s.final_rank}</td>
                  <th scope="row">
                    <ModelBadge model={m} />
                  </th>
                  <td data-testid={`history-total-${m}`}>{pts(s.total)}</td>
                  <td>{s.mean_per_gameweek.toFixed(2)}</td>
                  <td data-testid={`history-delta-${m}`}>
                    {d ? (
                      <>
                        {signed(d.mean)} [{signed(d.ci_low)}, {signed(d.ci_high)}]
                        {d.significant ? <span className="history-sig" title="95% CI excludes zero"> ★</span> : null}
                        <span className="history-sub"> · {signed(d.total, 0)} total</span>
                      </>
                    ) : (
                      "reference"
                    )}
                  </td>
                  <td>{s.gameweeks_won}</td>
                  <td>{pts(s.hit_points)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="models-note">
        Δ is the paired per-GW difference to the champion; CIs are an iid gameweek bootstrap ({history.bootstrap.draws}{" "}
        draws, seed {history.bootstrap.seed}). ★ = CI excludes zero, with no multiple-comparison correction across four
        models. One season of 38 GWs is a weak basis for choosing a model. GWs won = ranked first of the five (ties
        shared).
      </p>
      {unavailable.length > 0 && (
        <ul className="history-unavailable" data-testid="history-unavailable">
          {unavailable.map((m) => (
            <li key={m.id}>
              {m.label}: unavailable — {m.unavailable_reason}
            </li>
          ))}
        </ul>
      )}

      <h3>Cumulative points</h3>
      <CumulativeChart history={history} ids={ids} highlight={highlight} />

      <h3 id="history-gw-heading">Per gameweek</h3>
      <div className="table-scroll history-gw-scroll" tabIndex={0} role="region" aria-labelledby="history-gw-heading">
        <table className="models-table history-gw" data-testid="history-gw-table">
          <caption className="visually-hidden">
            Points per gameweek, rank of five in brackets, then captain and vice for the highlighted model
          </caption>
          <thead>
            <tr>
              <th scope="col">GW</th>
              {ids.map((m) => (
                <th scope="col" key={m} className={m === highlight ? "is-highlight" : ""}>
                  {MODEL_LABELS[m]}
                </th>
              ))}
              <th scope="col">{MODEL_LABELS[highlight]}: captain / vice</th>
              <th scope="col">Transfers</th>
            </tr>
          </thead>
          <tbody>
            {history.gameweeks.map((g) => {
              const h = g.models[highlight];
              return (
                <tr key={g.gameweek}>
                  <th scope="row">{g.gameweek}</th>
                  {ids.map((m) => {
                    const e = g.models[m];
                    return (
                      <td key={m} className={`${m === highlight ? "is-highlight" : ""}${e?.rank === 1 ? " is-best" : ""}`}>
                        {e ? pts(e.points) : "—"}
                        {e ? <span className="history-sub"> ({e.rank})</span> : null}
                        {e && e.hit_points !== 0 ? <span className="models-hit"> {pts(e.hit_points)}</span> : null}
                      </td>
                    );
                  })}
                  <td className="history-text">
                    {h ? (
                      <>
                        {h.captain} ({pts(h.captain_points)}) / {h.vice_captain}
                        {h.vice_used ? " — vice used" : ""}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="history-text">{h && h.transfers.length > 0 ? h.transfers.join(", ") : "Roll"}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Total</th>
              {ids.map((m) => (
                <td key={m} className={m === highlight ? "is-highlight" : ""}>
                  <strong>{pts(summary.get(m)?.total ?? 0)}</strong>
                </td>
              ))}
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>

      <details className="history-provenance">
        <summary>Where these numbers come from</summary>
        <dl>
          {Object.entries(history.provenance).map(([k, v]) => (
            <div key={k}>
              <dt>{k.replace(/_/g, " ")}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}
