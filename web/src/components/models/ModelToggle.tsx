import { Link } from "react-router-dom";
import { useModel } from "../../data/DataProvider";
import { MODEL_DESCRIPTIONS, MODEL_LABELS } from "../../data/model";
import type { ModelChoice } from "../../data/model";
import "./models.css";

const CHOICES: ModelChoice[] = ["champion", "challenger"];

/** Champion/challenger switch. Champion is the default; the choice is remembered. */
export function ModelToggle() {
  const { effective, setModel, challengerAvailable } = useModel();
  return (
    <div className="model-toggle" data-testid="model-toggle">
      <div className="model-toggle-buttons" role="radiogroup" aria-label="Recommendation model">
        {CHOICES.map((choice) => {
          const disabled = choice === "challenger" && !challengerAvailable;
          return (
            <button
              key={choice}
              type="button"
              role="radio"
              aria-checked={effective === choice}
              disabled={disabled}
              title={disabled ? "No challenger published this run" : MODEL_DESCRIPTIONS[choice]}
              className={`model-toggle-button${effective === choice ? " active" : ""}`}
              data-testid={`model-toggle-${choice}`}
              onClick={() => setModel(choice)}
            >
              {MODEL_LABELS[choice]}
            </button>
          );
        })}
      </div>
      <span className="model-toggle-note" data-testid="model-toggle-note">
        {challengerAvailable
          ? `Showing: ${MODEL_DESCRIPTIONS[effective]}`
          : "Challenger not published this run — showing the champion"}
      </span>
      {challengerAvailable && (
        <Link to="/models" className="model-toggle-diff" data-testid="model-diff-link">
          Compare side by side
        </Link>
      )}
    </div>
  );
}
