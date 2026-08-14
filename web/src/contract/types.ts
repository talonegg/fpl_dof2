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

export interface MoveSide {
  player_id: number;
  web_name: string;
  price: number;
}

/** This week's decision: the deadline, the squad as it stands, what to do, and why. Times are UTC on the wire; the browser renders local zones itself (DL-11). */
export interface Week {
  contract_version: 1;
  run_id: string;
  /** True when no squad could be established. Before the first gameweek is scored there is no picks endpoint to read (DL-20), so this is a normal state and not a failure. */
  skipped: boolean;
  skipped_reason?: string;
  deadline: {
    gameweek: number;
    name: string;
    /** UTC. The offset between UK and local time changes twice a season and not on the same dates, so anything that reasons in local time is wrong for part of the year. */
    deadline_utc: string;
    /** Deliberately earlier than the deadline. Most deadlines land between 02:30 and 05:00 local, so the practical rule is to decide the evening before. */
    decide_by_utc: string;
    local_zone: string;
    uk_zone: string;
  };
  squad_state?: {
    /** How much was read versus inferred. Reported, never hidden. */
    provenance: "from_picks" | "reconstructed" | "declared";
    entry_id?: number | null;
    as_of_gameweek?: number | null;
    bank: number;
    /** What the squad would raise, after the sell-on fee. Not the same as its value at current prices. */
    sell_value: number;
    budget: number;
    free_transfers: number;
    chips_used?: string[];
    warnings?: string[];
  };
  recommendation?: {
    rationale: string;
    /** Doing nothing is a first-class option with a number attached, not the absence of a recommendation (FR-24). */
    is_roll: boolean;
    transfers: number;
    hit_points: number;
    net_expected_points: number;
    gain_over_roll?: number;
    bank_after?: number;
    moves?: {
      out: MoveSide;
      in: MoveSide;
    }[];
    /** Every course of action considered, including the roll, each with its own arithmetic. */
    options?: {
      transfers: number;
      hit_points: number;
      net_expected_points: number;
      gain_over_roll: number;
      moves?: string[];
    }[];
    warnings?: string[];
  };
  advised?: {
    gameweek: number;
    squad: number[];
    starting: number[];
    bench_order?: number[];
    reserve_goalkeeper?: number | null;
    captain: number;
    vice_captain: number;
    formation?: string;
    expected_points?: number;
  };
  alerts?: {
    severity: "info" | "warning" | "urgent";
    category: string;
    message: string;
    player_id?: number | null;
    detail?: Record<string, unknown>;
  }[];
  /** What was advised against what was actually played, for the previous gameweek. An unexplained difference usually means a submission error (E1-S5). */
  reconciliation?: {
    gameweek: number;
    entry_id: number;
    followed: boolean;
    advised?: Record<string, unknown>;
    played?: Record<string, unknown>;
    divergences?: {
      kind: "squad" | "starting" | "captain" | "vice_captain" | "bench_order";
      status: "override" | "unexplained";
      message: string;
      advised?: number[];
      played?: number[];
      reason?: string;
    }[];
  } | null;
}

export interface PlanDeadline {
  gameweek: number;
  name: string;
  deadline_utc: string;
  decide_by_utc: string;
  local_zone: string;
  uk_zone: string;
}

export interface PlanChip {
  gameweek: number;
  chip: string;
  chip_label: string;
}

export interface PlanWeek {
  gameweek: number;
  chip?: string | null;
  chip_label?: string | null;
  /** The persistent 15. Under a Free Hit this is what you keep, not what you field. */
  squad: number[];
  fielded: number[];
  starting: number[];
  bench_order?: number[];
  captain: number;
  vice_captain?: number;
  formation?: Record<string, number>;
  transfers_in?: number[];
  transfers_out?: number[];
  free_transfers: number;
  /** Transfers charged against the free allowance. Zero on a Wildcard or Free Hit gameweek even when transfers were made — C15, the half of the chip rule that gets missed. */
  charged_transfers?: number;
  hit_points?: number;
  bank_after?: number;
  expected_points?: number;
  net_expected_points?: number;
}

export interface PlanSimulation {
  mean: number;
  median: number;
  percentiles?: Record<string, number>;
  /** The percentile the risk dial ranks on. Never the mean: the mean is what the MILP already maximised. */
  score: number;
  draws: number;
}

export interface PlanOption {
  key: string;
  label: string;
  chips?: PlanChip[];
  status?: string;
  objective?: number;
  total_expected_points: number;
  total_hit_points?: number;
  score?: number;
  simulation?: PlanSimulation | null;
  weeks: PlanWeek[];
}

export interface ChipCalendarEntry {
  chip: string;
  chip_label: string;
  gameweek: number;
  is_double?: boolean;
  is_blank?: boolean;
  teams_doubling?: number[];
  teams_blanking?: number[];
  /** Read from the game's own chip windows, never assumed. Set one expiring at GW19 is true this season and is exactly the sort of fact that quietly stops being true. */
  expires_gameweek: number;
  gameweeks_until_expiry?: number;
  note?: string;
}

export interface ChipExpiry {
  chip: string;
  chip_label: string;
  expires_gameweek: number;
}

export interface ChipCalendar {
  from_gameweek: number;
  entries: ChipCalendarEntry[];
  expiring: ChipExpiry[];
  unavailable?: string[];
}

/** Something a human must weigh before acting, carried on the recommendation itself rather than as a footnote. D-13 is the one that matters here: the forecast is unvalidated at the head of the ranking, which is exactly where hits, chips and wildcards act. */
export interface PlanCaveat {
  code: string;
  headline: string;
  detail: string;
  applies_to: string[];
}

export interface PlanContribution {
  label: string;
  points: number;
  detail?: string;
}

export interface PlanRunnerUp {
  label: string;
  total_expected_points: number;
  margin: number;
  simulated_score?: number | null;
  reason?: string;
}

export interface PlanPriceExposure {
  spend: number;
  bank_after: number;
  sell_value_committed?: number;
  players_bought?: number;
  players_sold?: number;
  statement: string;
}

export interface PlanExplanation {
  headline: string;
  marginal_gain_over_doing_nothing: number;
  decomposition?: PlanContribution[];
  runners_up?: PlanRunnerUp[];
  ownership_bet?: OwnershipBet | null;
  price_exposure?: PlanPriceExposure | null;
  assumptions?: string[];
  caveats: PlanCaveat[];
}

export interface OwnershipPosition {
  player_id: number;
  web_name: string;
  /** FPL's published `selected_by_percent`. Always labelled 'selected by' and never 'effective ownership' (DL-24). */
  selected_by_percent: number;
  owned?: boolean;
  starting?: boolean;
  deviation: number;
}

/** The single most-captained player, as a plain callout rather than folded into an ownership number that would imply more precision than the data supports (DL-24). player_id is null when the figure is not published. */
export interface MostCaptained {
  player_id: number | null;
  web_name?: string;
  selected_by_percent?: number;
  owned?: boolean;
  statement: string;
}

export interface OwnershipBet {
  dial: "safe" | "balanced" | "aggressive";
  dial_description: string;
  /** Which ownership source is in use, stated in the UI as Design 7.1 requires. A risk dial driven by an estimated quantity presented as a measured one is worse than no risk dial. */
  source_statement: string;
  ownership_label: string;
  underweight?: OwnershipPosition[];
  overweight?: OwnershipPosition[];
  most_captained?: MostCaptained | null;
  statements?: string[];
}

export interface PruningReport {
  pool_size: number;
  full_size: number;
  target_size?: number;
  within_target?: boolean;
  by_reason?: Record<string, number>;
  by_position?: Record<string, number>;
}

/** The multi-gameweek plan and the chip calendar (E4). Where week.json answers 'what do I do before this deadline', this answers 'what is the plan, and when do the chips go'. Every recommendation involving a hit, a chip or a wildcard carries the D-13 caveat as data, not as a footnote. */
export interface Plan {
  contract_version: 1;
  run_id: string;
  /** True when no squad could be established, or when no legal plan exists. Both are normal states before the season starts (DL-20) and neither is a failure. */
  skipped: boolean;
  skipped_reason?: string;
  deadline: PlanDeadline;
  gameweeks?: number[];
  /** Which solver produced this. HiGHS from E4 onward (DL-15); CBC was only ever validated against the single-gameweek problem. */
  solver?: string;
  solve_seconds?: number;
  /** greedy_fallback means the solver did not converge in its budget and this is a legal but not optimal plan (DP-15). */
  status?: "optimal" | "greedy_fallback";
  /** True when nothing cleared the margin over doing nothing. Holding is a decision, not the absence of one. */
  is_hold?: boolean;
  rationale?: string;
  recommended?: PlanOption;
  /** Roll everything: no transfer, no chip. Always solved and always ranked. */
  baseline?: PlanOption;
  alternatives?: PlanOption[];
  chip_calendar?: ChipCalendar;
  explanation?: PlanExplanation;
  ownership?: OwnershipBet;
  pruning?: PruningReport;
  warnings?: string[];
}
