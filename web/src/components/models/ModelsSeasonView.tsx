import type { ModelAdvice, Models } from "../../contract/types";
import { formatPoints } from "../../format";
import { useRegistry } from "../../data/DataProvider";
import { modelLabel, orderIds, seriesStyle } from "../../data/registry";
import { ModelBadge } from "./ModelBadge";
import "./models.css";


/** Actual FPL points are whole numbers; xPts keep their decimals. */
const pts = (v: number) => String(Math.round(v));

export function transfersText(advice: ModelAdvice): string {
  const moves =
    advice.transfers.length > 0
      ? advice.transfers.map((t) => `${t.out_name} → ${t.in_name}`).join(", ")
      : "Roll (no transfer)";
  return advice.hit_points !== 0 ? `${moves} (${advice.hit_points} hit)` : moves;
}

/** Cumulative points per model as a line chart. Dash patterns as well as colour, for colour-blind readers. */
function CumulativeChart({ models }: { models: Models }) {
  const registry = useRegistry();
  const sty = (id: string) => seriesStyle(registry, id);
  const series = models.season_to_date.filter((s) => s.per_gameweek.length > 0);
  if (series.length === 0) return null;
  const switchGw = models.switch_gameweek ?? null;
  // The switch gameweek is on the axis even before anything is scored live, so the marker is always drawn.
  const gws = [
    ...new Set([
      ...series.flatMap((s) => s.per_gameweek.map((p) => p.gameweek)),
      ...(switchGw === null ? [] : [switchGw]),
    ]),
  ].sort((a, b) => a - b);
  const max = Math.max(1, ...series.flatMap((s) => s.per_gameweek.map((p) => p.cumulative)));
  const W = 600;
  const H = 220;
  const pad = 32;
  const x = (gw: number) =>
    gws.length === 1 ? W / 2 : pad + ((W - 2 * pad) * gws.indexOf(gw)) / (gws.length - 1);
  const y = (v: number) => H - pad - ((H - 2 * pad) * v) / max;
  const summary = series
    .map((s) => `${modelLabel(registry, s.model)} ${pts(s.total)}`)
    .join(", ");
  const switchLabel = switchGw === null ? null : `Live from GW${switchGw}`;
  return (
    <figure className="models-chart" data-testid="models-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Cumulative points: ${summary}${switchLabel ? `. ${switchLabel}` : ""}`}
      >
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="currentColor" opacity="0.4" />
        {switchGw !== null && (
          <g data-testid="models-switch-marker">
            <line
              x1={x(switchGw)}
              y1={pad / 2}
              x2={x(switchGw)}
              y2={H - pad}
              stroke="var(--border-strong)"
              strokeWidth="2"
              strokeDasharray="4 3"
            />
            <text
              x={x(switchGw) + (x(switchGw) > W / 2 ? -4 : 4)}
              y={pad / 2 + 8}
              textAnchor={x(switchGw) > W / 2 ? "end" : "start"}
              fontSize="11"
              fill="var(--text)"
            >
              {switchLabel}
            </text>
          </g>
        )}
        {gws.map((gw) => (
          <text key={gw} x={x(gw)} y={H - pad + 16} textAnchor="middle" fontSize="11" fill="currentColor">
            GW{gw}
          </text>
        ))}
        {series.map((s) => {
          const m = s.model;
          const pts = s.per_gameweek.map((p) => `${x(p.gameweek)},${y(p.cumulative)}`).join(" ");
          return (
            <g key={s.model}>
              <polyline
                points={pts}
                fill="none"
                stroke={sty(m).colour}
                strokeWidth={m === registry.champion ? 3 : 2}
                strokeDasharray={sty(m).dash}
              />
              {s.per_gameweek.map((p) => (
                <circle key={p.gameweek} cx={x(p.gameweek)} cy={y(p.cumulative)} r="3" fill={sty(m).colour} />
              ))}
            </g>
          );
        })}
      </svg>
      <figcaption className="models-legend">
        {series.map((s) => {
          const m = s.model;
          return (
            <span key={s.model} className="models-legend-item">
              <svg width="24" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="24" y2="4" stroke={sty(m).colour} strokeWidth="3" strokeDasharray={sty(m).dash} />
              </svg>
              {modelLabel(registry, m)}
            </span>
          );
        })}
      </figcaption>
    </figure>
  );
}

/** Season to date across all frozen models: totals, a per-GW table, a chart, and the latest advice. */
export function ModelsSeasonView({ models }: { models: Models | null }) {
  const registry = useRegistry();
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
  const order = orderIds(registry, models.models.map((m) => m.id));
  const scored = models.gameweeks.filter((g) => g.actual);
  const latest = models.gameweeks[models.gameweeks.length - 1];
  const totals = new Map(models.season_to_date.map((s) => [s.model, s]));
  return (
    <section className="models-season" data-testid="models-season">
      <h2>All models, season to date</h2>
      <p className="models-note">
        Points are the final XI after auto-subs, captain (vice if the captain did not play), minus
        hits. Live advice is the champion; the others are comparisons. A handful of gameweeks is far
        too few to call a winner.
      </p>
      {models.switch_gameweek != null && (
        <p className="models-note" data-testid="models-switch-note">
          Before GW{models.switch_gameweek} is the frozen record ({models.frozen.tag ?? "an unknown tag"}):
          each model&rsquo;s virtual season. From GW{models.switch_gameweek} it is each strategy&rsquo;s
          advice scored on your real squad. The two are different quantities; read across the switch
          with care.
        </p>
      )}
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Points per gameweek by model">
        <table className="models-table" data-testid="models-table">
          <caption className="visually-hidden">Points per gameweek and cumulative total, by model</caption>
          <thead>
            <tr>
              <th scope="col">GW</th>
              {order.map((m) => (
                <th scope="col" key={m}>
                  {modelLabel(registry, m)}
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
