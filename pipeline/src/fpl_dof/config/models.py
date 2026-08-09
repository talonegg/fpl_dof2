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


class Config(_Section):
    """The whole configuration, as one immutable object threaded through every stage."""

    runtime: RuntimeConfig = RuntimeConfig()
    http: HttpConfig = HttpConfig()
    sources: SourcesConfig = SourcesConfig()
    rules: RulesConfig = RulesConfig()
