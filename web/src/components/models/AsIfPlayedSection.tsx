import type { AsIfPlayed } from "../../contract/types";
import { useRegistry } from "../../data/DataProvider";
import { modelLabel, orderIds } from "../../data/registry";
import { unready, useArtefact } from "../../data/store";
import { ModelBadge } from "./ModelBadge";
import "../history/history.css";
import "./models.css";

const pts = (v: number) => String(Math.round(v));
const ABSENT =
  "The live season has not been replayed yet: the weekly backtest replays it once enough gameweeks are finished to fit every model.";

function Ladder({ played }: { played: AsIfPlayed }) {
  const ranked = [...played.summary].sort((a, b) => a.final_rank - b.final_rank);
  const liveFrom = new Map(played.models.map((m) => [m.id, m.live_from ?? null]));
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="as-if-played-caption">
      <table className="models-table" data-testid="as-if-played-ladder">
        <caption id="as-if-played-caption" className="models-caption">
          As if played: each model&rsquo;s own team, points to date, best first
        </caption>
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Model</th>
            <th scope="col">Points</th>
            <th scope="col">Per GW</th>
            <th scope="col">Hits</th>
            <th scope="col">Live from</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((s) => {
            const from = liveFrom.get(s.model) ?? null;
            return (
              <tr key={s.model} data-testid={`as-if-played-row-${s.model}`}>
                <td>{s.final_rank}</td>
                <th scope="row">
                  <ModelBadge model={s.model} />
                </th>
                <td data-testid={`as-if-played-total-${s.model}`}>{pts(s.total)}</td>
                <td>{s.mean_per_gameweek.toFixed(1)}</td>
                <td>{pts(s.hit_points)}</td>
                <td data-testid={`as-if-played-live-from-${s.model}`}>{from === null ? "Not live yet" : `GW${from}`}</td>
              </tr>
            );
          })}
          {played.models
            .filter((m) => !m.available)
            .map((m) => (
              <tr key={m.id} data-testid={`as-if-played-row-${m.id}`}>
                <td>—</td>
                <th scope="row">
                  <ModelBadge model={m.id} />
                </th>
                <td colSpan={4} className="models-what models-unavailable">
                  Unavailable{m.unavailable_reason ? `: ${m.unavailable_reason}` : ""}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

/** Each gameweek's points per model, each cell saying in words whether it was replayed or live. */
function PerGameweek({ played }: { played: AsIfPlayed }) {
  const registry = useRegistry();
  const ids = orderIds(registry, played.models.filter((m) => m.available).map((m) => m.id));
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label="As if played, points per gameweek by model">
      <table className="models-table" data-testid="as-if-played-gw-table">
        <caption className="visually-hidden">
          Points per gameweek as if each model had played, each marked replayed or live
        </caption>
        <thead>
          <tr>
            <th scope="col">GW</th>
            {ids.map((m) => (
              <th scope="col" key={m}>
                {modelLabel(registry, m)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {played.gameweeks.map((g) => (
            <tr key={g.gameweek}>
              <th scope="row">{g.gameweek}</th>
              {ids.map((m) => {
                const e = g.models[m];
                return (
                  <td key={m} data-testid={`as-if-played-${g.gameweek}-${m}`}>
                    {e ? pts(e.points) : "—"}
                    {e && e.hit_points !== 0 ? <span className="models-hit"> ({pts(e.hit_points)})</span> : null}
                    {e?.record ? (
                      <span className="history-sub"> {e.record}</span>
                    ) : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The live season as if each model had played it (ORC-13), from `as_if_played.json`: each model's
 * own team from its first replayed gameweek, every gameweek labelled replayed (before the model
 * advised live) or live. Beside the ladder of its advice on your squad; not the 2025/26 replay.
 */
export function AsIfPlayedSection() {
  const { state } = useArtefact("as_if_played");
  if (state.status === "loading") return <p data-testid="as-if-played-loading">Loading the as-if-played season…</p>;
  if (state.status !== "ready") {
    return (
      <section className="models-season" data-testid="as-if-played-absent">
        <h2>This season, as if each model had played</h2>
        <p>{unready(state, ABSENT)}</p>
      </section>
    );
  }
  const played = state.data;
  return (
    <section className="models-season" data-testid="as-if-played">
      <h2>
        This season, as if each model had played{" "}
        <span className="season-phase season-phase-prospective" data-testid="as-if-played-kind">
          Live season {played.season}, as if played
        </span>
      </h2>
      <p className="models-note">
        Each model playing its own team from GW{played.gameweeks[0]?.gameweek ?? "—"}, picked under the budget,
        with its own transfers and hits: not your squad (the ladder above) and not the 2025/26 replay, which
        is on its own tab. <strong>Replayed</strong> gameweeks are before the model advised live;{" "}
        <strong>live</strong> ones are from then on.
      </p>
      <p className="history-caveat" role="note">
        {played.caveat}
      </p>
      <Ladder played={played} />
      <h3>Per gameweek, as if played</h3>
      <PerGameweek played={played} />
    </section>
  );
}
