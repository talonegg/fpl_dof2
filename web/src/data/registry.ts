import type { Models, ModelsHistory, Strategies, Strategy, XpAccuracy } from "../contract/types";

/**
 * The strategy registry as the app sees it (MOD-07). Every model id, label, role, description and
 * artefact path comes from `strategies.json`; nothing here names a strategy.
 */
export interface Registry {
  champion: string;
  /** Champion first, then by role, published before unpublished (the order the pipeline publishes). */
  entries: Strategy[];
}

/** What a component outside a data provider sees: every id renders as itself. */
export const EMPTY_REGISTRY: Registry = { champion: "", entries: [] };

/**
 * The registry of a deployment that has no `strategies.json` yet: the champion alone, at the files
 * that deployment publishes. shortcut: the only place a file name is written down; goes once every
 * deployment publishes the registry.
 */
export function buildRegistry(published: Strategies | null): Registry {
  if (published) return { champion: published.champion, entries: published.strategies };
  const champion: Strategy = {
    id: "champion",
    label: "Champion",
    description: "The live advice.",
    role: "champion",
    published: true,
    aliases: [],
    digest: "",
    plan: true,
    artefacts: { week: "week.json", plan: "plan.json" },
  };
  return { champion: champion.id, entries: [champion] };
}

/** The registry id a legacy value (an old `?model=`, a saved preference, a legacy key) means. */
export function resolveModel(registry: Registry, value: string | null | undefined): string | null {
  const v = (value ?? "").trim().toLowerCase();
  if (!v) return null;
  const hit = registry.entries.find((e) => [e.id, ...e.aliases].some((a) => a.toLowerCase() === v));
  return hit?.id ?? null;
}

export const findStrategy = (registry: Registry, id: string): Strategy | undefined =>
  registry.entries.find((e) => e.id === id);

export const modelLabel = (registry: Registry, id: string): string => findStrategy(registry, id)?.label ?? id;

export const modelDescription = (registry: Registry, id: string): string =>
  findStrategy(registry, id)?.description ?? "";

/** Live advice is the champion's alone; every other strategy is a comparison. */
export const isComparison = (registry: Registry, id: string): boolean => id !== registry.champion;

/** `ids` in registry order, then any the registry has never heard of in the order given. */
export function orderIds(registry: Registry, ids: Iterable<string>): string[] {
  const set = new Set(ids);
  const known = registry.entries.map((e) => e.id).filter((id) => set.has(id));
  return [...known, ...[...set].filter((id) => !known.includes(id))];
}

/** Dash patterns so charts read without colour; colours are the `--series-n` design tokens. */
const SERIES = 5;
const DASHES = ["", "6 3", "2 3", "8 3 2 3", "1 2"];

/** Colour and dash by the strategy's position in the registry, never by its id. */
export function seriesStyle(registry: Registry, id: string): { colour: string; dash: string } {
  const at = registry.entries.findIndex((e) => e.id === id);
  const i = at >= 0 ? at : [...id].reduce((n, c) => n + c.charCodeAt(0), 0);
  return { colour: `var(--series-${(i % SERIES) + 1})`, dash: DASHES[i % SERIES] };
}

// Legacy ids in the checked-in static files and in older models.json are mapped through the aliases
// at load; the files themselves are not rewritten.
const rekey = <T>(r: Registry, rec: Record<string, T>): Record<string, T> =>
  Object.fromEntries(Object.entries(rec).map(([k, v]) => [resolveModel(r, k) ?? k, v]));
const rid = (r: Registry, id: string): string => resolveModel(r, id) ?? id;

export function normaliseModels(r: Registry, m: Models): Models {
  return {
    ...m,
    champion: rid(r, m.champion),
    models: m.models.map((x) => ({ ...x, id: rid(r, x.id) })),
    gameweeks: m.gameweeks.map((g) => ({
      ...g,
      availability: rekey(r, g.availability),
      advice: rekey(r, g.advice),
      actual: g.actual && rekey(r, g.actual),
    })),
    season_to_date: m.season_to_date.map((s) => ({ ...s, model: rid(r, s.model) })),
  };
}

export function normaliseHistory(r: Registry, h: ModelsHistory): ModelsHistory {
  return {
    ...h,
    champion: rid(r, h.champion),
    models: h.models.map((x) => ({ ...x, id: rid(r, x.id) })),
    gameweeks: h.gameweeks.map((g) => ({ ...g, models: rekey(r, g.models) })),
    summary: h.summary.map((s) => ({ ...s, model: rid(r, s.model) })),
  };
}

export function normaliseAccuracy(r: Registry, a: XpAccuracy): XpAccuracy {
  return {
    ...a,
    seasons: a.seasons.map((s) => ({
      ...s,
      pooled_mae: rekey(r, s.pooled_mae),
      missing_models: rekey(r, s.missing_models),
      gameweeks: s.gameweeks.map((g) => ({ ...g, mae: rekey(r, g.mae) })),
    })),
  };
}
