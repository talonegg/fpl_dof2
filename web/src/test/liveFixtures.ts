import type { Live, LiveFigures, LiveGame, LivePlayer, LiveTeam, Players } from "../contract/types";
import { players } from "./fixtures";

/**
 * `live.json` for the tests (LIVE-04 shape; validated against `contracts/v1/live.schema.json`).
 *
 * Gameweek 4, over the league in `leagueTable` (whose own figures are as at gameweek 3). The owner
 * is entry 200, "DOF Select", and the table below is the point of the fixture: the live order
 * is not the league's.
 *
 * | Entry | League table | Live total | Why |
 * | --- | --- | --- | --- |
 * | 200 DOF Select (owner) | 2nd, 198 | 239, 1st | 41 net of a 4-point hit |
 * | 100 Roy Race XI | 1st, 210 | 228, 2nd | 18, Triple Captain |
 * | 400 New Arrival | 4th, 150 | 165, 3rd | 15; never ranked before |
 * | 300 Beyond The Budget | 3rd, 175 | none | past the rival limit: "not live", listed last |
 *
 * The owner's fifteen is ids 1 to 15 in slot order: Watkins (2) is captain and doubles, Mbeumo
 * (3) is still playing with his bonus pending, player 6 is yet to play, and player 8 finished the
 * gameweek without a minute so player 12 is projected on for him.
 */

/** `players.json` with the owner's whole fifteen, so a name is a name and not `#7`. */
export const liveRoster: Players = {
  ...players,
  players: [
    ...players.players,
    ...Array.from({ length: 12 }, (_, i) => ({
      ...players.players[1],
      id: i + 4,
      name: `Squad man ${i + 4}`,
      full_name: `Squad man ${i + 4}`,
      position: "DEF" as const,
      team: "TST",
      xp_next: 2 + i / 10,
    })),
  ],
};

interface PlayerLine {
  minutes: number;
  points: number;
  bonus?: number;
  confirmed?: boolean;
  complete?: boolean;
  multiplier?: number;
}

function line(id: number, spec: PlayerLine, captain = 2, vice = 1): LivePlayer {
  return {
    player_id: id,
    slot: id,
    minutes: spec.minutes,
    points: spec.points,
    bonus: spec.bonus ?? 0,
    bonus_confirmed: spec.confirmed ?? true,
    complete: spec.complete ?? true,
    multiplier: spec.multiplier ?? (id <= 11 ? 1 : 0),
    is_captain: id === captain,
    is_vice_captain: id === vice,
  };
}

const OWNER_LINES: PlayerLine[] = [
  { minutes: 90, points: 6 }, // 1 Raya
  { minutes: 90, points: 8, bonus: 2, multiplier: 2 }, // 2 Watkins, the captain
  { minutes: 67, points: 5, confirmed: false, complete: false }, // 3 Mbeumo, still playing
  { minutes: 90, points: 2 }, // 4
  { minutes: 90, points: 1 }, // 5
  { minutes: 0, points: 0, complete: false }, // 6 yet to play
  { minutes: 90, points: 3 }, // 7
  { minutes: 0, points: 0, multiplier: 0 }, // 8 finished without a minute: projected off
  { minutes: 90, points: 2 }, // 9
  { minutes: 90, points: 6, bonus: 3 }, // 10
  { minutes: 80, points: 2 }, // 11
  { minutes: 30, points: 2, multiplier: 1 }, // 12 projected on for 8
  { minutes: 0, points: 0 }, // 13
  { minutes: 0, points: 0 }, // 14
  { minutes: 0, points: 0 }, // 15
];

/** Everyone plays ninety minutes and the captain doubles or triples: a rival with nothing to project. */
const rivalLines = (captainMultiplier: number): PlayerLine[] =>
  [1, 3, 1, 1, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0].map((points, i) => ({
    minutes: i < 11 ? 90 : 0,
    points,
    multiplier: i === 1 ? captainMultiplier : i < 11 ? 1 : 0,
  }));

/** Totals follow from the lines: points times the multiplier, less the hit, added to the last total. */
function figures(
  lines: PlayerLine[],
  status: Live["status"],
  extra: Partial<LiveFigures> & { last_total: number },
): LiveFigures {
  const players = lines.map((spec, i) => line(i + 1, spec));
  const before = players.reduce((sum, p) => sum + p.points * p.multiplier, 0);
  const hit = extra.hit_cost ?? 0;
  return {
    hit_cost: hit,
    chip: null,
    chip_label: null,
    status,
    captain_id: 2,
    vice_used: false,
    autosubs_in: [],
    autosubs_out: [],
    players,
    ...extra,
    points_before_hits: before,
    points: before - hit,
    live_total: extra.last_total + before - hit,
  };
}

function team(
  entry_id: number,
  entry_name: string,
  player_name: string | null,
  rank: number | null,
  live: LiveFigures | null,
  extra: Partial<LiveTeam> = {},
): LiveTeam {
  return {
    entry_id,
    entry_name,
    player_name,
    is_owner: false,
    rank,
    live,
    reason: live ? null : "no picks were read for this team",
    game: null,
    matches_game: null,
    ...extra,
  };
}

const game = (points: number, hit_cost: number, total: number, final: boolean): LiveGame => ({ points, hit_cost, total, final });

/**
 * Gameweek 4 at a given stage. `in_play` is a Saturday evening; `bonus_pending` and `complete`
 * every fixture at full time; `final` once FPL has data-checked it, when the scorer's figure is
 * compared with FPL's and `matches_game` is true (set false on a team to test the mismatch note).
 */
export function liveGameweek(status: Live["status"] = "in_play"): Live {
  const final = status === "final";
  const settled = status === "complete" || final;
  // Once everyone has played, nobody is mid-match and the projected substitution stands.
  const owner = figures(
    settled
      ? OWNER_LINES.map((spec, i) => (i === 2 ? { ...spec, minutes: 90, confirmed: true, complete: true } : i === 5 ? { ...spec, minutes: 15, points: 1, complete: true } : spec))
      : OWNER_LINES,
    status,
    { hit_cost: 4, last_total: 198, autosubs_in: [12], autosubs_out: [8] },
  );
  const rival = figures(rivalLines(3), status, { last_total: 210, chip: "3xc", chip_label: "Triple Captain" });
  const newcomer = figures(rivalLines(2), status, { last_total: 150 });
  const compared = (figs: LiveFigures): Pick<LiveTeam, "game" | "matches_game"> => ({
    game: game(figs.points_before_hits, figs.hit_cost, figs.live_total, final),
    matches_game: final ? true : null,
  });

  return {
    contract_version: 1,
    gameweek: 4,
    status,
    provisional: !final,
    as_of: "2026-09-19T21:30:00Z",
    observed_at: "2026-09-19T21:20:00Z",
    matchdays: [
      {
        date: "2026-09-19",
        fixtures: 2,
        fixtures_confirmed: settled ? 2 : 1,
        last_kickoff: "2026-09-19T16:30:00Z",
        done: settled,
        bonus_pending: false,
      },
    ],
    fixtures: [
      { fixture_id: 1, kickoff_time: "2026-09-19T14:00:00Z", matchday: "2026-09-19", home_team_id: 1, away_team_id: 2, state: "bonus_confirmed" },
      {
        fixture_id: 2,
        kickoff_time: "2026-09-19T16:30:00Z",
        matchday: "2026-09-19",
        home_team_id: 16,
        away_team_id: 3,
        state: settled ? "bonus_confirmed" : "playing",
      },
    ],
    teams: [
      team(200, "DOF Select", "The Owner", 1, owner, { is_owner: true, ...compared(owner) }),
      team(100, "Roy Race XI", "Alex Stone", 2, rival, compared(rival)),
      team(400, "New Arrival", "Jo Patel", 3, newcomer, compared(newcomer)),
      team(300, "Beyond The Budget", "Sam Reed", null, null, {
        reason: "past the rival limit, so its picks were not read",
      }),
    ],
  };
}
