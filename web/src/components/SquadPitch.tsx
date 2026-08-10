import type { Rules, Squad } from "../contract/types";
import { formatPrice } from "../format";
import { PlayerCard, type SquadPlayer } from "./PlayerCard";

interface SquadPitchProps {
  squad: Squad;
  rules: Rules;
}

const ROW_ORDER: SquadPlayer["position"][] = ["GKP", "DEF", "MID", "FWD"];

export function SquadPitch({ squad, rules }: SquadPitchProps) {
  const starters = squad.players.filter((p) => p.starting);
  const budget = squad.budget ?? rules.squad.budget;

  return (
    <section data-testid="squad-pitch" className="squad-section">
      <div className="squad-summary">
        <div>
          <strong>{formatPrice(squad.total_price)}</strong> of {formatPrice(budget)} budget
        </div>
        <div>
          Formation {ROW_ORDER.map((pos) => squad.formation[pos] ?? 0).join("-")}
        </div>
        <div>
          Status: <span className={`solve-status solve-status-${squad.status}`}>{squad.status}</span>
        </div>
      </div>

      {squad.status === "greedy_fallback" && (
        <div className="squad-fallback-notice" data-testid="squad-fallback-notice">
          This squad is legal but was produced by a fallback heuristic — it is not proven optimal.
        </div>
      )}

      <div className="pitch">
        {ROW_ORDER.map((pos) => {
          const rowPlayers = starters.filter((p) => p.position === pos);
          if (rowPlayers.length === 0) return null;
          return (
            <div className="pitch-row" key={pos} data-testid={`pitch-row-${pos}`}>
              {rowPlayers.map((p) => (
                <PlayerCard
                  key={p.player_id}
                  player={p}
                  isCaptain={p.player_id === squad.captain_id}
                  isViceCaptain={p.player_id === squad.vice_captain_id}
                  variant="pitch"
                />
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}
