import type { Meta } from "../contract/types";
import { formatLocalDateTime } from "../format";

interface HeaderProps {
  meta: Meta;
}

export function Header({ meta }: HeaderProps) {
  const priceDependence = meta.model.price_dependence;
  const showWarning = priceDependence === "repricing" || priceDependence === "thin";

  return (
    <header className="app-header" data-testid="header">
      <div className="app-header-row">
        <h1>FPL DOF</h1>
        <div className="app-header-meta">
          <span>{meta.season}</span>
          <span>Next GW {meta.next_gameweek}</span>
          <span>As at {formatLocalDateTime(meta.generated_at)}</span>
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
