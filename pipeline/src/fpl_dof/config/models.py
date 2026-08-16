"""Typed configuration.

Every tunable in the system is a field here with a default and a docstring saying why the default
is what it is (DP-06). Nothing reads a magic number from code.

``extra="forbid"`` throughout is deliberate: a mistyped key in a YAML override is a silent
behaviour change otherwise, and this project cannot afford silent behaviour changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeConfig(_Section):
    """Execution context. Not a model parameter — none of this changes a number."""

    env: Literal["local", "ci"] = "local"
    data_dir: Path = Field(
        default=Path("data"),
        description="Data root. Resolved to an absolute path at load time.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    timezone: str = Field(
        default="Australia/Sydney",
        description=(
            "Rendering zone only. Everything is stored and computed in UTC (DL-11); this is used "
            "at the display edge and nowhere else."
        ),
    )


class RateLimitConfig(_Section):
    """Politeness, not performance. NFR-10."""

    requests_per_second: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Sustained request rate against a single host. 2/s puts the largest per-player "
            "sweep any adapter declares at roughly six minutes, which is acceptable and polite."
        ),
    )
    max_concurrency: int = Field(
        default=1,
        ge=1,
        description="Serial by default. Parallelising a public free API we do not own is rude.",
    )


class RetryConfig(_Section):
    """Transient failure handling. Deterministic ceilings so a bad day cannot hang a run."""

    max_attempts: int = Field(default=4, ge=1)
    backoff_base_seconds: float = Field(default=0.5, gt=0)
    backoff_max_seconds: float = Field(default=30.0, gt=0)
    jitter_fraction: float = Field(
        default=0.25,
        ge=0,
        le=1,
        description="Proportional jitter applied to each backoff, to avoid synchronised retries.",
    )
    retry_on_status: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)


class HttpConfig(_Section):
    """Everything the adapter base class needs to make an outbound request."""

    user_agent_template: str = Field(
        default="fpl-dof/{version} (+{contact})",
        description="NFR-10 requires honest client identification.",
    )
    user_agent_contact: str = Field(
        default="https://github.com/talonegg/fpl_dof2",
        description="Overridable via FPL_DOF_USER_AGENT_CONTACT. Never a personal address.",
    )
    timeout_seconds: float = Field(default=30.0, gt=0)
    rate_limit: RateLimitConfig = RateLimitConfig()
    retry: RetryConfig = RetryConfig()
    default_cache_ttl_seconds: int = Field(
        default=3600,
        ge=0,
        description=(
            "Re-running inside this window makes zero network calls. Per-endpoint overrides live "
            "in the adapter's own resource declarations."
        ),
    )


class SourceOverride(_Section):
    """Per-source configuration, keyed by source name.

    Generic on purpose. No source's name appears as a field anywhere in this file, because a named
    field is a downstream module knowing that source exists (Invariant 1).
    """

    enabled: bool | None = None
    cache_ttl_seconds: dict[str, int] = Field(
        default_factory=dict,
        description="Per-resource TTL overrides, keyed by the resource name the adapter declares.",
    )
    credit_budget: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Requests this source may make per calendar month, enforced inside the adapter rather "
            "than by scheduling discipline (CON-7, R-08). Generic because metering is a property "
            "some providers have, not a property of one named provider. None means unmetered, or "
            "the adapter's own default where it has one."
        ),
    )


class EntityResolutionConfig(_Section):
    """Matching players across sources (FR-07, R-10).

    The highest-risk silent failure in the system: a bad match attributes one footballer's expected
    goals to another and nothing visibly breaks. Every number here is a threshold on how much
    guessing is tolerated, which is precisely the sort of thing that must be adjustable without a
    code change (DP-06).
    """

    fuzzy_threshold: float = Field(
        default=0.90,
        ge=0,
        le=1,
        description=(
            "Token-set similarity a fuzzy match must reach. High on purpose: an unmatched player "
            "is a visible gap, a wrongly matched one is an invisible error, so the asymmetry "
            "should be paid for in misses."
        ),
    )
    fuzzy_margin: float = Field(
        default=0.05,
        ge=0,
        le=1,
        description=(
            "How far the best candidate within a club must beat the runner-up before a fuzzy "
            "match is accepted. Design §3.2 requires the match to be unambiguous, and two players "
            "at 0.93 and 0.92 is not."
        ),
    )
    match_on_position: bool = Field(
        default=True,
        description=(
            "Require position agreement in the deterministic tier. Sources disagree about where a "
            "wing-back plays; when that becomes noisier than it is useful, turn it off here "
            "rather than in code."
        ),
    )


class SourcesConfig(_Section):
    overrides: dict[str, SourceOverride] = Field(default_factory=dict)
    backfill_seasons: tuple[str, ...] = Field(
        default=(),
        description=(
            "Historical seasons any source capable of supplying them should backfill, as "
            "'2024/25'. Generic on purpose: a source that cannot answer ignores it. Empty means "
            "the source's own default."
        ),
    )
    resolution: EntityResolutionConfig = EntityResolutionConfig()
    field_precedence: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description=(
            "Canonical field name -> source names to try, in order (NFR-15). Precedence is "
            "configuration, not code (DP-01): where two sources supply the same field, this is the "
            "only place that decides. Empty means the source layer's declared default, which is "
            "where the source *names* live so that no module outside it has to know them "
            "(Invariant 1). A field named here overrides that default outright."
        ),
    )


class SupplementaryScoring(_Section):
    """Scoring values FPL does not publish. See config/defaults/rules.yaml for why each is here."""

    long_play_minutes: int = 60
    saves_per_point: int = Field(default=3, gt=0)
    goals_conceded_per_point: int = Field(default=2, gt=0)
    defensive_contribution_threshold: dict[str, int] = Field(
        default_factory=lambda: {"GKP": 0, "DEF": 10, "MID": 12, "FWD": 12}
    )
    bonus_points: tuple[int, ...] = (3, 2, 1)


class SupplementaryTransfers(_Section):
    max_free_transfers: int = Field(default=5, gt=0)
    extra_transfer_cost: int = -4


class RulesConfig(_Section):
    """The supplementary half of the rules. The rest is seeded from the source snapshot."""

    season: str = "2026/27"
    scoring: SupplementaryScoring = SupplementaryScoring()
    transfers: SupplementaryTransfers = SupplementaryTransfers()


class MinutesConfig(_Section):
    """How playing time is turned into expected minutes.

    E0 has no minutes model (debt D-02) and no start model (D-12). These are priors, and their
    crudeness is the single biggest known weakness of the v0 forecast.
    """

    full_match: int = Field(default=90, description="Minutes in a match.")
    team_games_per_season: int = Field(default=38, gt=0)
    starter_minutes: float = Field(
        default=82.0,
        gt=0,
        description="Average minutes played when a player starts, allowing for substitutions off.",
    )
    substitute_minutes: float = Field(
        default=20.0,
        gt=0,
        description="Average minutes played when appearing from the bench.",
    )
    appearance_rate_if_not_starting: float = Field(
        default=0.35,
        ge=0,
        le=1,
        description="Probability a non-starter appears at all. A squad player, not an absentee.",
    )


class ShrinkageConfig(_Section):
    """How hard a thin sample is pulled toward its group prior."""

    rate_prior_minutes: float = Field(
        default=900.0,
        gt=0,
        description=(
            "Minutes of prior-season evidence at which a player's own rate carries half the "
            "weight. 900 is ten full matches: enough to mean something, far from conclusive."
        ),
    )
    start_prior_games: float = Field(
        default=10.0,
        gt=0,
        description="Equivalent prior weight, in games, for the start-probability estimate.",
    )


class FixtureDifficultyConfig(_Section):
    """Multipliers by FPL's own 1-5 difficulty rating.

    Preseason team strength_attack/defence fields are all zero, so the fixture's own difficulty is
    the only signal available. Defence swings harder than attack because a clean sheet is a
    threshold event and a goal is not (debt D-05: an xG-based model replaces this in E3).
    """

    attack: dict[int, float] = Field(
        default_factory=lambda: {1: 1.15, 2: 1.08, 3: 1.00, 4: 0.92, 5: 0.85}
    )
    defence: dict[int, float] = Field(
        default_factory=lambda: {1: 1.30, 2: 1.14, 3: 1.00, 4: 0.86, 5: 0.72}
    )


class UncertaintyConfig(_Section):
    """Deliberately wide bands (Invariant 6).

    A heuristic coefficient of variation, not a modelled variance — debt D-09. Wide is the honest
    choice for a forecast that has never been backtested.
    """

    coefficient_of_variation: dict[str, float] = Field(
        default_factory=lambda: {"high": 0.45, "medium": 0.60, "low": 0.80, "none": 1.00}
    )
    floor: float = Field(
        default=0.5,
        ge=0,
        description="Minimum standard deviation in points, so a near-zero xP is not near-certain.",
    )


class PriorSeasonConfig(_Section):
    """Prior-season advanced metrics, as a player-specific prior (D-22).

    The conformed advanced tables carry **running season totals**, which are legitimate only once
    the season they describe has finished — a finished season's total is unusable at any deadline
    inside that season (Invariant 5). So they enter the model as a *previous*-season feature and
    nothing else.

    **A ratio, not a rate.** What is trusted about an external provider's numbers is the ordering
    they imply, not their absolute scale: one provider's "defensive action" is not the official
    feed's, and a per-90 count taken literally would bias every prior it touches. Each statistic is
    therefore divided by the mean among that player's position, and the result scales the position
    prior the model already uses.

    **Off by default (DP-08).** It ships dark and is promoted only if a backtest says it earns its
    place, which is the entire point of the story that added it.
    """

    enabled: bool = Field(
        default=False,
        description=(
            "Whether the prior-season prior is used at all. Off until measured: the toggle is what "
            "makes the before/after comparison a single configuration change rather than a diff."
        ),
    )
    statistics: dict[str, tuple[str, ...]] = Field(
        default_factory=lambda: {
            "non_penalty_expected_goals": ("non_penalty_expected_goals",),
            "expected_assists": ("expected_assists",),
            "defensive_actions": ("tackles", "interceptions", "blocks", "clearances", "recoveries"),
        },
        description=(
            "Feature stem -> the canonical metric columns summed to build it. Summed rather than "
            "named singly because the defensive proxy is a count of several actions, and which "
            "actions a provider reports is exactly the kind of thing that belongs in configuration."
        ),
    )
    component_priors: dict[str, str] = Field(
        default_factory=lambda: {
            "goals_scored": "non_penalty_expected_goals",
            "assists": "expected_assists",
            "defensive_contribution": "defensive_actions",
        },
        description=(
            "Rate component -> the feature stem whose ratio scales its position prior. A component "
            "absent from this map is unaffected, which is how the signal reaches M3 and M4 without "
            "reaching anything it was never argued to inform."
        ),
    )
    minimum_minutes: float = Field(
        default=450.0,
        ge=0,
        description=(
            "Prior-season minutes below which the rate is noise. Five full matches: enough that a "
            "single cameo cannot set a player's prior for a whole season."
        ),
    )
    prior_minutes: float = Field(
        default=900.0,
        gt=0,
        description=(
            "Prior-season minutes at which the player's own ratio carries half the weight against "
            "a neutral 1.0. Deliberately the same figure as the rate shrinkage: last season's "
            "evidence is not stronger than this season's, and pretending otherwise would let a "
            "stale number outvote what the player is doing now."
        ),
    )
    minimum_ratio: float = Field(
        default=0.5,
        gt=0,
        description="Floor on the position-relative ratio. A prior may be halved, not erased.",
    )
    maximum_ratio: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Ceiling on the position-relative ratio. Bounded because the tail of a ratio of small "
            "numbers is meaningless, and an unbounded one would let a fringe player's 300 minutes "
            "triple a prior."
        ),
    )


class ExpectedGoalsConfig(_Section):
    """Observe player scoring rates through expected goals, not actual goals (DP-08, ships dark).

    The best-established use of xG in football forecasting: a player's expected goals regress far
    less than their actual goals, so recent xG estimates the underlying scoring rate better than
    recent goals do — most sharply over the short windows FPL forces. A striker with two goals from
    0.4 xG got lucky, and next week's forecast should mostly not believe the two.

    Both ``expected_goals`` and ``expected_assists`` are carried by the **official feed itself**, so
    this needs no scraped source and is unblocked by D-23. It is the live realisation of the M2/M3
    xG design that [DL-33] found described in the conceptual design but implemented nowhere.

    **Off by default.** Promoted only if the walk-forward backtest says it earns its place, which is
    the discipline DP-12 asks for. The toggle makes the before/after a single configuration change.
    """

    enabled: bool = Field(
        default=False,
        description=(
            "Whether goal and assist rates are observed and fitted through expected goals rather "
            "than actual. Off until the backtest measures it (DP-08, DP-12)."
        ),
    )
    rate_sources: dict[str, str] = Field(
        default_factory=lambda: {
            "goals_scored": "expected_goals",
            "assists": "expected_assists",
        },
        description=(
            "Rate component -> the statistic whose per-90 is observed and whose position prior is "
            "fitted in its place. A component absent from this map keeps observing itself, so the "
            "xG signal reaches goal involvement without touching cards, saves or bonus. Column "
            "names only, never source names (Invariant 1)."
        ),
    )
    team_strength_from_xg: bool = Field(
        default=False,
        description=(
            "Whether M2 fits attack and defence on expected goals for and against rather than on "
            "actual goals. Separable from the rate switch because the two are independent bets: "
            "team-level xG and player-level xG can each earn their place or fail to."
        ),
    )


class FeatureConfig(_Section):
    """The feature store. Windows are configuration because the right length is an empirical
    question the backtest is supposed to answer, not a constant to be asserted."""

    rolling_windows: tuple[int, ...] = Field(
        default=(3, 6, 12),
        description=(
            "Match counts for rolling rates. Three is form, twelve is closer to true rate, six is "
            "the compromise; carrying all three lets the model weigh them rather than being told."
        ),
    )
    rolling_statistics: tuple[str, ...] = Field(
        default=(
            "goals_scored",
            "assists",
            "clean_sheets",
            "saves",
            "bonus",
            "bps",
            "defensive_contribution",
            "expected_goals",
            "expected_assists",
            "total_points",
        ),
        description="Per-90 rates to compute over each window. Absent columns become null.",
    )
    minimum_minutes_for_rate: int = Field(
        default=90,
        ge=0,
        description="Below this, a per-90 rate is noise dressed as evidence and is shrunk hard.",
    )
    prior_season: PriorSeasonConfig = PriorSeasonConfig()


class ForecastConfig(_Section):
    """The v0 expected-points model. Every tunable is here; none is in code (DP-06)."""

    horizon_gameweeks: int = Field(default=6, ge=1, le=38)
    horizon_discount: float = Field(
        default=0.92,
        gt=0,
        le=1,
        description="Per-gameweek discount on future value. Nearer gameweeks are more knowable.",
    )
    defensive_contribution_seasons: tuple[str, ...] = Field(
        default=("2025/26",),
        description=(
            "Seasons in which Defensive Contribution was actually recorded. Earlier seasons show "
            "zero because the metric did not exist, not because nobody defended — reading those "
            "as evidence would systematically underrate defenders."
        ),
    )
    starts_recorded_from_season: str = Field(
        default="2022/23",
        description="Before this, starts are not recorded: the same absence-of-measurement trap.",
    )
    max_history_seasons: int = Field(
        default=3,
        ge=1,
        description="How far back to look. Older football is weaker evidence about this season.",
    )
    season_recency_decay: float = Field(
        default=0.6,
        gt=0,
        le=1,
        description="Weight applied per season of age, before minutes weighting.",
    )
    confidence_minutes_high: int = Field(default=1800, ge=0)
    confidence_minutes_medium: int = Field(default=600, ge=0)
    price_tiers: int = Field(
        default=4, ge=2, description="Quantile buckets, within position, for the group prior."
    )
    minimum_start_probability_for_xi: float = Field(
        default=0.60,
        ge=0,
        le=1,
        description=(
            "E0-S5 acceptance: nothing below this may start. With no minutes model and preseason "
            "status flags almost universally 'a', this is what stops the optimiser filling the XI "
            "with cheap players who will never play."
        ),
    )
    status_multiplier: dict[str, float] = Field(
        default_factory=lambda: {"a": 1.0, "d": 0.5, "i": 0.0, "s": 0.0, "u": 0.0, "n": 0.0},
        description="FPL availability flags: available, doubtful, injured, suspended, unavailable.",
    )
    minutes: MinutesConfig = MinutesConfig()
    shrinkage: ShrinkageConfig = ShrinkageConfig()
    fixture_difficulty: FixtureDifficultyConfig = FixtureDifficultyConfig()
    uncertainty: UncertaintyConfig = UncertaintyConfig()
    features: FeatureConfig = FeatureConfig()
    expected_goals: ExpectedGoalsConfig = ExpectedGoalsConfig()


class ChipReplayConfig(_Section):
    """D-18 — replaying real historical deadlines through the whole decision engine.

    Every field here exists to *bound* the replay. One deadline costs a model refit plus two
    multi-gameweek solves over a full chip enumeration, which DL-26 measured in the tens of
    seconds; an unbounded sweep of the backtest window would run for hours and answer the same
    question the bounded one does.
    """

    deadline_stride: int = Field(
        default=6,
        ge=1,
        description=(
            "Take every Nth scoreable deadline. Spacing the sample rather than taking a run of "
            "consecutive gameweeks is deliberate: consecutive deadlines share almost all their "
            "training data and their fixture run, so they are close to one observation repeated."
        ),
    )
    first_gameweek: int = Field(
        default=6,
        ge=1,
        description=(
            "Earliest gameweek sampled. Before this the component models are fitted on a handful "
            "of matches, so the chip timing being compared reflects the prior rather than the "
            "fixtures."
        ),
    )
    last_gameweek: int = Field(
        default=32,
        ge=1,
        description=(
            "Latest gameweek sampled. Late enough in the season that the horizon runs off the end "
            "leaves the chip enumerator almost no timings to choose between."
        ),
    )
    max_deadlines: int = Field(
        default=8,
        ge=1,
        description="Hard ceiling on sampled deadlines, whatever the stride implies.",
    )
    bank: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Money in the bank of the replayed squad. Zero because the squad is solved to the "
            "budget: a replay is not a manager's actual season, and pretending it had savings "
            "would be an invented fact."
        ),
    )
    free_transfers: int = Field(
        default=1,
        ge=0,
        description="Free transfers the replayed squad starts each sampled deadline with.",
    )


class BacktestConfig(_Section):
    """Walk-forward replay. The measurement that makes every later change evaluable (FR-37)."""

    chip_replay: ChipReplayConfig = ChipReplayConfig()
    training_seasons: tuple[str, ...] = Field(
        default=("2022/23", "2023/24", "2024/25", "2025/26"),
        description="Seasons available to the harness. Which of them a component may use is a "
        "per-component question — see the scoring-regime table in E2-S3.",
    )
    minimum_training_matches: int = Field(
        default=4,
        ge=1,
        description=(
            "Gameweeks of history required before a deadline is scored. Predicting gameweek 1 "
            "from nothing measures the prior, not the model."
        ),
    )
    top_n_precision: int = Field(
        default=20,
        gt=0,
        description="Charter tier-2 metric: precision within the top N predicted scorers.",
    )
    minimum_minutes_for_scoring: int = Field(
        default=1,
        ge=0,
        description=(
            "Players below this are excluded from accuracy metrics. Scoring against players who "
            "did not feature measures the minutes model twice and flatters both."
        ),
    )
    captaincy_pool: int = Field(
        default=1,
        gt=0,
        description="How many top picks count as a captaincy hit. One is the honest test.",
    )


class OptimiserConfig(_Section):
    """The squad solver."""

    bench_weight: float = Field(
        default=0.15,
        ge=0,
        le=1,
        description=(
            "How much a bench player's expected points counts toward the objective. Not zero: a "
            "bench that never plays is still four squad places and real money."
        ),
    )
    captain_multiplier: int = Field(default=2, ge=1)
    solve_time_limit_seconds: int = Field(default=60, gt=0)
    solver: str = Field(default="CBC", description="PuLP's bundled solver. HiGHS arrives in E4.")
    enforce_start_probability_floor: bool = Field(
        default=True,
        description=(
            "Bar players below the forecast's start-probability floor from the starting XI. "
            "A locked player is exempt: an explicit human override outranks the heuristic."
        ),
    )
    locked_player_ids: tuple[int, ...] = Field(
        default=(),
        description="Must be in the squad. The E0-S8 review applies overrides through here.",
    )
    banned_player_ids: tuple[int, ...] = Field(default=(), description="Must not be selected.")
    excluded_team_ids: tuple[int, ...] = Field(
        default=(), description="No player from these clubs may be selected."
    )


class CandidateConfig(_Section):
    """E4-S1 candidate pruning. Roughly 700 players reduced to a tractable pool, without bias.

    Every number here widens or narrows the pool. None of them may *bias* it: the owned squad, any
    locked player and the cheap enablers are included unconditionally, because a pure
    expected-points ranking drops the enablers and a squad that cannot afford a premium is worse
    than one that can.
    """

    top_n_per_position_by_points: int = Field(
        default=30,
        gt=0,
        description="Best per position on horizon expected points. The obvious half of the pool.",
    )
    top_n_per_position_by_value: int = Field(
        default=20,
        gt=0,
        description="Best per position on expected points per £m. Overlaps the above by design.",
    )
    cheap_enablers_per_position: int = Field(
        default=10,
        ge=0,
        description=(
            "Cheapest credible players per position, taken on expected points *within* the cheap "
            "band. Structurally necessary to afford premiums, and invisible to any xP ranking."
        ),
    )
    cheap_enabler_price_quantile: float = Field(
        default=0.25,
        gt=0,
        le=1,
        description="Price quantile, within position, defining the cheap band.",
    )
    minimum_expected_points: float = Field(
        default=0.0,
        ge=0,
        description="Floor on horizon expected points before a player can enter on merit.",
    )
    target_pool_size: int = Field(
        default=250,
        gt=0,
        description=(
            "Advisory, not enforced: the pruning rule is composed of the rules above, and this is "
            "the size they are tuned to produce. Reported so drift is visible rather than assumed."
        ),
    )


class HorizonConfig(_Section):
    """E4-S2 multi-gameweek MILP. FR-18."""

    gameweeks: int = Field(
        default=5,
        ge=1,
        le=8,
        description=(
            "Rolling horizon length. Design §6.2 calls for 5-8; five is the short end because the "
            "forecast is unvalidated at the head of the ranking (DL-21) and a longer horizon "
            "compounds that, not the solver's difficulty."
        ),
    )
    discount: float = Field(
        default=0.85,
        gt=0,
        le=1,
        description="Per-gameweek discount on future expected points. Design §6.2's gamma.",
    )
    max_transfers_per_gameweek: int = Field(
        default=2,
        ge=0,
        le=15,
        description=(
            "Cap on transfers in any one non-chip gameweek. Not a rule of the game — a bound that "
            "keeps the model honest about how much churn is plausible, and keeps it tractable."
        ),
    )
    solver: Literal["HiGHS", "CBC"] = Field(
        default="HiGHS",
        description=(
            "DL-15: HiGHS from E4 onward. The single-gameweek E1 and E0 models stay on CBC, which "
            "E0 validated against them; this is the model CBC was never validated for."
        ),
    )
    solve_time_limit_seconds: int = Field(
        default=120,
        gt=0,
        description="Wall clock per scenario solve. Exceeding it falls back to greedy (DP-15).",
    )
    scenario_time_budget_seconds: int = Field(
        default=600,
        gt=0,
        description="Total budget across every chip scenario. R-07 is rated High; this bounds it.",
    )
    incumbency_bonus: float = Field(
        default=0.01,
        ge=0,
        description=(
            "Design §6.2's ε. Added per gameweek for every player already held. Small enough never "
            "to overturn a genuine expected-points difference, large enough to break the massive "
            "degeneracy of the squad problem so the same inputs return the same squad (R-16)."
        ),
    )
    transfer_margin: float = Field(
        default=0.5,
        ge=0,
        description=(
            "Expected points a plan must beat the roll-everything plan by before a transfer is "
            "recommended. The tie-break's other half: a transfer clears a margin, never merely "
            "ties. Zero would restore the churn the tie-break exists to stop."
        ),
    )
    bench_weight: float = Field(
        default=0.15,
        ge=0,
        le=1,
        description="Design §6.2's β. Exactly 1 in a Bench Boost gameweek, which is the chip.",
    )


class ChipConfig(_Section):
    """E4-S3 chip modelling, by scenario enumeration rather than decision variables (DL-15)."""

    max_scenarios: int = Field(
        default=24,
        gt=0,
        description=(
            "Ceiling on (chip, gameweek) assignments solved. Enumeration is only tractable while "
            "the set stays small; beyond this the pruning below is doing too little."
        ),
    )
    runners_up: int = Field(
        default=3,
        ge=0,
        description="Scenarios kept beside the winner. They are what the explanation needs.",
    )
    calendar_gameweeks: int = Field(
        default=38,
        ge=1,
        le=38,
        description="How far the long-range chip calendar projects. The season, by default.",
    )
    bench_boost_minimum_fixtures: float = Field(
        default=1.0,
        ge=0,
        description=(
            "Mean fixtures per squad club below which Bench Boost is not even enumerated. A Bench "
            "Boost in a blank gameweek is not a candidate."
        ),
    )
    captain_multiplier_by_chip: dict[str, int] = Field(
        default_factory=lambda: {"3xc": 3},
        description=(
            "Captain multiplier a chip imposes, overriding the ordinary one. Configuration rather "
            "than a literal 3 in the solver (Invariant 2). The game exposes this as "
            "`overrides.pick_multiplier` on each chip; until the silver chip table carries that "
            "field (D-15) this is the seeded value, and it is here so it is one line to correct."
        ),
    )
    force_chip_gameweek: dict[str, int] = Field(
        default_factory=dict,
        description="E4-S5 override: chip name -> gameweek it must be played in.",
    )
    forbid_chip_gameweeks: dict[str, tuple[int, ...]] = Field(
        default_factory=dict,
        description="E4-S5 override: chip name -> gameweeks it must not be played in.",
    )


class RiskConfig(_Section):
    """E4-S4 risk dial and ownership. FR-21, FR-16, DL-07, DL-24.

    **Ownership is `selected_by_percent` and nothing else** (DL-24, resolving OD-06). There is no
    captaincy term, because captaincy share is exposed by no public endpoint and modelling it would
    be presenting an estimate as a measurement. Every figure this produces is labelled "selected
    by"; the single most-captained player is surfaced separately as a plain callout.
    """

    dial: Literal["safe", "balanced", "aggressive"] = Field(
        default="balanced",
        description=(
            "OD-05, resolved at DL-25: Balanced by default, in the absence of a stated target "
            "rank. Design §7.1's own table names Balanced the default posture — a small penalty "
            "that broadly follows expected points and avoids only the most extreme template gaps."
        ),
    )
    ownership_weight: dict[str, float] = Field(
        default_factory=lambda: {"safe": 0.020, "balanced": 0.005, "aggressive": -0.010},
        description=(
            "Expected points added per percentage point of `selected_by_percent`, per starter, per "
            "gameweek. Positive pulls toward the template; negative rewards differentials. A "
            "linear proxy for a quadratic quantity, and the UI says so."
        ),
    )
    same_club_starting_limit: int = Field(
        default=2,
        ge=1,
        le=11,
        description=(
            "Design §6.2 C16. Two players from one club in the starting XI, aimed squarely at the "
            "dominant correlation a MILP cannot represent. Q-12 asks whether 2 or 3 is better; 2 "
            "is the documented default."
        ),
    )
    relax_club_cap_team_ids: tuple[int, ...] = Field(
        default=(),
        description="E4-S5 override: clubs exempt from C16, for a deliberate triple-up.",
    )


class SimulationConfig(_Section):
    """E4-S4a simulation re-rank. Most of the stochastic layer, none of the solver work."""

    enabled: bool = True
    draws: int = Field(
        default=4000,
        gt=0,
        description="Samples per candidate plan. Enough to separate plans a point or two apart.",
    )
    seed: int = Field(
        default=20262027,
        description="Fixed, because a recommendation that changes on refresh is not one (R-16).",
    )
    match_variance_share: float = Field(
        default=0.45,
        ge=0,
        le=1,
        description=(
            "Fraction of a player's variance that is shared with everyone else in his match. This "
            "is the whole point: two defenders from one club share a clean sheet, and a re-rank "
            "that samples players independently is not modelling the thing it exists to model."
        ),
    )
    percentile_by_dial: dict[str, float] = Field(
        default_factory=lambda: {"safe": 0.30, "balanced": 0.50, "aggressive": 0.75},
        description=(
            "Which point of the simulated distribution each dial position is scored on. "
            "Deliberately a percentile rather than the mean even at Balanced: the mean is what the "
            "MILP already "
            "maximised, so re-ranking on it could only ever reproduce the MILP's own ordering, and "
            "Bench Boost and Triple Captain are exactly the decisions the mean cannot see."
        ),
    )


class DecisionConfig(_Section):
    """E4's decision engine: pruning, the multi-gameweek plan, chips, risk and simulation."""

    candidates: CandidateConfig = CandidateConfig()
    horizon: HorizonConfig = HorizonConfig()
    chips: ChipConfig = ChipConfig()
    risk: RiskConfig = RiskConfig()
    simulation: SimulationConfig = SimulationConfig()
    maximum_spend: float | None = Field(
        default=None,
        gt=0,
        description="E4-S5 override: cap total squad spend below the budget, in £m. None means no "
        "cap beyond the budget itself.",
    )
    forced_formation: dict[str, int] | None = Field(
        default=None,
        description=(
            "E4-S5 override: an exact starting formation, as position -> count. None means any "
            "legal formation. An illegal one is rejected with a reason rather than solved around."
        ),
    )


class DeclaredPick(_Section):
    """One player in a manually declared squad.

    ``purchase_price`` is not optional and cannot be inferred: selling value depends on what was
    paid (the 50% sell-on fee), and no public endpoint reveals a purchase price until picks exist.
    Guessing it would quietly misprice every transfer the optimiser costs.
    """

    player_id: int = Field(gt=0)
    purchase_price: float = Field(gt=0, le=25.0, description="What you paid, in £m.")
    selling_price: float | None = Field(
        default=None,
        gt=0,
        le=25.0,
        description=(
            "Override for the computed selling price. Normally left unset — the sell-on fee is "
            "derived from purchase price and current price by the rules module."
        ),
    )


class EntryConfig(_Section):
    """The owner's own team.

    Nothing here names a data source. ``team_id`` is an FPL *game* concept — the entry ID — and the
    adapter that knows which URL exposes it lives in ``sources/`` (Invariant 1).
    """

    team_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Your FPL entry ID, from the URL /entry/{id}/event/1. Overridable via FPL_DOF_TEAM_ID. "
            "Public, not a secret (NFR-11). Unset means the weekly loop runs on a declared squad."
        ),
    )
    declared_squad: tuple[DeclaredPick, ...] = Field(
        default=(),
        description=(
            "A manually stated squad. Before GW1 is scored there is no picks endpoint to read "
            "(DL-20), so this is the primary input for the first weekly run, not a fallback."
        ),
    )
    declared_bank: float = Field(
        default=0.0, ge=0, description="Money in the bank, in £m, for a declared squad."
    )
    declared_free_transfers: int = Field(
        default=1, ge=0, description="Free transfers available, for a declared squad."
    )
    declared_chips_used: tuple[str, ...] = Field(
        default=(), description="Chip names already played, for a declared squad."
    )
    prefer_declared: bool = Field(
        default=False,
        description=(
            "Force the declared squad even when picks are available. The escape hatch for a "
            "reconstruction that disagrees with reality; normally false."
        ),
    )
    league_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "A classic mini-league to compare against, from the URL /leagues/{id}/standings/c. "
            "Overridable via FPL_DOF_LEAGUE_ID. "
            "Public, not a secret (NFR-11). **Unset is the normal state**: leave it unset and no "
            "league is fetched, no league artefact is published, and the app says so plainly "
            "(E6-S10, DP-15). A game concept, not a source concept — the adapter that knows which "
            "URL exposes it lives in sources/ (Invariant 1)."
        ),
    )
    league_rival_limit: int = Field(
        default=20,
        ge=0,
        le=50,
        description=(
            "How many entries, from the top of the standings down, to fetch squads for. Each one "
            "costs a request per scored gameweek read, so this is the knob that decides what "
            "rival analysis costs; 0 publishes standings alone with no overlap. The cap exists "
            "because a public league can have hundreds of thousands of entries and fetching them "
            "would be both useless and rude to an API this project is a guest on."
        ),
    )


class TransferConfig(_Section):
    """The weekly transfer decision. Separate from the squad optimiser: a different question."""

    max_transfers: int = Field(
        default=2,
        ge=0,
        le=15,
        description=(
            "How many transfers to evaluate. E1 scope is 0, 1 or 2 — beyond that is multi-week "
            "planning, which is E4."
        ),
    )
    min_gain_over_hit: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Expected points a hit must gain *beyond* its 4-point cost before it is recommended. "
            "Zero means break-even is enough; raise it to demand a margin against forecast error."
        ),
    )
    horizon_gameweeks: int = Field(
        default=1,
        ge=1,
        le=38,
        description=(
            "Gameweeks the transfer decision is judged over. E1 is single-gameweek by scope; the "
            "multi-gameweek version is E4."
        ),
    )


class AlertsConfig(_Section):
    """What the weekly output should shout about without being asked."""

    decide_by_hours_before_deadline: float = Field(
        default=12.0,
        gt=0,
        description=(
            "The 'decide by' time is this far before the deadline. It exists because most UK "
            "deadlines land between 02:30 and 05:00 local (DL-11), so the practical rule is to "
            "decide the evening before rather than to be awake for it."
        ),
    )
    price_change_ownership_threshold: float = Field(
        default=0.4,
        ge=0,
        description=(
            "Net transfers in a day, as a percentage of all managers, above which a price change "
            "is called likely. A rule of thumb, not a model — the real price algorithm is not "
            "published."
        ),
    )
    doubtful_chance_threshold: int = Field(
        default=75,
        ge=0,
        le=100,
        description="Chance of playing at or below which an owned player raises an alert.",
    )
    chip_warning_gameweek: int = Field(
        default=12,
        ge=1,
        le=38,
        description="Gameweek from which unused set-1 chips start warning (E2-S7).",
    )
    chip_urgent_gameweek: int = Field(
        default=16,
        ge=1,
        le=38,
        description="Gameweek from which the warning becomes unmissable.",
    )


class QualityConfig(_Section):
    """Thresholds for the data quality gates.

    Here rather than in the gate definitions because a threshold is exactly the sort of thing that
    needs changing at 03:00 when the league expands or a source behaves oddly, and a code change
    under deadline pressure is how gates get disabled instead of adjusted (DP-06, Invariant 7).
    """

    minimum_players: int = Field(
        default=400,
        gt=0,
        description=(
            "A full Premier League season carries roughly 700 registered players. 400 is a floor "
            "well below any legitimate value and well above a partial-outage response."
        ),
    )
    minimum_volume_ratio: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description=(
            "Row count as a fraction of the previous run. Catches a table that halves while "
            "staying above the absolute floor, which an absolute floor alone cannot see."
        ),
    )
    expected_teams: int = Field(default=20, gt=0)
    expected_fixtures: int = Field(
        default=380,
        gt=0,
        description="20 clubs playing each other home and away. Warn, not error: postponements "
        "and rearrangements are normal and do not make the data wrong.",
    )
    maximum_snapshot_age_hours: float = Field(
        default=48.0,
        gt=0,
        description=(
            "Beyond this the run is flagged as stale. A warning, not a block: a stale but honest "
            "recommendation still beats no recommendation before a deadline (DP-15)."
        ),
    )
    minimum_price: float = Field(default=3.0, gt=0)
    maximum_price: float = Field(
        default=20.0,
        gt=0,
        description=(
            "Bounds that catch the tenths-versus-millions unit error, which is the most likely "
            "silent unit bug in this pipeline and produces a squad nobody can afford."
        ),
    )
    maximum_unmatched_player_rate: float = Field(
        default=0.10,
        ge=0,
        le=1,
        description=(
            "Fraction of a source's players that entity resolution may fail to match before the "
            "run is blocked (FR-07). Not zero: reserve and youth players appear on scraped pages "
            "and never in the game, so a few percent unmatched is the healthy state. A tenth "
            "unmatched means the matcher, not the tail, is what changed."
        ),
    )
    fail_on_warnings: bool = Field(
        default=False,
        description=(
            "Promote every warning to a blocking error. Off by default; useful in CI, where "
            "publishing nothing is cheap and a surprise is expensive."
        ),
    )


class HistoryArtefactConfig(_Section):
    """How the per-player trend series is compacted on the way out (DL-37, E6-S3/S5)."""

    ownership_change_threshold: float = Field(
        default=0.5,
        ge=0,
        le=100,
        description=(
            "Emit a price/ownership observation when ownership has moved at least this many "
            "percentage points since the last one emitted, or whenever the price changed at all. "
            "A daily observation per player is ~176,000 points over a season, most of them "
            "identical to the one before; price and ownership are step functions, so emitting on "
            "change is close to lossless. Lower keeps more detail and costs payload; 0 emits every "
            "observation. Set at 0.5 because that is roughly the resolution an ownership trend is "
            "read at, and finer movement is noise on a chart this size."
        ),
    )


class FixtureTickerConfig(_Section):
    """How a fixture's expected goals become a 1-5 difficulty (DL-37, E6-S8)."""

    difficulty_anchor_ratio: float = Field(
        default=2.0,
        gt=1,
        description=(
            "Sets the steepness of the difficulty scale: a side the model expects to score this "
            "multiple of the league mean scores `minimum` (1.0) for attack, and the same ratio "
            "conceded scores `maximum` (5.0) for defence. A league-average fixture is always 3.0 "
            "regardless of this value, because the scale is anchored on the ratio to the league "
            "mean rather than on a rank within the window. Higher makes the scale flatter and the "
            "extremes rarer. Two is chosen because doubling the league mean is roughly what the "
            "best attack against the worst defence actually produces, so the top of the scale is "
            "reachable but not routine."
        ),
    )
    minimum: float = Field(
        default=1.0,
        description="Easiest score. FPL's own FDR runs 1-5, and matching it keeps the "
        "grid legible to anyone who has ever read a fixture ticker.",
    )
    maximum: float = Field(default=5.0, description="Hardest score. Scores are clipped to this.")
    neutral: float = Field(
        default=3.0,
        description="Where a league-average fixture lands. The midpoint of the published range.",
    )


class PublishConfig(_Section):
    """Tunables that shape published artefacts rather than the models behind them."""

    history: HistoryArtefactConfig = HistoryArtefactConfig()
    fixtures: FixtureTickerConfig = FixtureTickerConfig()


class Config(_Section):
    """The whole configuration, as one immutable object threaded through every stage."""

    runtime: RuntimeConfig = RuntimeConfig()
    http: HttpConfig = HttpConfig()
    sources: SourcesConfig = SourcesConfig()
    rules: RulesConfig = RulesConfig()
    forecast: ForecastConfig = ForecastConfig()
    optimiser: OptimiserConfig = OptimiserConfig()
    entry: EntryConfig = EntryConfig()
    transfers: TransferConfig = TransferConfig()
    alerts: AlertsConfig = AlertsConfig()
    quality: QualityConfig = QualityConfig()
    backtest: BacktestConfig = BacktestConfig()
    decision: DecisionConfig = DecisionConfig()
    publish: PublishConfig = PublishConfig()
