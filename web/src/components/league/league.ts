/**
 * Mini-league comparison: pure functions over `league.json` (E6-S10, FR-32).
 *
 * DOM-free on purpose, like `fixtures/ticker.ts` — everything interesting here is set arithmetic
 * over two squads, and it should be checkable without rendering anything.
 *
 * The pipeline publishes the standings and the squads; the comparison is derived here rather than
 * precomputed there, so the reader sees the answer next to the fifteen it came from (DP-10). Three
 * rules the tests exist to hold:
 *
 * - **The anchor is the owner's own row, never the recommended squad.** `squad.json` is what the
 *   optimiser suggests, which is usually *not* what is fielded; measuring differentials against it
 *   would report players the owner does not own as players the owner is differentiating with. When
 *   there is no owner row, or no squad on it, the comparison is refused rather than approximated —
 *   `anchor` says which, so the view can explain itself instead of rendering an empty column.
 * - **Absent is not empty.** A rival outside the fetch budget has `squad: null`, which is a
 *   different claim from "a rival who owns nobody in common". They never collapse to the same row.
 * - **Differentials have a direction.** A player only the rival owns is a risk; a player only the
 *   owner owns is a bet. One number cannot say both, so they are never summed.
 */

import type { League, LeagueEntry, LeagueSquad, Players } from "../../contract/types";

/** Why a comparison could or could not be anchored. Drives the copy, and is not cosmetic. */
export type AnchorState =
  /** The owner is in this league and their squad was published: comparisons are real. */
  | "anchored"
  /** No gameweek has been scored, so nobody — owner or rival — has a squad to read (DL-20). */
  | "no_gameweek"
  /** No team is configured, or the configured team is not in this league. */
  | "no_owner_row"
  /** The owner is in the league but their squad was not published for this gameweek. */
  | "no_owner_squad";

export interface SquadComparison {
  /** Players both squads hold, ascending. */
  overlapIds: number[];
  /** Held by the owner and not by this rival — the owner's bet against them. */
  ownerOnlyIds: number[];
  /** Held by this rival and not by the owner — what the owner is exposed to. */
  rivalOnlyIds: number[];
  /** This rival's captain. Null when the picks carried no captain flag. */
  captainId: number | null;
  /**
   * Whether this rival captained someone other than the owner did. Null — not false — when either
   * captain is unknown: "we cannot tell" and "they agree" are different answers, and rendering the
   * first as the second is the quiet kind of wrong (DP-09).
   */
  captainDiverges: boolean | null;
}

export interface LeagueRow {
  entry: LeagueEntry;
  isOwner: boolean;
  /** Movement since the last update: positive is places gained. Null when not reported. */
  rankChange: number | null;
  /** Points behind the leader. Zero for the leader; never negative. */
  pointsBehindLeader: number;
  /**
   * The comparison against the owner, or null when there is none to make — because this row *is*
   * the owner, because this rival has no published squad, or because the anchor is missing.
   */
  comparison: SquadComparison | null;
}

export interface LeagueView {
  rows: LeagueRow[];
  anchor: AnchorState;
  owner: LeagueEntry | null;
  ownerSquad: LeagueSquad | null;
  /** Rivals with a published squad, excluding the owner. What the comparison columns can fill. */
  comparableCount: number;
}

/** The whole view model, in rank order. */
export function buildLeagueView(league: League): LeagueView {
  const rows = [...league.entries].sort((a, b) => a.rank - b.rank || a.entry_id - b.entry_id);
  const owner = rows.find((entry) => entry.is_owner) ?? null;
  const ownerSquad = owner?.squad ?? null;
  const leaderTotal = rows.length > 0 ? Math.max(...rows.map((entry) => entry.total)) : 0;

  const anchor = anchorState(league, owner, ownerSquad);

  return {
    anchor,
    owner,
    ownerSquad,
    comparableCount: rows.filter((entry) => !entry.is_owner && entry.squad).length,
    rows: rows.map((entry) => ({
      entry,
      isOwner: entry.is_owner,
      rankChange: rankChange(entry),
      // Clamped at zero: `total` is the season total and the leader holds the maximum, but a table
      // read mid-update could momentarily disagree, and a negative "behind" reads as nonsense.
      pointsBehindLeader: Math.max(0, leaderTotal - entry.total),
      comparison:
        anchor === "anchored" && ownerSquad && !entry.is_owner && entry.squad
          ? compareSquads(ownerSquad, entry.squad)
          : null,
    })),
  };
}

function anchorState(
  league: League,
  owner: LeagueEntry | null,
  ownerSquad: LeagueSquad | null,
): AnchorState {
  if (league.gameweek === null) return "no_gameweek";
  if (!owner) return "no_owner_row";
  if (!ownerSquad) return "no_owner_squad";
  return "anchored";
}

function rankChange(entry: LeagueEntry): number | null {
  // Zero is the API's "had no previous rank", not a rank of zero — a new entry has not held
  // still, it has never been placed, and reporting it as "no movement" would invent a history.
  if (entry.last_rank === null || entry.last_rank === undefined || entry.last_rank === 0) {
    return null;
  }
  return entry.last_rank - entry.rank;
}

/** Set arithmetic over two fifteens. The whole of the overlap and differential story. */
export function compareSquads(owner: LeagueSquad, rival: LeagueSquad): SquadComparison {
  const ownerIds = new Set(owner.player_ids);
  const rivalIds = new Set(rival.player_ids);

  return {
    overlapIds: owner.player_ids.filter((id) => rivalIds.has(id)).sort((a, b) => a - b),
    ownerOnlyIds: owner.player_ids.filter((id) => !rivalIds.has(id)).sort((a, b) => a - b),
    rivalOnlyIds: rival.player_ids.filter((id) => !ownerIds.has(id)).sort((a, b) => a - b),
    captainId: rival.captain_id,
    captainDiverges:
      owner.captain_id === null || rival.captain_id === null
        ? null
        : owner.captain_id !== rival.captain_id,
  };
}

/** Player id to display name, for turning an id list into something a human can read. */
export function playerNames(players: Players): Map<number, string> {
  return new Map(players.players.map((player) => [player.id, player.name]));
}

/**
 * Name a list of player ids, longest-held convention first: known names in the order given, and an
 * id that is not in `players.json` rendered as an id rather than dropped. A silently dropped player
 * would make an overlap of eleven read as an overlap of nine.
 */
export function nameList(ids: number[], names: Map<number, string>): string[] {
  return ids.map((id) => names.get(id) ?? `#${id}`);
}

/** Rivals ordered by how much of the owner's squad they share, most alike first. */
export function byOverlapDescending(rows: LeagueRow[]): LeagueRow[] {
  return [...rows].sort((a, b) => {
    const left = a.comparison?.overlapIds.length ?? -1;
    const right = b.comparison?.overlapIds.length ?? -1;
    // A row with no comparison sorts last in this order rather than as a zero overlap, for the
    // same reason a null mean sorts last in the fixture ticker: unknown is not extreme.
    if (left !== right) return right - left;
    return a.entry.rank - b.entry.rank;
  });
}
