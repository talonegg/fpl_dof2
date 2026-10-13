import type { Models } from "../../contract/types";
import { formatPoints } from "../../format";
import { MODEL_LABELS, parseModel } from "../../data/model";
import type { ModelChoice } from "../../data/model";
import { ModelBadge } from "./ModelBadge";
import { transfersText } from "./ModelAdviceCard";
import { COLOURS, DASHES } from "./modelStyle";
import "./models.css";


/** Actual FPL points are whole numbers; xPts keep their decimals. */
const pts = (v: number) => String(Math.round(v));

function ids(models: Models): ModelChoice[] {
  return models.models.map((m) => parseModel(m.id)).filter((m): m is ModelChoice => m !== null);
}

/** Cumulative points per model as a line chart. Dash patterns as well as colour, for colour-blind readers. */
function CumulativeChart({ models }: { models: Models }) {
  const series = models.season_to_date.filter((s) => s.per_gameweek.length > 0);
  if (series.length === 0) return null;
  const gws = [...new Set(series.flatMap((s) => s.per_gameweek.map((p) => p.gameweek)))].sort(
    (a, b) => a - b,
  );
  const max = Math.max(1, ...series.flatMap((s) => s.per_gameweek.map((p) => p.cumulative)));
  const W = 600;
  const H = 220;
  const pad = 32;
  const x = (gw: number) =>
    gws.length === 1 ? W / 2 : pad + ((W - 2 * pad) * gws.indexOf(gw)) / (gws.length - 1);
  const y = (v: number) => H - pad - ((H - 2 * pad) * v) / max;
  const summary = series
    .map((s) => `${MODEL_LABELS[parseModel(s.model) ?? "champion"]} ${pts(s.total)}`)
    .join(", ");
  return (
    <figure className="models-chart" data-testid="models-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Cumulative points: ${summary}`}>
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="currentColor" opacity="0.4" />
        {gws.map((gw) => (
          <text key={gw} x={x(gw)} y={H - pad + 16} textAnchor="middle" fontSize="11" fill="currentColor">
            GW{gw}
          </text>
        ))}
        {series.map((s) => {
          const m = parseModel(s.model) ?? "champion";
          const pts = s.per_gameweek.map((p) => `${x(p.gameweek)},${y(p.cumulative)}`).join(" ");
          return (
            <g key={s.model}>
              <polyline
                points={pts}
                fill="none"
                stroke={COLOURS[m]}
                strokeWidth={m === "champion" ? 3 : 2}
                strokeDasharray={DASHES[m]}
              />
              {s.per_gameweek.map((p) => (
                <circle key={p.gameweek} cx={x(p.gameweek)} cy={y(p.cumulative)} r="3" fill={COLOURS[m]} />
              ))}
            </g>
          );
        })}
      </svg>
      <figcaption className="models-legend">
        {series.map((s) => {
          const m = parseModel(s.model) ?? "champion";
          return (
            <span key={s.model} className="models-legend-item">
              <svg width="24" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="24" y2="4" stroke={COLOURS[m]} strokeWidth="3" strokeDasharray={DASHES[m]} />
              </svg>
              {MODEL_LABELS[m]}
            </span>
          );
        })}
      </figcaption>
    </figure>
  );
}

/** Season to date across all frozen models: totals, a per-GW table, a chart, and the latest advice. */
export function ModelsSeasonView({ models }: { models: Models | null }) {
  if (!models) {
    return (
      <section className="models-season" data-testid="models-season-empty">
        <h2>All models, season to date</h2>
        <p>
          The five-model comparison has not been published yet. It appears once the frozen models
          record their first pre-deadline decision.
        </p>
      </section>
    );
  }
  const order = ids(models);
  const scored = models.gameweeks.filter((g) => g.actual);
  const latest = models.gameweeks[models.gameweeks.length - 1];
  const totals = new Map(models.season_to_date.map((s) => [s.model, s]));
  return (
    <section className="models-season" data-testid="models-season">
      <h2>All models, season to date</h2>
      <p className="models-note">
        Frozen at {models.frozen.tag ?? "an unknown tag"}. Points are the final XI after auto-subs,
        captain (vice if the captain did not play), minus hits. Live advice is the champion; the others
        are comparisons. A handful of gameweeks is far too few to call a winner.
      </p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Points per gameweek by model">
        <table className="models-table" data-testid="models-table">
          <caption className="visually-hidden">Points per gameweek and cumulative total, by model</caption>
          <thead>
            <tr>
              <th scope="col">GW</th>
              {order.map((m) => (
                <th scope="col" key={m}>
                  {MODEL_LABELS[m]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {scored.map((g) => (
              <tr key={g.gameweek}>
                <th scope="row">{g.gameweek}</th>
                {order.map((m) => {
                  const a = g.actual?.[m];
                  return (
                    <td key={m}>
                      {a ? pts(a.points) : "—"}
                      {a && a.hit_points !== 0 ? <span className="models-hit"> ({a.hit_points})</span> : null}
                    </td>
                  );
                })}
              </tr>
            ))}
            {scored.length === 0 && (
              <tr>
                <td colSpan={order.length + 1}>No gameweek has been scored yet.</td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Total</th>
              {order.map((m) => (
                <td key={m} data-testid={`models-total-${m}`}>
                  <strong>{pts(totals.get(m)?.total ?? 0)}</strong>
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
      <CumulativeChart models={models} />
      {latest && (
        <>
          <h3>GW{latest.gameweek} advice by model</h3>
          <div className="models-advice-list" data-testid="models-advice-list">
            {order.map((m) => {
              const adv = latest.advice[m];
              if (!adv) return null;
              return (
                <article key={m} className="models-advice-item" data-testid={`models-advice-${m}`}>
                  <h4>
                    <ModelBadge model={m} />
                  </h4>
                  <p>
                    <strong>Transfers:</strong> {transfersText(adv)}
                  </p>
                  <p>
                    <strong>Captain:</strong> {adv.captain_name} · <strong>Vice:</strong> {adv.vice_name}{" "}
                    · <strong>xPts:</strong> {formatPoints(adv.expected_points)}
                  </p>
                </article>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
