import { useMemo } from "react";
import { useData } from "../data/DataProvider";
import { SquadPitch } from "../components/SquadPitch";
import { Bench } from "../components/Bench";
import { SquadBuilder } from "../components/squad/SquadBuilder";
import { PlanTimeline } from "../components/squad/PlanTimeline";
import { indexPlayers } from "../components/squad/draft";
import "../components/squad/squad.css";

/**
 * `/squad` — the squad builder and transfer planner (E6-S7, FR-31).
 *
 * Three layers, in the order a reader wants them:
 *
 * 1. **What the optimiser produced** — the pitch and bench, unchanged from E6-S1. This is the
 *    recommendation, and it stays visually distinct from anything the reader then does to it.
 * 2. **What the reader can do to it** — the builder: swap players, start and bench them, lock and
 *    ban, and re-optimise around those constraints. Every edit is checked live against `rules.json`
 *    by `components/squad/legality.ts`, which is parameterised from the published rules and restates
 *    none of them (DL-14, Invariant 9).
 * 3. **What happens next** — the multi-gameweek plan as named transfers per gameweek, and the chip
 *    calendar with its expiry clock, both from `plan.json` (E4).
 *
 * The plan section is absent, rather than empty, when nothing has been published: before the first
 * scored gameweek there is no squad to plan around, which is a normal state and not a failure
 * (DL-20, DP-15).
 */
export function SquadRoute() {
  const { rules, squad, players, week, plan } = useData();
  const index = useMemo(() => indexPlayers(players.players, squad), [players, squad]);

  return (
    <>
      <SquadPitch squad={squad} rules={rules} />
      <Bench squad={squad} />
      <SquadBuilder players={players.players} squad={squad} rules={rules} week={week} />
      {plan && <PlanTimeline plan={plan} index={index} />}
    </>
  );
}
