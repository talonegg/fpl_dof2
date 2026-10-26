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

import type { League, LeagueEntry, LeagueSquad, Live, LiveFigures, LiveTeam, Players, Rules } from "../../contract/types";

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
  /**
   * The rank shown: the live rank while a gameweek is in play and this team has a live figure, the
   * league table's own rank otherwise (LIVE-05).
   */
  shownRank: number;
  /** Position in the view's order, from zero; what a re-ordered view falls back on. */
  place: number;
  /** Movement since FPL's last rank: positive is places gained. Null when not reported. */
  rankChange: number | null;
  /**
   * Points behind the leader. Zero for the leader; never negative. Null for a team with no live
   * figure in the live view, whose total is FPL's table, updated on FPL's clock rather than the
   * scorer's, and so cannot be set against the others.
   */
  pointsBehindLeader: number | null;
  /** The team as `live.json` publishes it, or null in the plain table or when it is not in it. */
  liveTeam: LiveTeam | null;
  /** Its provisional gameweek; null in the plain table and for a team that is "not live". */
  figures: LiveFigures | null;
  /**
   * The comparison against the owner, or null when there is none to make — because this row *is*
   * the owner, because this rival has no published squad, or because the anchor is missing.
   */
  comparison: SquadComparison | null;
}

export interface LeagueView {
  /** `live` while `live.json` is published (LIVE-05); `table` is the league table as FPL ranks it. */
  mode: "live" | "table";
  rows: LeagueRow[];
  anchor: AnchorState;
  owner: LeagueEntry | null;
  ownerSquad: LeagueSquad | null;
  /** Rivals with a published squad, excluding the owner. What the comparison columns can fill. */
  comparableCount: number;
}

/**
 * The whole view model.
 *
 * Without `live` it is the league table in FPL's rank order. With `live.json` (LIVE-05) the rows
 * are **ordered by live total**, each carrying its live rank (equal totals share one, as published)
 * and the movement since FPL's last rank. A team with no live figure, because it is past
 * `league_rival_limit` or its picks were not read, is not dropped and not guessed at: it keeps the
 * league table's own figures, is marked "not live", and is listed **after every live team in the
 * league table's own order**. Its figures are FPL's table, which FPL updates on its own clock while
 * the gameweek is scored, so setting them against the scorer's live totals would rank two
 * different moments as one.
 */
export function buildLeagueView(league: League, live: Live | null = null): LeagueView {
  const tableOrder = [...league.entries].sort((a, b) => a.rank - b.rank || a.entry_id - b.entry_id);
  const liveOf = (entry: LeagueEntry): LiveTeam | null =>
    live?.teams.find((team) => team.entry_id === entry.entry_id) ?? null;
  // A stable sort over the table order: live teams by live rank, then the ones that are not live.
  const rows = live
    ? [...tableOrder].sort(
        (a, b) => Number(!liveOf(a)?.live) - Number(!liveOf(b)?.live) || (liveOf(a)?.rank ?? 0) - (liveOf(b)?.rank ?? 0),
      )
    : tableOrder;
  const owner = tableOrder.find((entry) => entry.is_owner) ?? null;
  const ownerSquad = owner?.squad ?? null;
  const leaderTotal = tableOrder.length > 0 ? Math.max(...tableOrder.map((entry) => entry.total)) : 0;
  const liveTotals = rows.flatMap((entry) => liveOf(entry)?.live?.live_total ?? []);
  const liveLeader = liveTotals.length > 0 ? Math.max(...liveTotals) : 0;

  const anchor = anchorState(league, owner, ownerSquad);

  return {
    mode: live ? "live" : "table",
    anchor,
    owner,
    ownerSquad,
    comparableCount: tableOrder.filter((entry) => !entry.is_owner && entry.squad).length,
    rows: rows.map((entry, place) => {
      const team = liveOf(entry);
      const figures = team?.live ?? null;
      const liveRank = figures ? team?.rank : null;
      return {
        entry,
        isOwner: entry.is_owner,
        shownRank: liveRank ?? entry.rank,
        place,
        rankChange: movement(entry.last_rank, liveRank ?? entry.rank),
        // Clamped at zero: `total` is the season total and the leader holds the maximum, but a table
        // read mid-update could momentarily disagree, and a negative "behind" reads as nonsense.
        pointsBehindLeader: live
          ? figures
            ? Math.max(0, liveLeader - figures.live_total)
            : null
          : Math.max(0, leaderTotal - entry.total),
        liveTeam: team,
        figures,
        comparison:
          anchor === "anchored" && ownerSquad && !entry.is_owner && entry.squad
            ? compareSquads(ownerSquad, entry.squad)
            : null,
      };
    }),
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

function movement(lastRank: number | null | undefined, rank: number): number | null {
  // Zero is the API's "had no previous rank", not a rank of zero — a new entry has not held
  // still, it has never been placed, and reporting it as "no movement" would invent a history.
  if (lastRank === null || lastRank === undefined || lastRank === 0) return null;
  return lastRank - rank;
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

/**
 * What each of a squad's fifteen scored for that team in the published gameweek (ORC-14). Only the
 * fielded players count: `starting_ids` is the picks' own multipliers, so it is the XI after the
 * game's automatic substitutions (all fifteen under a bench chip); the bench earns nothing. The
 * armband is `rules.json`'s multiplier for the chip played, worn by the captain or, when he was not
 * fielded, the vice-captain. Null for a fielded player with no recorded points. Without published
 * chip rules no multiplier is applied (Invariant 9: never a literal).
 */
export function fieldedPoints(
  squad: LeagueSquad,
  chip: string | null,
  chips: Rules["chips"],
  pointsOf: (id: number) => number | null,
): Map<number, number | null> {
  const armband = chips ? (chips.captain_multiplier_by_chip[chip ?? ""] ?? chips.captain_multiplier) : 1;
  const fielded = new Set(squad.starting_ids);
  const wearer = [squad.captain_id, squad.vice_captain_id].find((id) => id !== null && fielded.has(id));
  return new Map(
    squad.player_ids.map((id): [number, number | null] => {
      if (!fielded.has(id)) return [id, 0];
      const points = pointsOf(id);
      return [id, points === null ? null : points * (id === wearer ? armband : 1)];
    }),
  );
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
    return a.place - b.place;
  });
}
