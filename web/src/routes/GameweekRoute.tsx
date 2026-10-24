import { useMemo } from "react";
import { useData } from "../data/DataProvider";
import { DecisionView } from "../components/gameweek/DecisionView";
import { PlanPanel } from "../components/PlanPanel";
import { PlanTimeline } from "../components/squad/PlanTimeline";
import { indexPlayers } from "../components/squad/draft";
import { currentSquad } from "../data/effective";
import "../components/squad/squad.css";

/**
 * `/gameweek` — this gameweek's decision for the chosen strategy (WEB-12). No `week.json`
 * is the normal preseason answer (DL-20), said rather than left blank (DP-15).
 */
export function GameweekRoute() {
  const { week, plan, squad, publishedSquad, rules, players, meta } = useData();
  if (!week) {
    return (
      <section className="placeholder" data-testid="gameweek-absent">
        <h2>This gameweek</h2>
        <p className="placeholder-summary">
          No decision has been published yet. It appears once the first gameweek has been scored.
        </p>
      </section>
    );
  }
  return (
    <DecisionView
      week={week}
      plan={plan}
      squad={squad}
      rules={rules}
      players={players}
      horizonGameweeks={meta.horizon_gameweeks}
      currentValue={currentSquad(publishedSquad, week, players).total_price}
    />
  );
}

/** `/gameweek/plan` — Plan ahead: the multi-gameweek plan and the chip calendar, from `plan.json`. */
export function PlanAheadRoute() {
  const { plan, players, squad } = useData();
  const index = useMemo(() => indexPlayers(players.players, squad), [players, squad]);
  if (!plan) {
    return (
      <section className="placeholder" data-testid="plan-absent">
        <h2>Plan ahead</h2>
        <p className="placeholder-summary">
          No plan has been published yet. It appears once there is a squad to plan around.
        </p>
      </section>
    );
  }
  return (
    <>
      <PlanPanel plan={plan} />
      <PlanTimeline plan={plan} index={index} />
    </>
  );
}
