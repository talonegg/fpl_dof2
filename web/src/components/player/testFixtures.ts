/**
 * Fixtures for the two lazy trend artefacts.
 *
 * Local to this story rather than added to `src/test/fixtures.ts`: `history.json` and
 * `fixtures.json` are not part of the shell's eager load (DL-37), so the shared stub does not serve
 * them and does not need to. Keeping them here means the player tests can stub whatever shape they
 * need without moving the ground under every other suite.
 *
 * The shapes here deliberately include the awkward cases: a double gameweek, a blank, a gameweek
 * with no `xg` measured, and a player with no gameweeks at all.
 */

import type { Fixtures, History } from "../../contract/types";

/** A season under way: Raya (id 1) has played, with one double and one unmeasured gameweek. */
export const history: History = {
  contract_version: 1,
  season: "2026/27",
  gameweeks_played: 4,
  observed_from: "2026-08-01",
  observed_to: "2026-09-12",
  players: [
    {
      id: 1,
      gameweeks: [
        { gw: 1, pts: 6, mins: 90, goals: 0, assists: 0, xg: 0.05, xa: 0.1, dc: 3, dc_pts: 0, price: 6.0 },
        // GW2 has no xg/xa: absent means not measured, not a nil return.
        { gw: 2, pts: 2, mins: 90, goals: 0, assists: 0, price: 6.0 },
        // GW3 is a double — two entries with the same `gw`.
        { gw: 3, pts: 3, mins: 45, goals: 0, assists: 0, xg: 0.0, xa: 0.0, dc: 2, dc_pts: 0, price: 6.1 },
        { gw: 3, pts: 5, mins: 45, goals: 1, assists: 0, xg: 0.4, xa: 0.0, dc: 1, dc_pts: 0, price: 6.1 },
        { gw: 4, pts: 8, mins: 90, goals: 0, assists: 1, xg: 0.0, xa: 0.6, dc: 4, dc_pts: 2, price: 6.1 },
      ],
      prices: [
        { on: "2026-08-01", price: 6.0, owned: 28.4 },
        { on: "2026-09-02", price: 6.1, owned: 31.0 },
        { on: "2026-09-12", price: 6.2, owned: 33.7 },
      ],
    },
    // Watkins (id 2) has price observations but has never featured — a real state, and the one that
    // breaks a view that infers "no data" from the wrong array.
    {
      id: 2,
      gameweeks: [],
      prices: [
        { on: "2026-08-01", price: 8.0, owned: 12.5 },
        { on: "2026-09-02", price: 8.1, owned: 14.0 },
      ],
    },
  ],
};

/** Preseason: nothing scored, but prices have been observed since the pipeline started watching. */
export const preseasonHistory: History = {
  contract_version: 1,
  season: "2026/27",
  gameweeks_played: 0,
  observed_from: "2026-08-01",
  observed_to: "2026-08-14",
  players: [
    {
      id: 1,
      gameweeks: [],
      prices: [
        { on: "2026-08-01", price: 6.0, owned: 28.4 },
        { on: "2026-08-14", price: 6.1, owned: 31.0 },
      ],
    },
  ],
};

function entry(
  opponentId: number,
  opponent: string,
  atHome: boolean,
  attack: number,
  defence: number,
) {
  return {
    opponent_id: opponentId,
    opponent,
    at_home: atHome,
    kickoff_utc: "2026-08-22T14:00:00Z",
    expected_goals_for: 1.7,
    expected_goals_against: 1.1,
    difficulty: (attack + defence) / 2,
    attack_difficulty: attack,
    defence_difficulty: defence,
  };
}

/** Arsenal (team_id 1) only. Watkins's club (team_id 2) is absent, which is the degrade case. */
export const fixtures: Fixtures = {
  contract_version: 1,
  from_gameweek: 5,
  to_gameweek: 8,
  scale: {
    minimum: 1,
    neutral: 3,
    maximum: 5,
    anchor_ratio: 1.8,
    description: "Scored from the model's own expected goals, not FPL's static preseason FDR.",
  },
  model: {
    name: "M2_team_strength",
    league_mean_goals: 1.42,
    home_advantage: 1.15,
    teams_rated: 20,
  },
  teams: [
    {
      team_id: 1,
      team: "ARS",
      name: "Arsenal",
      mean_difficulty: 2.6,
      mean_attack_difficulty: 2.4,
      mean_defence_difficulty: 2.8,
      gameweeks: [
        { gameweek: 5, is_double: false, is_blank: false, fixtures: [entry(3, "BUR", true, 1.4, 1.6)] },
        { gameweek: 6, is_double: false, is_blank: false, fixtures: [entry(4, "MCI", false, 4.6, 4.8)] },
        { gameweek: 7, is_double: false, is_blank: true, fixtures: [] },
        {
          gameweek: 8,
          is_double: true,
          is_blank: false,
          fixtures: [entry(5, "EVE", true, 2.6, 2.9), entry(6, "WOL", false, 3.0, 3.1)],
        },
      ],
    },
  ],
};

/** The same grid with a model that has rated nothing — visible degradation, not silent (DP-15). */
export const unratedFixtures: Fixtures = {
  ...fixtures,
  model: { ...fixtures.model, teams_rated: 0 },
};
