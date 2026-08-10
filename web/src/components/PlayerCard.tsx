import type { Squad } from "../contract/types";
import { formatPrice, formatXp } from "../format";

export type SquadPlayer = Squad["players"][number];

interface PlayerCardProps {
  player: SquadPlayer;
  isCaptain: boolean;
  isViceCaptain: boolean;
  variant?: "pitch" | "bench";
}

export function PlayerCard({ player, isCaptain, isViceCaptain, variant = "pitch" }: PlayerCardProps) {
  return (
    <div className={`player-card player-card-${variant}`} data-testid="squad-player-card">
      <div className="player-card-badges">
        {isCaptain && <span className="badge badge-captain" title="Captain">C</span>}
        {isViceCaptain && <span className="badge badge-vice" title="Vice-captain">V</span>}
      </div>
      <div className="player-card-name">{player.web_name}</div>
      <div className="player-card-sub">
        {player.team} · {formatPrice(player.price)}
      </div>
      <div className="player-card-xp">{formatXp(player.xp_next, player.xp_next_sd)}</div>
    </div>
  );
}
