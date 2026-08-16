import type { Week } from "../../contract/types";
import { formatPoints, formatPrice } from "../../format";
import { rollComparison, formatSignedPoints, formatTransferLabel } from "./roll";

type Recommendation = NonNullable<Week["recommendation"]>;
type SquadState = NonNullable<Week["squad_state"]>;

/**
 * What to do before this deadline, and what it beat.
 *
 * The hierarchy is the argument: the action, then the *marginal gain over doing nothing*, then the
 * moves themselves, then every option the optimiser weighed with its own arithmetic. DP-09 requires
 * that every recommendation show what it beat and by how much, and FR-24 requires that doing
 * nothing always be one of the things shown — so the roll sits beside the recommendation whichever
 * way round the recommendation went, not only when the answer happens to be "hold".
 */
export function RecommendationCard({
  recommendation,
  squadState,
}: {
  recommendation: Recommendation;
  squadState?: SquadState;
}) {
  const comparison = rollComparison(recommendation);

  return (
    <section
      className="dash-recommendation"
      aria-labelledby="dash-recommendation-heading"
      data-testid="dashboard-recommendation"
    >
      <h2 id="dash-recommendation-heading">This week</h2>

      <p className="dash-recommendation-action" data-testid="week-rationale">
        {recommendation.rationale}
      </p>

      {/* The roll comparison, always. This is the element that must not become conditional. */}
      <div className="dash-roll" data-testid="dashboard-roll-comparison">
        <p className="dash-roll-statement">{comparison.statement}</p>
        <div className="dash-roll-sides">
          <div
            className={`dash-roll-side ${comparison.isRoll ? "" : "dash-roll-side-chosen"}`}
          >
            <span className="dash-roll-side-label">
              {comparison.isRoll
                ? "Roll (recommended)"
                : formatTransferLabel(recommendation.transfers)}
            </span>
            <span className="dash-roll-side-value">
              {formatPoints(comparison.recommendedNet)}
              <span className="dash-roll-side-unit"> net xP</span>
            </span>
            {recommendation.hit_points !== 0 && (
              <span className="dash-roll-side-hit">
                after {Math.abs(recommendation.hit_points)} points of hits
              </span>
            )}
          </div>

          {comparison.counterfactual && (
            <div
              className={`dash-roll-side ${comparison.isRoll ? "dash-roll-side-chosen" : ""}`}
              data-testid="dashboard-roll-counterfactual"
            >
              <span className="dash-roll-side-label">
                {comparison.isRoll
                  ? `Best transfer (${comparison.counterfactual.label})`
                  : "Roll (do nothing)"}
              </span>
              <span className="dash-roll-side-value">
                {formatPoints(comparison.counterfactual.net)}
                <span className="dash-roll-side-unit"> net xP</span>
              </span>
              <span className="dash-roll-side-hit">
                {formatSignedPoints(comparison.counterfactual.gainOverRoll)} against rolling
              </span>
            </div>
          )}
        </div>
      </div>

      {recommendation.moves && recommendation.moves.length > 0 && (
        <ul className="dash-moves" data-testid="week-moves">
          {recommendation.moves.map((move) => (
            <li key={`${move.out.player_id}-${move.in.player_id}`}>
              <span className="dash-move-out">
                {move.out.web_name} {formatPrice(move.out.price)}
              </span>
              <span aria-hidden="true"> → </span>
              <span className="dash-move-in">
                {move.in.web_name} {formatPrice(move.in.price)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {squadState && <SquadStateLine state={squadState} />}

      {recommendation.options && recommendation.options.length > 0 && (
        <details className="dash-options" data-testid="dashboard-options">
          <summary>Every option considered</summary>
          {/* Outside the scroller, so it wraps and stays readable on a narrow screen rather than
              scrolling sideways with the table it describes. */}
          <p className="dash-options-caption">
            Doing nothing is one of them, with its own number.
          </p>
          <div className="dash-options-scroll">
            <table className="dash-options-table" data-testid="week-options">
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
                  const chosen = option.transfers === recommendation.transfers;
                  return (
                    <tr
                      key={option.transfers}
                      className={chosen ? "dash-option-chosen" : undefined}
                      data-testid={`week-option-${option.transfers}`}
                    >
                      <th scope="row">
                        {formatTransferLabel(option.transfers)}
                        {chosen && (
                          <span className="dash-chosen-badge"> recommended</span>
                        )}
                      </th>
                      <td>{option.hit_points === 0 ? "—" : option.hit_points}</td>
                      <td>{formatPoints(option.net_expected_points)}</td>
                      <td>{formatSignedPoints(option.gain_over_roll)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {recommendation.warnings && recommendation.warnings.length > 0 && (
        <ul className="dash-recommendation-warnings" data-testid="dashboard-recommendation-warnings">
          {recommendation.warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Bank, sell value, free transfers — and how the squad was established.
 *
 * Provenance is reported, never hidden: a squad read from the picks endpoint and one declared by
 * hand in configuration deserve different amounts of trust, and the difference is invisible in the
 * numbers themselves (DL-20, DP-09).
 */
function SquadStateLine({ state }: { state: SquadState }) {
  return (
    <p className="dash-state" data-testid="week-state">
      <span>
        Bank {formatPrice(state.bank)} · sell value {formatPrice(state.sell_value)} ·{" "}
        {state.free_transfers} free transfer{state.free_transfers === 1 ? "" : "s"}
      </span>
      <span className={`dash-provenance dash-provenance-${state.provenance}`}>
        squad {state.provenance.replace("_", " ")}
      </span>
    </p>
  );
}
