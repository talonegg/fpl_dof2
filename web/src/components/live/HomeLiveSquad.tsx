import { useMemo } from "react";
import type { Live, LiveFigures, LiveTeam } from "../../contract/types";
import { useData } from "../../data/DataProvider";
import { isProvisional } from "../../data/live";
import { LiveSquadTable } from "./LiveSquadTable";
import { ProvisionalMark, StatusMark, UpdatedAt } from "./LiveMarks";

/**
 * Home's squad card while a gameweek is in play (LIVE-06): each player's points so far (the
 * captain's multiplied), the projected substitutions, the gameweek total, its status and when it
 * was last refreshed, with the next gameweek's expected points beside each player. The advice of
 * each model stays in its own card below, as before.
 *
 * Everything shown was published in `live.json`, scored by the one realised scorer; it is
 * provisional until FPL data-checks the gameweek and says so. `log.json` stays the record.
 */
export function HomeLiveSquad({ live, owner, figures }: { live: Live; owner: LiveTeam; figures: LiveFigures }) {
  const { players } = useData();
  const byId = useMemo(() => new Map(players.players.map((p) => [p.id, p])), [players]);

  return (
    <section className="home-card" aria-labelledby="home-squad-heading" data-testid="home-squad">
      <h2 id="home-squad-heading">Your squad</h2>
      <p className="live-summary" data-testid="home-live">
        <span className="live-marks">
          <span>Gameweek {live.gameweek}</span>
          <StatusMark status={figures.status} testId="home-live-status" />
          {isProvisional(figures) && <ProvisionalMark testId="home-live-provisional" />}
        </span>
        <UpdatedAt asOf={live.as_of} testId="home-live-as-of" />
      </p>
      <dl className="home-facts">
        <div>
          <dt>Gameweek total</dt>
          <dd data-testid="home-live-points">
            {figures.points}
            {figures.hit_cost > 0 && <span className="home-sub"> after a {figures.hit_cost}-point hit</span>}
          </dd>
        </div>
        <div>
          <dt>Season total, live</dt>
          <dd data-testid="home-live-total">{figures.live_total}</dd>
        </div>
        {owner.rank !== null && (
          <div>
            <dt>Rank by live total</dt>
            <dd data-testid="home-live-rank">{owner.rank}</dd>
          </div>
        )}
        {figures.chip_label && (
          <div>
            <dt>Chip played</dt>
            <dd>{figures.chip_label}</dd>
          </div>
        )}
      </dl>
      {figures.vice_used && (
        <p className="home-sub" data-testid="home-live-vice">
          The captain has not played, so the armband counts for the vice-captain.
        </p>
      )}
      <LiveSquadTable
        figures={figures}
        players={byId}
        extra="xp"
        rowTestId={(id) => `home-squad-${id}`}
        caption={`Your squad in gameweek ${live.gameweek}: minutes and points so far, and expected points next gameweek`}
      />
      <p className="home-sub">
        Points are this gameweek&apos;s so far, the captain&apos;s multiplied; xP next is the forecast for the next
        gameweek.
      </p>
    </section>
  );
}
