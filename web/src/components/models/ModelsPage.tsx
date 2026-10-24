import { Navigate, useSearchParams } from "react-router-dom";
import type { Models, Strategy } from "../../contract/types";
import { useData, useDataState, useRegistry } from "../../data/DataProvider";
import { useArtefact } from "../../data/store";
import type { ArtefactState } from "../../data/store";
import { ModelHistoryView } from "../history/ModelHistoryView";
import "../history/history.css";
import { LastGameweek } from "../review/LastGameweek";
import { AccuracySection } from "./AccuracySection";
import { ComparePanel } from "./ComparePanel";
import { ModelsSeasonView } from "./ModelsSeasonView";
import { ModelStatus, ProvisionalNote, unavailableNow } from "./ModelStatus";
import "./models.css";
import "./modelsPage.css";

/** Old `?section=` links to the parts that moved to their own tab (WEB-07, WEB-10). */
const MOVED: Record<string, string> = {
  history: "/models/2025-26",
  hindsight: "/review",
  accuracy: "/models/season",
};

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

/** The sections below only ask "still loading?" and "what data, if any?": a missing or unreadable
 * history or accuracy file explains its own section (DP-15). */
function settled<T>(state: ArtefactState<T>): { status: "loading" | "settled"; data: T | null } {
  if (state.status === "loading") return { status: "loading", data: null };
  return { status: "settled", data: state.status === "ready" ? state.data : null };
}

/**
 * `/models` — what each model is, from `strategies.json`: its role, what it plans, whether it is
 * advising now; then this gameweek's advice compared. This season is `/models/season`, the 2025/26
 * playthrough `/models/2025-26` (WEB-10).
 */
export function ModelsPage() {
  const { state } = useDataState();
  const data = state.status === "ready" ? state.data : null;
  const history = settled(useArtefact("models_history").state);
  const [params] = useSearchParams();
  const registry = useRegistry();
  const moved = MOVED[params.get("section") ?? ""];
  if (moved) return <Navigate to={moved} replace />;
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

      {data && <ComparePanel data={data} history={history.data} />}
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
  const accuracy = settled(useArtefact("xp_accuracy").state);
  return (
    <div className="models-page" data-testid="models-season-page">
      <ProvisionalNote models={models} />
      <ModelsSeasonView models={models} />
      <AccuracySection
        accuracy={accuracy.data}
        status={accuracy.status === "loading" ? "loading" : "ready"}
        kinds={["replay", "prospective"]}
      />
    </div>
  );
}

/** `/models/2025-26` — how each model would have played 2025/26 (the backtest's models history). */
export function ModelsBacktestPage() {
  const history = settled(useArtefact("models_history").state);
  const accuracy = settled(useArtefact("xp_accuracy").state);
  return (
    <div className="models-page" data-testid="models-backtest">
      {history.status === "loading" ? (
        <p data-testid="history-loading">Loading the model history…</p>
      ) : history.data ? (
        <ModelHistoryView history={history.data} />
      ) : (
        <section className="models-page-section">
          <h2>2025/26 playthrough</h2>
          <p data-testid="history-absent">The models history has not been published yet.</p>
        </section>
      )}
      <AccuracySection
        accuracy={accuracy.data}
        status={accuracy.status === "loading" ? "loading" : "ready"}
        kinds={["backtest"]}
      />
    </div>
  );
}

/** `/review` — last gameweek: each model, you and the hindsight optimum (WEB-11). */
export function HindsightPage() {
  return <LastGameweek />;
}
