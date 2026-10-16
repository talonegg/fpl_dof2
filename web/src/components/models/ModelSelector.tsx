import { useId, useRef } from "react";
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
import { PROVISIONAL_TITLE, ProvisionalBadge } from "./ProvisionalBadge";
import "./models.css";

/** Why a model cannot be picked right now. */
export const NOT_PUBLISHED_TITLE =
  "Not available: this model has no advice published for the current gameweek yet, or its inputs failed the freshness check.";

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
export function ModelSelector({
  available: availableOverride,
  value,
  onChange,
  label = "Recommendation model",
  showCompareLink = true,
  testId = "model-toggle",
  note: noteOverride,
  provisional: provisionalOverride,
}: {
  /** Standalone use (e.g. the model history page): which models can be picked. */
  available?: ModelChoice[];
  value?: ModelChoice;
  onChange?: (model: ModelChoice) => void;
  label?: string;
  showCompareLink?: boolean;
  testId?: string;
  /** Replaces the live/comparison note, for pages where the choice only highlights. */
  note?: string;
  /** Standalone use: which models' advice is provisional. */
  provisional?: ModelChoice[];
} = {}) {
  const prefix = testId === "model-toggle" ? "model" : testId;
  const global = useModel();
  const available = availableOverride ?? global.available;
  const effective = value ?? global.effective;
  const provisional = provisionalOverride ?? global.provisional;
  const setModel = onChange ?? global.setModel;
  const noteId = `model-selector-note-${useId().replace(/:/g, "")}`;
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
    <div className="model-toggle" data-testid={testId}>
      <div
        className="model-segmented"
        role="radiogroup"
        aria-label={label}
        aria-describedby={noteId}
        onKeyDown={onKeyDown}
        data-testid={`${prefix}-segmented`}
      >
        {MODEL_CHOICES.map((choice) => {
          const disabled = !available.includes(choice);
          const checked = effective === choice;
          const prov = !disabled && provisional.includes(choice);
          return (
            <button
              key={choice}
              ref={(el) => {
                refs.current[choice] = el;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              aria-label={`${MODEL_LABELS[choice]}${isComparison(choice) ? " (comparison)" : " (live)"}${prov ? " (provisional)" : ""}`}
              tabIndex={checked ? 0 : -1}
              disabled={disabled}
              title={
                disabled
                  ? NOT_PUBLISHED_TITLE
                  : prov
                  ? `${MODEL_DESCRIPTIONS[choice]}. ${PROVISIONAL_TITLE}`
                  : MODEL_DESCRIPTIONS[choice]
              }
              className={`model-toggle-button${checked ? " active" : ""}`}
              data-testid={`${testId}-${choice}`}
              onClick={() => setModel(choice)}
            >
              {MODEL_SHORT_LABELS[choice]}
              {prov && (
                <span className="provisional-dot" aria-hidden="true" data-testid={`${testId}-${choice}-provisional`}>
                  {" "}·P
                </span>
              )}
            </button>
          );
        })}
      </div>
      <label className="model-select" data-testid={`${prefix}-select-wrap`}>
        <span className="model-select-label">Model</span>
        <select
          value={effective}
          onChange={(e) => setModel(e.target.value as ModelChoice)}
          aria-describedby={noteId}
          data-testid={`${prefix}-select`}
        >
          {MODEL_CHOICES.map((choice) => (
            <option key={choice} value={choice} disabled={!available.includes(choice)}>
              {MODEL_LABELS[choice]}
              {isComparison(choice) ? " — comparison" : " — live"}
              {provisional.includes(choice) && available.includes(choice) ? " (provisional)" : ""}
            </option>
          ))}
        </select>
      </label>
      <span
        id={noteId}
        className="model-toggle-note"
        role="status"
        data-testid={`${testId}-note`}
      >
        {noteOverride ?? note}
      </span>
      {provisional.includes(effective) && <ProvisionalBadge testId={`${prefix}-provisional`} />}
      {showCompareLink && available.length > 1 && (
        <Link to="/models" className="model-toggle-diff" data-testid="model-diff-link">
          Compare all models
        </Link>
      )}
    </div>
  );
}
