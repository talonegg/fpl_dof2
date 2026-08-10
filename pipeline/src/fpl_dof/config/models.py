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


class SourcesConfig(_Section):
    overrides: dict[str, SourceOverride] = Field(default_factory=dict)


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


class Config(_Section):
    """The whole configuration, as one immutable object threaded through every stage."""

    runtime: RuntimeConfig = RuntimeConfig()
    http: HttpConfig = HttpConfig()
    sources: SourcesConfig = SourcesConfig()
    rules: RulesConfig = RulesConfig()
    forecast: ForecastConfig = ForecastConfig()
    optimiser: OptimiserConfig = OptimiserConfig()
