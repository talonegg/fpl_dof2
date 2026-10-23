/**
 * Per-GW all-player xP MAE: the 2025/26 backtest (web/public/static/xp_accuracy.json) and the live season.
 * Types are generated from contracts/v1/xp_accuracy.schema.json into contract/types.ts.
 */
import type { XpAccuracy, XpAccuracyGameweek, XpAccuracySeason } from "../../contract/types";
import { XP_ACCURACY_URL, dataStore } from "../../data/store";

export type { XpAccuracy, XpAccuracyGameweek, XpAccuracySeason };
export { XP_ACCURACY_URL };

/** **Never throws**: null when missing, non-JSON or malformed. */
export function fetchXpAccuracy(): Promise<XpAccuracy | null> {
  return dataStore.get("xp_accuracy");
}
