/** Hover/aria text for provisional advice: what it is and when it stops being provisional. */
export const PROVISIONAL_TITLE =
  "Provisional: this model's current advice, previewed before its decision is frozen. " +
  "It may change, and freezes at the decision window before the deadline; the frozen decision then replaces it.";

/** A clear 'Provisional' marker for advice that is not yet the frozen decision. */
export function ProvisionalBadge({ testId = "provisional-badge" }: { testId?: string }) {
  return (
    <span className="provisional-badge" title={PROVISIONAL_TITLE} aria-label={PROVISIONAL_TITLE} data-testid={testId}>
      Provisional
    </span>
  );
}
