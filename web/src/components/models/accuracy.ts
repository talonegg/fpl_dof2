/** Per-GW all-player xP MAE (web/public/static/xp_accuracy.json, scripts/models_history/build_xp_accuracy.py). Static app data, typed here (contract/types.ts is generated). */
export interface XpAccuracySeason {
  season: string;
  kind: "backtest" | "replay" | "prospective";
  gameweeks: { gameweek: number; phase: "backtest" | "replay" | "prospective"; mae: Record<string, number> }[];
  pooled_mae: Record<string, number>;
  missing_models: Record<string, string>;
}

export interface XpAccuracy {
  contract_version: 1;
  metric: string;
  seasons: XpAccuracySeason[];
}

import { XP_ACCURACY_URL, dataStore } from "../../data/store";

export { XP_ACCURACY_URL };

/** **Never throws**: null when missing, non-JSON or malformed. */
export function fetchXpAccuracy(): Promise<XpAccuracy | null> {
  return dataStore.get("xp_accuracy");
}
