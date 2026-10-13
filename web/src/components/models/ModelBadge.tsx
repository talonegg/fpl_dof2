import { useModel } from "../../data/DataProvider";
import { MODEL_LABELS, isComparison } from "../../data/model";
import type { ModelChoice } from "../../data/model";

/**
 * Which model a recommendation came from. Shown on every recommendation. Without an explicit
 * model it names the model the on-screen week came from (champion, or C1 when chosen). Anything
 * but the champion is marked as a comparison: live advice is the champion's alone.
 */
export function ModelBadge({ model }: { model?: ModelChoice }) {
  const { weekModel } = useModel();
  const shown = model ?? weekModel;
  const comparison = isComparison(shown);
  return (
    <span
      className={`model-badge model-badge-${shown}`}
      data-testid="model-badge"
      data-model={shown}
    >
      {MODEL_LABELS[shown]}
      {comparison && <span className="model-badge-tag"> · comparison</span>}
    </span>
  );
}
