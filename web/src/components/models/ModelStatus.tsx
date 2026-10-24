import type { Models } from "../../contract/types";
import { latestGameweek as latest } from "../../data/season";
import { ProvisionalBadge } from "./ProvisionalBadge";

/** "Unavailable for GW10: reason" when the latest gameweek left the model without advice, else null. */
export function unavailableNow(models: Models | null, m: string): string | null {
  const last = latest(models);
  const a = last?.availability?.[m];
  return a && a.available === false ? `Unavailable for GW${last?.gameweek}${a.reason ? `: ${a.reason}` : ""}` : null;
}

/** The latest advice for the model is the pre-window preview, not the frozen decision. */
export const provisionalNow = (models: Models | null, m: string): boolean => {
  const last = latest(models);
  return !!last?.provisional && last.advice[m] !== undefined;
};

/** The provisional badge and the unavailable reason, wherever a model is named in a ladder or outline. */
export function ModelStatus({ models, id, testId }: { models: Models | null; id: string; testId: string }) {
  const unavailable = unavailableNow(models, id);
  return (
    <>
      {provisionalNow(models, id) && (
        <>
          {" "}
          <ProvisionalBadge testId={`${testId}-provisional`} />
        </>
      )}
      {unavailable && (
        <span className="models-unavailable" data-testid={`${testId}-unavailable`}>
          {" "}
          {unavailable}
        </span>
      )}
    </>
  );
}

/** The banner over a view whose latest gameweek is a preview. */
export function ProvisionalNote({ models }: { models: Models | null }) {
  if (!models?.provisional) return null;
  return (
    <p className="models-provisional-note" data-testid="models-provisional-note">
      <ProvisionalBadge testId="models-provisional-banner" /> GW{latest(models)?.gameweek} advice is a preview of each
      model’s current pick. It freezes at the decision window before the deadline, when the frozen decision replaces it.
    </p>
  );
}
