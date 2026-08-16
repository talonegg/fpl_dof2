import { useMemo, useState } from "react";
import type { Plan, PlanOption, PlanWeek } from "../../contract/types";
import { formatPoints, formatPrice } from "../../format";
import type { PlayerIndex } from "./draft";

/**
 * The multi-gameweek plan as a timeline, and the chip calendar with its expiry clock (E6-S7, FR-31).
 *
 * This is deliberately *not* a second `PlanPanel`. That panel makes the argument — the headline, the
 * caveats, the runners-up, the ownership bet — and it belongs on the dashboard where the reader
 * arrives. What is missing there, and what a squad page needs, is the mechanics: which players
 * actually move in which gameweek, and how long the chips have left. So this renders the weeks as
 * named transfers rather than counts, lets the reader step through the alternatives the solver also
 * ranked, and gives the chip calendar an expiry clock.
 *
 * **No chip expiry is written down here.** "Set one expires at GW19" is true this season and is
 * exactly the sort of fact that quietly stops being true; the gameweek comes from
 * `chip_calendar.expiring`, read from the game's own chip windows (Invariant 2).
 */
export function PlanTimeline({ plan, index }: { plan: Plan; index: PlayerIndex }) {
  const options = useMemo(() => planOptions(plan), [plan]);
  const [optionKey, setOptionKey] = useState<string>(() => options[0]?.key ?? "");
  const option = options.find((candidate) => candidate.key === optionKey) ?? options[0] ?? null;

  if (plan.skipped) {
    return (
      <section className="timeline" aria-labelledby="timeline-heading">
        <h2 id="timeline-heading">The plan, week by week</h2>
        <p data-testid="timeline-skipped">
          {plan.skipped_reason ??
            "No squad is available yet, so there is nothing to plan around."}
        </p>
      </section>
    );
  }

  return (
    <section className="timeline" data-testid="plan-timeline" aria-labelledby="timeline-heading">
      <h2 id="timeline-heading">The plan, week by week</h2>

      {options.length > 1 && (
        <label className="timeline-field">
          <span>Show</span>
          <select
            value={option?.key ?? ""}
            onChange={(event) => setOptionKey(event.target.value)}
            data-testid="timeline-option"
          >
            {options.map((candidate) => (
              <option key={candidate.key} value={candidate.key}>
                {candidate.label} · {formatPoints(candidate.total_expected_points)} xP
              </option>
            ))}
          </select>
        </label>
      )}

      {option ? (
        <ol className="timeline-weeks" data-testid="timeline-weeks">
          {option.weeks.map((week) => (
            <WeekCard key={week.gameweek} week={week} index={index} />
          ))}
        </ol>
      ) : (
        <p data-testid="timeline-empty">No plan option has been published.</p>
      )}

      <ChipClock plan={plan} />
    </section>
  );
}

/**
 * Every option the solver ranked, recommended first and the roll always present.
 *
 * Holding is a decision with a number on it, never the absence of one (FR-24, DP-09), so the
 * baseline is in this list on the same footing as the rest.
 */
function planOptions(plan: Plan): PlanOption[] {
  const options: PlanOption[] = [];
  const seen = new Set<string>();
  for (const option of [plan.recommended, plan.baseline, ...(plan.alternatives ?? [])]) {
    if (!option || seen.has(option.key)) continue;
    seen.add(option.key);
    options.push(option);
  }
  return options;
}

function WeekCard({ week, index }: { week: PlanWeek; index: PlayerIndex }) {
  const nameOf = (id: number) => index.get(id)?.name ?? `#${id}`;
  const movesIn = week.transfers_in ?? [];
  const movesOut = week.transfers_out ?? [];
  const moved = movesIn.length > 0 || movesOut.length > 0;

  return (
    <li className="timeline-week" data-testid={`timeline-week-${week.gameweek}`}>
      <div className="timeline-week-head">
        <span className="timeline-gw">GW{week.gameweek}</span>
        {week.chip_label && (
          <span className="timeline-chip" data-testid={`timeline-chip-${week.gameweek}`}>
            {week.chip_label}
          </span>
        )}
      </div>

      {moved ? (
        <p className="timeline-moves">
          {movesOut.map(nameOf).join(", ") || "nobody"} <span aria-hidden="true">→</span>{" "}
          <span className="timeline-in">{movesIn.map(nameOf).join(", ") || "nobody"}</span>
        </p>
      ) : (
        <p className="timeline-moves timeline-hold">No transfer — the squad rolls.</p>
      )}

      <dl className="timeline-figures">
        <div>
          <dt>Free</dt>
          <dd>{week.free_transfers}</dd>
        </div>
        <div>
          <dt>Charged</dt>
          <dd>{week.charged_transfers ?? 0}</dd>
        </div>
        <div>
          <dt>Hit</dt>
          <dd>{week.hit_points ? week.hit_points : "—"}</dd>
        </div>
        <div>
          <dt>Bank</dt>
          <dd>{week.bank_after === undefined ? "—" : formatPrice(week.bank_after)}</dd>
        </div>
        <div>
          <dt>Net xP</dt>
          <dd>
            {week.net_expected_points === undefined
              ? "—"
              : formatPoints(week.net_expected_points)}
          </dd>
        </div>
      </dl>

      {week.charged_transfers === 0 && moved && week.chip_label && (
        <p className="timeline-note">
          Transfers made under {week.chip_label} are not charged against the free allowance.
        </p>
      )}
    </li>
  );
}

/**
 * How many gameweeks from now a chip expiry starts being called urgent.
 *
 * DP-06: named and defaulted rather than a literal in a comparison. It is presentation-only —
 * nothing downstream reads it, and the expiry gameweek itself always comes from the published
 * calendar. Four is roughly a month of deadlines, which is about the point at which "I will use it
 * later" stops being a plan.
 */
export const CHIP_URGENT_WITHIN = 4;

function ChipClock({ plan }: { plan: Plan }) {
  const calendar = plan.chip_calendar;
  if (!calendar) return null;

  const from = calendar.from_gameweek;
  const expiring = calendar.expiring ?? [];
  const entries = calendar.entries ?? [];

  return (
    <div className="timeline-chips" data-testid="timeline-chips">
      <h3>Chips, and how long they have</h3>

      {expiring.length === 0 ? (
        <p>No chips remain in this set.</p>
      ) : (
        <ul className="timeline-expiry" data-testid="timeline-expiry">
          {expiring.map((chip) => {
            const remaining = chip.expires_gameweek - from;
            const urgent = remaining <= CHIP_URGENT_WITHIN;
            return (
              <li
                key={chip.chip}
                className={urgent ? "timeline-expiry-urgent" : undefined}
                data-testid={`timeline-expiry-${chip.chip}`}
              >
                <strong>{chip.chip_label}</strong> expires at the GW{chip.expires_gameweek}{" "}
                deadline — {remaining <= 0 ? "this is the last chance" : `${remaining} gameweek(s) away`}
              </li>
            );
          })}
        </ul>
      )}

      {entries.length > 0 && (
        <ul className="timeline-windows" data-testid="timeline-windows">
          {entries.map((entry, order) => (
            <li key={`${entry.chip}-${entry.gameweek}-${order}`}>
              <strong>
                {entry.chip_label} · GW{entry.gameweek}
              </strong>
              {entry.is_double && <span className="timeline-tag">double</span>}
              {entry.is_blank && <span className="timeline-tag">blank</span>}
              {entry.note && <span className="timeline-note-inline"> {entry.note}</span>}
            </li>
          ))}
        </ul>
      )}

      {calendar.unavailable && calendar.unavailable.length > 0 && (
        <p className="timeline-unavailable" data-testid="timeline-unavailable">
          Already used, or otherwise unavailable: {calendar.unavailable.join(", ")}.
        </p>
      )}
    </div>
  );
}
