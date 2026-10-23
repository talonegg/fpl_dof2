import type { Meta } from "../contract/types";
import { formatLocalDateTime } from "../format";

interface HeaderProps {
  meta: Meta;
}

/** `schedule`, `manual`, `day-before` or `change:<kinds>` in words. */
export function describeTrigger(trigger: string): string {
  if (trigger.startsWith("change:")) {
    return `after a ${trigger.slice("change:".length).split(",").join(", ")} change`;
  }
  const words: Record<string, string> = {
    schedule: "scheduled run",
    manual: "manual run",
    "day-before": "day-before refresh",
  };
  return words[trigger] ?? trigger;
}

export function Header({ meta }: HeaderProps) {
  const priceDependence = meta.model.price_dependence;
  const showWarning = priceDependence === "repricing" || priceDependence === "thin";

  return (
    <header className="app-header" data-testid="header">
      {/* The app's title is the shell's `h1` (E6-S1). This banner describes the *run*: which
          season, which gameweek, how fresh, and how much the forecast can be trusted. */}
      <div className="app-header-row">
        <div className="app-header-meta">
          <span>{meta.season}</span>
          <span>Next GW {meta.next_gameweek}</span>
          {/* The snapshot the advice was decided on, and what started the run (ORC-03). */}
          <span data-testid="header-as-at">
            As at {formatLocalDateTime(meta.as_of ?? meta.generated_at)}
            {meta.trigger ? ` · ${describeTrigger(meta.trigger)}` : ""}
          </span>
        </div>
      </div>

      {showWarning ? (
        <div
          className="model-warning model-warning-loud"
          data-testid="model-warning"
          role="alert"
        >
          <strong>Caution:</strong> this forecast is {priceDependence === "repricing"
            ? "dominated by price and position alone (repricing)"
            : "thinly supported (little beyond price and position)"}
          {" "}— r² on price {meta.model.r_squared_on_price.toFixed(2)}. Treat expected points as
          low-confidence until the model has more data.
        </div>
      ) : (
        <div className="model-warning model-warning-quiet" data-testid="model-warning">
          Model {meta.model.name}: r² on price {meta.model.r_squared_on_price.toFixed(2)} —
          forecast is informative beyond price alone.
        </div>
      )}
    </header>
  );
}
