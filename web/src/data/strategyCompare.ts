import type { Plan, Players, Week } from "../contract/types";

export interface DiffPlayer {
  id: number;
  name: string;
  position: string;
}

/** One strategy's advice for this gameweek, flattened from its week and plan artefacts. */
export interface StrategyAdvice {
  id: string;
  transfers: string[];
  transferKeys: string[];
  hitPoints: number;
  netXp: number | null;
  captain: number | null;
  vice: number | null;
  formation: string | null;
  starting: number[];
  bench: number[];
  chip: string | null;
}

/** Where one strategy's advice departs from the baseline's. */
export interface StrategyDiff {
  transfersDiffer: boolean;
  captainDiffers: boolean;
  viceDiffers: boolean;
  benchDiffers: boolean;
  chipDiffers: boolean;
  /** In this strategy's XI but not the baseline's. */
  xiIn: number[];
  /** In the baseline's XI but not this strategy's. */
  xiOut: number[];
}

/** A player the compared strategies do not all agree on, with the xP their week artefacts carry. */
export interface Disagreement {
  player: DiffPlayer;
  inXI: Record<string, boolean>;
  /** Strategies that captain him. */
  captainOf: string[];
  /** xP for the next gameweek where a strategy's recommended moves mention him; absent otherwise. */
  xp: Record<string, number>;
}

export interface Comparison {
  baseline: string;
  /** The compared strategies that have a week, in the order given. */
  advice: StrategyAdvice[];
  /** Against the baseline, for every strategy but the baseline. */
  diffs: Record<string, StrategyDiff>;
  disagreements: Disagreement[];
  /** Asked for but with no week to compare. */
  missing: string[];
}

function adviceOf(id: string, week: Week, plan: Plan | undefined): StrategyAdvice {
  const moves = week.recommendation?.moves ?? [];
  const adv = week.advised;
  return {
    id,
    transfers: moves.map((m) => `${m.out.web_name} → ${m.in.web_name}`),
    transferKeys: moves.map((m) => `${m.out.player_id}>${m.in.player_id}`).sort(),
    hitPoints: week.recommendation?.hit_points ?? 0,
    netXp: week.recommendation?.net_expected_points ?? null,
    captain: adv?.captain ?? null,
    vice: adv?.vice_captain ?? null,
    formation: adv?.formation ?? null,
    starting: adv?.starting ?? [],
    bench: adv?.bench_order ?? [],
    chip: plan?.recommended?.weeks[0]?.chip_label ?? null,
  };
}

function same<T>(a: T[], b: T[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * Compare the advice of two or more strategies for the same gameweek against a baseline (the
 * champion by default). Pure: it reads only the week and plan artefacts it is given.
 */
export function compareStrategies(
  baselineId: string,
  ids: string[],
  weeks: Record<string, Week | undefined>,
  plans: Record<string, Plan | undefined>,
  players: Players,
): Comparison {
  const present = ids.filter((id) => weeks[id]);
  const advice = present.map((id) => adviceOf(id, weeks[id]!, plans[id]));
  const baseline = present.includes(baselineId) ? baselineId : (present[0] ?? baselineId);
  const base = advice.find((a) => a.id === baseline);

  const diffs: Record<string, StrategyDiff> = {};
  if (base) {
    for (const a of advice) {
      if (a.id === baseline) continue;
      diffs[a.id] = {
        transfersDiffer: !same(a.transferKeys, base.transferKeys),
        captainDiffers: a.captain !== base.captain,
        viceDiffers: a.vice !== base.vice,
        benchDiffers: !same(a.bench, base.bench),
        chipDiffers: a.chip !== base.chip,
        xiIn: a.starting.filter((p) => !base.starting.includes(p)),
        xiOut: base.starting.filter((p) => !a.starting.includes(p)),
      };
    }
  }

  const byId = new Map(players.players.map((p) => [p.id, p]));
  const asPlayer = (id: number): DiffPlayer => {
    const p = byId.get(id);
    return { id, name: p?.name ?? `#${id}`, position: p?.position ?? "" };
  };
  const everyone = new Set(advice.flatMap((a) => [...a.starting, ...(a.captain != null ? [a.captain] : [])]));
  const disagreements: Disagreement[] = [];
  for (const id of [...everyone].sort((a, b) => a - b)) {
    const inXI = Object.fromEntries(advice.map((a) => [a.id, a.starting.includes(id)]));
    const captainOf = advice.filter((a) => a.captain === id).map((a) => a.id);
    const xiAgree = new Set(Object.values(inXI)).size === 1;
    const capAgree = captainOf.length === 0 || captainOf.length === advice.length;
    if (xiAgree && capAgree) continue;
    const xp: Record<string, number> = {};
    for (const a of advice) {
      for (const m of weeks[a.id]?.recommendation?.moves ?? []) {
        for (const side of [m.in, m.out]) {
          if (side.player_id === id && side.xp_next !== undefined) xp[a.id] = side.xp_next;
        }
      }
    }
    disagreements.push({ player: asPlayer(id), inXI, captainOf, xp });
  }

  return { baseline, advice, diffs, disagreements, missing: ids.filter((id) => !weeks[id]) };
}
