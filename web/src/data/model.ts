/**
 * Champion/challenger model choice.
 *
 * `week.json` is the champion (the live engine, and the default). `week_challenger.json`, when the
 * pipeline published one, is the C1 boosted xG+minutes model's answer in the same schema. The
 * choice is remembered in localStorage and can be forced with `?model=challenger` (or
 * `?model=champion`) in either the page query or the hash route's query, so a link can share it.
 */
export type ModelChoice = "champion" | "challenger";

export const MODEL_STORAGE_KEY = "fpl-dof.model";
export const MODEL_PARAM = "model";

export const MODEL_LABELS: Record<ModelChoice, string> = {
  champion: "Champion",
  challenger: "Challenger (C1)",
};

export const MODEL_DESCRIPTIONS: Record<ModelChoice, string> = {
  champion: "Current engine",
  challenger: "C1 boosted xG + minutes model",
};

function parse(value: string | null | undefined): ModelChoice | null {
  return value === "champion" || value === "challenger" ? value : null;
}

function fromUrl(): ModelChoice | null {
  if (typeof window === "undefined") return null;
  const search = new URLSearchParams(window.location.search).get(MODEL_PARAM);
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  const hashParam = q >= 0 ? new URLSearchParams(hash.slice(q + 1)).get(MODEL_PARAM) : null;
  return parse(hashParam) ?? parse(search);
}

export function readModelChoice(): ModelChoice {
  const url = fromUrl();
  if (url) return url;
  try {
    return parse(window.localStorage.getItem(MODEL_STORAGE_KEY)) ?? "champion";
  } catch {
    return "champion";
  }
}

export function storeModelChoice(model: ModelChoice): void {
  try {
    window.localStorage.setItem(MODEL_STORAGE_KEY, model);
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts for the session only.
  }
}
