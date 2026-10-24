import { useId, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { LogGameweek, LogHindsightOptimal, LogHindsightPlan, LogOracleDiagnostic, ModelGameweek } from "../../contract/types";
import { useData, useRegistry } from "../../data/DataProvider";
import { modelLabel, orderIds, resolveModel } from "../../data/registry";
import { transfersText } from "../../data/season";
import { useArtefact } from "../../data/store";
import { formatHits, formatPoints, plural, signed } from "../../format";
import { ModelBadge } from "../models/ModelBadge";
import { OptionsTable, movesText, planGain, planPoints } from "../OptionsTable";
import { rankBy } from "../models/rank";
import "../models/models.css";
import "../models/modelsPage.css";
import "./review.css";

/** The owner's own row in the evaluation's rankings: the one that is not a strategy. */
const PLAYED = "played";


const CATEGORY: Record<LogOracleDiagnostic["category"], string> = {
  model_blindspot: "Model blind spot",
  high_variance_outlier: "High-variance haul",
  captaincy_trap: "Captaincy trap",
};

interface Row {
  key: string;
  who: ReactNode;
  did: string;
  xp: number | null;
  points: number | null;
}

/** What you did, from the game's record and the reconciliation against the advice. */
function playedText(gw: LogGameweek | undefined, name: (id: number | null) => string): string {
  if (!gw) return "Not in the season log";
  const parts = [`captain ${name(gw.played.captain)}`];
  if (gw.score) parts.unshift(`${plural(gw.score.transfers, "transfer")}${gw.score.transfers_cost ? ` (${formatHits(gw.score.transfers_cost)})` : ""}`);
  if (gw.chip) parts.push(`chip ${gw.chip}`);
  const r = gw.reconciliation;
  const unexplained = r?.divergences.filter((d) => d.status === "unexplained").length ?? 0;
  parts.push(
    !r
      ? "no advice recorded"
      : r.followed
        ? "followed the advice"
        : unexplained > 0
          ? `${plural(unexplained, "unexplained difference")} from the advice`
          : "overrode the advice",
  );
  return parts.join(" · ");
}

/** One of the three options in a comparison cell: its moves, net and gain over the roll. */
function optionCell(plan: LogHindsightPlan | null, realised: boolean, roll: boolean): string {
  if (!plan) return "—";
  const net = planPoints(plan.net_points, realised);
  return roll ? net : `${movesText(plan)} · ${net} (${planGain(plan.gain_over_roll, realised)})`;
}

/**
 * What each model weighed at the deadline, on its own xP, beside what the hindsight weighed on the
 * points that happened (ORC-11): the same three options, so the miss is visible option by option.
 */
function WeighedTable({
  gameweek,
  hindsight,
  ids,
  advice,
}: {
  gameweek: number;
  hindsight: LogHindsightOptimal | null;
  ids: string[];
  advice: ModelGameweek["advice"];
}) {
  const captionId = useId();
  const row = (key: string, who: ReactNode, set: LogHindsightOptimal | undefined | null, realised: boolean) => (
    <tr key={key} data-testid={`review-weighed-${key}`}>
      <th scope="row">{who}</th>
      {set ? (
        <>
          <td>{optionCell(set.baseline_roll, realised, true)}</td>
          <td className="models-what">{optionCell(set.optimal_single, realised, false)}</td>
          <td className="models-what">{optionCell(set.optimal_overall, realised, set.optimal_overall.transfers_count === 0)}</td>
        </>
      ) : (
        <td colSpan={3}>Not recorded at the deadline</td>
      )}
    </tr>
  );
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-labelledby={captionId}>
      <table className="models-table" data-testid="review-weighed">
        <caption id={captionId} className="models-caption">
          GW{gameweek}: the options each model weighed on its xP, beside the hindsight on the points that happened
        </caption>
        <thead>
          <tr>
            <th scope="col">Who</th>
            <th scope="col">Roll</th>
            <th scope="col">Best single transfer</th>
            <th scope="col">Best overall</th>
          </tr>
        </thead>
        <tbody>
          {hindsight && row("optimum", "Hindsight (points)", hindsight, true)}
          {ids.map((m) => row(m, <ModelBadge model={m} />, advice[m]?.option_set, false))}
        </tbody>
      </table>
    </div>
  );
}

/** The players who decided the optimum, and why the models missed them. */
function Diagnostics({ diagnostics }: { diagnostics: LogOracleDiagnostic[] }) {
  const registry = useRegistry();
  if (diagnostics.length === 0) return <p className="models-note">Nothing stood out: no blind spot, haul or captaincy trap.</p>;
  const label = (key: string) => modelLabel(registry, resolveModel(registry, key) ?? key);
  return (
    <ul className="review-diagnostics" data-testid="review-diagnostics">
      {diagnostics.map((d) => {
        // Evaluations before ORC-12 published a team's xP keyed by its captain as models_xp (D-37);
        // the per-player xP comes with underlying_points, so its presence marks a reliable one.
        const reliable = d.underlying_points !== undefined;
        const xps = Object.entries(d.models_xp);
        return (
          <li key={`${d.role}-${d.player_id}`} className="review-diagnostic" data-testid={`review-diagnostic-${d.player_id}`}>
            <p>
              <span className="review-tag">{CATEGORY[d.category]}</span> <strong>{d.player_name}</strong>,{" "}
              {d.role === "captain" ? "the optimum's captain" : "brought in by the optimum"}: {d.actual_points} pts
              {d.underlying_points != null && <> ({formatPoints(d.underlying_points)} underlying xP)</>}
            </p>
            <p>{d.explanation}</p>
            {reliable && xps.length > 0 && (
              <p data-testid={`review-diagnostic-xp-${d.player_id}`}>
                Each model&rsquo;s xP for him: {xps.map(([m, xp]) => `${label(m)} ${formatPoints(xp)}`).join(", ")}.
              </p>
            )}
            {d.models_trapped.length > 0 && <p>Caught out: {d.models_trapped.map(label).join(", ")}.</p>}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * `/review` — one evaluated gameweek (the latest by default, any earlier one by choice): every
 * model's advice against what you played and against what happened, the hindsight optimum with its
 * options, and the players that decided it (WEB-11). Points come from `models.json` and `log.json`;
 * either missing leaves the other's rows standing (DP-15). Each model's own options, recorded with
 * its advice at the deadline and published in `models.json`, sit beside the hindsight's (ORC-11).
 */
export function LastGameweek() {
  const { players, models } = useData();
  const registry = useRegistry();
  const { state, retry } = useArtefact("log");
  const selectId = useId();
  const log = state.status === "ready" ? state.data : null;
  const names = useMemo(() => new Map(players.players.map((p) => [p.id, p.name])), [players]);
  const name = (id: number | null) => (id === null ? "—" : (names.get(id) ?? `#${id}`));

  const gameweeks = useMemo(
    () =>
      [
        ...new Set([
          ...(log?.gameweeks.filter((g) => g.score !== null || g.hindsight).map((g) => g.gameweek) ?? []),
          ...(models?.gameweeks.filter((g) => g.actual).map((g) => g.gameweek) ?? []),
        ]),
      ].sort((a, b) => a - b),
    [log, models],
  );
  const [chosen, setChosen] = useState<number | null>(null);
  const gameweek = chosen ?? gameweeks[gameweeks.length - 1] ?? null;

  if (state.status === "loading") {
    return (
      <section className="models-page" data-testid="review-loading">
        <h1>Last gameweek</h1>
        <p>Loading the season log…</p>
      </section>
    );
  }

  const logProblem =
    state.status === "absent"
      ? "No season log is published yet, so your points and the hindsight optimum are missing."
      : state.status !== "ready"
        ? "The season log could not be loaded, so your points and the hindsight optimum are missing."
        : null;

  if (gameweek === null) {
    return (
      <section className="models-page" data-testid="review-empty">
        <h1>Last gameweek</h1>
        <p>Nothing has been evaluated yet. A gameweek appears here once it is finished and its points are scored.</p>
        {logProblem && <p>{logProblem}</p>}
      </section>
    );
  }

  const lg = log?.gameweeks.find((g) => g.gameweek === gameweek);
  const mg: ModelGameweek | undefined = models?.gameweeks.find((g) => g.gameweek === gameweek);
  const hindsight = lg?.hindsight ?? null;
  const ranking = new Map(
    (hindsight?.rankings ?? []).map((r) => [r.model_name === PLAYED ? PLAYED : (resolveModel(registry, r.model_name) ?? r.model_name), r]),
  );
  const ids = orderIds(registry, [...(models?.models.map((m) => m.id) ?? []), ...[...ranking.keys()].filter((k) => k !== PLAYED)]);
  const you = ranking.get(PLAYED);
  const yours = lg?.score?.points ?? you?.score.net_points ?? null;

  const rows: Row[] = [
    {
      key: PLAYED,
      who: <strong>You</strong>,
      did: playedText(lg, name),
      // Your team carries no forecast of its own; the advice's xP is on the champion's row.
      xp: null,
      points: yours,
    },
    ...ids.map((m): Row => {
      const advice = mg?.advice[m];
      const rk = ranking.get(m);
      const availability = mg?.availability[m];
      return {
        key: m,
        who: <ModelBadge model={m} />,
        did: advice
          ? `${transfersText(advice)} · captain ${advice.captain_name}`
          : rk
            ? `captain ${name(rk.score.captain_id)}`
            : availability?.available === false
              ? `Unavailable${availability.reason ? `: ${availability.reason}` : ""}`
              : "No advice recorded",
        xp: advice?.expected_points ?? rk?.score.expected_points ?? null,
        points: mg?.actual?.[m]?.points ?? rk?.score.net_points ?? null,
      };
    }),
  ];
  const ranked = rankBy(rows, (r) => r.points);
  const optimum = hindsight?.optimal?.optimal_overall ?? null;

  return (
    <div className="models-page" data-testid="review">
      <h1>Last gameweek</h1>
      <div className="review-picker">
        <label htmlFor={selectId}>Gameweek</label>
        <select
          id={selectId}
          value={gameweek}
          onChange={(e) => setChosen(Number(e.target.value))}
          data-testid="review-gameweek"
        >
          {gameweeks.map((g) => (
            <option key={g} value={g}>
              GW{g}
              {g === gameweeks[gameweeks.length - 1] ? " (latest)" : ""}
            </option>
          ))}
        </select>
      </div>
      {logProblem && (
        <p className="models-note" data-testid="review-log-problem">
          {logProblem}{" "}
          <button type="button" onClick={retry}>
            Try again
          </button>
        </p>
      )}
      {mg && mg.record !== "live" && (
        <p className="models-note" data-testid="review-frozen-note">
          GW{gameweek} is from the frozen record: each model&rsquo;s points are its own virtual team&rsquo;s, not advice on your
          squad.
        </p>
      )}

      <section className="models-page-section" aria-labelledby="review-models-caption">
        <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="review-models-caption">
          <table className="models-table" data-testid="review-models">
            <caption id="review-models-caption" className="models-caption">
              GW{gameweek}: each model&rsquo;s advice against what you played and what happened
            </caption>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Who</th>
                <th scope="col">Advice, or what you did</th>
                <th scope="col">xP before the deadline</th>
                <th scope="col">Points</th>
                <th scope="col">Against you</th>
              </tr>
            </thead>
            <tbody>
              {optimum && (
                <tr data-testid="review-row-optimum" className="is-best">
                  <td>—</td>
                  <th scope="row">Hindsight optimum</th>
                  <td className="models-what">
                    {movesText(optimum)} · captain {optimum.captain_name} (the best legal move, knowing the points)
                  </td>
                  <td>—</td>
                  <td data-testid="review-points-optimum">
                    <strong>{optimum.net_points}</strong>
                  </td>
                  <td>{yours === null ? "—" : signed(optimum.net_points - yours, 0)}</td>
                </tr>
              )}
              {ranked.map(({ item: r, rank }) => (
                <tr key={r.key} data-testid={`review-row-${r.key}`}>
                  <td>{rank ?? "—"}</td>
                  <th scope="row">{r.who}</th>
                  <td className="models-what" data-testid={`review-did-${r.key}`}>
                    {r.did}
                  </td>
                  <td>{r.xp === null ? "—" : formatPoints(r.xp)}</td>
                  <td data-testid={`review-points-${r.key}`}>{r.points === null ? "—" : Math.round(r.points)}</td>
                  <td>{r.key === PLAYED || r.points === null || yours === null ? "—" : signed(Math.round(r.points - yours), 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="models-note">
          Points are the final XI after automatic substitutions and the captain&rsquo;s armband, net of hits. Against you is
          each row&rsquo;s points minus yours.
        </p>
      </section>

      <section className="models-page-section" aria-labelledby="review-optimum-heading">
        <h2 id="review-optimum-heading">The hindsight optimum</h2>
        {!lg ? (
          <p className="models-note" data-testid="review-no-optimal">
            {logProblem ?? `GW${gameweek} is not in the season log.`}
          </p>
        ) : !hindsight?.optimal ? (
          <p className="models-note" data-testid="review-no-optimal">
            {hindsight?.optimal_unavailable_reason ?? `The hindsight optimum was not worked out for GW${gameweek}.`}
          </p>
        ) : (
          <>
            <OptionsTable
              optimal={hindsight.optimal}
              caption={`GW${gameweek} hindsight options, scored on the points that happened`}
              realised
              testId="review-options"
            />
            <p className="models-note">
              Best overall XI: {hindsight.optimal.optimal_overall.starting.map(name).join(", ")}.
            </p>
            <h3>The players who decided it</h3>
            <Diagnostics diagnostics={hindsight.diagnostics} />
          </>
        )}
      </section>

      <section className="models-page-section" aria-labelledby="review-weighed-heading">
        <h2 id="review-weighed-heading">What each model weighed</h2>
        {ids.some((m) => mg?.advice[m]?.option_set) ? (
          <WeighedTable gameweek={gameweek} hindsight={hindsight?.optimal ?? null} ids={ids} advice={mg?.advice ?? {}} />
        ) : (
          <p className="models-note" data-testid="review-no-weighed">
            No model&rsquo;s options were recorded at the GW{gameweek} deadline: they are kept from R1.4.1 on.
          </p>
        )}
      </section>
    </div>
  );
}
