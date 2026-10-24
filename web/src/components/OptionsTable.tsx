import { useId } from "react";
import type { LogHindsightOptimal, LogHindsightPlan, Plan, PlanOption } from "../contract/types";
import { formatHits, formatPoints, plural } from "../format";
import "./OptionsTable.css";

export function movesText(plan: LogHindsightPlan): string {
  return plan.moves.length === 0 ? "Roll" : plan.moves.map((m) => `${m.player_out_name} → ${m.player_in_name}`).join(", ");
}

const same = (a: LogHindsightPlan | null, b: LogHindsightPlan) => a !== null && JSON.stringify(a) === JSON.stringify(b);

/** A plan's points: whole when realised (the hindsight), to two places when predicted (a model's xP). */
export function planPoints(n: number, realised: boolean): string {
  return realised ? String(Math.round(n)) : formatPoints(n);
}

/** A plan's gain over the roll, signed, in the same units as its points. */
export function planGain(n: number, realised: boolean): string {
  const shown = realised ? Math.round(n) : n;
  return shown === 0 ? "±0" : `${shown > 0 ? "+" : "−"}${planPoints(Math.abs(shown), realised)}`;
}

/**
 * Every option a transfer solve weighed (ORC-11): the hindsight's on the points that happened, or
 * a model's on its own predicted xP. One shape, one table, so the two read alike.
 */
export function OptionsTable({
  optimal,
  caption,
  realised,
  testId,
}: {
  optimal: LogHindsightOptimal;
  caption: string;
  realised: boolean;
  testId: string;
}) {
  const captionId = useId();
  const fallback = [optimal.baseline_roll, optimal.optimal_single, optimal.optimal_overall].filter(
    (p, i, all): p is LogHindsightPlan => p !== null && all.findIndex((q) => same(q, p)) === i,
  );
  const options = optimal.all_options.length > 0 ? optimal.all_options : fallback;
  const tags = (p: LogHindsightPlan) =>
    [
      same(optimal.baseline_roll, p) && "roll",
      same(optimal.optimal_single, p) && "best single transfer",
      same(optimal.optimal_overall, p) && "best overall",
    ]
      .filter(Boolean)
      .join(", ");
  return (
    <div className="options-scroll" tabIndex={0} role="region" aria-labelledby={captionId}>
      <table className="options-table" data-testid={testId}>
        <caption id={captionId} className="options-caption">
          {caption}
        </caption>
        <thead>
          <tr>
            <th scope="col">Option</th>
            <th scope="col">Moves</th>
            <th scope="col">Captain</th>
            <th scope="col">Before hits</th>
            <th scope="col">Hits</th>
            <th scope="col">Net</th>
            <th scope="col">Gain over roll</th>
          </tr>
        </thead>
        <tbody>
          {options.map((p, i) => {
            const tag = tags(p);
            return (
              <tr key={i} data-testid={`${testId}-${i}`} className={same(optimal.optimal_overall, p) ? "is-best" : undefined}>
                <th scope="row">
                  {plural(p.transfers_count, "transfer")}
                  {tag && <span className="options-tag"> {tag}</span>}
                </th>
                <td className="options-moves">{movesText(p)}</td>
                <td>{p.captain_name}</td>
                <td>{planPoints(p.points_before_hits, realised)}</td>
                <td>{formatHits(p.hit_points)}</td>
                <td>
                  <strong>{planPoints(p.net_points, realised)}</strong>
                </td>
                <td>{planGain(p.gain_over_roll, realised)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The chip scenarios a model's multi-week plan enumerated (ORC-11): each option of `plan.json` that
 * plays a chip, read as published — no new solve. Its points are over the plan's horizon, net of
 * hits, so they sit beside this gameweek's options rather than in the same table.
 */
export function ChipScenarios({ plan }: { plan: Plan | null }) {
  const captionId = useId();
  if (!plan || plan.skipped) {
    return (
      <p className="options-note" data-testid="decision-no-scenarios">
        This model publishes no multi-week plan, so it has no chip scenarios.
      </p>
    );
  }
  const seen = new Set<string>();
  const scenarios = [plan.recommended, ...(plan.alternatives ?? [])].filter((o): o is PlanOption => {
    if (!o || seen.has(o.key) || (o.chips ?? []).length === 0) return false;
    seen.add(o.key);
    return true;
  });
  if (scenarios.length === 0) {
    return (
      <p className="options-note" data-testid="decision-no-scenarios">
        This model&apos;s plan enumerated no chip scenario this gameweek.
      </p>
    );
  }
  const weeks = plan.gameweeks ?? [];
  const span = weeks.length > 0 ? `GW${weeks[0]}–GW${weeks[weeks.length - 1]}` : "the plan's horizon";
  const roll = plan.baseline?.total_expected_points;
  return (
    <div className="options-scroll" tabIndex={0} role="region" aria-labelledby={captionId}>
      <table className="options-table" data-testid="decision-scenarios">
        <caption id={captionId} className="options-caption">
          The chip scenarios its plan weighed, {span}, on this model&apos;s xP net of hits
        </caption>
        <thead>
          <tr>
            <th scope="col">Scenario</th>
            <th scope="col">Hits</th>
            <th scope="col">Net</th>
            <th scope="col">Gain over roll</th>
          </tr>
        </thead>
        <tbody>
          {scenarios.map((o) => (
            <tr key={o.key} data-testid={`decision-scenario-${o.key}`} className={o === plan.recommended ? "is-best" : undefined}>
              <th scope="row">
                {o.label}
                {o === plan.recommended && <span className="options-tag"> recommended</span>}
              </th>
              <td>{formatHits(o.total_hit_points ?? 0)}</td>
              <td>
                <strong>{formatPoints(o.total_expected_points)}</strong>
              </td>
              <td>{roll === undefined ? "—" : planGain(o.total_expected_points - roll, false)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
