import type { Player } from "../contract/types";
import { formatXp } from "../format";

interface DecompositionProps {
  player: Player;
}

const LABELS: Record<keyof Player["components"], string> = {
  appearance: "Appearance",
  goals: "Goals",
  assists: "Assists",
  clean_sheet: "Clean sheet",
  goals_conceded: "Goals conceded",
  saves: "Saves",
  defensive_contribution: "Defensive contribution",
  bonus: "Bonus",
  cards: "Cards",
};

export function Decomposition({ player }: DecompositionProps) {
  const entries = Object.entries(player.components) as [keyof Player["components"], number][];
  const sum = entries.reduce((acc, [, v]) => acc + v, 0);

  return (
    <div className="decomposition" data-testid="decomposition">
      <h3>
        {player.name} — xP next {formatXp(player.xp_next, player.xp_next_sd)}
      </h3>
      <p className="decomposition-hint">
        These components sum to xP next: {sum.toFixed(2)} ≈ {player.xp_next.toFixed(2)}
      </p>
      <ul className="decomposition-list">
        {entries.map(([key, value]) => (
          <li key={key} className={value < 0 ? "component-negative" : "component-positive"}>
            <span className="component-label">{LABELS[key]}</span>
            <span className="component-value">{value.toFixed(2)}</span>
          </li>
        ))}
      </ul>
      {player.news && <p className="decomposition-news">{player.news}</p>}
    </div>
  );
}
