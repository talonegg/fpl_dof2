import type { Plan, PlanCaveat, PlanOption } from "../contract/types";
import { formatPoints, formatPrice } from "../format";

/**
 * "The plan" — the multi-gameweek view, the chip calendar, and the argument for both (E4).
 *
 * Three deliberate choices about what it shows, all of them obligations rather than preferences.
 *
 * **The D-13 caveat renders before the recommendation, not after it.** DL-21 found the forecast
 * loses to a model-free benchmark at the head of the ranking, which is exactly where a hit, a chip
 * or a wildcard acts. The pipeline attaches the caveat to the recommendation as data; this renders
 * it prominently, because a caveat below the fold is a caveat nobody reads.
 *
 * **Every ownership figure says "selected by".** Never "effective ownership" (DL-24). Captaincy
 * share is published by no FPL endpoint, so the most-captained player is a separate plain callout
 * rather than folded into a number that would imply precision the data does not have.
 *
 * **Holding is an option with a number on it.** The runners-up table always contains "roll
 * everything", ranked alongside the rest.
 */
export function PlanPanel({ plan }: { plan: Plan }) {
  if (plan.skipped) {
    return (
      <section className="plan plan-skipped" aria-labelledby="plan-heading">
        <h2 id="plan-heading">The plan</h2>
        <p className="plan-skipped-reason" data-testid="plan-skipped">
          {plan.skipped_reason ??
            "No squad is available yet, so there is nothing to plan around."}
        </p>
      </section>
    );
  }

  const explanation = plan.explanation;
  const caveats = explanation?.caveats ?? [];
  const recommended = plan.recommended;

  return (
    <section className="plan" aria-labelledby="plan-heading">
      <h2 id="plan-heading">The plan</h2>

      {caveats.length > 0 && (
        <div className="plan-caveats" role="note" data-testid="plan-caveats">
          {caveats.map((caveat: PlanCaveat) => (
            <div className="plan-caveat" key={caveat.code}>
              <p className="plan-caveat-headline">
                <span className="plan-caveat-code">{caveat.code}</span>
                {caveat.headline}
              </p>
              <p className="plan-caveat-detail">{caveat.detail}</p>
            </div>
          ))}
        </div>
      )}

      <p className="plan-rationale" data-testid="plan-rationale">
        {explanation?.headline ?? plan.rationale}
      </p>

      {plan.gameweeks && plan.gameweeks.length > 0 && (
        <p className="plan-scope" data-testid="plan-scope">
          Gameweeks {plan.gameweeks[0]}–{plan.gameweeks[plan.gameweeks.length - 1]} ·{" "}
          {plan.solver ?? "solver"}
          {plan.status === "greedy_fallback" && (
            <span className="plan-fallback"> · fallback quality, not optimal</span>
          )}
        </p>
      )}

      {recommended && <WeekByWeek option={recommended} />}

      {explanation?.runners_up && explanation.runners_up.length > 0 && (
        <div className="plan-runners-wrap">
          <p className="plan-runners-caption">
            Every option considered, and by how much it lost. Rolling everything is
            one of them, with its own number.
          </p>
          <div className="plan-runners-scroll">
            <table className="plan-runners" data-testid="plan-runners">
              <thead>
                <tr>
                  <th scope="col">Option</th>
                  <th scope="col">Expected points</th>
                  <th scope="col">Margin</th>
                  <th scope="col">Why it lost</th>
                </tr>
              </thead>
              <tbody>
                {explanation.runners_up.map((item, index) => (
                  <tr key={`${item.label}-${index}`}>
                    <th scope="row">{item.label}</th>
                    <td>{formatPoints(item.total_expected_points)}</td>
                    <td>{formatPoints(item.margin)}</td>
                    <td>{item.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <OwnershipBet plan={plan} />
      <ChipCalendar plan={plan} />

      {explanation?.price_exposure && (
        <p className="plan-price" data-testid="plan-price">
          {explanation.price_exposure.statement}
        </p>
      )}

      {explanation?.assumptions && explanation.assumptions.length > 0 && (
        <details className="plan-assumptions" data-testid="plan-assumptions">
          <summary>What this assumes</summary>
          <ul>
            {explanation.assumptions.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </details>
      )}

      {plan.warnings && plan.warnings.length > 0 && (
        <ul className="plan-warnings" data-testid="plan-warnings">
          {plan.warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function WeekByWeek({ option }: { option: PlanOption }) {
  return (
    <div className="plan-weeks-scroll">
      <table className="plan-weeks" data-testid="plan-weeks">
        <thead>
          <tr>
            <th scope="col">GW</th>
            <th scope="col">Chip</th>
            <th scope="col">Transfers</th>
            <th scope="col">Free</th>
            <th scope="col">Hit</th>
            <th scope="col">Bank</th>
            <th scope="col">Net xP</th>
          </tr>
        </thead>
        <tbody>
          {option.weeks.map((week) => (
            <tr key={week.gameweek} data-testid={`plan-week-${week.gameweek}`}>
              <th scope="row">{week.gameweek}</th>
              <td>{week.chip_label ?? "—"}</td>
              <td>{week.transfers_in?.length ?? 0}</td>
              <td>{week.free_transfers}</td>
              <td>{week.hit_points === 0 ? "—" : week.hit_points}</td>
              <td>
                {week.bank_after === undefined ? "—" : formatPrice(week.bank_after)}
              </td>
              <td>
                {week.net_expected_points === undefined
                  ? "—"
                  : formatPoints(week.net_expected_points)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The ownership bet, stated plainly (FR-16, DL-24).
 *
 * The source statement is not decoration: Design 7.1 requires the UI to say which ownership source
 * is in use, because a risk dial driven by an estimated quantity presented as a measured one is
 * worse than no risk dial at all.
 */
function OwnershipBet({ plan }: { plan: Plan }) {
  const ownership = plan.ownership;
  if (!ownership) return null;

  return (
    <div className="plan-ownership" data-testid="plan-ownership">
      <h3>The bet you are making</h3>
      <p className="plan-dial">{ownership.dial_description}</p>
      {ownership.statements && ownership.statements.length > 0 && (
        <ul className="plan-ownership-statements">
          {ownership.statements.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
      {ownership.most_captained && (
        <p className="plan-most-captained" data-testid="plan-most-captained">
          {ownership.most_captained.statement}
        </p>
      )}
      <p className="plan-ownership-source" data-testid="plan-ownership-source">
        {ownership.source_statement}
      </p>
    </div>
  );
}

/**
 * The chip calendar. Expiry is read from the game's own chip windows, never written down here —
 * "set one expires at GW19" is true this season and is exactly the sort of fact that quietly stops
 * being true (Invariant 2).
 */
function ChipCalendar({ plan }: { plan: Plan }) {
  const calendar = plan.chip_calendar;
  if (!calendar) return null;
  const expiring = calendar.expiring ?? [];
  const entries = calendar.entries ?? [];

  return (
    <div className="plan-calendar" data-testid="plan-calendar">
      <h3>Chip calendar</h3>
      {expiring.length > 0 ? (
        <ul className="plan-chip-expiry" data-testid="plan-chip-expiry">
          {expiring.map((item) => (
            <li key={item.chip}>
              {item.chip_label} expires at the gameweek {item.expires_gameweek}{" "}
              deadline
            </li>
          ))}
        </ul>
      ) : (
        <p className="plan-chip-expiry">No chips remain in this set.</p>
      )}
      {entries.length > 0 && (
        <ul className="plan-chip-windows">
          {entries.slice(0, 8).map((entry, index) => (
            <li key={`${entry.chip}-${entry.gameweek}-${index}`}>
              <strong>
                {entry.chip_label} · GW{entry.gameweek}
              </strong>{" "}
              {entry.note}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
