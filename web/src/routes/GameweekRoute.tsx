import { useMemo } from "react";
import { useData } from "../data/DataProvider";
import { WeekPanel } from "../components/WeekPanel";
import { PlanTimeline } from "../components/squad/PlanTimeline";
import { indexPlayers } from "../components/squad/draft";
import "../components/squad/squad.css";

/**
 * `/gameweek` — this gameweek's decision for the chosen strategy (WEB-07 interim; WEB-12 builds it
 * out). No `week.json` is the normal preseason answer (DL-20), said rather than left blank (DP-15).
 */
export function GameweekRoute() {
  const { week } = useData();
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
  return <WeekPanel week={week} />;
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
  return <PlanTimeline plan={plan} index={index} />;
}
