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
