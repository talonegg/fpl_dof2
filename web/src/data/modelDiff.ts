import type { Players, Week } from "../contract/types";

export interface DiffPlayer {
  id: number;
  name: string;
  position: string;
}

export interface ModelDiff {
  transfersDiffer: boolean;
  captainDiffers: boolean;
  viceDiffers: boolean;
  /** In the champion's XI but not the challenger's. */
  onlyChampionXI: DiffPlayer[];
  /** In the challenger's XI but not the champion's. */
  onlyChallengerXI: DiffPlayer[];
  sharedXI: DiffPlayer[];
  differenceCount: number;
}

function moveKey(week: Week): string[] {
  return (week.recommendation?.moves ?? [])
    .map((m) => `${m.out.player_id}>${m.in.player_id}`)
    .sort();
}

/** Where the two published recommendations disagree: transfers, captain/vice and XI. */
export function diffModels(champion: Week, challenger: Week, players: Players): ModelDiff {
  const byId = new Map(players.players.map((p) => [p.id, p]));
  const asPlayer = (id: number): DiffPlayer => {
    const p = byId.get(id);
    return { id, name: p?.name ?? `#${id}`, position: p?.position ?? "" };
  };
  const a = new Set(champion.advised?.starting ?? []);
  const b = new Set(challenger.advised?.starting ?? []);
  const onlyChampionXI = [...a].filter((id) => !b.has(id)).map(asPlayer);
  const onlyChallengerXI = [...b].filter((id) => !a.has(id)).map(asPlayer);
  const sharedXI = [...a].filter((id) => b.has(id)).map(asPlayer);
  const transfersDiffer = moveKey(champion).join(",") !== moveKey(challenger).join(",");
  const captainDiffers = champion.advised?.captain !== challenger.advised?.captain;
  const viceDiffers = champion.advised?.vice_captain !== challenger.advised?.vice_captain;
  return {
    transfersDiffer,
    captainDiffers,
    viceDiffers,
    onlyChampionXI,
    onlyChallengerXI,
    sharedXI,
    differenceCount:
      Number(transfersDiffer) + Number(captainDiffers) + Number(viceDiffers) + onlyChampionXI.length,
  };
}
