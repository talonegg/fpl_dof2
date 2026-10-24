import { useState } from "react";
import type { Plan, Players, Rules, Squad, Week } from "../../contract/types";
import { formatPrice } from "../../format";
import { SquadPitch } from "../SquadPitch";
import { Bench } from "../Bench";
import { Decomposition } from "../Decomposition";
import { OwnershipBet } from "../PlanPanel";
import { ModelBadge } from "../models/ModelBadge";
import { AlertsPanel } from "../dashboard/AlertsPanel";
import { DeadlineCountdown } from "../dashboard/DeadlineCountdown";
import { RecommendationCard } from "../dashboard/RecommendationCard";
import { SquadSummary } from "./SquadSummary";
import "../dashboard/dashboard.css";

/**
 * This gameweek's decision for the chosen model (WEB-12, Drop A). Every number is the selected
 * model's own: `useData` has already swapped in its week, plan and effective squad, so switching
 * the header selector changes what is shown here with no logic of its own.
 *
 * Order is by what changes the decision: deadline, alerts, the move beside its roll comparison
 * (FR-24, always rendered by `RecommendationCard`), the XI/captain/bench with expected points,
 * then the reasoning. Drop B's per-model options (ORC-11) go between the recommendation and the XI.
 */
export function DecisionView({
  week,
  plan,
  squad,
  rules,
  players,
  horizonGameweeks,
}: {
  week: Week;
  plan: Plan | null;
  squad: Squad;
  rules: Rules;
  players: Players;
  horizonGameweeks: number;
}) {
  const recommendation = week.skipped ? undefined : week.recommendation;
  return (
    <div className="dashboard" data-testid="decision-view">
      <DeadlineCountdown deadline={week.deadline} />
      <AlertsPanel alerts={week.alerts} tone="actionable" />

      {recommendation ? (
        <RecommendationCard recommendation={recommendation} squadState={week.squad_state} />
      ) : (
        <section className="dash-recommendation dash-recommendation-empty" data-testid="week-skipped">
          <h2>
            This gameweek <ModelBadge />
          </h2>
          <p className="dash-recommendation-action">
            {week.skipped_reason ??
              "No squad is available yet, so there is nothing to advise on. This is the normal state before the first gameweek is scored."}
          </p>
        </section>
      )}

      {!week.skipped && (
        <>
          <SquadSummary squad={squad} horizonGameweeks={horizonGameweeks} advised={week.advised} />
          <p className="dash-model-line" data-testid="decision-xi-model">
            Advised XI, captain and bench from <ModelBadge />
          </p>
          <SquadPitch squad={squad} rules={rules} />
          <Bench squad={squad} />
          <WhyThisNumber squad={squad} players={players} />
        </>
      )}

      {plan && !plan.skipped && <OwnershipBet plan={plan} />}
      <RulesSay rules={rules} plan={plan} />
      <AlertsPanel alerts={week.alerts} tone="informational" />
    </div>
  );
}

/** The component breakdown of any player in the advised squad, the captain first. */
function WhyThisNumber({ squad, players }: { squad: Squad; players: Players }) {
  const [picked, setPicked] = useState<number | null>(null);
  const id = picked ?? squad.captain_id ?? squad.players[0]?.player_id;
  const player = players.players.find((p) => p.id === id);
  if (!player) return null;
  return (
    <section className="player-panel" data-testid="why-this-number" aria-labelledby="why-heading">
      <h3 id="why-heading">Why this number</h3>
      <label>
        <span>Player </span>
        <select value={id} onChange={(e) => setPicked(Number(e.target.value))} data-testid="why-player">
          {squad.players.map((p) => (
            <option key={p.player_id} value={p.player_id}>
              {p.web_name}
              {p.player_id === squad.captain_id ? " (C)" : ""}
            </option>
          ))}
        </select>
      </label>
      <Decomposition player={player} />
    </section>
  );
}

/** The rules the advice was solved under, read from `rules.json` and the chip windows (Invariant 9). */
function RulesSay({ rules, plan }: { rules: Rules; plan: Plan | null }) {
  const { squad, transfers } = rules;
  const expiring = plan?.chip_calendar?.expiring ?? [];
  return (
    <section data-testid="rules-say" aria-labelledby="rules-heading">
      <h3 id="rules-heading">What the rules say</h3>
      <ul>
        <li>
          {squad.size} players, {squad.starting_size} in the XI, at most {squad.club_limit} from one
          club, within {formatPrice(squad.budget)}.
        </li>
        <li>
          Up to {transfers.max_free_transfers} free transfers can be banked; each extra transfer
          costs {Math.abs(transfers.extra_transfer_cost)} points.
        </li>
        {expiring.map((chip) => (
          <li key={chip.chip}>
            {chip.chip_label} expires at the GW{chip.expires_gameweek} deadline.
          </li>
        ))}
      </ul>
    </section>
  );
}
