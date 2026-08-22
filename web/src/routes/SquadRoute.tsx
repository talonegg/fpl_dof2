import { useMemo } from "react";
import { useData } from "../data/DataProvider";
import { useOwnerIdentity } from "../components/settings/identity";
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
 *
 * **Whose squad is this, against the team ID entered in Settings (E13-S2)?** `week.squad_state`
 * carries the `entry_id` the pipeline actually read picks for, when it read any — a declared or
 * reconstructed squad may carry none. Three states follow: no team ID entered (nothing to check,
 * nothing said), an `entry_id` that agrees (confirmed), or one that disagrees (said plainly, not
 * hidden — DP-09).
 */
export function SquadRoute() {
  const { rules, squad, players, week, plan } = useData();
  const identity = useOwnerIdentity();
  const index = useMemo(() => indexPlayers(players.players, squad), [players, squad]);
  const entryId = week?.squad_state?.entry_id ?? null;

  return (
    <>
      {identity.teamId !== null && entryId !== null && entryId !== identity.teamId && (
        <p className="squad-owned-note squad-owned-note-warn" data-testid="squad-owned-mismatch">
          This squad was built for entry {entryId}, not team ID {identity.teamId} entered in
          Settings — the badges on the scout table reflect entry {entryId}, not your own.
        </p>
      )}
      {identity.teamId !== null && entryId !== null && entryId === identity.teamId && (
        <p className="squad-owned-note" data-testid="squad-owned-match">
          This is your squad (entry {entryId}) — these fifteen are badged "In squad" on the scout
          table.
        </p>
      )}
      {identity.teamId !== null && entryId === null && (
        <p className="squad-owned-note" data-testid="squad-owned-unverified">
          Team ID {identity.teamId} is set in Settings, but this run has no entry ID to check it
          against — these fifteen are still badged "In squad" on the scout table.
        </p>
      )}
      <SquadPitch squad={squad} rules={rules} />
      <Bench squad={squad} />
      <SquadBuilder players={players.players} squad={squad} rules={rules} week={week} />
      {plan && <PlanTimeline plan={plan} index={index} />}
    </>
  );
}
