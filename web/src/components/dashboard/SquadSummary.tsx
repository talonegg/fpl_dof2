import type { Squad, Week } from "../../contract/types";
import { formatPoints, formatPrice, formatXpRange } from "../../format";
import { squadTotals } from "./totals";

/**
 * What the squad is currently worth, in points rather than pounds.
 *
 * Every figure here is a *sum of forecasts*, and the panel says so rather than presenting a total
 * as though it were a measurement (DP-09, Invariant 6):
 *
 * - the plausible range comes from `formatXpRange`, so no mean is ever shown bare;
 * - the range is explicitly described as too narrow, because combining standard deviations in
 *   quadrature assumes fifteen independent forecasts and four defenders sharing a clean sheet are
 *   not independent. An optimistically narrow band presented without that caveat is exactly the
 *   "estimate dressed as an observation" DP-09 exists to prevent;
 * - captaincy is excluded, because the multiplier is a game rule and no rule value may be written
 *   into a component (Invariant 2, Invariant 9). Where the pipeline published its own advised total
 *   — which does include captaincy — that number is shown next to these, sourced rather than
 *   recomputed.
 */
export function SquadSummary({
  squad,
  horizonGameweeks,
  advised,
}: {
  squad: Squad;
  horizonGameweeks: number;
  advised?: Week["advised"];
}) {
  const totals = squadTotals(squad);
  const budget = squad.budget;

  return (
    <section
      className="dash-squad-summary"
      aria-labelledby="dash-squad-summary-heading"
      data-testid="dashboard-squad-summary"
    >
      <h2 id="dash-squad-summary-heading">Your squad</h2>

      <div className="dash-metrics">
        <Metric
          label="Starting XI, next gameweek"
          value={formatPoints(totals.startingXpNext)}
          detail={formatXpRange(totals.startingXpNext, totals.startingSdNext)}
          testId="dashboard-xp-next"
        />
        <Metric
          label={`Starting XI, next ${horizonGameweeks} gameweeks`}
          value={formatPoints(totals.startingXpHorizon)}
          detail={formatXpRange(totals.startingXpHorizon, totals.startingSdHorizon)}
          testId="dashboard-xp-horizon"
        />
        <Metric
          label="Bench, next gameweek"
          value={formatPoints(totals.benchXpNext)}
          detail={`All ${squad.players.length} players total ${formatPoints(totals.squadXpNext)}`}
          testId="dashboard-xp-bench"
        />
        <Metric
          label="Squad value"
          value={formatPrice(squad.total_price)}
          detail={
            budget === undefined
              ? `Solve status: ${squad.status}`
              : `of a ${formatPrice(budget)} budget · ${squad.status}`
          }
          testId="dashboard-squad-value"
        />
      </div>

      {advised?.expected_points !== undefined && (
        <p className="dash-squad-advised" data-testid="dashboard-advised-total">
          The pipeline's own advised total for gameweek {advised.gameweek} is{" "}
          {formatPoints(advised.expected_points)} points, which includes captaincy. The totals above
          do not.
        </p>
      )}

      <p className="dash-squad-caveat" data-testid="dashboard-totals-caveat">
        These are sums of forecasts, not observations. The plausible ranges assume the individual
        forecasts are independent, which they are not — players share fixtures — so the true ranges
        are wider than the ones shown.
      </p>
    </section>
  );
}

function Metric({
  label,
  value,
  detail,
  testId,
}: {
  label: string;
  value: string;
  detail: string;
  testId: string;
}) {
  return (
    <div className="dash-metric" data-testid={testId}>
      <span className="dash-metric-label">{label}</span>
      <span className="dash-metric-value">{value}</span>
      <span className="dash-metric-detail">{detail}</span>
    </div>
  );
}
