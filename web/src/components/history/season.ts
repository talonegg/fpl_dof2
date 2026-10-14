import type { Models, SeasonReplay } from "../../contract/types";
import { MODEL_CHOICES } from "../../data/model";
import type { ModelChoice } from "../../data/model";

/**
 * The current season, assembled from two sources that must never be confused:
 * - `replay`: the checked-in GW1–n replay (frozen models run *after* the gameweeks were played);
 * - `prospective`: models.json, whose picks the frozen harness recorded *before* each deadline and
 *   scored after it. Only scored gameweeks after the replay's last one are taken from it.
 * Pure: no I/O.
 */
export type Phase = "replay" | "prospective";

export interface SeasonRow {
  gameweek: number;
  phase: Phase;
  /** Points per model; absent when the model had no scored result that week. */
  points: Partial<Record<ModelChoice, number>>;
  cumulative: Partial<Record<ModelChoice, number>>;
}

export interface Season {
  season: string;
  rows: SeasonRow[];
  models: ModelChoice[];
  /** Last gameweek with any result, per phase (null if none). */
  asOf: { replay: number | null; prospective: number | null };
  totals: Partial<Record<ModelChoice, { replay: number; prospective: number; total: number }>>;
}

const isModel = (m: string): m is ModelChoice => (MODEL_CHOICES as readonly string[]).includes(m);

export function buildSeason(replay: SeasonReplay | null, models: Models | null): Season {
  const rows: SeasonRow[] = [];
  const replayLast = replay?.as_of_gameweek ?? 0;
  for (const g of replay?.gameweeks ?? []) {
    const points: SeasonRow["points"] = {};
    for (const [m, e] of Object.entries(g.models)) if (isModel(m)) points[m] = e.points;
    rows.push({ gameweek: g.gameweek, phase: "replay", points, cumulative: {} });
  }
  const sameSeason = !replay || !models || models.season === replay.season;
  if (models && sameSeason) {
    for (const g of [...models.gameweeks].sort((a, b) => a.gameweek - b.gameweek)) {
      if (g.gameweek <= replayLast || !g.actual) continue;
      const points: SeasonRow["points"] = {};
      for (const [m, a] of Object.entries(g.actual)) if (isModel(m) && a) points[m] = a.points;
      if (Object.keys(points).length) rows.push({ gameweek: g.gameweek, phase: "prospective", points, cumulative: {} });
    }
  }
  const seen = new Set<ModelChoice>();
  rows.forEach((r) => Object.keys(r.points).forEach((m) => seen.add(m as ModelChoice)));
  const ids = MODEL_CHOICES.filter((m) => seen.has(m));
  const totals: Season["totals"] = {};
  for (const m of ids) totals[m] = { replay: 0, prospective: 0, total: 0 };
  for (const r of rows) {
    for (const m of ids) {
      const p = r.points[m];
      const t = totals[m]!;
      if (p !== undefined) {
        t[r.phase] += p;
        t.total += p;
      }
      r.cumulative[m] = t.total;
    }
  }
  const last = (ph: Phase) => {
    const gw = rows.filter((r) => r.phase === ph).map((r) => r.gameweek);
    return gw.length ? Math.max(...gw) : null;
  };
  return {
    season: replay?.season ?? models?.season ?? "",
    rows,
    models: ids,
    asOf: { replay: last("replay"), prospective: last("prospective") },
    totals,
  };
}
