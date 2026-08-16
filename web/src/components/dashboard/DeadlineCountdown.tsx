import type { Week } from "../../contract/types";
import { formatInZone, timeUntil, urgencyOf } from "./deadline";
import { useNow } from "./useNow";

/**
 * The deadline, in both zones, with the time remaining.
 *
 * This is the first thing on the dashboard and the largest thing on it, because on a Friday evening
 * — or a Saturday at 03:00, which is what a UK evening deadline is for the owner — the question is
 * "how long have I got", and everything else on the page is downstream of the answer.
 *
 * **Both zones are labelled, never one converted number.** FPL publishes in UK time and the owner
 * is on AEST; showing only the local conversion means every conversation about a deadline needs
 * arithmetic, and showing only UK time means the deadline is quoted in a zone nobody is standing
 * in. The offset is computed by the browser from the UTC instant rather than carried on the wire,
 * because it changes twice a season on two different dates (DL-11).
 *
 * **Decide-by is shown as well as the deadline**, in local time, because that is the one of the two
 * that is actually actionable: most deadlines land between 02:30 and 05:00 locally, so the real
 * rule is to decide the evening before.
 */
export function DeadlineCountdown({ deadline }: { deadline: Week["deadline"] }) {
  const now = useNow();
  const target = new Date(deadline.deadline_utc);
  const decideBy = new Date(deadline.decide_by_utc);
  const urgency = urgencyOf(target, now);
  const remaining = timeUntil(target, now);

  return (
    <section
      className={`dash-deadline dash-deadline-${urgency}`}
      aria-labelledby="dash-deadline-heading"
      data-testid="week-deadline"
    >
      <div className="dash-deadline-head">
        <h2 id="dash-deadline-heading">{deadline.name} deadline</h2>
        <p className="dash-deadline-remaining">
          <span className="dash-deadline-count" data-testid="week-countdown">
            {remaining}
          </span>
          <span className="dash-deadline-count-label">
            {urgency === "passed" ? "the deadline has gone" : "remaining"}
          </span>
        </p>
      </div>

      <dl className="dash-deadline-zones">
        <div className="dash-deadline-zone">
          <dt>UK</dt>
          <dd>
            <time dateTime={deadline.deadline_utc}>
              {formatInZone(target, deadline.uk_zone)}
            </time>
          </dd>
        </div>
        <div className="dash-deadline-zone">
          <dt>Local</dt>
          <dd>
            <time dateTime={deadline.deadline_utc}>
              {formatInZone(target, deadline.local_zone)}
            </time>
          </dd>
        </div>
        <div className="dash-deadline-zone dash-deadline-decide">
          <dt>Decide by</dt>
          <dd>
            <time dateTime={deadline.decide_by_utc}>
              {formatInZone(decideBy, deadline.local_zone)}
            </time>
          </dd>
        </div>
      </dl>
    </section>
  );
}
