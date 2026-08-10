import type { Squad } from "../contract/types";
import { PlayerCard } from "./PlayerCard";

interface BenchProps {
  squad: Squad;
}

export function Bench({ squad }: BenchProps) {
  const nonStarters = squad.players.filter((p) => !p.starting);
  const reserveKeeper = nonStarters.find((p) => p.position === "GKP");
  const outfieldBench = squad.bench_order
    .map((id) => nonStarters.find((p) => p.player_id === id))
    .filter((p): p is NonNullable<typeof p> => p !== undefined);

  const orderedBench = [reserveKeeper, ...outfieldBench].filter(
    (p): p is NonNullable<typeof p> => p !== undefined,
  );

  return (
    <section data-testid="bench" className="bench-section">
      <h2>Bench</h2>
      <div className="bench-row">
        {orderedBench.map((p, i) => (
          <div key={p.player_id} className="bench-slot">
            <div className="bench-slot-label">{i === 0 ? "GK" : i}</div>
            <PlayerCard
              player={p}
              isCaptain={p.player_id === squad.captain_id}
              isViceCaptain={p.player_id === squad.vice_captain_id}
              variant="bench"
            />
          </div>
        ))}
      </div>
    </section>
  );
}
