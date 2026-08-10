import type { Week } from "../contract/types";
import { formatPoints, formatPrice } from "../format";

/**
 * "This week" — the panel that answers the only question that matters on a Thursday evening.
 *
 * Two deliberate choices about what it shows.
 *
 * **Both deadlines, always.** FPL publishes deadlines in UK time and the owner is on AEST, and the
 * offset between them changes twice a season on different dates. Rendering both removes the mental
 * arithmetic at exactly the hour nobody should be doing arithmetic. The wire carries UTC only; the
 * browser converts, which is why this is the one place zones exist (DL-11).
 *
 * **The roll is shown with a number on it.** Every option the optimiser considered is listed with
 * its own expected gain, including doing nothing. A recommendation to hold is a decision, not the
 * absence of one (FR-24), and presenting it as a blank space is how a manager talks themselves into
 * a hit.
 */
export function WeekPanel({ week }: { week: Week }) {
  if (week.skipped) {
    return (
      <section className="week week-skipped" aria-labelledby="week-heading">
        <h2 id="week-heading">This week</h2>
        <DeadlineTimes week={week} />
        <p className="week-skipped-reason" data-testid="week-skipped">
          {week.skipped_reason ??
            "No squad is available yet, so there is nothing to advise on."}
        </p>
      </section>
    );
  }

  const recommendation = week.recommendation;
  const state = week.squad_state;
  const urgent = (week.alerts ?? []).filter(
    (alert) => alert.severity === "urgent",
  );

  return (
    <section className="week" aria-labelledby="week-heading">
      <h2 id="week-heading">This week</h2>
      <DeadlineTimes week={week} />

      {state && (
        <p className="week-state" data-testid="week-state">
          <span>
            Bank {formatPrice(state.bank)} · sell value{" "}
            {formatPrice(state.sell_value)} · {state.free_transfers} free
            transfer{state.free_transfers === 1 ? "" : "s"}
          </span>
          <span
            className={`week-provenance week-provenance-${state.provenance}`}
          >
            squad {state.provenance.replace("_", " ")}
          </span>
        </p>
      )}

      {recommendation && (
        <>
          <p className="week-rationale" data-testid="week-rationale">
            {recommendation.rationale}
          </p>

          {recommendation.moves && recommendation.moves.length > 0 && (
            <ul className="week-moves" data-testid="week-moves">
              {recommendation.moves.map((move) => (
                <li key={`${move.out.player_id}-${move.in.player_id}`}>
                  <span className="week-move-out">
                    {move.out.web_name} {formatPrice(move.out.price)}
                  </span>
                  <span aria-hidden="true"> → </span>
                  <span className="week-move-in">
                    {move.in.web_name} {formatPrice(move.in.price)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {recommendation.options && recommendation.options.length > 0 && (
            <div className="week-options-wrap">
              {/* Outside the scroller, so it wraps and stays readable on a narrow screen rather
                  than scrolling sideways with the table it describes. */}
              <p className="week-options-caption">
                Every option considered. Doing nothing is one of them, with its
                own number.
              </p>
              <div className="week-options-scroll">
                <table className="week-options" data-testid="week-options">
                  <thead>
                    <tr>
                      <th scope="col">Option</th>
                      <th scope="col">Hit</th>
                      <th scope="col">Net xP</th>
                      <th scope="col">Gain vs roll</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recommendation.options.map((option) => {
                      const chosen =
                        option.transfers === recommendation.transfers;
                      return (
                        <tr
                          key={option.transfers}
                          className={chosen ? "week-option-chosen" : undefined}
                          data-testid={`week-option-${option.transfers}`}
                        >
                          <th scope="row">
                            {option.transfers === 0
                              ? "Roll (no transfer)"
                              : `${option.transfers} transfer${option.transfers === 1 ? "" : "s"}`}
                            {chosen && (
                              <span className="week-chosen-badge">
                                {" "}
                                recommended
                              </span>
                            )}
                          </th>
                          <td>
                            {option.hit_points === 0 ? "—" : option.hit_points}
                          </td>
                          <td>{formatPoints(option.net_expected_points)}</td>
                          <td>
                            {option.gain_over_roll > 0 ? "+" : ""}
                            {formatPoints(option.gain_over_roll)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {urgent.length > 0 && (
        <ul className="week-alerts" data-testid="week-alerts">
          {urgent.map((alert, index) => (
            <li
              key={`${alert.category}-${alert.player_id ?? index}`}
              className="week-alert-urgent"
            >
              {alert.message}
            </li>
          ))}
        </ul>
      )}

      {week.reconciliation && !week.reconciliation.followed && (
        <p className="week-reconciliation" data-testid="week-reconciliation">
          Gameweek {week.reconciliation.gameweek}: what was played differed from
          what was advised in {week.reconciliation.divergences?.length ?? 0}{" "}
          place
          {(week.reconciliation.divergences?.length ?? 0) === 1 ? "" : "s"}.
        </p>
      )}
    </section>
  );
}

/**
 * Both zones and the countdown.
 *
 * The offset is computed by the browser from the UTC instant rather than being carried on the wire,
 * because it is not a constant: the UK leaves BST in late October and Australia enters AEDT in
 * early October, so the gap moves from +9 to +11 within a few weeks. A number baked in at publish
 * time would be silently wrong for exactly the fortnight nobody is checking.
 */
function DeadlineTimes({ week }: { week: Week }) {
  const deadline = new Date(week.deadline.deadline_utc);
  const decideBy = new Date(week.deadline.decide_by_utc);
  const now = new Date();

  return (
    <div className="week-deadline" data-testid="week-deadline">
      <div className="week-deadline-row">
        <span className="week-zone-label">UK</span>
        <time dateTime={week.deadline.deadline_utc}>
          {inZone(deadline, week.deadline.uk_zone)}
        </time>
      </div>
      <div className="week-deadline-row">
        <span className="week-zone-label">Local</span>
        <time dateTime={week.deadline.deadline_utc}>
          {inZone(deadline, week.deadline.local_zone)}
        </time>
      </div>
      <div className="week-deadline-row week-countdown">
        <span className="week-zone-label">In</span>
        <span data-testid="week-countdown">{untilText(deadline, now)}</span>
      </div>
      <div className="week-deadline-row week-decide-by">
        <span className="week-zone-label">Decide by</span>
        <time dateTime={week.deadline.decide_by_utc}>
          {inZone(decideBy, week.deadline.local_zone)}
        </time>
      </div>
    </div>
  );
}

function inZone(instant: Date, zone: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(instant);
  } catch {
    // An unknown IANA zone must not blank the whole panel. UTC is wrong but legible, which beats
    // a deadline that renders as nothing at all.
    return `${instant.toISOString().slice(0, 16).replace("T", " ")} UTC`;
  }
}

function untilText(target: Date, now: Date): string {
  const seconds = Math.floor((target.getTime() - now.getTime()) / 1000);
  if (seconds <= 0) return "passed";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return days > 0 ? `${days}d ${hours}h` : `${hours}h ${minutes}m`;
}
