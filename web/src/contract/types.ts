// Generated from contracts/v1/*.schema.json — do not edit by hand.
// Regenerate with: fpl-dof contract types
//
// These types are generated from the same schemas the publisher validates against, so the app
// cannot compile against a shape the pipeline does not produce.

export const CONTRACT_VERSION = 1;

export const CONTRACT_MINOR = 8;

/** What this publication is, when it was made, and what produced it. The browser reads this first and can render an honest 'as at' line without trusting anything else. */
export interface Meta {
  /** Bumped only for a breaking change. The app refuses to render a version it does not know. */
  contract_version: 1;
  /** Bumped by every additive change within the major. Absent in data older than WEB-02; the app reads that as 0 and warns when it is below the minor the app needs. */
  contract_minor?: number;
  /** UTC (DL-11). */
  generated_at: string;
  /** Traces back to the run manifest. */
  run_id: string;
  /** UTC instant of the input snapshot the advice was decided on (ORC-03, DL-94). Absent before R1.3.0. */
  as_of?: string;
  /** What started the run: the schedule, a change of the named kinds, a manual dispatch or the day-before refresh (ORC-03). Absent before R1.3.0. The results kind, a matchday of the gameweek in play done or the gameweek finished or data-checked, from contract minor 7 (LIVE-02). */
  trigger?: string;
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
    free_transfers_per_gameweek?: number;
  };
  /** What each chip does to a finished gameweek's score, so the browser scores a team as the game did (the League's differentials). Absent before contract minor 6. */
  chips?: {
    /** The armband's ordinary multiplier. */
    captain_multiplier: number;
    /** Chip name, as the API names it, to the armband multiplier it imposes instead. */
    captain_multiplier_by_chip: Record<string, number>;
    /** Chips under which all fifteen score. */
    bench_scores_with: string[];
    /** Chips under which the gameweek's transfers cost no points. */
    transfers_free_with: string[];
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
  /** P(the player appears at all). The XI floor is applied to this, never to P(60+ minutes), which is already inside xP (DL-66). */
  start_probability: number;
  /** The model-free benchmark: points per match over the last six appearances this season, as the backtest defines it. Null before the player has appeared (DL-70). */
  form_points_per_match?: number | null;
  /** Rank on form_points_per_match among players with at least one appearance; null otherwise (DL-70). */
  form_rank?: number | null;
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
  /** A greedy fallback is legal but not optimal, and the app says so. Skipped means nothing was solved: in-season the from-scratch squad is not the decision (DL-67), and players is empty. */
  status: "optimal" | "greedy_fallback" | "skipped";
  /** True when the from-scratch solve did not run this gameweek (DL-67). The app then starts from this week's advised squad in week.json instead. */
  skipped?: boolean;
  skipped_reason?: string;
  /** Where these fifteen came from. The pipeline always writes solver output; the app sets week_advice when it substitutes this week's advised squad for a skipped solve (DL-67). */
  source?: "solver" | "week_advice";
  objective: number;
  solve_seconds?: number;
  total_price: number;
  budget?: number;
  /** Starters per position, keyed by position code. */
  formation: Record<string, number>;
  captain_id: number | null;
  vice_captain_id: number | null;
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
  /** The forecast's side of the disagreement (DL-70). */
  xp_next?: number;
  /** The model-free benchmark's side: points per match over the last six appearances, null before the player has appeared (DL-70). */
  form_points_per_match?: number | null;
}

/** Every option a transfer solve weighed: the roll, the best single transfer and the best overall. The hindsight solves it on realised points (whole); each model's decision on its predicted xP (ORC-11). The same definition is in week.schema.json and models.schema.json, and the type generator fails if they differ. */
export interface LogHindsightOptimal {
  gameweek: number;
  baseline_roll: LogHindsightPlan;
  optimal_single: LogHindsightPlan | null;
  optimal_overall: LogHindsightPlan;
  all_options: LogHindsightPlan[];
}

export interface LogHindsightPlan {
  transfers_count: number;
  moves: {
    player_out_id: number;
    player_out_name: string;
    player_in_id: number;
    player_in_name: string;
    selling_price: number;
    buying_price: number;
  }[];
  starting: number[];
  captain_id: number;
  captain_name: string;
  points_before_hits: number;
  hit_points: number;
  net_points: number;
  gain_over_roll: number;
}

/** This week's decision: the deadline, the squad as it stands, what to do, and why. Times are UTC on the wire; the browser renders local zones itself (DL-11). */
export interface Week {
  contract_version: 1;
  run_id: string;
  /** UTC instant of the input snapshot the advice was decided on (ORC-03, DL-94). Absent before R1.3.0. */
  as_of?: string;
  /** What started the run: the schedule, a change of the named kinds, a manual dispatch or the day-before refresh (ORC-03). Absent before R1.3.0. The results kind, a matchday of the gameweek in play done or the gameweek finished or data-checked, from contract minor 7 (LIVE-02). */
  trigger?: string;
  /** True when no squad could be established. Before the first gameweek is scored there is no picks endpoint to read (DL-20), so this is a normal state and not a failure. */
  skipped: boolean;
  skipped_reason?: string;
  /** Which strategy produced this recommendation. week.json is the champion's (the live advice); every other published strategy writes week_<id>.json in the same schema, at the path strategies.json names. */
  model?: {
    id: string;
    label: string;
    /** The strategy's registry role, as strategies.json lists it. */
    role: "champion" | "challenger" | "experiment" | "retired";
  };
  /** The registered strategy that produced this advice: its id in the strategy registry (strategies.json) and its digest (MOD-03): sha256 over the registry entry, the source that decides its advice and the run config it reads. */
  strategy?: {
    id: string;
    digest: string;
  };
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
  /** This run's strategy failed after an earlier success for the gameweek; the file shows that success, the advice of record, stamped with its own as_of (ORC-03, DL-94). Absent when this run succeeded. */
  last_failure?: {
    as_of: string;
    reason: string;
  };
  /** The source this strategy waited for arrived and the strategy was refreshed with it: it had no advice for the gameweek in the ledger's record because the source's data was missing, and advises in this run, whatever started it; the file's trigger says what did (ORC-07). Absent otherwise, and gone from the next run's file. */
  arrived?: {
    /** The awaited sources' labels, as the data health page names them. */
    sources: string[];
    /** UTC instant of the snapshot the source arrived in. */
    at: string;
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
    /** Every course of action considered, including the roll, each with its own arithmetic. From R1.4.1 derived from option_set, in its rounding (one solve, one home); kept in this shape for the recommendation card and earlier week files. */
    options?: {
      transfers: number;
      hit_points: number;
      net_expected_points: number;
      gain_over_roll: number;
      moves?: string[];
    }[];
    /** What this model weighed on its own predicted xP, in the hindsight optimum's shape: the roll, the best single transfer and the best overall, each with its moves, captain, points before hits, hits, net and gain over roll (ORC-11). Recorded with the advice in the ledger. Absent before R1.4.1. */
    option_set?: LogHindsightOptimal;
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
  /** UTC instant of the input snapshot the advice was decided on (ORC-03, DL-94). Absent before R1.3.0. */
  as_of?: string;
  /** What started the run: the schedule, a change of the named kinds, a manual dispatch or the day-before refresh (ORC-03). Absent before R1.3.0. The results kind, a matchday of the gameweek in play done or the gameweek finished or data-checked, from contract minor 7 (LIVE-02). */
  trigger?: string;
  /** True when no squad could be established, or when no legal plan exists. Both are normal states before the season starts (DL-20) and neither is a failure. */
  skipped: boolean;
  skipped_reason?: string;
  /** The registered strategy that produced this advice: its id in the strategy registry (strategies.json) and its digest (MOD-03): sha256 over the registry entry, the source that decides its advice and the run config it reads. */
  strategy?: {
    id: string;
    digest: string;
  };
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

/** One player's two series. Keyed by the same `id` as players.json, so a view joins on it directly. */
export interface PlayerHistory {
  /** Matches `id` in players.json. This is FPL's element id, which is reassigned between seasons — safe here precisely because this artefact is one season. */
  id: number;
  /** Performance by gameweek, ascending. Empty until the first gameweek is scored. A player with two fixtures in one gameweek appears once per fixture, so a double gameweek is two entries with the same `gw`. */
  gameweeks: HistoryGameweek[];
  /** Price and ownership, ascending by date, emitted only when something changed. Price and ownership are step functions, so the omitted days are the days the value was unchanged — carry the last value forward to fill them. */
  prices: HistoryPrice[];
}

/** What a player did in one fixture. Field names are abbreviated deliberately: at ~700 players over 38 gameweeks the key names are a material fraction of the payload. */
export interface HistoryGameweek {
  gw: number;
  /** FPL points actually scored in this fixture. */
  pts: number;
  mins: number;
  /** Goals actually scored. */
  goals: number;
  /** Assists actually made. */
  assists: number;
  /** Expected goals for this fixture. Absent means not measured, which is not the same claim as zero (DL-18) — a chart must not plot an absent value as a nil return. */
  xg?: number;
  /** Expected assists for this fixture. Absent means not measured. */
  xa?: number;
  /** Defensive Contribution actions counted for this player's position. Absent means not measured — the component did not exist before 2025/26. */
  dc?: number;
  /** Points actually awarded for those actions. All-or-nothing at a per-position threshold, computed from the same rules configuration the pipeline scores with, never from a literal (Invariant 2). Absent whenever `dc` is. */
  dc_pts?: number;
  /** Price at this gameweek, in £m. */
  price: number;
}

/** One price/ownership observation. Emitted only on change, plus the first and last observation of the season. */
export interface HistoryPrice {
  /** Observation date, ISO 8601 (YYYY-MM-DD). */
  on: string;
  /** In £m. */
  price: number;
  /** Ownership as a percentage of all managers, as FPL publishes it. This is the only ownership figure in this artefact and it is always a percentage — the per-gameweek `selected_by` in the source table is a raw manager count on a different scale, and carrying both is how a wrong chart gets drawn (DL-37). */
  owned: number;
}

/** Per-player time series for the current season: what each player actually did, gameweek by gameweek, and how their price and ownership moved. Measured history, not forecast — so unlike players.json these numbers carry no uncertainty, because inventing an error bar for something that was counted would be worse than having none (DL-37). Lazy-loaded by route: it is larger than the other artefacts combined once the season is under way, and only the trend-bearing views want it. */
export interface History {
  contract_version: 1;
  /** The season every series here belongs to, e.g. 2026/27. One season only: a chart mixing two scoring regimes on one axis is a chart that misleads (DL-37). */
  season: string;
  /** How many gameweeks have been scored. Zero before the season starts, which is a normal state and not a failure (DL-20) — a view should say 'no gameweeks played yet' rather than render an empty axis. */
  gameweeks_played: number;
  /** Date of the earliest price observation, ISO 8601. Null when nothing has been observed yet. FPL publishes only the current price, so history exists only for days something recorded it — nothing can reconstruct the days nobody watched. */
  observed_from?: string | null;
  /** Date of the most recent price observation, ISO 8601. Null when nothing has been observed yet. */
  observed_to?: string | null;
  players: PlayerHistory[];
}

/** What a difficulty number means, published alongside the numbers so the reader can argue with the scale rather than take it on faith (DP-10). */
export interface DifficultyScale {
  /** Easiest possible score. Scores are clipped to this. */
  minimum: number;
  /** A fixture the model rates exactly league-average. Not a midpoint by convention — the arithmetic genuinely lands here for an average fixture. */
  neutral: number;
  /** Hardest possible score. Scores are clipped to this. */
  maximum: number;
  /** The tunable that sets the scale's steepness: a side expected to score this multiple of the league mean scores `minimum` for attack. Named and defaulted rather than buried as a literal (DP-06). */
  anchor_ratio: number;
  /** The formula in words, for a tooltip. */
  description: string;
}

/** Which model produced these expectations, and its fitted parameters. A difficulty rating whose origin cannot be recovered is one nobody can challenge (DP-09). */
export interface FixtureModel {
  /** The component model, e.g. M2_team_strength. */
  name: string;
  /** Time-decayed mean goals per team per match. The denominator every ratio below is taken against. */
  league_mean_goals: number;
  /** Multiplier applied to the home side's expected goals. */
  home_advantage: number;
  /** How many clubs the model actually has ratings for. Zero means it fell back to league-average everywhere, which makes every fixture a 3 — visible degradation rather than silent (DP-15). */
  teams_rated: number;
}

/** One club's run over the window. The summary means are what 'sortable by run quality' sorts on. */
export interface TeamFixtures {
  team_id: number;
  /** Short club name, e.g. ARS. */
  team: string;
  /** Full club name. */
  name: string;
  /** Mean overall difficulty across the fixtures actually scheduled in the window. Blanks contribute nothing rather than counting as maximally hard — a blank is flagged separately so a view can penalise it on its own terms. Null when the club has no fixture at all in the window. */
  mean_difficulty?: number | null;
  /** As `mean_difficulty`, for the attacking half of the scale. */
  mean_attack_difficulty?: number | null;
  /** As `mean_difficulty`, for the defensive half of the scale. */
  mean_defence_difficulty?: number | null;
  /** One entry per gameweek in the window, always present and always in ascending order — including the gameweeks this club blanks, which is exactly the entry that would otherwise be invisible. */
  gameweeks: FixtureGameweek[];
}

/** One club, one gameweek. A double is two fixtures here; a blank is none. */
export interface FixtureGameweek {
  gameweek: number;
  /** This club has two or more fixtures in this gameweek. */
  is_double: boolean;
  /** This club has no fixture in this gameweek. */
  is_blank: boolean;
  fixtures: FixtureEntry[];
}

/** One fixture, rated from the perspective of the club whose row it sits in. */
export interface FixtureEntry {
  opponent_id: number;
  /** Short club name of the opposition. */
  opponent: string;
  at_home: boolean;
  /** UTC. The browser renders local zones itself (DL-11). Null for a fixture with no confirmed time. */
  kickoff_utc?: string | null;
  /** Goals the model expects this club to score. The derivation behind the difficulty score, published so the score is checkable (DP-09). */
  expected_goals_for: number;
  /** Goals the model expects this club to concede. */
  expected_goals_against: number;
  /** Overall difficulty: the mean of the attacking and defensive scores. Lower is easier. */
  difficulty: number;
  /** Difficulty for this club's attackers, from expected goals for. Published separately because a high-scoring game between two good sides is a good fixture for forwards and a bad one for defenders, and collapsing that into one number is most of what is wrong with a single FDR figure. */
  attack_difficulty: number;
  /** Difficulty for this club's defenders and goalkeeper, from expected goals against. */
  defence_difficulty: number;
  /** The bookmaker market for this fixture, margin removed. Null until odds are posted, and for a finished fixture (ORC-15). */
  odds?: FixtureOdds | null;
}

/** Match odds as probabilities, always from the perspective of the club whose row it sits in: win is this club winning, loss is the opponent winning. There are no player odds; no free source has them. */
export interface FixtureOdds {
  /** This club wins, from the match-result (1X2) prices with the bookmaker margin removed proportionally, not from the goals fitted to them; win + draw + loss is 1 to rounding. */
  win: number;
  draw: number;
  /** The opponent wins. */
  loss: number;
  /** More than 2.5 goals in the match, from the over/under 2.5 prices with the margin removed; the same for both clubs. Null when no totals market is posted. */
  over_2_5: number | null;
  /** UTC time the odds were captured. */
  as_of: string;
}

/** The fixture ticker: a team-by-gameweek difficulty grid built from the model's own expected goals rather than FPL's static preseason FDR (DL-37). Covers the same gameweek window plan.json does, so the ticker and the plan cannot disagree about how far ahead 'ahead' is. Doubles and blanks come from the same fixture-counting the chip calendar uses, not from a second derivation of the same fact. */
export interface Fixtures {
  contract_version: 1;
  /** First gameweek in the grid — the next one to be played. */
  from_gameweek: number;
  /** Last gameweek in the grid, inclusive. Clipped at the end of the season. */
  to_gameweek: number;
  scale: DifficultyScale;
  model: FixtureModel;
  /** UTC instant of the next fast-ingest firing that fetches fixture odds, for the 'odds not posted yet' wording (ORC-07, ORC-15). Null when no check is due before the deadline. */
  odds_next_check?: string | null;
  teams: TeamFixtures[];
}

/** Which league this is, and how much of it was read. Published because 'you are 4th' means something different in a league of 8 than in one of 800,000, and because the rows here are the top of a table rather than all of it. */
export interface LeagueMeta {
  /** The FPL classic league ID, as configured. */
  id: number;
  name: string;
  /** Rows in `entries`. The first page of the standings, capped at what the API returns per page — not necessarily the whole league. */
  entries_published: number;
  /** How many of those entries have a `squad`. Below `squad_limit` means squads were asked for and not available, which is normal before a gameweek is scored. */
  squads_published: number;
  /** The configured budget for how many entries' squads to fetch. Zero means squads were never requested, so an absent squad says nothing about availability — the tunable behind the cost, named rather than buried (DP-06). */
  squad_limit: number;
}

/** One manager's row in the table, with their squad when it was read. */
export interface LeagueEntry {
  entry_id: number;
  /** The team name, as it appears on the league's own public page. */
  entry_name: string;
  /** The manager's display name, as it appears on the league's own public page. */
  player_name: string;
  rank: number;
  /** Rank at the previous update. Zero for an entry that had none. Null when not reported. */
  last_rank?: number | null;
  /** Points scored in the latest scored gameweek. Null when not reported. */
  event_total?: number | null;
  /** Points for the season to date. */
  total: number;
  /** This row is the configured team. **The comparison is anchored on this row and no other**: differentials are measured against the squad actually fielded, never against the squad the optimiser recommended, because a differential against a team you do not own is not a differential (DP-09). At most one entry has this set, and none does when no team is configured or the owner is not in this league. */
  is_owner: boolean;
  squad?: LeagueSquad | null;
  /** What this manager did in the published gameweek (ORC-14). Null when it was not read - outside the squad budget, or the fetch failed - which is a different claim from a manager who made no transfers (an object with an empty list). A failed fetch degrades this one team only (NFR-15). */
  moves?: LeagueMoves | null;
}

/** A manager's transfers, hit and chip for one gameweek, from the public entry history and transfers endpoints. Players are ids; the app names them from players.json. */
export interface LeagueMoves {
  gameweek: number;
  /** Points deducted for extra transfers, as the game reports it. */
  hit_cost: number;
  /** The chip played that gameweek, by the API's own name (the key rules.json's chips use). Null when none. */
  chip: string | null;
  /** The chip's name as the game shows it ("Triple Captain", not "3xc"), as the plan's chip labels. Null when none. */
  chip_label: string | null;
  transfers: {
    out_id: number;
    in_id: number;
  }[];
}

/** A manager's fifteen for the published gameweek, as the public picks endpoint reports them. Carries no prices: the endpoint does not report another manager's purchase or selling price, and this project will never authenticate to obtain one (Invariant 4). */
export interface LeagueSquad {
  /** All fifteen, ascending. What overlap and differentials are computed from. */
  player_ids: number[];
  /** The eleven who started, in squad order. */
  starting_ids: number[];
  /** Null when the picks carried no captain flag. */
  captain_id: number | null;
  vice_captain_id: number | null;
}

/** A classic mini-league: its table, and the squads of the entries near the top of it (E6-S10, FR-32). Published only when a league is configured — when it is not, this file is absent from the published directory entirely, which is a different and more honest statement than an empty table. The comparison itself (overlap, differentials, captain divergence) is derived in the app from these facts rather than precomputed here, so the reader can see what it was derived from (DP-09, DP-10). */
export interface League {
  contract_version: 1;
  league: LeagueMeta;
  /** The gameweek every published squad is from — the most recent one with a final score. Null before any gameweek has been scored, when no manager has picks to read (DL-20) and the table is the only thing this artefact can carry. */
  gameweek: number | null;
  entries: LeagueEntry[];
}

/** The manifest excerpt: what the last run was, and how it ended. */
export interface HealthRun {
  /** The same id meta.json carries. Traces back to the full manifest on disk (DP-11). */
  run_id: string;
  git_sha?: string | null;
  /** True when the working tree had uncommitted changes. Such a run is not reproducible from its recorded inputs, and the page says so rather than leaving it implied. */
  git_dirty?: boolean | null;
  started_at: string;
  /** Null when the run did not reach the end. A manifest is written after every stage, so an unfinished run still publishes what it got through. */
  finished_at?: string | null;
  /** The run's own outcome. Null while it is still in flight — which is the state of the run that wrote this file. */
  status?: "succeeded" | "failed" | "skipped" | null;
  duration_seconds?: number | null;
  /** Every stage the run recorded, in the order it ran them. */
  stages: HealthStage[];
}

export interface HealthStage {
  name: string;
  status: "succeeded" | "failed" | "skipped";
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  /** Why the stage failed, when it did. Present so a failure can be read here rather than only in a CI log that expires. */
  error?: string | null;
}

/** One source's freshness and status. `source` is an opaque label from the data: render it, never test it. `label` and `description` are the plain-English text the source declares for itself, so the page can show them without knowing which source it is. */
export interface HealthSource {
  source: string;
  /** `live`: fetched on a schedule, so it has a freshness age. `reference`: fixed data that doesn't update, shown with `as_of` (and `check`, where its files are pinned) instead of an age. Absent on artefacts published before T-003; read absent as `live`. */
  kind?: "live" | "reference";
  /** Plain-English name. Null for a label the run saw that no source describes; render `source` then. */
  label?: string | null;
  /** One line on what the source is for. */
  description?: string | null;
  /** `ok`: the latest fetch worked (this run's own, or a scheduled ingest's snapshot within the freshness limit). `stale`: it worked before, but its newest data is older than the limit. `degraded`: the fetch failed or was partial and the run continued without (some of) this source's fields (NFR-15, DP-15); for a reference source, its file check failed. `not_configured`: switched on but missing something it needs (an API key), so it collects nothing. `disabled`: switched off on purpose. `unknown`: this run recorded nothing about it — which is not the same as healthy, and is not shown as healthy. A `reference` source is `ok` unless something is known to be wrong with it; the page shows it as Reference rather than OK. */
  status: "ok" | "stale" | "degraded" | "not_configured" | "disabled" | "unknown";
  /** The reason behind the status, in words: the exception class a stage caught, the reason it recorded, or the source's own explanation for being switched off, not set up or fixed. A flag without its reason is an assertion (DP-09). */
  detail?: string | null;
  /** Which stage recorded the degradation. Fetching and conforming fail differently and are worth telling apart. */
  degraded_at_stage?: string | null;
  /** When this source's freshest snapshot was captured. Null when it has never been captured. */
  observed_at?: string | null;
  /** `generated_at` minus `observed_at`. Published rather than left to the browser so the number cannot drift with the reader's clock or with how long a cached page has been open. Null for a reference source: fixed data has no freshness age. */
  age_seconds?: number | null;
  /** The date a reference dataset is as of. Null for live sources. */
  as_of?: string | null;
  /** For a reference source whose files are pinned: whether the last check found them byte-identical to the pinned copies. Null when there is no such check, or it has not run. */
  check?: "pass" | "fail" | null;
  /** When `check` was made. */
  checked_at?: string | null;
  /** Resource name to row or record count, exactly as the run recorded it. */
  resources?: Record<string, number>;
  network_calls?: number | null;
  /** A run served entirely from cache is a legitimate, fast run — and also the reason a source can be 'ok' while its data is older than the run. Published so the two are distinguishable. */
  cache_hits?: number | null;
  /** Captures of this source held in quarantine because they broke its contract (ORC-10). None of them is ever read: the run used the last valid capture, whose age `observed_at` already gives. Absent on artefacts published before R1.3.0; read absent as 0. */
  quarantined?: number;
}

/** The quality gate report. A blocking failure means nothing was published and the last good artefact is still live (Invariant 7) — so a health page showing a blocked run is being served by the run before it. */
export interface HealthGates {
  /** False only when an error-severity gate failed. A failed warning still publishes. */
  passed: boolean;
  counts: {
    passed: number;
    failed: number;
    /** A gate whose table was absent. Distinct from passing: a gate that never ran proves nothing. */
    skipped: number;
  };
  blocking: string[];
  results: HealthGate[];
}

export interface HealthGate {
  gate: string;
  /** Which kind of assertion this is — shape, range, referential integrity, or freshness and volume. */
  class: string;
  severity: "info" | "warn" | "error";
  outcome: "passed" | "failed" | "skipped";
  /** Why it landed where it did, in words, whether it passed or failed. This is the reason a failure can be acted on without opening a log. */
  message: string;
  /** The requirement this gate protects (DP-14). A gate nobody can trace to a requirement is one that gets deleted by whoever it inconveniences. */
  requirement: string;
}

/** A short rolling series over recent runs. Oldest first. */
export interface HealthMetricsHistory {
  /** Where the series came from. The shape here is the contract; the storage behind it is not, so this value may change without a schema change (DL-41). */
  derived_from: string;
  runs: HealthMetricsPoint[];
}

/** One run's measurements. Every field but the id is nullable, because a run that failed early recorded fewer of them, and a gap must draw as a gap rather than as a zero. */
export interface HealthMetricsPoint {
  run_id: string;
  finished_at?: string | null;
  status?: "succeeded" | "failed" | "skipped" | null;
  duration_seconds?: number | null;
  /** How long the squad MILP took. The measurement that says whether the optimiser is still comfortably inside the pre-deadline window. */
  solve_seconds?: number | null;
  /** Total conformed silver rows. The volume signal: a source returning 30 players instead of 700 produces a perfectly valid, perfectly wrong silver layer, and this is where that shows. */
  rows_total?: number | null;
  /** Per-table row counts for the same run. */
  rows?: Record<string, number>;
  /** R-15's PRICE-DEPENDENCE DIAGNOSTIC, not a measure of accuracy: how much of the forecast is explained by price and position alone. High is bad. Skill is measured against a baseline in the backtest and reported in the model card (DP-12), deliberately not here. */
  r_squared_on_price?: number | null;
  gates_failed?: number | null;
}

/** How the pipeline itself is doing: what the last run did, which sources are degraded, which quality gates passed, and how a handful of run-level measurements have moved. Assembled from the run manifest, the gate report and the bronze snapshot times — never measured here, so the page cannot hold a second opinion about health that disagrees with the manifest (DL-41). */
export interface Health {
  /** Additive at v1: a client that has never heard of this artefact keeps working. */
  contract_version: 1;
  /** UTC (DL-11). Every age on this page is measured from here, not from the reader's clock, so a stale cached copy reports the ages it was published with rather than ages that keep growing. */
  generated_at: string;
  run: HealthRun;
  /** One entry per data source the run knew about. Source names are DATA, discovered from the registry and the bronze store — no consumer of this artefact may branch on one (Invariant 1, DP-01). */
  sources: HealthSource[];
  /** The gate report from this run, or null when none was published with it. Nullable rather than defaulted to a pass: a gate report that is missing has proved nothing, and rendering that as 'all clear' is exactly the silent wrongness the gates exist to catch (DP-13, DP-15). */
  gates: HealthGates | null;
  /** Recent runs as a short series, or null when no history could be assembled. Nullable on purpose: the page degrades to 'no history yet' rather than to an error (DP-15). */
  metrics_history?: HealthMetricsHistory | null;
}

export interface LogGameweek {
  gameweek: number;
  played: LogPlayed;
  /** Null when the game has not yet reported a score for the gameweek. */
  score: LogScore | null;
  /** The chip played, if any. */
  chip: string | null;
  /** Null when no advice was recorded before the deadline. GW1 to GW4 of 2026/27 were decided without the tool, and say so. */
  advised: LogAdvised | null;
  /** Null whenever advised is null: there is nothing to compare. */
  reconciliation: LogReconciliation | null;
  /** Multi-model realized score rankings, hindsight optimal ceiling, and oracle gap diagnostics (E14). Optional / null when not scored. */
  hindsight?: LogHindsight | null;
}

export interface LogPlayed {
  squad: number[];
  starting: number[];
  /** Slots 12 to 15 in order, goalkeeper first. */
  bench_order: number[];
  captain: number | null;
  vice_captain: number | null;
}

export interface LogScore {
  /** Gameweek points after hits, as the game reports them. */
  points: number;
  total_points: number;
  rank: number | null;
  overall_rank: number | null;
  points_on_bench: number;
  transfers: number;
  transfers_cost: number;
}

export interface LogAdvised {
  /** The run whose manifest can reproduce this advice (DP-11). */
  run_id: string;
  /** UTC, when the ledger entry was last written — always before the deadline. */
  recorded_at: string;
  squad: number[];
  starting: number[];
  captain: number | null;
  vice_captain: number | null;
  expected_points: number;
  transfers: number;
  hit_points: number;
  moves: {
    out: number | null;
    in: number | null;
  }[];
}

export interface LogReconciliation {
  followed: boolean;
  divergences: {
    kind: string;
    status: "override" | "unexplained";
    message: string;
    advised: number[];
    played: number[];
    reason: string;
  }[];
}

export interface LogHindsight {
  rankings: LogModelRank[];
  /** Null when the squad state (bank, free transfers) was not recorded for the gameweek: the rankings need neither, the optimal does. */
  optimal: LogHindsightOptimal | null;
  /** Why optimal is null, in words. Absent when optimal is present. */
  optimal_unavailable_reason?: string;
  diagnostics: LogOracleDiagnostic[];
}

export interface LogModelRank {
  model_name: string;
  rank: number;
  score: {
    final_starting: number[];
    points_before_hits: number;
    hit_points: number;
    net_points: number;
    captain_id: number;
    vice_used: boolean;
    armband_points: number;
    autosubs_in: number[];
    autosubs_out: number[];
    expected_points: number;
    prediction_delta: number;
  };
}

export interface LogOracleDiagnostic {
  player_id: number;
  player_name: string;
  role: string;
  actual_points: number;
  category: "model_blindspot" | "high_variance_outlier" | "captaincy_trap";
  explanation: string;
  /** Each model's pre-deadline xP for this player, from evaluation version 4 (D-37); a model that did not price him is absent. Before it, the model's team xP over the armband keyed by its own captain, so not the player's. */
  models_xp: Record<string, number>;
  models_trapped: string[];
  /** The player's underlying expected points for the gameweek: the game's rules applied to his minutes and FPL's expected goals, assists and goals conceded (ORC-12). Absent before evaluation version 4. */
  underlying_points?: number | null;
}

/** The season log: per finished gameweek, what the owner played, what it scored, what the pipeline advised beforehand, and how the two differ (DL-69, E8 §3). Advice is read from the ledger written before each deadline and is null where none was recorded — it is never reconstructed after the event. */
export interface Log {
  /** Additive at v1: a client that has never heard of this artefact keeps working. */
  contract_version: 1;
  season: string;
  entry_id: number;
  summary: {
    gameweeks_played: number;
    gameweeks_advised: number;
    advice_followed: number;
    advice_overridden: number;
    total_points: number;
  };
  gameweeks: LogGameweek[];
}

export interface ModelInfo {
  /** The strategy's id in the strategy registry (strategies.json). */
  id: string;
  /** The frozen harness's key for this strategy, one of its registry aliases. */
  key: string;
  label: string;
  /** The strategy's registry role. */
  role: string;
  description: string;
  /** Whether the latest gameweek's advice passed the CI input-freshness check. */
  available: boolean;
  /** Why not, shown verbatim in the app. */
  unavailable_reason: string | null;
  /** The latest advice is a provisional preview that freezes at the decision window. Absent means false. */
  provisional?: boolean;
}

export interface ModelAvailability {
  available: boolean;
  reason: string | null;
  /** The sources whose missing data left the strategy without advice, by the labels the data health page uses (ORC-07). Absent when it is not waiting for a source. */
  sources?: string[];
  /** UTC instant of the first run in this gameweek that found the source's data missing (ORC-07). */
  since?: string | null;
  /** When the source is next fetched: the next fast-ingest firing before the deadline, which GitHub may drop. Null for a gameweek no longer Open, or none before its deadline (ORC-07). */
  next_check?: string | null;
}

export interface ModelTransfer {
  out: number | null;
  out_name: string;
  in: number | null;
  in_name: string;
}

export interface ModelAdvice {
  transfers: ModelTransfer[];
  n_transfers: number;
  hit_points: number;
  starting: number[];
  /** UTC instant of the input snapshot the advice was decided on (ORC-03, DL-94). Absent before R1.3.0. */
  as_of?: string;
  /** What started the run: the schedule, a change of the named kinds, a manual dispatch or the day-before refresh (ORC-03). Absent before R1.3.0. The results kind, a matchday of the gameweek in play done or the gameweek finished or data-checked, from contract minor 7 (LIVE-02). */
  trigger?: string;
  starting_names: string[];
  bench_order: number[];
  bench_names: string[];
  captain: number | null;
  captain_name: string;
  vice_captain: number | null;
  vice_name: string;
  /** xPts of the XI with the armband, before hits (hit_points carries those). */
  expected_points: number;
  /** The options the model weighed at the deadline on its predicted xP, from the ledger's advice of record (ORC-11), for setting beside the hindsight optimum. Absent for frozen gameweeks and advice recorded before R1.4.1. */
  option_set?: LogHindsightOptimal;
}

export interface ModelActual {
  points: number;
  points_before_hits: number;
  hit_points: number;
  n_autosubs: number;
  vice_used: boolean;
  armband_points: number;
  /** The same final XI and armband, before hits, scored on each player's underlying expected points: the game's rules applied to his minutes and FPL's expected goals, assists and goals conceded (ORC-12). Absent for the frozen record and before evaluation version 4. */
  underlying_points?: number;
  /** The advice's xP less underlying_points: what the forecast missed by. Absent with underlying_points. */
  forecast_error?: number;
  /** points_before_hits less underlying_points: positive when the XI scored more than its chances were worth. xP less points is forecast_error less luck. Absent with underlying_points. */
  luck?: number;
}

export interface ModelGameweek {
  gameweek: number;
  deadline: string | null;
  decided_at: string | null;
  /** Per model: did every input it needs pass the freshness check for this decision? Advice and points appear only for models that did (fail closed). */
  availability: Record<string, ModelAvailability>;
  advice: Record<string, ModelAdvice>;
  /** Null until the gameweek is finished and scored. */
  actual: Record<string, ModelActual> | null;
  /** Where this gameweek's advice and points come from: the retired frozen harness, or the live ledger scored on the owner's real squad. Absent means frozen. */
  record?: "frozen" | "live";
  /** A dry-run preview of current advice, published before the frozen decision exists and replaced by it at the decision window. Never scored. Absent means false. */
  provisional?: boolean;
}

export interface ModelSeason {
  model: string;
  gameweeks_scored: number;
  total: number;
  per_gameweek: {
    gameweek: number;
    points: number;
    cumulative: number;
  }[];
}

/** The five frozen models side by side. Per gameweek: each model's pre-deadline advice, recorded before the deadline by the prospective harness, and — once the gameweek is finished — the points it actually scored (final XI after auto-subs, armband with vice fallback, minus hits). Live advice is the champion's alone; every other model is a comparison. Absent until the harness has recorded a decision, so like log.json its absence is a normal published state. */
export interface Models {
  contract_version: 1;
  season: string;
  /** UTC instant of the input snapshot the advice was decided on (ORC-03, DL-94). Absent before R1.3.0. */
  as_of?: string;
  /** What started the run: the schedule, a change of the named kinds, a manual dispatch or the day-before refresh (ORC-03). Absent before R1.3.0. The results kind, a matchday of the gameweek in play done or the gameweek finished or data-checked, from contract minor 7 (LIVE-02). */
  trigger?: string;
  /** The model id whose advice is live. */
  champion: string;
  /** The first gameweek recorded live. Earlier gameweeks are the retired frozen harness's virtual seasons; later ones are each strategy's advice on the owner's real squad (DL-87, DL-89). Null when the frozen record decided nothing. Absent means null. */
  switch_gameweek?: number | null;
  frozen: {
    tag: string | null;
    code_commit: string | null;
  };
  /** True when the latest gameweek is a provisional preview (no frozen decision yet). Absent means false. */
  provisional?: boolean;
  models: ModelInfo[];
  gameweeks: ModelGameweek[];
  season_to_date: ModelSeason[];
}

export interface ModelHistoryModel {
  /** The strategy's id in the strategy registry (strategies.json); a file built before the registry carries one of its legacy aliases. */
  id: string;
  label: string;
  /** The strategy's registry role; a file built before the registry says comparison for a challenger. */
  role: string;
  available: boolean;
  unavailable_reason: string | null;
}

export interface ModelHistoryEntry {
  /** Final XI after auto-subs, armband (vice fallback), net of hits. */
  points: number;
  points_before_hits: number;
  hit_points: number;
  n_transfers: number;
  transfers: string[];
  captain: string;
  vice_captain: string;
  captain_points: number;
  vice_used: boolean;
  n_autosubs: number;
  cumulative: number;
  rank: number;
  cumulative_rank: number;
  /** The chip played this gameweek, by its name in rules.json; absent when none was (in_sample only: the backtest plays none). */
  chip?: string;
}

export interface ModelHistoryGameweek {
  gameweek: number;
  models: Record<string, ModelHistoryEntry>;
  /** in_sample only: strategy id -> why it could not play this gameweek (its inputs absent at the deadline); such a model has no entry under models. Absent when every model played. */
  unavailable?: Record<string, string>;
}

export interface ModelHistoryDelta {
  mean: number;
  ci_low: number;
  ci_high: number;
  total: number;
  /** The 95% CI excludes zero. One season; not a decision rule. */
  significant: boolean;
  gameweeks_better: number;
  gameweeks_worse: number;
}

export interface ModelHistorySummary {
  model: string;
  total: number;
  mean_per_gameweek: number;
  /** Gameweeks ranked first among the strategies (ties shared). */
  gameweeks_won: number;
  hit_points: number;
  final_rank: number;
  delta_vs_champion: null | ModelHistoryDelta;
}

/** How every registered strategy would have played an archive season in the standing backtest (FPL auto-subs, vice-captain fallback, hits, no chips), each on its own fresh squad, scored by the one realised-points scorer. A backtest, not real play. Simulated by the weekly `fpl-dof backtest`, recorded on the `ledger` branch under `models_history/`, and the latest season published by `fpl-dof publish` (ORC-06). The same shape, `kind` `in_sample`, is `as_if_played.json`: today's published models replayed in-sample on the live season's finished gameweeks, each on its own squad with its own transfers, hits and chips; not evidence of skill (ORC-13, DL-97). */
export interface ModelsHistory {
  contract_version: 1;
  season: string;
  /** backtest: an archive season, out of sample (models_history.json). in_sample: today's models replayed on the live season (as_if_played.json). */
  kind: "backtest" | "in_sample";
  caveat: string;
  champion: string;
  /** Where the numbers came from: the backtest run, its config digest, the simulator, the scorer and the settings. */
  provenance: Record<string, string>;
  bootstrap: {
    draws: number;
    seed: number;
    unit: string;
    level: number;
  };
  models: ModelHistoryModel[];
  gameweeks: ModelHistoryGameweek[];
  summary: ModelHistorySummary[];
}

export type AsIfPlayed = ModelsHistory;

export interface XpAccuracyGameweek {
  gameweek: number;
  phase: "backtest" | "replay" | "prospective";
  mae: Record<string, number>;
}

export interface XpAccuracySeason {
  season: string;
  kind: "backtest" | "replay" | "prospective";
  gameweeks: XpAccuracyGameweek[];
  pooled_mae: Record<string, number>;
  missing_models: Record<string, string>;
}

/** Per-GW all-player xP MAE across seasons (backtest, replay, and live prospective). */
export interface XpAccuracy {
  contract_version: 1;
  metric: string;
  seasons: XpAccuracySeason[];
}

export interface Strategy {
  /** Stable; never reused, never a role name. */
  id: string;
  label: string;
  description: string;
  role: "champion" | "challenger" | "experiment" | "retired";
  /** Runs every refresh and appears in the app. */
  published: boolean;
  /** Legacy ids that mean this strategy: the frozen harness's key and the app's old model ids. */
  aliases: string[];
  /** sha256 over the registry entry and the run config sections it reads, as canonical JSON, and the source that decides its advice: it changes whenever any of the three does. */
  digest: string;
  /** Whether the strategy gets the multi-gameweek plan and chips. */
  plan: boolean;
  /** Where the app finds this strategy's published week and plan, relative to the data directory; null where it publishes none. The app reads these paths and never builds one. */
  artefacts: {
    week: string | null;
    plan: string | null;
  };
}

/** The strategy registry as published (MOD-03, DL-86): every registered strategy — a forecaster paired with a decision policy — generated from the committed files under config/strategies/. Every per-strategy artefact names its strategy by the id and digest listed here. Additive in contract v1. */
export interface Strategies {
  contract_version: 1;
  /** The id of the one strategy whose role is champion: the live advice. */
  champion: string;
  /** Champion first, then by role, published before unpublished, then by id. */
  strategies: Strategy[];
}

/** The gameweek's fixtures that share a kick-off date in the configured matchday zone (UK time, R1.4.3 §5 Q1). */
export interface LiveMatchday {
  /** The kick-off date in the matchday zone. */
  date: string;
  fixtures: number;
  /** Fixtures finished with their bonus confirmed. */
  fixtures_confirmed: number;
  /** UTC (DL-11). */
  last_kickoff: string;
  /** Every fixture's bonus confirmed, or the settle cap passed since the last kick-off. */
  done: boolean;
  /** Done by the settle cap with a bonus still unconfirmed: its points are without that bonus. */
  bonus_pending: boolean;
}

export interface LiveFixture {
  fixture_id: number;
  /** UTC (DL-11). */
  kickoff_time: string | null;
  /** The `date` of the matchday it belongs to. */
  matchday: string | null;
  home_team_id: number;
  away_team_id: number;
  /** FPL's flags: not started; started; full time (minutes final, bonus not yet confirmed); finished with bonus confirmed. */
  state: "to_come" | "playing" | "full_time" | "bonus_confirmed";
}

/** One team's gameweek in play. A team whose picks, FPL figures or live scores were not read has `live: null` and a `reason`; that team alone degrades (NFR-15). */
export interface LiveTeam {
  entry_id: number;
  entry_name: string;
  /** The manager's display name from the league table; null for an owner outside the league. */
  player_name: string | null;
  is_owner: boolean;
  /** Rank by live total among the published teams with one; equal totals share a rank. Null without a live figure. */
  rank: number | null;
  live: LiveFigures | null;
  /** Why `live` is null; null when it is not. */
  reason: string | null;
  game: LiveGame | null;
  /** Once the gameweek is finished and FPL's figures are final: whether the scorer's gameweek points equal FPL's, both net of the hit (LIVE-03's check, a warning gate, R1.4.3 §5 Q3). Null until then, or without a live figure. */
  matches_game: boolean | null;
}

/** The team's provisional gameweek, from the one realised scorer (ORC-04). */
export interface LiveFigures {
  /** Provisional gameweek points, net of the hit. */
  points: number;
  points_before_hits: number;
  /** This gameweek's hit, as FPL reports it, taken once. */
  hit_cost: number;
  /** The chip played this gameweek, by the API's own name. Null when none. */
  chip: string | null;
  /** The chip's name as the game shows it. Null when none. */
  chip_label: string | null;
  /** The season total after the last finished gameweek. */
  last_total: number;
  /** `last_total` plus `points`. */
  live_total: number;
  /** The team's own status, on the gameweek's rule, over the fixtures its fifteen have (LIVE-03). */
  status: "in_play" | "bonus_pending" | "complete" | "final";
  /** The player the armband counts for: the captain, or the vice-captain once the captain's gameweek is over without a minute. */
  captain_id: number;
  vice_used: boolean;
  /** Projected substitutes coming on: only for a starter whose gameweek is over without a minute. */
  autosubs_in: number[];
  autosubs_out: number[];
  /** The fifteen in slot order. */
  players: LivePlayer[];
}

export interface LivePlayer {
  player_id: number;
  /** As submitted: 1-11 start, 12-15 bench in order. */
  slot: number;
  minutes: number;
  /** His gameweek so far, every fixture summed, bonus included as FPL has it. */
  points: number;
  /** FPL's bonus so far; never estimated from BPS. */
  bonus: number;
  /** Every fixture he has has its bonus confirmed (true for a player with none). */
  bonus_confirmed: boolean;
  /** Every fixture he has is at full time: his minutes are final. False for a player yet to play. */
  complete: boolean;
  /** As applied: 0 off the field, 1 on it, the armband's multiplier on `captain_id`. */
  multiplier: number;
  is_captain: boolean;
  is_vice_captain: boolean;
}

/** FPL's own figures for the team, from its picks. Before the gameweek is data-checked they are the deadline's capture, so they are not the gameweek's points (`final` false). */
export interface LiveGame {
  /** The gameweek's points before the hit, as FPL showed them. */
  points: number;
  hit_cost: number;
  /** The season total, this gameweek included. */
  total: number;
  /** Captured once FPL had data-checked the gameweek. */
  final: boolean;
}

/** The gameweek in play (LIVE-04, DL-99): the latest gameweek past its deadline, from its first kick-off until the next deadline moves the live tables on. Its status, its matchdays and fixtures, and for the owner and each mini-league rival their provisional points from the one realised scorer (ORC-04), live total and rank among the published teams. **Provisional, and says so**: until FPL data-checks the gameweek the figures can move; `log.json` and the evaluation are the record, and nothing reads this file back (DP-14). Absent preseason and between a deadline and that gameweek's first kick-off, never empty (DP-15). From contract minor 8. */
export interface Live {
  contract_version: 1;
  gameweek: number;
  /** How far a gameweek, or one team's part of it, has got (LIVE-03): `in_play` a fixture still to finish; `bonus_pending` every fixture at full time, a bonus not yet confirmed (bonus is never estimated from BPS); `complete` every bonus confirmed, not yet data-checked; `final` FPL has data-checked it. */
  status: "in_play" | "bonus_pending" | "complete" | "final";
  /** True until FPL data-checks the gameweek (`status` is `final`): every figure here can still move. */
  provisional: boolean;
  /** UTC instant of the run's snapshot (ORC-03). */
  as_of: string;
  /** UTC instant the live scores were captured; null when none were read, and then no team has a live figure. */
  observed_at: string | null;
  /** The gameweek's matchdays in date order, done and to come (LIVE-02). */
  matchdays: LiveMatchday[];
  /** The gameweek's fixtures in kick-off order. A postponed fixture has left the gameweek and is not here. */
  fixtures: LiveFixture[];
  /** The owner and every team in the mini-league table, ranked by live total first; teams without a live figure follow, by entry id. */
  teams: LiveTeam[];
}

/** Every published artefact and how the app loads it, from `ARTEFACTS`. */
export const ARTEFACTS = {
  "meta": {
    "path": "meta.json",
    "required": true,
    "warm": true
  },
  "rules": {
    "path": "rules.json",
    "required": true,
    "warm": true
  },
  "players": {
    "path": "players.json",
    "required": true,
    "warm": true
  },
  "squad": {
    "path": "squad.json",
    "required": true,
    "warm": true
  },
  "week": {
    "path": "week.json",
    "required": false,
    "warm": false
  },
  "plan": {
    "path": "plan.json",
    "required": false,
    "warm": false
  },
  "history": {
    "path": "history.json",
    "required": true,
    "warm": false
  },
  "fixtures": {
    "path": "fixtures.json",
    "required": true,
    "warm": false
  },
  "league": {
    "path": "league.json",
    "required": false,
    "warm": false
  },
  "health": {
    "path": "health.json",
    "required": true,
    "warm": false
  },
  "log": {
    "path": "log.json",
    "required": false,
    "warm": false
  },
  "models": {
    "path": "models.json",
    "required": false,
    "warm": true
  },
  "models_history": {
    "path": "models_history.json",
    "required": false,
    "warm": false
  },
  "as_if_played": {
    "path": "as_if_played.json",
    "required": false,
    "warm": false
  },
  "xp_accuracy": {
    "path": "xp_accuracy.json",
    "required": true,
    "warm": false
  },
  "strategies": {
    "path": "strategies.json",
    "required": false,
    "warm": true
  },
  "live": {
    "path": "live.json",
    "required": false,
    "warm": true
  }
} as const;

/** Each artefact's type, by key. */
export interface ArtefactMap {
  meta: Meta;
  rules: Rules;
  players: Players;
  squad: Squad;
  week: Week;
  plan: Plan;
  history: History;
  fixtures: Fixtures;
  league: League;
  health: Health;
  log: Log;
  models: Models;
  models_history: ModelsHistory;
  as_if_played: AsIfPlayed;
  xp_accuracy: XpAccuracy;
  strategies: Strategies;
  live: Live;
}

export type ArtefactKey = keyof ArtefactMap;
