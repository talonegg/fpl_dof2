import { useModel, useRegistry } from "../../data/DataProvider";
import { isComparison, modelLabel, seriesStyle } from "../../data/registry";

/**
 * Which strategy a recommendation came from. Shown on every recommendation. Without an explicit
 * model it names the strategy the on-screen week came from. Anything but the champion is marked as
 * a comparison: live advice is the champion's alone.
 */
export function ModelBadge({ model }: { model?: string }) {
  const { effective } = useModel();
  const registry = useRegistry();
  const shown = model ?? effective;
  return (
    <span
      className="model-badge"
      style={{ borderColor: seriesStyle(registry, shown).colour }}
      data-testid="model-badge"
      data-model={shown}
    >
      {modelLabel(registry, shown)}
      {isComparison(registry, shown) && <span className="model-badge-tag"> · comparison</span>}
    </span>
  );
}
