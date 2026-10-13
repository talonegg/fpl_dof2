/**
 * Model choice: the champion and four frozen comparison models.
 *
 * `week.json` is the champion (the live engine, and the default). `week_challenger.json`, when the
 * pipeline published one, is C1's answer in week.json's schema, so choosing the challenger swaps the
 * whole week. `models.json` carries every frozen model's pre-deadline advice and actual points; the
 * engine, A and A+odds are shown from it as comparison cards. **Live advice is the champion's
 * alone** — every other model is labelled as a comparison wherever it appears.
 *
 * The choice is remembered in localStorage and can be forced with `?model=<id>` in either the page
 * query or the hash route's query, so a link can share it.
 */
export const MODEL_CHOICES = ["champion", "challenger", "engine", "a", "a_odds"] as const;
export type ModelChoice = (typeof MODEL_CHOICES)[number];

export const MODEL_STORAGE_KEY = "fpl-dof.model";
export const MODEL_PARAM = "model";

export const MODEL_LABELS: Record<ModelChoice, string> = {
  champion: "Champion",
  challenger: "Challenger (C1)",
  engine: "Engine",
  a: "Model A",
  a_odds: "A + odds",
};

export const MODEL_SHORT_LABELS: Record<ModelChoice, string> = {
  champion: "Champion",
  challenger: "C1",
  engine: "Engine",
  a: "A",
  a_odds: "A+odds",
};

export const MODEL_DESCRIPTIONS: Record<ModelChoice, string> = {
  champion: "Current engine (C3), live advice",
  challenger: "C1 boosted xG + minutes model",
  engine: "Original engine, engine captain",
  a: "Component xPts model A",
  a_odds: "Model A with the odds team layer",
};

/** Whether a model's advice is the live one. Everything else is a comparison. */
export function isComparison(model: ModelChoice): boolean {
  return model !== "champion";
}

/** Models that ship a full week (week.json schema). The rest are shown from models.json. */
export function hasFullWeek(model: ModelChoice): model is "champion" | "challenger" {
  return model === "champion" || model === "challenger";
}

export function parseModel(value: string | null | undefined): ModelChoice | null {
  return (MODEL_CHOICES as readonly string[]).includes(value ?? "") ? (value as ModelChoice) : null;
}

function fromUrl(): ModelChoice | null {
  if (typeof window === "undefined") return null;
  const search = new URLSearchParams(window.location.search).get(MODEL_PARAM);
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  const hashParam = q >= 0 ? new URLSearchParams(hash.slice(q + 1)).get(MODEL_PARAM) : null;
  return parseModel(hashParam) ?? parseModel(search);
}

export function readModelChoice(): ModelChoice {
  const url = fromUrl();
  if (url) return url;
  try {
    return parseModel(window.localStorage.getItem(MODEL_STORAGE_KEY)) ?? "champion";
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
