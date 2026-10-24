import type { Models, Strategy } from "../../contract/types";
import { useData, useDataState, useRegistry } from "../../data/DataProvider";
import { unready, useArtefact } from "../../data/store";
import { ModelHistoryView } from "../history/ModelHistoryView";
import "../history/history.css";
import { AccuracySection } from "./AccuracySection";
import { ComparePanel } from "./ComparePanel";
import { ModelsSeasonView } from "./ModelsSeasonView";
import { ModelStatus, ProvisionalNote, unavailableNow } from "./ModelStatus";
import "./models.css";
import "./modelsPage.css";

function roleText({ role, published }: Strategy): string {
  if (role === "champion") return "Champion: its advice is the live advice";
  if (role === "experiment") return "Experiment, not published";
  return published ? "Comparison, run every refresh" : "Comparison, not yet run live";
}

function nowText(models: Models | null, s: Strategy): string {
  const unavailable = unavailableNow(models, s.id);
  if (unavailable) return unavailable;
  const last = models?.gameweeks[models.gameweeks.length - 1];
  if (last?.advice[s.id]) return `Advice published for GW${last.gameweek}`;
  return s.published ? "No advice in the season record yet" : "Not run live";
}

const HISTORY_ABSENT = "The models history has not been published yet.";

/**
 * `/models` — what each model is, from `strategies.json`: its role, what it plans, whether it is
 * advising now; then this gameweek's advice compared. This season is `/models/season`, the 2025/26
 * playthrough `/models/2025-26` (WEB-10).
 */
export function ModelsPage() {
  const { state } = useDataState();
  const data = state.status === "ready" ? state.data : null;
  const history = useArtefact("models_history").state;
  const registry = useRegistry();
  const models = data?.models ?? null;

  return (
    <div className="models-page" data-testid="models-page">
      <h1 className="models-page-title">Models</h1>
      <ProvisionalNote models={models} />
      <section className="models-page-section" aria-labelledby="models-outline-heading">
        <h2 id="models-outline-heading">What each model is</h2>
        <div className="models-detail-grid" data-testid="models-outline">
          {registry.entries
            .filter((e) => e.role !== "retired")
            .map((e) => (
              <article key={e.id} className="models-detail-card" data-testid={`models-outline-${e.id}`}>
                <h3>
                  {e.label}
                  <ModelStatus models={models} id={e.id} testId={`outline-${e.id}`} />
                </h3>
                <p>{e.description}</p>
                <dl>
                  <div>
                    <dt>Role</dt>
                    <dd data-testid={`outline-role-${e.id}`}>{roleText(e)}</dd>
                  </div>
                  <div>
                    <dt>Plans</dt>
                    <dd>{e.plan ? "A multi-gameweek plan, with chips" : "This gameweek only, without chips"}</dd>
                  </div>
                  <div>
                    <dt>Now</dt>
                    <dd data-testid={`outline-now-${e.id}`}>{nowText(models, e)}</dd>
                  </div>
                </dl>
              </article>
            ))}
        </div>
      </section>

      {data && (
        <ComparePanel
          data={data}
          history={history.status === "ready" ? history.data : null}
          historyWhy={unready(history, HISTORY_ABSENT)}
        />
      )}
    </div>
  );
}

/**
 * `/models/season` — the live season: the ladder of each model's advice on your squad and how its
 * xP compared with the points scored. Drop B adds the "as if played" ladder (ORC-13) and underlying
 * xP (ORC-12) here.
 */
export function ModelsSeasonPage() {
  const { models } = useData();
  return (
    <div className="models-page" data-testid="models-season-page">
      <ProvisionalNote models={models} />
      <ModelsSeasonView models={models} />
      <AccuracySection kinds={["replay", "prospective"]} />
    </div>
  );
}

/** `/models/2025-26` — how each model would have played 2025/26 (the backtest's models history). */
export function ModelsBacktestPage() {
  const { state: history, retry } = useArtefact("models_history");
  return (
    <div className="models-page" data-testid="models-backtest">
      {history.status === "loading" ? (
        <p data-testid="history-loading">Loading the model history…</p>
      ) : history.status === "ready" ? (
        <ModelHistoryView history={history.data} />
      ) : (
        <section className="models-page-section">
          <h2>Past-season playthrough</h2>
          <p data-testid="history-absent">
            {history.status === "absent" ? HISTORY_ABSENT : `The models history is unavailable: ${unready(history, HISTORY_ABSENT)}`}{" "}
            {history.status !== "absent" && (
              <button type="button" onClick={retry}>
                Try again
              </button>
            )}
          </p>
        </section>
      )}
      <AccuracySection kinds={["backtest"]} />
    </div>
  );
}
