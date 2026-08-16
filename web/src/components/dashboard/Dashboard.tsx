import type { Meta, Plan, Rules, Squad, Week } from "../../contract/types";
import { SquadPitch } from "../SquadPitch";
import { Bench } from "../Bench";
import { PlanPanel } from "../PlanPanel";
import { DeadlineCountdown } from "./DeadlineCountdown";
import { AlertsPanel } from "./AlertsPanel";
import { RecommendationCard } from "./RecommendationCard";
import { SquadSummary } from "./SquadSummary";
import "./dashboard.css";

/**
 * The dashboard (E6-S6, FR-26) — the product's front page.
 *
 * **The order is the design.** This is the page most likely to be opened on a phone at 02:00 with
 * an hour to go, so it is ordered by what changes a decision, not by what is interesting:
 *
 * 1. the deadline, in both zones, with the time remaining;
 * 2. alerts that change what you do — injuries, suspensions, anything urgent;
 * 3. the recommendation, with the roll option beside it whichever way round it went;
 * 4. the squad and what it is expected to score;
 * 5. price notes and the multi-gameweek plan, below the fold, where they belong.
 *
 * Everything below the recommendation is context. Everything above it is the decision.
 *
 * **Skipped is a state, not a failure.** Before the first gameweek is scored there is no picks
 * endpoint to read, so `week.skipped` and `plan.skipped` are the normal preseason answer (DL-20).
 * The deadline is still true in that state and is still rendered; only the advice is missing, and
 * the page says why rather than showing a blank (DP-15).
 */
export function Dashboard({
  meta,
  rules,
  squad,
  week,
  plan,
}: {
  meta: Meta;
  rules: Rules;
  squad: Squad;
  week: Week | null;
  plan: Plan | null;
}) {
  const recommendation = week?.skipped ? undefined : week?.recommendation;

  return (
    <div className="dashboard">
      {week && <DeadlineCountdown deadline={week.deadline} />}

      <AlertsPanel alerts={week?.alerts} tone="actionable" />

      {recommendation ? (
        <RecommendationCard
          recommendation={recommendation}
          squadState={week?.squad_state}
        />
      ) : (
        week && <NoAdvice week={week} />
      )}

      <SquadSummary
        squad={squad}
        horizonGameweeks={meta.horizon_gameweeks}
        advised={week?.skipped ? undefined : week?.advised}
      />

      <SquadPitch squad={squad} rules={rules} />
      <Bench squad={squad} />

      <AlertsPanel alerts={week?.alerts} tone="informational" />

      {plan && <PlanPanel plan={plan} />}
    </div>
  );
}

/**
 * There is a deadline but nothing to advise on.
 *
 * Two ways to arrive here: the pipeline skipped the week because no squad could be established, or
 * it ran and published no recommendation. Both are stated plainly. A silent gap where the
 * recommendation should be reads as a bug and sends the reader to check the pipeline, which is the
 * expensive failure mode.
 */
function NoAdvice({ week }: { week: Week }) {
  return (
    <section
      className="dash-recommendation dash-recommendation-empty"
      aria-labelledby="dash-recommendation-heading"
      data-testid="week-skipped"
    >
      <h2 id="dash-recommendation-heading">This week</h2>
      <p className="dash-recommendation-action">
        {week.skipped_reason ??
          "No squad is available yet, so there is nothing to advise on. This is the normal state before the first gameweek is scored."}
      </p>
    </section>
  );
}
