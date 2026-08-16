import type {
  FixtureEntry,
  Fixtures,
  League,
  Meta,
  Plan,
  Players,
  Rules,
  Squad,
  Week,
} from "../contract/types";

export const meta: Meta = {
  contract_version: 1,
  generated_at: "2026-08-10T10:15:58.217761Z",
  run_id: "20260810T101557Z-d705a43f",
  git_sha: "14c97bc018cebb4fa8b7ac525097ca54d402af75",
  season: "2026/27",
  next_gameweek: 1,
  deadline_utc: "2026-08-21T17:30:00Z",
  horizon_gameweeks: 6,
  model: {
    name: "xp_v0",
    r_squared_on_price: 0.4943,
    price_dependence: "informative",
  },
  counts: { players: 2, teams: 20 },
};

export const rules: Rules = {
  contract_version: 1,
  season: "2026/27",
  source_snapshot_sha256: "abc",
  derived: {},
  squad: {
    size: 15,
    starting_size: 11,
    budget: 100.0,
    club_limit: 3,
    composition: { GKP: 2, DEF: 5, MID: 5, FWD: 3 },
    formation_min: { GKP: 1, DEF: 3, MID: 2, FWD: 1 },
    formation_max: { GKP: 1, DEF: 5, MID: 5, FWD: 3 },
    sell_on_fee: 0.5,
    sell_at_purchase_price: false,
  },
  scoring: {
    goals_scored: { GKP: 10, DEF: 6, MID: 5, FWD: 4 },
    assists: 3,
    clean_sheets: { GKP: 4, DEF: 4, MID: 1, FWD: 0 },
    defensive_contribution: { GKP: 0, DEF: 2, MID: 2, FWD: 2 },
  },
  transfers: { max_free_transfers: 5, extra_transfer_cost: -4 },
};

function components() {
  return {
    appearance: 1.8,
    goals: 0.5,
    assists: 0.2,
    clean_sheet: 1.0,
    goals_conceded: -0.3,
    saves: 0.0,
    defensive_contribution: 0.1,
    bonus: 0.2,
    cards: -0.1,
  };
}

export const players: Players = {
  contract_version: 1,
  players: [
    {
      id: 1,
      name: "Raya",
      full_name: "David Raya",
      position: "GKP",
      team: "ARS",
      team_id: 1,
      price: 6.0,
      xp_next: 4.199,
      xp_next_sd: 1.89,
      xp_horizon: 19.255,
      xp_horizon_sd: 8.665,
      start_probability: 0.938,
      confidence: "high",
      selected_by_percent: 31.0,
      status: "a",
      news: "",
      components: components(),
    },
    {
      id: 2,
      name: "Watkins",
      full_name: "Ollie Watkins",
      position: "FWD",
      team: "AVL",
      team_id: 2,
      price: 8.0,
      xp_next: 4.517,
      xp_next_sd: 2.033,
      xp_horizon: 22.214,
      xp_horizon_sd: 9.996,
      start_probability: 0.837,
      confidence: "high",
      selected_by_percent: 12.5,
      status: "a",
      news: "",
      components: components(),
    },
    {
      id: 3,
      name: "Mbeumo",
      full_name: "Bryan Mbeumo",
      position: "MID",
      team: "MUN",
      team_id: 16,
      price: 8.0,
      xp_next: 3.2,
      xp_next_sd: 1.5,
      xp_horizon: 15.0,
      xp_horizon_sd: 6.0,
      start_probability: 0.8,
      confidence: "medium",
      selected_by_percent: 20.0,
      status: "a",
      news: "",
      components: components(),
    },
  ],
};

export const squad: Squad = {
  contract_version: 1,
  run_id: "20260809T160802Z-c0972065",
  status: "optimal",
  objective: 231.322,
  solve_seconds: 0.512,
  total_price: 100.0,
  budget: 100.0,
  formation: { GKP: 1, DEF: 1, MID: 1, FWD: 1 },
  captain_id: 2,
  vice_captain_id: 1,
  bench_order: [3],
  players: [
    {
      player_id: 1,
      web_name: "Raya",
      position: "GKP",
      team: "ARS",
      team_id: 1,
      price: 6.0,
      xp_next: 4.199,
      xp_next_sd: 1.89,
      xp_horizon: 19.255,
      xp_horizon_sd: 8.665,
      start_probability: 0.938,
      confidence: "high",
      starting: true,
      is_captain: false,
      is_vice_captain: true,
      components: components(),
    },
    {
      player_id: 2,
      web_name: "Watkins",
      position: "FWD",
      team: "AVL",
      team_id: 2,
      price: 8.0,
      xp_next: 4.517,
      xp_next_sd: 2.033,
      xp_horizon: 22.214,
      xp_horizon_sd: 9.996,
      start_probability: 0.837,
      confidence: "high",
      starting: true,
      is_captain: true,
      is_vice_captain: false,
      components: components(),
    },
    {
      player_id: 3,
      web_name: "Mbeumo",
      position: "MID",
      team: "MUN",
      team_id: 16,
      price: 8.0,
      xp_next: 3.2,
      xp_next_sd: 1.5,
      xp_horizon: 15.0,
      xp_horizon_sd: 6.0,
      start_probability: 0.8,
      confidence: "medium",
      starting: false,
      is_captain: false,
      is_vice_captain: false,
      components: components(),
    },
  ],
};

/**
 * A week where one transfer is worth making.
 *
 * Deliberately includes a *losing* two-transfer option: the whole point of the panel is that every
 * option is shown with its own arithmetic, so a fixture with only the winner in it would let the
 * component drop the rest without a test noticing.
 */
export const week: Week = {
  contract_version: 1,
  run_id: "20260810T101557Z-d705a43f",
  skipped: false,
  deadline: {
    gameweek: 2,
    name: "Gameweek 2",
    // 18:30 BST on a Friday, which is 03:30 Saturday in Sydney — the case that motivated
    // rendering both zones at all.
    deadline_utc: "2026-08-28T17:30:00Z",
    decide_by_utc: "2026-08-28T05:30:00Z",
    local_zone: "Australia/Sydney",
    uk_zone: "Europe/London",
  },
  squad_state: {
    provenance: "declared",
    entry_id: 1234567,
    as_of_gameweek: null,
    bank: 0.5,
    sell_value: 99.5,
    budget: 100.0,
    free_transfers: 1,
    chips_used: [],
    warnings: ["squad declared by hand: no published picks are available"],
  },
  recommendation: {
    rationale: "1 free transfer(s) gain 2.40 expected points",
    is_roll: false,
    transfers: 1,
    hit_points: 0,
    net_expected_points: 52.4,
    gain_over_roll: 2.4,
    bank_after: 0.2,
    moves: [
      {
        out: { player_id: 1, web_name: "Salah", price: 14.5 },
        in: { player_id: 2, web_name: "Saka", price: 14.8 },
      },
    ],
    options: [
      { transfers: 0, hit_points: 0, net_expected_points: 50.0, gain_over_roll: 0, moves: [] },
      { transfers: 1, hit_points: 0, net_expected_points: 52.4, gain_over_roll: 2.4, moves: [] },
      { transfers: 2, hit_points: -4, net_expected_points: 49.1, gain_over_roll: -0.9, moves: [] },
    ],
    warnings: [],
  },
  advised: {
    gameweek: 2,
    squad: [1, 2, 3],
    starting: [1, 2],
    bench_order: [3],
    reserve_goalkeeper: null,
    captain: 2,
    vice_captain: 1,
    formation: "1-4-4-2",
    expected_points: 52.4,
  },
  alerts: [
    {
      severity: "urgent",
      category: "availability",
      message: "Salah is unavailable (injured): Hamstring",
      player_id: 1,
      detail: {},
    },
    {
      severity: "info",
      category: "price",
      message: "Saka is under pressure to rise",
      player_id: 2,
      detail: {},
    },
  ],
  reconciliation: null,
};

/** Preseason: no squad exists yet, which is normal rather than broken (DL-20). */
export const skippedWeek: Week = {
  contract_version: 1,
  run_id: "run-1",
  skipped: true,
  skipped_reason: "no published picks are available, and no squad is declared in configuration",
  deadline: week.deadline,
};

/**
 * A plan that recommends a chip, so the D-13 caveat is present. That is the case worth fixing in a
 * test: a chip recommendation without its caveat is precisely the regression E4's own gate exists
 * to prevent.
 */
export const plan: Plan = {
  contract_version: 1,
  run_id: "20260810T101557Z-d705a43f",
  skipped: false,
  deadline: week.deadline,
  gameweeks: [2, 3, 4, 5, 6],
  solver: "HiGHS",
  solve_seconds: 12.4,
  status: "optimal",
  is_hold: false,
  rationale: "Bench Boost in GW4 gains 6.20 points over holding",
  recommended: {
    key: "bboost@4",
    label: "Bench Boost in GW4",
    chips: [{ gameweek: 4, chip: "bboost", chip_label: "Bench Boost" }],
    status: "optimal",
    objective: 210.4,
    total_expected_points: 248.1,
    total_hit_points: -4,
    score: 251.3,
    simulation: {
      mean: 248.0,
      median: 247.2,
      percentiles: { p10: 210.0, p30: 232.0, p50: 247.2, p75: 262.4, p90: 280.1 },
      score: 251.3,
      draws: 4000,
    },
    weeks: [
      {
        gameweek: 2,
        chip: null,
        chip_label: null,
        squad: [1, 2, 3],
        fielded: [1, 2, 3],
        starting: [1, 2],
        bench_order: [3],
        captain: 2,
        vice_captain: 1,
        formation: { GKP: 1, DEF: 4, MID: 4, FWD: 2 },
        transfers_in: [2],
        transfers_out: [4],
        free_transfers: 1,
        charged_transfers: 1,
        hit_points: 0,
        bank_after: 0.2,
        expected_points: 51.2,
        net_expected_points: 51.2,
      },
      {
        gameweek: 4,
        chip: "bboost",
        chip_label: "Bench Boost",
        squad: [1, 2, 3],
        fielded: [1, 2, 3],
        starting: [1, 2],
        bench_order: [3],
        captain: 2,
        vice_captain: 1,
        formation: { GKP: 1, DEF: 4, MID: 4, FWD: 2 },
        transfers_in: [],
        transfers_out: [],
        free_transfers: 2,
        charged_transfers: 0,
        hit_points: 0,
        bank_after: 0.2,
        expected_points: 60.4,
        net_expected_points: 60.4,
      },
    ],
  },
  chip_calendar: {
    from_gameweek: 2,
    entries: [
      {
        chip: "bboost",
        chip_label: "Bench Boost",
        gameweek: 4,
        is_double: true,
        is_blank: false,
        teams_doubling: [1, 2],
        teams_blanking: [],
        expires_gameweek: 19,
        gameweeks_until_expiry: 17,
        note: "2 club(s) play twice; Bench Boost expires at the GW19 deadline (17 gameweek(s) away)",
      },
    ],
    expiring: [
      { chip: "bboost", chip_label: "Bench Boost", expires_gameweek: 19 },
      { chip: "wildcard", chip_label: "Wildcard", expires_gameweek: 19 },
    ],
    unavailable: [],
  },
  explanation: {
    headline: "Bench Boost in GW4 beats Bench Boost in GW5 by 2.1 points; beats playing no chip by 6.2.",
    marginal_gain_over_doing_nothing: 6.2,
    decomposition: [
      { label: "GW2", points: 51.2, detail: "XI and captain 51.20, 1 transfer(s) in" },
    ],
    runners_up: [
      {
        label: "roll everything (no transfer, no chip)",
        total_expected_points: 241.9,
        margin: -6.2,
        simulated_score: 245.1,
        reason: "holding the squad and making no transfer — always ranked, never assumed",
      },
    ],
    ownership_bet: null,
    price_exposure: {
      spend: 14.8,
      bank_after: 0.2,
      sell_value_committed: 14.5,
      players_bought: 1,
      players_sold: 1,
      statement: "£14.8m committed to 1 incoming player(s), funded by £14.5m raised from 1 outgoing.",
    },
    assumptions: ["Salah is assumed to start, which the model puts at 71%."],
    caveats: [
      {
        code: "D-13",
        headline: "This call rests on a forecast that is unvalidated at the head of the ranking.",
        detail: "The walk-forward backtest (DL-21) found the worst top-20 precision of anything measured.",
        applies_to: ["hit", "chip", "wildcard"],
      },
    ],
  },
  ownership: {
    dial: "balanced",
    dial_description: "Balanced — a small penalty.",
    source_statement: "Ownership is FPL's published selected_by_percent.",
    ownership_label: "selected by",
    underweight: [
      {
        player_id: 9,
        web_name: "Haaland",
        selected_by_percent: 62.5,
        owned: false,
        starting: false,
        deviation: -62.5,
      },
    ],
    overweight: [],
    most_captained: {
      player_id: null,
      web_name: "",
      selected_by_percent: 0,
      owned: false,
      statement:
        "The most-captained player for this gameweek is not available in the published data (D-15).",
    },
    statements: ["You are 63% underweight on Haaland (62.5% selected by)."],
  },
  pruning: {
    pool_size: 214,
    full_size: 703,
    target_size: 250,
    within_target: true,
    by_reason: { owned: 15, top_by_points: 120 },
    by_position: { GKP: 30, DEF: 62, MID: 78, FWD: 44 },
  },
  warnings: [],
};

/** Preseason: nothing to plan around yet (DL-20). */
export const skippedPlan: Plan = {
  contract_version: 1,
  run_id: "run-1",
  skipped: true,
  skipped_reason: "no published picks are available, and no squad is declared in configuration",
  deadline: week.deadline,
};

// --- The mini-league (E6-S10) ------------------------------------------------------------------
//
// Four entries chosen for the cases that are easy to get wrong rather than for realism: the owner
// sits second, one rival has no published squad at all (outside the fetch budget), and one has a
// squad with no captain flag. Those last two must not render the same as each other, and neither
// may render as a zero — "not measured" and "measured as none" are different claims (DP-09).

export const leagueTable: League = {
  contract_version: 1,
  league: {
    id: 314159,
    name: "The Sunday League",
    entries_published: 4,
    squads_published: 3,
    squad_limit: 3,
  },
  gameweek: 3,
  entries: [
    {
      entry_id: 100,
      entry_name: "Roy Race XI",
      player_name: "Alex Stone",
      rank: 1,
      last_rank: 3,
      event_total: 68,
      total: 210,
      is_owner: false,
      // Shares Raya and Watkins, captains Raya where the owner captains Watkins, and holds one
      // player the owner does not (#4, deliberately absent from `players.json`).
      squad: { player_ids: [1, 2, 4], starting_ids: [1, 2], captain_id: 1, vice_captain_id: 2 },
    },
    {
      entry_id: 200,
      entry_name: "DOF Select",
      player_name: "The Owner",
      rank: 2,
      last_rank: 1,
      event_total: 54,
      total: 198,
      is_owner: true,
      squad: { player_ids: [1, 2, 3], starting_ids: [1, 2], captain_id: 2, vice_captain_id: 1 },
    },
    {
      entry_id: 300,
      entry_name: "Beyond The Budget",
      player_name: "Sam Reed",
      rank: 3,
      last_rank: 2,
      event_total: 41,
      total: 175,
      is_owner: false,
      squad: null,
    },
    {
      entry_id: 400,
      entry_name: "New Arrival",
      player_name: "Jo Patel",
      rank: 4,
      // Zero is the API's "never previously ranked", not a rank that held still.
      last_rank: 0,
      event_total: null,
      total: 150,
      is_owner: false,
      squad: { player_ids: [2, 3, 5], starting_ids: [2, 3], captain_id: null, vice_captain_id: null },
    },
  ],
};

/** A configured league before any gameweek has been scored: a table and nothing else (DL-20). */
export const preseasonLeague: League = {
  contract_version: 1,
  league: {
    id: 314159,
    name: "The Sunday League",
    entries_published: 2,
    squads_published: 0,
    squad_limit: 3,
  },
  gameweek: null,
  entries: [
    {
      entry_id: 100,
      entry_name: "Roy Race XI",
      player_name: "Alex Stone",
      rank: 1,
      last_rank: null,
      event_total: null,
      total: 0,
      is_owner: false,
      squad: null,
    },
    {
      entry_id: 200,
      entry_name: "DOF Select",
      player_name: "The Owner",
      rank: 2,
      last_rank: null,
      event_total: null,
      total: 0,
      is_owner: true,
      squad: null,
    },
  ],
};

// --- The fixture ticker grid (E6-S8) -----------------------------------------------------------
//
// Five clubs over a four-gameweek window, built to exercise the cases that are easy to get wrong
// rather than to be realistic: ARS has a double in GW3, MUN blanks twice, and MCI has the lowest
// mean difficulty in the set while playing only half the fixtures — which is exactly the row that
// makes "easiest run first" misleading if the blanks are not shown alongside it.

function fixtureEntry(
  opponentId: number,
  opponent: string,
  atHome: boolean,
  attack: number,
  defence: number,
  goalsFor: number,
  goalsAgainst: number,
): FixtureEntry {
  return {
    opponent_id: opponentId,
    opponent,
    at_home: atHome,
    kickoff_utc: null,
    expected_goals_for: goalsFor,
    expected_goals_against: goalsAgainst,
    difficulty: (attack + defence) / 2,
    attack_difficulty: attack,
    defence_difficulty: defence,
  };
}

function played(gameweek: number, entries: FixtureEntry[]) {
  return {
    gameweek,
    is_double: entries.length > 1,
    is_blank: entries.length === 0,
    fixtures: entries,
  };
}

export const fixtureGrid: Fixtures = {
  contract_version: 1,
  from_gameweek: 1,
  to_gameweek: 4,
  scale: {
    minimum: 1.0,
    neutral: 3.0,
    maximum: 5.0,
    anchor_ratio: 2.0,
    description:
      "3 is a fixture the model rates exactly league-average; lower is easier. Scores are clipped to 1-5.",
  },
  model: {
    name: "M2_team_strength",
    league_mean_goals: 1.42,
    home_advantage: 1.18,
    teams_rated: 20,
  },
  teams: [
    {
      team_id: 1,
      team: "ARS",
      name: "Arsenal",
      mean_difficulty: 2.46,
      mean_attack_difficulty: 2.4,
      mean_defence_difficulty: 2.52,
      gameweeks: [
        played(1, [fixtureEntry(5, "BUR", true, 1.4, 1.8, 2.4, 0.7)]),
        played(2, [fixtureEntry(16, "MUN", false, 3.6, 3.2, 1.1, 1.5)]),
        played(3, [
          fixtureEntry(13, "MCI", true, 1.6, 2.2, 2.2, 0.9),
          fixtureEntry(2, "AVL", false, 3.2, 2.8, 1.3, 1.2),
        ]),
        played(4, [fixtureEntry(2, "AVL", true, 2.2, 2.6, 1.8, 1.0)]),
      ],
    },
    {
      team_id: 2,
      team: "AVL",
      name: "Aston Villa",
      mean_difficulty: 3.45,
      mean_attack_difficulty: 3.53,
      mean_defence_difficulty: 3.38,
      gameweeks: [
        played(1, [fixtureEntry(13, "MCI", false, 4.8, 4.4, 0.7, 2.1)]),
        played(2, [fixtureEntry(5, "BUR", true, 1.8, 2.2, 2.1, 0.9)]),
        played(3, [fixtureEntry(1, "ARS", true, 3.6, 3.2, 1.2, 1.4)]),
        played(4, [fixtureEntry(1, "ARS", false, 3.9, 3.7, 1.0, 1.7)]),
      ],
    },
    {
      team_id: 5,
      team: "BUR",
      name: "Burnley",
      mean_difficulty: 4.23,
      mean_attack_difficulty: 4.35,
      mean_defence_difficulty: 4.1,
      gameweeks: [
        played(1, [fixtureEntry(1, "ARS", false, 4.6, 4.2, 0.6, 2.3)]),
        played(2, [fixtureEntry(2, "AVL", false, 4.2, 4.0, 0.8, 2.0)]),
        played(3, [fixtureEntry(13, "MCI", true, 4.9, 4.7, 0.5, 2.5)]),
        played(4, [fixtureEntry(16, "MUN", false, 3.7, 3.5, 0.9, 1.8)]),
      ],
    },
    {
      team_id: 13,
      team: "MCI",
      name: "Manchester City",
      mean_difficulty: 1.5,
      mean_attack_difficulty: 1.4,
      mean_defence_difficulty: 1.6,
      gameweeks: [
        played(1, [fixtureEntry(2, "AVL", true, 1.2, 1.4, 2.6, 0.6)]),
        played(2, []),
        played(3, [fixtureEntry(5, "BUR", false, 1.6, 1.8, 2.3, 0.8)]),
        played(4, []),
      ],
    },
    {
      team_id: 16,
      team: "MUN",
      name: "Manchester United",
      mean_difficulty: 2.55,
      mean_attack_difficulty: 2.7,
      mean_defence_difficulty: 2.4,
      gameweeks: [
        played(1, []),
        played(2, [fixtureEntry(1, "ARS", true, 3.0, 2.8, 1.4, 1.3)]),
        played(3, []),
        played(4, [fixtureEntry(5, "BUR", false, 2.4, 2.0, 1.9, 0.8)]),
      ],
    },
  ],
};
