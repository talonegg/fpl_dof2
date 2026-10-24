import { useId } from "react";
import type { LogHindsightOptimal, LogHindsightPlan } from "../contract/types";
import { formatPoints } from "../format";
import "./models/models.css";
import "./models/modelsPage.css";
import "./review/review.css";

const hits = (n: number) => (n === 0 ? "—" : `−${Math.abs(n)}`);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

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
    <div className="table-scroll" tabIndex={0} role="region" aria-labelledby={captionId}>
      <table className="models-table" data-testid={testId}>
        <caption id={captionId} className="models-caption">
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
                  {tag && <span className="review-tag"> {tag}</span>}
                </th>
                <td className="models-what">{movesText(p)}</td>
                <td>{p.captain_name}</td>
                <td>{planPoints(p.points_before_hits, realised)}</td>
                <td>{hits(p.hit_points)}</td>
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
