import type { Live } from "../../contract/types";
import { formatLocalDateTime } from "../../format";
import { statusLabel, statusMeaning } from "../../data/live";
import "./live.css";

/**
 * The small marks the live views share (LIVE-05, LIVE-06): a status, "Provisional", "not live" and
 * the time of the last refresh. Each says its meaning in words; the border and tint only reinforce
 * it, so none of them is carried by colour alone (NFR-14).
 */

/** Where a gameweek, or one team's part of it, has got: in play, bonus pending, complete or final. */
export function StatusMark({ status, testId }: { status: Live["status"]; testId?: string }) {
  return (
    <span className={`live-mark live-status-${status}`} title={`${statusLabel(status)}: ${statusMeaning(status)}`} data-testid={testId}>
      {statusLabel(status)}
    </span>
  );
}

/** The figures can still move: FPL has not data-checked the gameweek. */
export function ProvisionalMark({ testId }: { testId?: string }) {
  return (
    <span
      className="live-mark live-provisional"
      title="Provisional: these points are scored from FPL's live data and can still change until FPL data-checks the gameweek. The season log is the record."
      data-testid={testId}
    >
      Provisional
    </span>
  );
}

/** A team the pipeline has no live figure for: it shows the league table's own figures. */
export function NotLiveMark({ reason, testId }: { reason: string | null; testId?: string }) {
  return (
    <span
      className="live-mark live-not-live"
      title={`Not live: ${reason ?? "no live figure was published for this team"}. Showing the league table's own figures.`}
      data-testid={testId}
    >
      not live
    </span>
  );
}

/** When the figures were last refreshed (`as_of`), in the reader's own zone (DL-11). */
export function UpdatedAt({ asOf, testId }: { asOf: string; testId?: string }) {
  return (
    <span data-testid={testId}>
      Updated <time dateTime={asOf}>{formatLocalDateTime(asOf)}</time>
    </span>
  );
}
