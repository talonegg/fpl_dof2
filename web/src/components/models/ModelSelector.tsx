import { useId, useRef } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useModel, useRegistry } from "../../data/DataProvider";
import { findStrategy, isComparison, modelDescription, modelLabel, orderIds } from "../../data/registry";
import type { ModelChoice } from "../../data/model";
import { PROVISIONAL_TITLE, ProvisionalBadge } from "./ProvisionalBadge";
import "./models.css";

/**
 * The model selector: every published strategy that has a week, the champion first.
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
  const registry = useRegistry();
  const available = availableOverride ?? global.available;
  const effective = value ?? global.effective;
  const provisional = provisionalOverride ?? global.provisional;
  const setModel = onChange ?? global.setModel;
  const noteId = `model-selector-note-${useId().replace(/:/g, "")}`;
  const refs = useRef<Partial<Record<ModelChoice, HTMLButtonElement | null>>>({});
  const enabled = orderIds(registry, available);
  // Tagged as ModelBadge tags it: an experiment is not a comparison model.
  const tag = (choice: ModelChoice) =>
    !isComparison(registry, choice) ? "live" : findStrategy(registry, choice)?.role === "experiment" ? "experiment" : "comparison";

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
    : isComparison(registry, effective)
    ? `Comparison only — live advice is the champion. Showing ${modelDescription(registry, effective) || modelLabel(registry, effective)}`
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
        {enabled.map((choice) => {
          const checked = effective === choice;
          const prov = provisional.includes(choice);
          return (
            <button
              key={choice}
              ref={(el) => {
                refs.current[choice] = el;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              aria-label={`${modelLabel(registry, choice)} (${tag(choice)})${prov ? " (provisional)" : ""}`}
              tabIndex={checked ? 0 : -1}
              title={
                prov
                  ? `${modelDescription(registry, choice)} ${PROVISIONAL_TITLE}`
                  : modelDescription(registry, choice)
              }
              className={`model-toggle-button${checked ? " active" : ""}`}
              data-testid={`${testId}-${choice}`}
              onClick={() => setModel(choice)}
            >
              {modelLabel(registry, choice)}
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
          onChange={(e) => setModel(e.target.value)}
          aria-describedby={noteId}
          data-testid={`${prefix}-select`}
        >
          {enabled.map((choice) => (
            <option key={choice} value={choice}>
              {modelLabel(registry, choice)}
              {` — ${tag(choice)}`}
              {provisional.includes(choice) ? " (provisional)" : ""}
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
