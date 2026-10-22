/**
 * Model choice: which registered strategy the app shows.
 *
 * The strategies, their labels and what each publishes come from `strategies.json` (see
 * `registry.ts`). The champion is the default and the only live advice; every other strategy is a
 * comparison wherever it appears. The choice is remembered in localStorage and can be forced with
 * `?model=<id or legacy alias>` in either the page query or the hash route's query, so a link can
 * share it; `resolveModel` maps the value to a registry id once the registry has loaded.
 */
export type ModelChoice = string;

export const MODEL_STORAGE_KEY = "fpl-dof.model";
export const MODEL_PARAM = "model";

function fromUrl(): string | null {
  if (typeof window === "undefined") return null;
  const search = new URLSearchParams(window.location.search).get(MODEL_PARAM);
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  const hashParam = q >= 0 ? new URLSearchParams(hash.slice(q + 1)).get(MODEL_PARAM) : null;
  return hashParam || search || null;
}

/** The raw requested model: the URL first, then the saved preference. Empty means the champion. */
export function readModelChoice(): string {
  const url = fromUrl();
  if (url) return url;
  try {
    return window.localStorage.getItem(MODEL_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function storeModelChoice(model: string): void {
  try {
    window.localStorage.setItem(MODEL_STORAGE_KEY, model);
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts for the session only.
  }
}
