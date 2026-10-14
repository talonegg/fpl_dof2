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

export const XP_ACCURACY_URL = `${import.meta.env.BASE_URL}static/xp_accuracy.json`;

/** **Never throws**: null when missing, non-JSON or malformed. */
export async function fetchXpAccuracy(): Promise<XpAccuracy | null> {
  try {
    const res = await fetch(XP_ACCURACY_URL);
    if (!res.ok) return null;
    const contentType = res.headers.get("content-type") ?? "";
    if (contentType && !contentType.includes("json")) return null;
    const body = (await res.json()) as XpAccuracy;
    return body && typeof body === "object" && Array.isArray(body.seasons) ? body : null;
  } catch {
    return null;
  }
}
