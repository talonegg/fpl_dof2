import type { Week } from "../../contract/types";
import { formatPrice } from "../../format";
import { Metric } from "./SquadSummary";

/**
 * What the squad is worth and whether this model's advice fits the budget.
 *
 * The value is at today's prices; the budget is the bank plus what the squad sells for after the
 * sell-on fee, which is what can actually be spent (`squad_state`). The check rebuilds the bank
 * after the advised moves from their published prices (out at its selling price, in at its buying
 * price) and compares it with the pipeline's own `bank_after`, so a solve that overspent, or a
 * mismatch between the two, is said rather than hidden (DP-15).
 */
export function SquadBudget({
  state,
  recommendation,
  currentValue,
  advisedValue,
}: {
  state: NonNullable<Week["squad_state"]>;
  recommendation: Week["recommendation"];
  currentValue: number;
  advisedValue: number;
}) {
  const moves = recommendation?.moves ?? [];
  const net = moves.reduce((sum, m) => sum + m.in.price - m.out.price, 0);
  const bankAfter = state.bank - net;
  const published = recommendation?.bank_after;
  // Prices move in tenths, so compare as shown rather than as floats.
  const agrees = published === undefined || formatPrice(published) === formatPrice(bankAfter);
  const short = Number(bankAfter.toFixed(1)) < 0;

  let check: string;
  if (short) {
    check = `Over budget: the advised moves cost ${formatPrice(net)} net with ${formatPrice(state.bank)} in the bank, ${formatPrice(-bankAfter)} short.`;
  } else if (!agrees) {
    check = `Check before acting: the moves' prices leave ${formatPrice(bankAfter)} in the bank, but the advice says ${formatPrice(published ?? 0)}.`;
  } else if (moves.length === 0) {
    check = `Within budget: no transfers, so ${formatPrice(state.bank)} stays in the bank.`;
  } else {
    const cost = net >= 0 ? `cost ${formatPrice(net)} net` : `raise ${formatPrice(-net)} net`;
    check = `Within budget: the advised moves ${cost}, leaving ${formatPrice(bankAfter)} in the bank.`;
  }

  return (
    <section className="dash-squad-summary" aria-labelledby="squad-budget-heading" data-testid="squad-budget">
      <h2 id="squad-budget-heading">Value and budget</h2>
      <div className="dash-metrics">
        <Metric
          label="Squad value, today's prices"
          value={formatPrice(currentValue)}
          detail={`${formatPrice(advisedValue)} after the advised moves`}
          testId="squad-budget-value"
        />
        <Metric
          label="Budget"
          value={formatPrice(state.budget)}
          detail={`${formatPrice(state.bank)} in the bank + ${formatPrice(state.sell_value)} the squad sells for`}
          testId="squad-budget-budget"
        />
      </div>
      <p
        className="dash-squad-advised"
        role={short || !agrees ? "alert" : undefined}
        data-testid="squad-budget-check"
      >
        {check}
      </p>
    </section>
  );
}
