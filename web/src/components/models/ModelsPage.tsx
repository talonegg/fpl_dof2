import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import type { Models, ModelsHistory } from "../../contract/types";
import { useDataState, useRegistry } from "../../data/DataProvider";
import { useArtefact } from "../../data/store";
import { ModelHistoryView } from "../history/ModelHistoryView";
import { SeasonView } from "../history/SeasonView";
import "../history/history.css";
import { useLog } from "../log/useLog";
import { AccuracySection } from "./AccuracySection";
import type { XpAccuracy } from "./accuracy";
import { HindsightSection } from "./HindsightSection";
import { ModelBadge } from "./ModelBadge";
import { ComparePanel } from "./ComparePanel";
import { ModelsSeasonView } from "./ModelsSeasonView";
import { ProvisionalBadge } from "./ProvisionalBadge";
import "./models.css";
import "./modelsPage.css";

const SECTIONS = [
  ["compare", "Compare"],
  ["summary", "Summary"],
  ["details", "Details"],
  ["accuracy", "Accuracy"],
  ["hindsight", "Hindsight"],
  ["history", "History"],
] as const;


function unavailableNow(models: Models | null, m: string): string | null {
  const last = models?.gameweeks[models.gameweeks.length - 1];
  const a = last?.availability?.[m];
  return a && a.available === false ? `Unavailable for GW${last?.gameweek}${a.reason ? `: ${a.reason}` : ""}` : null;
}

/** (a) One row per model. */
function SummaryTable({ history, accuracy, models }: { history: ModelsHistory | null; accuracy: XpAccuracy | null; models: Models | null }) {
  const registry = useRegistry();
  const back = new Map(history?.summary.map((s) => [s.model, s]) ?? []);
  const acc = (season: string) => accuracy?.seasons.find((s) => s.season === season);
  const a2526 = acc("2025/26");
  const a2627 = acc("2026/27");
  const f = (v: number | undefined, dp: number) => (v === undefined ? "—" : v.toFixed(dp));
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="models-summary-heading">
      <table className="models-table models-summary" data-testid="models-summary">
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">What it is</th>
            <th scope="col">
              Backtest XI pts/GW <span className="history-sub">2025/26</span>
            </th>
            <th scope="col">
              xP MAE <span className="history-sub">2025/26</span>
            </th>
            <th scope="col">
              xP MAE <span className="history-sub">2026/27 GW1–6 replay</span>
            </th>
            <th scope="col">Status / caveat</th>
          </tr>
        </thead>
        <tbody>
          {registry.entries.filter((e) => e.role !== "retired").map(({ id: m, description, role, published }) => {
            const b = back.get(m);
            const now = unavailableNow(models, m);
            const last = models?.gameweeks[models.gameweeks.length - 1];
            const prov = !!last?.provisional && last.advice[m] !== undefined;
            return (
              <tr key={m} data-testid={`models-summary-${m}`}>
                <th scope="row">
                  <ModelBadge model={m} />
                  {prov && (
                    <>
                      {" "}
                      <ProvisionalBadge testId={`summary-provisional-${m}`} />
                    </>
                  )}
                </th>
                <td className="models-what">{description}</td>
                <td data-testid={`summary-xi-${m}`}>{f(b?.mean_per_gameweek, 2)}</td>
                <td data-testid={`summary-mae-${m}`}>{f(a2526?.pooled_mae[m], 3)}</td>
                <td>{f(a2627?.pooled_mae[m], 3)}</td>
                <td className="models-what">
                  <strong>
                    {role === "champion"
                      ? "Champion — live advice"
                      : role === "experiment"
                        ? "Experiment, not published"
                        : published
                          ? "Comparison"
                          : "Comparison, not yet live"}
                    .
                  </strong>
                  {now ? <span className="models-unavailable"> {now}.</span> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * `/models` — every frozen model on one page: (a) summary, (b) per-model details, (c) xP accuracy,
 * (d) history (2025/26 backtest, 2026/27 replay then live). `/history` redirects to the History
 * section. Every part degrades on its own: a missing file hides or explains its section only.
 */
export function ModelsPage() {
  const { state } = useDataState();
  const data = state.status === "ready" ? state.data : null;
  const history = useArtefact("models_history_2526");
  const replay = useArtefact("models_history_2627_replay");
  const accuracy = useArtefact("xp_accuracy");
  const { state: logState } = useLog();
  const [params] = useSearchParams();
  const section = params.get("section");
  const allLoaded = history.status === "ready" && replay.status === "ready" && accuracy.status === "ready";
  useEffect(() => {
    if (section && allLoaded) document.getElementById(`models-${section}`)?.scrollIntoView?.({ block: "start" });
  }, [section, allLoaded]);
  const models = data?.models ?? null;
  const registry = useRegistry();

  return (
    <div className="models-page" data-testid="models-page">
      <h1 className="models-page-title">Models</h1>
      <nav className="models-page-nav" aria-label="Models page sections">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#/models?section=${id}`} data-testid={`models-jump-${id}`}>
            {label}
          </a>
        ))}
      </nav>

      {data && <ComparePanel data={data} history={history.data} />}

      <section className="models-page-section" id="models-summary" aria-labelledby="models-summary-heading">
        <h2 id="models-summary-heading">Summary</h2>
        {models?.provisional && (
          <p className="models-provisional-note" data-testid="models-provisional-note">
            <ProvisionalBadge testId="models-provisional-banner" /> GW
            {models.gameweeks[models.gameweeks.length - 1]?.gameweek} advice is a preview of each model’s current pick. It
            freezes at the decision window before the deadline, when the frozen decision replaces it.
          </p>
        )}
        <SummaryTable history={history.data} accuracy={accuracy.data} models={models} />
        <p className="models-note">
          Backtest XI pts/GW: realistic walk-forward 2025/26 (auto-subs, vice fallback, hits, no chips) — not real play. xP
          MAE: all-player mean absolute error of next-GW xP, lower is better. “—” = no data for that model.
        </p>
      </section>

      <section className="models-page-section" id="models-details" aria-labelledby="models-details-heading">
        <h2 id="models-details-heading">Details</h2>
        <div className="models-detail-grid" data-testid="models-details">
          {registry.entries.filter((e) => e.role !== "retired").map((e) => {
            const b = history.data?.summary.find((x) => x.model === e.id);
            return (
              <article key={e.id} className="models-detail-card" data-testid={`models-detail-${e.id}`}>
                <h3>
                  {e.label} <span className="history-sub">({e.id})</span>
                </h3>
                <p>{e.description}</p>
                <dl>
                  <div>
                    <dt>Role</dt>
                    <dd>
                      {e.role}
                      {e.published ? ", published" : ", not yet published"}
                    </dd>
                  </div>
                  {b && (
                    <div>
                      <dt>2025/26 backtest</dt>
                      <dd>
                        {Math.round(b.total)} pts, rank {b.final_rank} of {history.data?.summary.length}
                      </dd>
                    </div>
                  )}
                </dl>
              </article>
            );
          })}
        </div>
        {data && <ModelsSeasonView models={data.models} />}
      </section>

      <AccuracySection accuracy={accuracy.data} status={accuracy.status === "loading" ? "loading" : "ready"} />

      <HindsightSection
        log={logState.status === "ready" ? logState.log : null}
        players={data?.players ?? null}
        status={logState.status}
      />

      <section className="models-page-section" id="models-history" aria-labelledby="models-history-heading">
        <h2 id="models-history-heading">History</h2>
        <SeasonView replay={replay.data} models={models} />
        {history.status === "loading" ? (
          <p data-testid="history-loading">Loading the model history…</p>
        ) : history.data ? (
          <ModelHistoryView history={history.data} />
        ) : (
          <p data-testid="history-absent">The 2025/26 backtest file could not be loaded.</p>
        )}
      </section>
    </div>
  );
}
