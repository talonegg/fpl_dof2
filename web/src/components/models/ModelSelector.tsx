import { useRef } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useModel } from "../../data/DataProvider";
import {
  MODEL_CHOICES,
  MODEL_DESCRIPTIONS,
  MODEL_LABELS,
  MODEL_SHORT_LABELS,
  isComparison,
} from "../../data/model";
import type { ModelChoice } from "../../data/model";
import "./models.css";

/**
 * The model selector: champion (default) plus the four frozen comparison models.
 *
 * Two renderings of one choice, swapped by CSS at 768px so only one is ever visible (and the hidden
 * one is `display: none`, so it is out of the accessibility tree too):
 * - wide screens: a segmented control — an ARIA radiogroup with roving tabindex, arrow keys,
 *   Home/End, 44px targets;
 * - small screens: a native `<select>`, which every mobile OS renders as its own touch-friendly
 *   picker or bottom sheet.
 */
export function ModelSelector() {
  const { effective, setModel, available } = useModel();
  const refs = useRef<Partial<Record<ModelChoice, HTMLButtonElement | null>>>({});
  const enabled = MODEL_CHOICES.filter((m) => available.includes(m));

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const i = enabled.indexOf(effective);
    let next: ModelChoice | undefined;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = enabled[(i + 1) % enabled.length];
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp")
      next = enabled[(i - 1 + enabled.length) % enabled.length];
    else if (event.key === "Home") next = enabled[0];
    else if (event.key === "End") next = enabled[enabled.length - 1];
    if (!next) return;
    event.preventDefault();
    setModel(next);
    refs.current[next]?.focus();
  };

  const note = available.length === 1
    ? "Comparison models not published this run — showing the champion (live advice)."
    : isComparison(effective)
    ? `Comparison only — live advice is the champion. Showing ${MODEL_DESCRIPTIONS[effective]}.`
    : "Live advice: champion. Other models are comparisons.";

  return (
    <div className="model-toggle" data-testid="model-toggle">
      <div
        className="model-segmented"
        role="radiogroup"
        aria-label="Recommendation model"
        aria-describedby="model-selector-note"
        onKeyDown={onKeyDown}
        data-testid="model-segmented"
      >
        {MODEL_CHOICES.map((choice) => {
          const disabled = !available.includes(choice);
          const checked = effective === choice;
          return (
            <button
              key={choice}
              ref={(el) => {
                refs.current[choice] = el;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              aria-label={`${MODEL_LABELS[choice]}${isComparison(choice) ? " (comparison)" : " (live)"}`}
              tabIndex={checked ? 0 : -1}
              disabled={disabled}
              title={disabled ? "Not published this run" : MODEL_DESCRIPTIONS[choice]}
              className={`model-toggle-button${checked ? " active" : ""}`}
              data-testid={`model-toggle-${choice}`}
              onClick={() => setModel(choice)}
            >
              {MODEL_SHORT_LABELS[choice]}
            </button>
          );
        })}
      </div>
      <label className="model-select" data-testid="model-select-wrap">
        <span className="model-select-label">Model</span>
        <select
          value={effective}
          onChange={(e) => setModel(e.target.value as ModelChoice)}
          aria-describedby="model-selector-note"
          data-testid="model-select"
        >
          {MODEL_CHOICES.map((choice) => (
            <option key={choice} value={choice} disabled={!available.includes(choice)}>
              {MODEL_LABELS[choice]}
              {isComparison(choice) ? " — comparison" : " — live"}
            </option>
          ))}
        </select>
      </label>
      <span
        id="model-selector-note"
        className="model-toggle-note"
        role="status"
        data-testid="model-toggle-note"
      >
        {note}
      </span>
      {available.length > 1 && (
        <Link to="/models" className="model-toggle-diff" data-testid="model-diff-link">
          Compare all models
        </Link>
      )}
    </div>
  );
}
