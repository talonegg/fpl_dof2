import type { Week } from "../../contract/types";

type Recommendation = NonNullable<Week["recommendation"]>;
type Option = NonNullable<Recommendation["options"]>[number];

/**
 * The recommendation set beside the roll, always both ways round.
 *
 * FR-24 and DP-09: doing nothing is a first-class option with a number attached, not the absence of
 * a recommendation. That obligation runs in both directions and it is the second direction that is
 * usually dropped —
 *
 * - when the advice is to transfer, the reader must still see what rolling would net, or the
 *   recommendation is unarguable;
 * - when the advice is to roll, the reader must still see what the best available transfer would
 *   have cost, or "hold" reads as the optimiser having found nothing rather than having weighed
 *   something and rejected it.
 *
 * Pure, so the wording can be tested without a DOM.
 */
export interface RollComparison {
  isRoll: boolean;
  /** Net expected points of the recommended course. */
  recommendedNet: number;
  /** Net expected points of rolling, when the roll was published as an option. */
  rollNet?: number;
  /** Points the recommendation gains over rolling. Negative would mean rolling wins. */
  gainOverRoll?: number;
  /** The lead line, phrased for whichever way round the recommendation went. */
  statement: string;
  /**
   * The other side of the argument: the best transfer when the advice is to roll, or the roll
   * itself when the advice is to transfer. Absent only when the pipeline published no options.
   */
  counterfactual?: {
    label: string;
    net: number;
    gainOverRoll: number;
  };
}

function points(value: number): string {
  return value.toFixed(2);
}

function signed(value: number): string {
  return `${value > 0 ? "+" : ""}${points(value)}`;
}

function transferLabel(transfers: number): string {
  if (transfers === 0) return "Roll (no transfer)";
  return `${transfers} transfer${transfers === 1 ? "" : "s"}`;
}

/**
 * Build the comparison from the published options, falling back to `gain_over_roll` alone when the
 * option list is absent — a thinner artefact still has to render something honest (DP-15).
 */
export function rollComparison(recommendation: Recommendation): RollComparison {
  const options: Option[] = recommendation.options ?? [];
  const rollOption = options.find((option) => option.transfers === 0);
  const rollNet = rollOption?.net_expected_points;

  const gainOverRoll =
    recommendation.gain_over_roll ??
    (rollNet === undefined ? undefined : recommendation.net_expected_points - rollNet);

  if (recommendation.is_roll) {
    // The best thing that was *not* done, so holding is visibly a choice between alternatives.
    const best = options
      .filter((option) => option.transfers > 0)
      .reduce<Option | undefined>(
        (bestSoFar, option) =>
          bestSoFar === undefined || option.gain_over_roll > bestSoFar.gain_over_roll
            ? option
            : bestSoFar,
        undefined,
      );

    const statement =
      best === undefined
        ? "Rolling your free transfer is the recommendation."
        : best.gain_over_roll >= 0
          ? `Rolling your free transfer is the recommendation, even though the best transfer available nets ${signed(best.gain_over_roll)} against it.`
          : `Rolling your free transfer is the recommendation: the best transfer available nets ${points(Math.abs(best.gain_over_roll))} fewer points than holding.`;

    return {
      isRoll: true,
      recommendedNet: recommendation.net_expected_points,
      rollNet: rollNet ?? recommendation.net_expected_points,
      gainOverRoll,
      statement,
      counterfactual:
        best === undefined
          ? undefined
          : {
              label: transferLabel(best.transfers),
              net: best.net_expected_points,
              gainOverRoll: best.gain_over_roll,
            },
    };
  }

  const moveLabel = transferLabel(recommendation.transfers);
  const statement =
    gainOverRoll === undefined
      ? `${moveLabel} is the recommendation. The gain over rolling your free transfer is not published in this run.`
      : gainOverRoll >= 0
        ? `Making this move nets ${signed(gainOverRoll)} over rolling your free transfer.`
        : `This move nets ${points(Math.abs(gainOverRoll))} fewer points than rolling your free transfer.`;

  return {
    isRoll: false,
    recommendedNet: recommendation.net_expected_points,
    rollNet,
    gainOverRoll,
    statement,
    counterfactual:
      rollNet === undefined
        ? undefined
        : { label: transferLabel(0), net: rollNet, gainOverRoll: 0 },
  };
}

export { signed as formatSignedPoints, transferLabel as formatTransferLabel };
