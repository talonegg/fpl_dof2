import type { History, ModelAdvice, ModelGameweek, Models } from "../contract/types";

/** The most recent gameweek the harness recorded advice for, or null. */
export const latestGameweek = (models: Models | null): ModelGameweek | null =>
  models?.gameweeks[models.gameweeks.length - 1] ?? null;

/** Raw points a player scored in one gameweek (a double gameweek sums), or null when no fixture is recorded. */
export function pointsIn(history: History | null, playerId: number, gameweek: number | null): number | null {
  if (!history || gameweek === null) return null;
  const rows = history.players.find((p) => p.id === playerId)?.gameweeks.filter((g) => g.gw === gameweek) ?? [];
  return rows.length === 0 ? null : rows.reduce((sum, g) => sum + g.pts, 0);
}

/** A model's moves for a gameweek in one line, the hit beside them. */
export function transfersText(advice: ModelAdvice): string {
  const moves =
    advice.transfers.length > 0
      ? advice.transfers.map((t) => `${t.out_name} → ${t.in_name}`).join(", ")
      : "Roll (no transfer)";
  return advice.hit_points !== 0 ? `${moves} (${advice.hit_points} hit)` : moves;
}
