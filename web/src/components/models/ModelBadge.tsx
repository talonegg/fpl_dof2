import { useModel } from "../../data/DataProvider";
import { MODEL_LABELS } from "../../data/model";
import type { ModelChoice } from "../../data/model";

/** Which model a recommendation came from. Shown on every recommendation (champion/challenger). */
export function ModelBadge({ model }: { model?: ModelChoice }) {
  const { effective } = useModel();
  const shown = model ?? effective;
  return (
    <span
      className={`model-badge model-badge-${shown}`}
      data-testid="model-badge"
      data-model={shown}
    >
      {MODEL_LABELS[shown]}
    </span>
  );
}
