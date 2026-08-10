// Generated from contracts/v1/*.schema.json — do not edit by hand.
// Regenerate with: fpl-dof publish
//
// These types are generated from the same schemas the publisher validates against, so the app
// cannot compile against a shape the pipeline does not produce.

export const CONTRACT_VERSION = 1;

/** What this publication is, when it was made, and what produced it. The browser reads this first and can render an honest 'as at' line without trusting anything else. */
export interface Meta {
  /** Bumped only for a breaking change. The app refuses to render a version it does not know. */
  contract_version: 1;
  /** UTC (DL-11). */
  generated_at: string;
  /** Traces back to the run manifest. */
  run_id: string;
  git_sha?: string | null;
  season: string;
  next_gameweek: number;
  deadline_utc?: string | null;
  horizon_gameweeks: number;
  model: {
    name: string;
    /** R-15: how much of xP is explained by price and position alone. */
    r_squared_on_price: number;
    /** The app surfaces this: a 'repricing' forecast must not be read as a forecast. */
    price_dependence: "informative" | "thin" | "repricing";
  };
  counts: {
    players: number;
    teams: number;
  };
}

export interface Positionmap {
  GKP: number;
  DEF: number;
  MID: number;
  FWD: number;
}

/** The game rules the pipeline actually used, published so the browser obeys the same numbers (DL-14, Invariant 9). A hardcoded 3 for the club limit in a .tsx file is the same bug as a hardcoded 4 for a forward goal in a .py file — this file is why neither is necessary. */
export interface Rules {
  contract_version: 1;
  season: string;
  source_snapshot_sha256?: string | null;
  /** Provenance per field group: which numbers the game published, and which we configured. */
  derived: Record<string, "api" | "config">;
  squad: {
    size: number;
    starting_size: number;
    budget: number;
    club_limit: number;
    composition: Positionmap;
    formation_min: Positionmap;
    formation_max: Positionmap;
    sell_on_fee: number;
    sell_at_purchase_price: boolean;
  };
  scoring: {
    goals_scored: Positionmap;
    assists: number;
    clean_sheets: Positionmap;
    defensive_contribution: Positionmap;
  };
  transfers: {
    max_free_transfers: number;
    extra_transfer_cost: number;
  };
}

export interface Player {
  id: number;
  name: string;
  full_name?: string;
  position: "GKP" | "DEF" | "MID" | "FWD";
  /** Short club name, e.g. ARS. */
  team: string;
  team_id: number;
  /** In £m. */
  price: number;
  /** Expected points, next gameweek. */
  xp_next: number;
  /** Invariant 6: a mean is never published without its uncertainty. */
  xp_next_sd: number;
  xp_horizon: number;
  xp_horizon_sd: number;
  start_probability: number;
  confidence: "high" | "medium" | "low" | "none";
  selected_by_percent?: number;
  /** FPL availability flag. */
  status: string;
  news?: string;
  /** DP-09: every number carries its derivation. These sum to xp_next. */
  components: Components;
}

export interface Components {
  appearance: number;
  goals: number;
  assists: number;
  clean_sheet: number;
  goals_conceded: number;
  saves: number;
  defensive_contribution: number;
  bonus: number;
  cards: number;
}

/** Every player, with the forecast and its decomposition. This is the scouting table's data. */
export interface Players {
  contract_version: 1;
  players: Player[];
}

/** The recommended squad, its lineup, and how it was arrived at. */
export interface Squad {
  contract_version: 1;
  run_id: string;
  /** A greedy fallback is legal but not optimal, and the app says so. */
  status: "optimal" | "greedy_fallback";
  objective: number;
  solve_seconds?: number;
  total_price: number;
  budget?: number;
  /** Starters per position, keyed by position code. */
  formation: Record<string, number>;
  captain_id: number;
  vice_captain_id: number;
  /** Outfield substitutes, in the order they come on. */
  bench_order: number[];
  players: {
    player_id: number;
    web_name: string;
    position: "GKP" | "DEF" | "MID" | "FWD";
    team: string;
    team_id: number;
    price: number;
    xp_next: number;
    xp_next_sd?: number;
    xp_horizon: number;
    xp_horizon_sd?: number;
    start_probability?: number;
    confidence?: "high" | "medium" | "low" | "none";
    starting: boolean;
    is_captain: boolean;
    is_vice_captain: boolean;
    components?: Record<string, number>;
  }[];
}
