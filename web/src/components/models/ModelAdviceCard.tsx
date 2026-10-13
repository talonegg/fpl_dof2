import type { ModelAdvice, ModelGameweek } from "../../contract/types";
import { formatPoints } from "../../format";
import { MODEL_DESCRIPTIONS } from "../../data/model";
import type { ModelChoice } from "../../data/model";
import { ModelBadge } from "./ModelBadge";
import "./models.css";

export function transfersText(advice: ModelAdvice): string {
  const moves =
    advice.transfers.length > 0
      ? advice.transfers.map((t) => `${t.out_name} → ${t.in_name}`).join(", ")
      : "Roll (no transfer)";
  return advice.hit_points !== 0 ? `${moves} (${advice.hit_points} hit)` : moves;
}

/**
 * One frozen model's pre-deadline advice from models.json, clearly marked as a comparison. Used for
 * the models that do not ship a full week (engine, A, A+odds).
 */
export function ModelAdviceCard({
  model,
  gameweek,
}: {
  model: ModelChoice;
  gameweek: ModelGameweek;
}) {
  const advice = gameweek.advice[model];
  if (!advice) return null;
  return (
    <section
      className="dash-recommendation model-advice-card"
      aria-labelledby="model-advice-heading"
      data-testid="model-advice-card"
      data-model={model}
    >
      <h2 id="model-advice-heading">
        GW{gameweek.gameweek} <ModelBadge model={model} />
      </h2>
      <p className="model-comparison-banner" role="note" data-testid="model-comparison-banner">
        Comparison only — not live advice. Follow the champion. {MODEL_DESCRIPTIONS[model]}, frozen
        model, decided before the deadline.
      </p>
      <dl className="model-advice-grid">
        <dt>Transfers</dt>
        <dd data-testid="model-advice-transfers">{transfersText(advice)}</dd>
        <dt>Captain</dt>
        <dd data-testid="model-advice-captain">{advice.captain_name}</dd>
        <dt>Vice</dt>
        <dd>{advice.vice_name}</dd>
        <dt>xPts</dt>
        <dd>{formatPoints(advice.expected_points)}</dd>
        <dt>XI</dt>
        <dd>{advice.starting_names.join(", ")}</dd>
        <dt>Bench</dt>
        <dd>{advice.bench_names.join(", ") || "—"}</dd>
      </dl>
    </section>
  );
}
