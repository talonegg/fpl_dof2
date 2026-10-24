import type { Models } from "../../contract/types";
import { formatPoints } from "../../format";
import { useRegistry } from "../../data/DataProvider";
import { modelLabel, orderIds, seriesStyle } from "../../data/registry";
import { transfersText } from "../../data/season";
import { ModelBadge } from "./ModelBadge";
import { ModelStatus } from "./ModelStatus";
import { rankBy } from "./rank";
import "../history/history.css";
import "./models.css";


/** Actual FPL points are whole numbers; xPts keep their decimals. */
const pts = (v: number) => String(Math.round(v));

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

/** Every model, ranked on its points to date; a model with nothing scored is listed, unranked, last. */
function SeasonLadder({ models, order }: { models: Models; order: string[] }) {
  const totals = new Map(models.season_to_date.map((s) => [s.model, s]));
  const ranked = rankBy(order, (m) => {
    const t = totals.get(m);
    return t && t.gameweeks_scored > 0 ? t.total : null;
  });
  const leader = ranked[0]?.score ?? null;
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="season-ladder-caption">
      <table className="models-table" data-testid="season-ladder">
        <caption id="season-ladder-caption" className="models-caption">
          This season&rsquo;s ladder: each model&rsquo;s points to date, best first
        </caption>
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Model</th>
            <th scope="col">Points</th>
            <th scope="col">GWs</th>
            <th scope="col">Per GW</th>
            <th scope="col">Behind the leader</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map(({ item: m, score, rank }) => {
            const t = totals.get(m);
            return (
              <tr key={m} data-testid={`ladder-row-${m}`}>
                <td data-testid={`ladder-rank-${m}`}>{rank ?? "—"}</td>
                <th scope="row" className="models-what">
                  <ModelBadge model={m} />
                  <ModelStatus models={models} id={m} testId={`ladder-${m}`} />
                </th>
                <td data-testid={`ladder-total-${m}`}>{score === null ? "—" : pts(score)}</td>
                <td>{t?.gameweeks_scored ?? 0}</td>
                <td>{score === null || !t ? "—" : (score / t.gameweeks_scored).toFixed(1)}</td>
                <td>{score === null || leader === null ? "Not scored yet" : score === leader ? "Leader" : `−${pts(leader - score)}`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const signed = (v: number) => (v > 0 ? `+${v.toFixed(1)}` : v < 0 ? `−${(-v).toFixed(1)}` : "±0.0");

/**
 * Each model's miss split in two per gameweek (ORC-12): forecast error, its XI's xP less the
 * underlying xP (the game's rules applied to FPL's expected goals, assists and goals conceded, and
 * the minutes played), and luck, the points before hits less the underlying xP.
 */
function ForecastSplit({ models, order }: { models: Models; order: string[] }) {
  const registry = useRegistry();
  const split = models.gameweeks.filter((g) => Object.values(g.actual ?? {}).some((a) => a.underlying_points !== undefined));
  return (
    <section data-testid="models-split">
      <h3>Forecast error and luck</h3>
      <p className="models-note">
        Underlying xP scores what each player produced, his minutes and FPL&rsquo;s expected goals, assists
        and goals conceded, by the game&rsquo;s rules. <strong>Forecast error</strong> is the XI&rsquo;s xP
        less its underlying xP (above zero: the model expected too much). <strong>Luck</strong> is the points
        before hits less the underlying xP (above zero: the finishing beat the chances).
      </p>
      {split.length === 0 ? (
        <p className="models-note" data-testid="models-split-empty">
          No gameweek has been evaluated with underlying xP yet.
        </p>
      ) : (
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Forecast error and luck per gameweek by model">
          <table className="models-table" data-testid="models-split-table">
            <caption className="visually-hidden">Forecast error and luck per gameweek, by model</caption>
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
              {split.map((g) => (
                <tr key={g.gameweek}>
                  <th scope="row">{g.gameweek}</th>
                  {order.map((m) => {
                    const a = g.actual?.[m];
                    return (
                      <td key={m} data-testid={`models-split-${g.gameweek}-${m}`}>
                        {a?.forecast_error === undefined || a.luck === undefined
                          ? "—"
                          : `error ${signed(a.forecast_error)}, luck ${signed(a.luck)}`}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Season to date across every model: the ladder, a per-GW table, a chart, and the latest advice. */
export function ModelsSeasonView({ models }: { models: Models | null }) {
  const registry = useRegistry();
  if (!models) {
    return (
      <section className="models-season" data-testid="models-season-empty">
        <h2>This season, on your squad</h2>
        <p>
          The model comparison has not been published yet. It appears once the frozen models
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
      <h2>
        This season, on your squad{" "}
        <span className="season-phase season-phase-prospective" data-testid="season-kind">
          Live season {models.season}
        </span>
      </h2>
      <p className="models-note" data-testid="season-kind-note">
        Each model&rsquo;s advice for this season, scored on what happened. Not the replay of a past season,
        which is on its own tab.
      </p>
      <SeasonLadder models={models} order={order} />
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
      <h3>Per gameweek</h3>
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
      <ForecastSplit models={models} order={order} />
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
