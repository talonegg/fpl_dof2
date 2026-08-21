"""Typed configuration.

Every tunable in the system is a field here with a default and a docstring saying why the default
is what it is (DP-06). Nothing reads a magic number from code.

``extra="forbid"`` throughout is deliberate: a mistyped key in a YAML override is a silent
behaviour change otherwise, and this project cannot afford silent behaviour changes.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class MinutesV2Config(_Section):
    """How M1 reacts to congestion and to a return from absence (E10-S1).

    Separated from the flag that switches it on: the flag says *whether* the candidate runs, these
    say *how hard* it pushes. Every one is a rotation prior chosen before the backtest measured it,
    which is why they are here and named rather than inline (DP-06) — the backtest is what settles
    them, and a number nobody can find is a number nobody can settle.

    All three adjustments only ever move probability **out of the 60+ state**. None of them can
    change P(play) computed from history, because neither congestion nor a completed return is
    evidence that a player is unavailable — they are evidence about how long he stays on.
    """

    congestion_baseline_matches: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Matches a club plays in the congestion window under a normal cadence. Two in a "
            "fortnight is one a week — the schedule a side with no midweek commitment keeps. "
            "Density is measured as the excess over this, so a normal fortnight adjusts nothing."
        ),
    )
    congestion_rotation_strength: float = Field(
        default=0.12,
        ge=0,
        le=1,
        description=(
            "Share of the 60+ state given up per extra match above the baseline cadence. 0.12 is "
            "a deliberately timid prior: it says a side playing one extra match in a fortnight "
            "rotates a given starter about an eighth of the time, which is well below what a "
            "manager rotating three of eleven would imply. Timid because the backtest has not yet "
            "measured it, and an over-strong rotation prior damages exactly the nailed starters "
            "the head of the ranking is made of."
        ),
    )
    return_ramp_strength: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description=(
            "Share of the 60+ state given up by a player who missed the whole recent window and is "
            "available again. A half, because the observed pattern is a substitute appearance or "
            "two before a full start, not an immediate 90 — and not more than a half, because the "
            "player is by construction an established starter and will get there."
        ),
    )
    return_established_appearance_rate: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description=(
            "Long-run appearance rate above which a recent run of blanks reads as an *absence* "
            "rather than as a fringe player being a fringe player. Below it there is nothing to "
            "return to and the ramp would be double-counting what the fitted band already knows."
        ),
    )
    availability_start_penalty: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description=(
            "How much harder a partial availability flag hits the 60+ state than the 1-59 state, "
            "on the live path only. A player at 50% who does play is far likelier to be eased in "
            "from the bench than to start and finish, and scaling both states equally — what the "
            "default chain does — prices him as a full starter half the time. P(play) is left "
            "exactly where the flag puts it; only its split between the two playing states moves."
        ),
    )


class AdaptiveShrinkageConfig(_Section):
    """How much of a rate's prior weight enough evidence is allowed to remove (E10-S2).

    :class:`ShrinkageConfig` sets one prior weight for everybody: a player's own per-90 rate carries
    half the weight once he has ``rate_prior_minutes`` of evidence, whoever he is. That constant is
    what [DL-21] measured as a **calibration slope of 0.70** — the head of the ranking compressed
    toward the position prior, which is the one part of the ranking anybody acts on. A nailed
    starter with two seasons behind him is being told he is probably average in exactly the way a
    player with three appearances should be.

    So the prior weight becomes a **function of evidence** instead of a constant. Below
    :attr:`onset_minutes` nothing changes at all — that is where shrinkage earns its keep and where
    a thin sample really is noise dressed as evidence. Above it the prior is scaled down linearly,
    reaching ``1 - strength`` of its usual weight at :attr:`full_minutes` and staying there. The
    shape is a straight line between two named points because it is a shape you can argue with
    (DP-10): a reader can say "a player with a season and a half behind him should not still be
    half prior" and see exactly which number to move.

    The evidence measure is the one the shrinkage already uses — recent minutes per match times
    matches observed — which is *both* of the quantities E10-S2 names, minutes played and sample
    size, in one number. A second definition of "how much do we know about this player" would be a
    second scale printed under one set of names.
    """

    strength: float = Field(
        default=0.4,
        ge=0,
        le=1,
        description=(
            "Share of the prior's weight removed at full evidence. 0 reproduces the flat prior "
            "exactly; 1 would let a well-observed player's own rate stand alone, with no pull "
            "toward his position at all. **0.4 is where the trade turns on the backtest, and was "
            "found there rather than chosen** (Q-14): top-20 precision rises to it and falls after "
            "it. It is not a value shown to be *better* — the rise is smaller than the noise in "
            "the measure and the calibration slope degrades throughout. Read DL-49 before turning "
            "the flag on; the honest summary is that this parameter has an optimum and the optimum "
            "does not help."
        ),
    )
    onset_minutes: float = Field(
        default=600.0,
        ge=0,
        description=(
            "Evidence below which shrinkage is untouched. Deliberately the same number as "
            "`confidence_minutes_medium`, and deliberately not the same parameter: that one tiers "
            "the uncertainty band shown to a human, this one shapes a rate. Coupling them would "
            "mean a shrinkage sweep silently re-tiered every published uncertainty band, which is "
            "how one experiment ends up measuring two changes."
        ),
    )
    full_minutes: float = Field(
        default=1800.0,
        gt=0,
        description=(
            "Evidence at and above which the full `strength` applies. Matches "
            "`confidence_minutes_high` for the same reason and with the same caveat as "
            "`onset_minutes`: twenty full matches is what this project already calls knowing a "
            "player well, and inventing a second threshold for it would invite the two to drift."
        ),
    )


class DutyEntryConfig(_Section):
    """One player's spell of penalty or set-piece duty at one club (E12-S2, D4).

    Curated knowledge rather than a measurement, so every field a reviewer needs to *disbelieve* the
    entry is present: who, where, when it became publicly knowable, when it lapsed, how strong the
    evidence was, and which snapshot it was seeded from (DP-09).

    ``player_code`` and not ``player_id``, because FPL reassigns element IDs every season and the
    code is stable for a career — a duty table keyed on the reassigned number would attribute one
    player's penalties to whoever inherited his shirt.
    """

    player_code: int = Field(gt=0, description="FPL's stable per-career player code.")
    name: str = Field(
        description="Web name, for a human reading the file. Never used to match a player."
    )
    club: str = Field(
        description="Club at the time of the spell, for a human reading the file. Not matched on."
    )
    duty: Literal["penalties", "direct_free_kicks", "corners"] = Field(
        default="penalties",
        description=(
            "Which dead ball. Only `penalties` is consumed by a model today; the other two are "
            "accepted and validated so the file can be completed ahead of a story that grades "
            "them, and are deliberately unseeded until one exists."
        ),
    )
    order: int = Field(
        default=1,
        ge=1,
        description=(
            "Where the player stands in the club's queue for this duty. Only order 1 contributes: "
            "a second taker takes some share of them, but nothing here knows what share, and "
            "inventing one would be a number with no basis (DP-09)."
        ),
    )
    known_from: dt.date = Field(
        description=(
            "The date the assignment became **publicly knowable** — not the date it was typed in. "
            "This is Invariant 5 for a hand-maintained file: a table written today and applied to "
            "a gameweek from two years ago is look-ahead, and the backtest is what it corrupts."
        )
    )
    known_until: dt.date | None = Field(
        default=None,
        description=(
            "The date the spell lapsed, exclusive, or null while it still holds. Half-open "
            "`[known_from, known_until)` so a handover on one date needs no gap and creates no "
            "overlap."
        ),
    )
    confidence: Literal["confirmed", "likely", "unconfirmed"] = Field(
        default="unconfirmed",
        description=(
            "How strong the evidence is. Scales the term rather than gating it, so a doubtful "
            "entry moves a forecast a little instead of either everything or nothing. The default "
            "is the weakest tier deliberately: an entry typed in by hand with no tier stated is an "
            "entry nobody has checked."
        ),
    )
    basis: str = Field(
        default="",
        description="Which snapshot or report this came from, so a reviewer can re-derive it.",
    )

    @model_validator(mode="after")
    def _window_is_ordered(self) -> DutyEntryConfig:
        if self.known_until is not None and self.known_until <= self.known_from:
            raise ValueError(
                f"duty entry for player_code {self.player_code} ends on or before it starts "
                f"({self.known_from} to {self.known_until})"
            )
        return self


class DutyConfig(_Section):
    """The committed penalty and set-piece duty reference table (E12-S2, D4, DL-50).

    Lives in its own ``config/defaults/duty.yaml`` — one hand-editable file with an owner
    maintenance note in it, reviewable on its own, exactly as the rules seed is. It is **the single
    source the E10-S3 duty term reads**; no module reaches past it to a feed.

    An empty table is a valid table and the term is a no-op under it (DP-15). Absence of an entry
    means *unknown*, never *no duty*, which is why nothing here subtracts anything from a player the
    file has never heard of.
    """

    entries: tuple[DutyEntryConfig, ...] = Field(
        default=(),
        description=(
            "Every known spell of duty. Order is irrelevant; the lookup is by player and date."
        ),
    )

    @model_validator(mode="after")
    def _spells_do_not_overlap(self) -> DutyConfig:
        """One player may not hold one duty at one order twice at the same moment.

        A silent overlap would make the answer depend on which entry the loader happened to see
        first, which is the kind of wrongness that never throws (DP-13).
        """
        spells: dict[tuple[int, str, int], list[tuple[dt.date, dt.date]]] = {}
        horizon = dt.date.max
        for entry in self.entries:
            key = (entry.player_code, entry.duty, entry.order)
            window = (entry.known_from, entry.known_until or horizon)
            for start, end in spells.setdefault(key, []):
                if window[0] < end and start < window[1]:
                    raise ValueError(
                        f"duty entries for player_code {entry.player_code} ({entry.duty}, order "
                        f"{entry.order}) overlap: {start}..{end} and {window[0]}..{window[1]}"
                    )
            spells[key].append(window)
        return self


class PenaltyDutyConfig(_Section):
    """What a penalty taker's duty is worth, and how much of it the model is missing (E10-S3).

    **The arithmetic.** A penalty is worth ``conversion`` times the position's goal points, and
    costs ``(1 - conversion)`` times ``penalties_missed`` when it fails; a club is awarded
    ``penalties_per_team_match`` of them per match. Every one of those scoring values comes from the
    rules (Invariant 2); only the two football rates are here.

    **Why the term is not simply that number.** A taker's own fitted per-90 already contains his
    penalties — they are goals, and M3 observes goals. What shrinkage does is pull that rate toward
    a position prior which contains almost none, so the part of his duty the model loses is exactly
    the part shrinkage replaced. The term therefore restores the prior's share of the contribution
    and no more, which is why it is largest for a newly appointed taker with a thin record and
    smallest for a well-observed one — and why it cannot double-count a player's own penalty history
    back onto him.
    """

    penalties_per_team_match: float = Field(
        default=0.13,
        ge=0,
        description=(
            "Penalties a club is awarded per match. About 100 per 380-match season is 0.13 per "
            "team-match. A cross-check against the archive's own missed-penalty counts implies "
            "0.08-0.10, but it reaches that only by assuming a conversion rate and by assuming "
            "FPL's `penalties_missed` counts every failure, which the saved-versus-missed totals "
            "suggest it does not — so the direct figure is used and the discrepancy is recorded "
            "rather than averaged away. Swept on the backtest, not settled here."
        ),
    )
    conversion_rate: float = Field(
        default=0.78,
        ge=0,
        le=1,
        description=(
            "Share of penalties scored. Long-run top-flight conversion sits close to this and "
            "moves little between seasons; it is flat across takers deliberately, because a "
            "per-taker conversion rate fitted on the handful of penalties a player takes in a "
            "season is noise with a name on it."
        ),
    )
    strength: float = Field(
        default=1.0,
        ge=0,
        description=(
            "Multiplier on the whole term. 1.0 is the formulation as argued — restore exactly the "
            "share of the penalty contribution shrinkage removed — and is the value to keep unless "
            "the backtest says otherwise. Above 1 the term starts adding penalty return the "
            "player's own rate already carries, so a swept optimum above 1 is evidence that "
            "something else is being compensated for, not that takers are worth more."
        ),
    )
    confidence_weights: dict[str, float] = Field(
        default_factory=lambda: {"confirmed": 1.0, "likely": 0.6, "unconfirmed": 0.25},
        description=(
            "How much of the term each confidence tier earns. A tier scales rather than gates so a "
            "doubtful entry is worth a little rather than all-or-nothing, and so the owner is not "
            "forced to choose between asserting something they are unsure of and saying nothing. "
            "A tier absent from this mapping contributes zero — an unknown tier is not a licence."
        ),
    )


class GoalkeeperConfig(_Section):
    """How a goalkeeper's saves are estimated when ``gkp_v2`` is on (E10-S4).

    **The finding this answers.** GKP Spearman is 0.04 — a whole position essentially unranked
    ([DL-21]). Three of the five things a goalkeeper scores for already come from M2: the clean
    sheet, the goals conceded and, through them, most of the bonus. The one that does not is
    **saves**, and it is not small — a keeper averages three a match, which is a point, against a
    clean-sheet expectation worth about 1.2. Saves are estimated by the same generic shrunk per-90
    used for every outfield rate stat, which is blind to the thing that actually produces them.

    **What actually produces a save is a shot, and nothing in this project counts shots.** The
    silver model carries no shot column on ``player_gameweek`` at all; ``shots`` exists only on the
    advanced-metrics table, it is a *player's own* shots taken, and no scraped source is enabled by
    default. So opponent shot volume is not available and is not invented (the same call
    [DL-48](../../../docs/planning/00-decision-log.md) made about European rotation). What is
    available is M2's **expected goals conceded** for the fixture, and it is used as the proxy,
    stated rather than substituted silently (DP-09, DP-10): more expected goals against a side
    means more shots faced by its keeper, because the one is computed from the other upstream.

    **Why the generic per-90 is wrong here, as a measurement rather than an argument.** Across the
    archive's regular goalkeepers, saves per 90 have a standard deviation of 0.64 on a mean of 3.1.
    Saves per unit of expected goal conceded have a standard deviation of 0.21 on a mean of 2.1. So
    **half the spread between goalkeepers' save rates is the defence in front of them, not them** —
    and the generic rate hands all of it to the keeper and then applies it identically to every
    fixture. A keeper of a leaky side is priced for saves he will not face when the fixture is kind.

    **Two formulations, because Q-15 asks for two.** Both end by scaling to the fixture; they differ
    in whether the keeper's own level is measured net of the defence he has been playing behind.
    See :attr:`mode`. Neither adds a variance term: the saves component contributes none today, in
    either arm, so the comparison measures one change rather than two ([DL-49]'s own argument).
    """

    mode: Literal["separate", "fixture_weighted"] = Field(
        default="separate",
        description=(
            "Which formulation the candidate runs, and the two halves of Q-15's falsifier. "
            "`separate` is the fully separate model: a keeper's own level is his save rate divided "
            "by the pressure he actually faced, shrunk toward the goalkeeper population, and then "
            "multiplied back by the pressure M2 expects in *this* fixture — so his history enters "
            "only as shot-stopping per unit of defence, and the defence comes from M2. "
            "`fixture_weighted` is the lighter touch: keep the existing shrunk per-90 exactly as "
            "it is and re-weight it by that same fixture factor. The first changes how goalkeepers "
            "rank against each other, the second only how one goalkeeper's weeks rank against each "
            "other, which is why they are different experiments and not two strengths of one."
        ),
    )
    fixture_weight: float = Field(
        default=1.0,
        ge=0,
        le=1,
        description=(
            "How far the fixture's expected goals conceded, as a ratio to the league mean, is "
            "allowed to move the save rate. 0 reproduces today's fixture-blind rate exactly and is "
            "the identity for the `fixture_weighted` arm; 1 applies the ratio in full. Between "
            "them the factor is `1 + w * (ratio - 1)`, which is a straight line through the "
            "average fixture — a shape a reader can disagree with in the terms it is stated in "
            "(DP-10). Damping is not cosmetic: M2's per-fixture expectation is noisier than the "
            "league-average pressure a keeper has actually faced over a season, so applying it in "
            "full is a claim that the fixture is as well measured as the history."
        ),
    )
    prior_minutes: float = Field(
        default=900.0,
        gt=0,
        description=(
            "Minutes at which a keeper's pressure-adjusted rate carries half the weight against "
            "the goalkeeper population's. Deliberately the same arithmetic as `RateModel` and "
            "deliberately its own parameter: ten full matches is what this project already calls "
            "half-known, but the quantity being shrunk here is a *normalised* rate whose "
            "between-keeper spread is half that of the raw one, so it may well deserve a different "
            "number and must be free to take one without moving every outfield rate with it."
        ),
    )


class DiscriminationConfig(_Section):
    """E10's candidate model behaviours, each behind its own flag, all off (DP-08, DL-47).

    E10 attacks the finding [DL-21] recorded: `xp_v1` has the best MAE and the worst top-20
    precision of anything measured, so it avoids error and fails to discriminate — backwards for a
    tool whose whole job is the head of the ranking. Every story in that epic is therefore **new
    model behaviour**, not a delivery bug, which is the case DP-08 exists for: it lands flagged,
    is graded by the backtest against the flag being off, and is promoted only once the E8 §5 bar
    is met — including six live shadow gameweeks, which cannot exist before the season does.

    So each flag here defaults to ``False`` and the shipped configuration leaves it there. With
    every flag off the component chain reproduces its previous output exactly; that is a
    regression test in each story's own test module (`tests/test_minutes_calibration.py`,
    `test_adaptive_shrinkage.py`, `test_duty.py`, `test_goalkeeper.py`), not an assertion made
    here — each asserts flag-off equivalence for its own component, since a single shared test
    would have to import every story's internals into one file for no benefit.

    **The naming scheme, for the stories still to land.** One ``bool`` per promotable story, named
    for the story (`minutes_v2` is E10-S1; `adaptive_shrinkage`, `duty_term` and `gkp_v2` follow for
    S2 to S4). Tunables a flag needs live in a sibling section named for the *component* they tune,
    not for the story — so S2's would be `shrinkage`, S4's `goalkeeper`, and none of them collides
    with the flag beside it.
    """

    minutes_v2: bool = Field(
        default=False,
        description=(
            "Whether M1 applies the E10-S1 rotation, injury-return and availability-split "
            "adjustments. Off until the backtest measures it (DP-08, DP-12, DL-47). The toggle is "
            "what makes the before/after a single configuration change rather than a diff."
        ),
    )
    minutes: MinutesV2Config = MinutesV2Config()

    adaptive_shrinkage: bool = Field(
        default=False,
        description=(
            "Whether M3-M7's shrinkage weight is a function of evidence rather than a constant "
            "(E10-S2). Off until the E8 §5 bar is met, which needs six live shadow gameweeks that "
            "cannot exist before the season does (DP-08, DL-47). The backtest evidence for it is "
            "in DL-49; what is missing is the live half, not the measured half."
        ),
    )
    shrinkage: AdaptiveShrinkageConfig = AdaptiveShrinkageConfig()

    duty_term: bool = Field(
        default=False,
        description=(
            "Whether penalty duty is an explicit additive term at the horizon scorer (E10-S3), "
            "read from the committed reference table at `forecast.duty`. Off until the E8 §5 bar "
            "is met (DP-08, DL-47, DL-50). The flag decides whether the table reaches the model at "
            "all: with it off the component chain never sees a duty assignment, which is what "
            "makes the before/after one configuration change rather than a diff."
        ),
    )
    penalties: PenaltyDutyConfig = PenaltyDutyConfig()

    gkp_v2: bool = Field(
        default=False,
        description=(
            "Whether a goalkeeper's saves are estimated from the pressure M2 expects in his "
            "fixture rather than from a fixture-blind shrunk per-90 (E10-S4). Off until the E8 §5 "
            "bar is met (DP-08, DL-47). The flag decides whether the goalkeeper model is fitted at "
            "all: with it off nothing in the chain knows the formulation exists, which is what "
            "makes the before/after one configuration change rather than a diff."
        ),
    )
    goalkeeper: GoalkeeperConfig = GoalkeeperConfig()


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
    congestion_window_days: int = Field(
        default=14,
        gt=0,
        description=(
            "Days before the deadline over which fixture density is counted (E10-S1). A fortnight "
            "holds two matches at a normal cadence and four when a club is playing midweek, so it "
            "separates a congested run from an ordinary one without being so long that a single "
            "postponement dominates it. Counted on the player's own rows, which is the club's "
            "calendar seen from where the model already stands — no team join, nothing new to "
            "keep in step."
        ),
    )
    return_window_matches: int = Field(
        default=4,
        gt=0,
        description=(
            "Matches examined for a recent absence (E10-S1). Four is roughly a month: long enough "
            "that a rested week is not read as an injury, short enough that a spell finished two "
            "months ago no longer counts as a return."
        ),
    )
    prior_season: PriorSeasonConfig = PriorSeasonConfig()


class PublishedModelConfig(_Section):
    """Which expected-points model reaches the app, and when it became the default (DL-46).

    The model *names* are not tunables — they are facts about which code exists — so neither
    ``xp_v1`` nor ``xp_v0`` appears here as a switchable value. DL-46 is explicit that there is no
    `enabled` flag gating ``xp_v1`` behind a promotion step: closing D-25 is the bug fix DP-08 names
    as its exception, not the introduction of an unproven model.

    What *is* tunable is the boundary between the two, and the date a reader of the model card needs
    in order to know which model produced the numbers in front of them (DP-09, DP-15).
    """

    default_since: dt.date = Field(
        default=dt.date(2026, 8, 17),
        description=(
            "The date `xp_v1` became the model the pipeline publishes, printed on every model "
            "card. Recorded rather than computed: taking today's date would have every run claim "
            "the model was promoted this morning, which is the opposite of provenance. Update it "
            "only when the published model actually changes, and record why in the decision log."
        ),
    )
    cold_start_minimum_gameweeks: int = Field(
        default=4,
        ge=1,
        description=(
            "Completed gameweeks of current-season history below which the run falls back to the "
            "cold-start `xp_v0`. Four, to match `backtest.minimum_training_matches`: the "
            "walk-forward harness refuses to *score* a deadline with less history than this, and "
            "publishing a model at a point its own grader declines to grade is precisely the "
            "shipped-is-not-graded mismatch E9 exists to close. Below it, a fitted component chain "
            "is reporting its priors with a fitted model's confidence, and `xp_v0`'s priors are "
            "built from several seasons rather than from three matches."
        ),
    )


class ForecastConfig(_Section):
    """The expected-points models. Every tunable is here; none is in code (DP-06).

    Most of what follows is ``xp_v0``'s — the cold-start model, retained as the documented fallback.
    ``published`` decides which of the two the app actually reads.
    """

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
    discrimination: DiscriminationConfig = DiscriminationConfig()
    duty: DutyConfig = DutyConfig()
    """The committed penalty/set-piece duty table (E12-S2). Reference knowledge, not a tunable, and
    it sits here rather than at the top level because the forecast is its only consumer — a section
    nothing outside one package reads is a section that belongs to that package."""

    published: PublishedModelConfig = PublishedModelConfig()


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


class MonolithConfig(_Section):
    """The shadow monolith's hyperparameters (E10-S5, DL-53). **Not a promotion candidate.**

    A gradient-boosted regressor fitted on the same feature store the component chain reads, scored
    by the same harness on the same folds, and reported alongside B0 and the model-free benchmark.
    Its only job is to answer one question every run: *how much accuracy is the chain's
    explainability costing?* If the gap at the head is small, DP-10's preference for the formulation
    you can argue with is free; if it is large, that is a trade the project is making and DP-10 says
    it must be an explicit decision rather than an assumption.

    **There is deliberately no flag here**, and its absence is the design. Every other E10 story
    ships behind a `discrimination` bool that a future promotion review can flip
    ([DL-47](../../../docs/planning/00-decision-log.md#dl-47)); this one has nothing to flip because
    the epic is explicit that it is "never promoted over the chain without an explicit DP-10
    decision". It always runs and always reports.

    **And it lives in `BacktestConfig` rather than `ForecastConfig` for the same reason.** Nothing
    on the forecast, optimise or publish path reads this section, so there is no configuration by
    which the monolith could reach a published ranking — the guarantee is structural rather than a
    default somebody could change.

    The values below are ordinary, unswept defaults, and that is the honest setting for a *ceiling*
    measurement: a monolith tuned against the same folds it is scored on would be reporting its own
    overfitting as the chain's deficit. If the gap ever matters enough to argue about, the answer is
    a held-out tuning season, not a sweep of these numbers (DP-12).
    """

    learning_rate: float = Field(
        default=0.05,
        gt=0,
        le=1,
        description=(
            "Shrinkage applied to each boosting stage. Low and slow with many iterations rather "
            "than fast and few, because the target is the noisiest quantity in the project and a "
            "large step size fits a gameweek's luck."
        ),
    )
    max_iterations: int = Field(
        default=400,
        gt=0,
        description=(
            "Boosting stages. Fixed rather than early-stopped: early stopping holds out a random "
            "slice of the training window, which in a walk-forward harness means a different "
            "amount of evidence per fold and a benchmark whose capacity drifts with the calendar."
        ),
    )
    max_leaf_nodes: int = Field(
        default=31,
        gt=1,
        description=(
            "Tree size, and so the highest order of interaction the monolith can represent. The "
            "library default. Raising it is how a ceiling measurement quietly becomes a memoriser."
        ),
    )
    min_samples_leaf: int = Field(
        default=50,
        gt=0,
        description=(
            "Rows required in a leaf. Deliberately well above the library default of 20: a leaf "
            "holding twenty player-gameweeks of a target whose standard deviation is around three "
            "points is a leaf fitted to noise."
        ),
    )
    l2_regularisation: float = Field(
        default=1.0,
        ge=0,
        description=(
            "L2 penalty on leaf values. Non-zero because the head of the ranking is exactly where "
            "leaves are thinnest, and an unpenalised leaf there is a confident extrapolation from "
            "a handful of hauls."
        ),
    )
    random_seed: int = Field(
        default=7,
        description=(
            "Seed for the binning subsample. Fixed so two runs on one archive report one gap "
            "(DP-11); the fit is otherwise deterministic, so this is the only channel through "
            "which it could vary."
        ),
    )
    minimum_training_rows: int = Field(
        default=200,
        gt=0,
        description=(
            "Below this many training rows, boosting is fitting noise. The monolith degrades to "
            "the training mean and says so on its card rather than reporting a confident number "
            "from nothing (DP-15) — early folds and any thin-history test fixture take this path."
        ),
    )


class BacktestConfig(_Section):
    """Walk-forward replay. The measurement that makes every later change evaluable (FR-37)."""

    chip_replay: ChipReplayConfig = ChipReplayConfig()
    monolith: MonolithConfig = MonolithConfig()
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
    fixture_difficulty_band_ratio: float = Field(
        default=1.15,
        gt=1,
        description=(
            "Where the fixture-difficulty breakdown cuts (E9-S2). A fixture is `hard` when M2 "
            "expects the opposition to score at least this multiple of what it expects the "
            "player's own club to score, `easy` at the reciprocal, and `average` between. One "
            "number rather than two edges, because the two are the same departure from even in "
            "opposite directions and configuring them separately invites them to disagree. Set "
            "at 1.15 because home advantage alone is worth roughly 1.25 either way, so a wider "
            "cut would put every neutral fixture in one band and measure nothing; narrower puts "
            "ordinary fixtures at the extremes. This bands the *report*, never a prediction — "
            "changing it cannot change a forecast, only how the evidence is sliced."
        ),
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


class RetentionConfig(_Section):
    """How long CI keeps the rolling bronze snapshot store (E7-S4, R-13).

    Applies only to the ``data`` branch's rolling bronze window, rebuilt from scratch and
    force-pushed every run — see ``pipeline/scripts/retention.py``. The ``snapshots`` branch is a
    separate, append-only evidence trail and is never pruned by this setting (NFR-06).
    """

    bronze_days: int = Field(
        default=30,
        gt=0,
        description=(
            "Rolling window of bronze snapshots kept on the `data` branch. Wide enough to debug "
            "the recent past (a bad forecast traced back a couple of weeks), narrow enough that "
            "the orphan-branch rebuild stays a few hundred MB rather than growing without bound "
            "(architecture §7.3). Not an archive — that is what the `snapshots` branch is for."
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


class HealthArtefactConfig(_Section):
    """How much run history the data health page carries (DL-41, E7-S6)."""

    history_runs: int = Field(
        default=30,
        ge=0,
        le=500,
        description=(
            "How many recent runs the rolling metrics series covers, newest last. Each point is a "
            "few hundred bytes, so this is a legibility budget rather than a payload one: a chart "
            "of the last thirty runs shows a trend, and one of the last three hundred shows a "
            "smear. Thirty is roughly a fortnight at the E7-S2 cadence — long enough to see a "
            "solve time drifting, short enough that a single bad run is still visible on it. "
            "0 disables the series, and the page then says there is no history rather than "
            "drawing an empty axis."
        ),
    )


class PublishConfig(_Section):
    """Tunables that shape published artefacts rather than the models behind them."""

    history: HistoryArtefactConfig = HistoryArtefactConfig()
    fixtures: FixtureTickerConfig = FixtureTickerConfig()
    health: HealthArtefactConfig = HealthArtefactConfig()


class ScheduleConfig(_Section):
    """When the automated workflows are allowed to do work (E7-S1, E7-S2).

    GitHub Actions cron is static and always UTC, so a cadence that depends on *the deadline* cannot
    be expressed in the schedule itself. Each workflow therefore fires on a fixed, frequent cron and
    asks :mod:`fpl_dof.week.schedule` whether this particular firing should proceed. The tunables
    live here rather than inline in YAML so they are named, defaulted and justified in one place
    (DP-06), and so the decision is unit-testable without a runner.

    Everything is UTC. The deadline is stored in UTC (DL-11) and Actions cron is UTC, so no
    conversion happens anywhere on this path — which is the point, because the UK/AEST offset moves
    twice a season and not on the same dates (CON-11).
    """

    fast_ingest_boundary_hours: tuple[int, ...] = Field(
        default=(0, 4, 8, 12, 16, 20),
        description=(
            "UTC hours at which the fast ingest runs in its base four-hourly cadence. Whole hours "
            "because an hourly cron is the finest granularity the guard can meaningfully test, and "
            "these six are simply 24 divided by four, starting at midnight."
        ),
    )
    fast_ingest_deadline_window_hours: float = Field(
        default=24.0,
        gt=0,
        description=(
            "Inside this many hours of the next deadline the fast ingest runs every hour instead "
            "of every four. Prices, availability and ownership move fastest in the last day, and "
            "those are exactly the fields NFR-05 puts a freshness bound on."
        ),
    )
    pipeline_offsets_minutes: tuple[int, ...] = Field(
        default=(180, 45),
        description=(
            "Minutes before the deadline at which the pipeline produces a recommendation: T-3h "
            "for a considered answer while there is still time to act on it, and T-45m as the "
            "last automatic refresh before the R-09 freeze."
        ),
    )
    pipeline_cron_interval_minutes: int = Field(
        default=15,
        gt=0,
        description=(
            "How often pipeline.yml's guard job fires. It must match the cron in that workflow — "
            "it is declared here so the tolerance below can be validated against it, rather than "
            "the two drifting apart silently."
        ),
    )
    pipeline_window_tolerance_minutes: float = Field(
        default=20.0,
        gt=0,
        description=(
            "How much EARLIER than an offset a firing still counts. The window is "
            "[offset, offset + tolerance] and never extends later, so the T-45m trigger can only "
            "ever fire at or before T-45m (R-09). It must exceed the cron interval, or an offset "
            "could fall between two firings and be missed entirely."
        ),
    )
    deadline_freeze_minutes: float = Field(
        default=45.0,
        ge=0,
        description=(
            "Nothing that produces a recommendation is scheduled inside this many minutes of a "
            "deadline (R-09). Scheduled runs are best-effort and can be delayed under platform "
            "load; the deadline is not. Manual dispatch remains the fallback."
        ),
    )

    @model_validator(mode="after")
    def _windows_are_reachable_and_outside_the_freeze(self) -> ScheduleConfig:
        if not self.pipeline_offsets_minutes:
            raise ValueError("schedule.pipeline_offsets_minutes must name at least one offset")
        if self.pipeline_window_tolerance_minutes <= self.pipeline_cron_interval_minutes:
            raise ValueError(
                "schedule.pipeline_window_tolerance_minutes "
                f"({self.pipeline_window_tolerance_minutes}) must exceed "
                f"pipeline_cron_interval_minutes ({self.pipeline_cron_interval_minutes}), or a "
                "pre-deadline window can fall between two cron firings and never be entered"
            )
        earliest = min(self.pipeline_offsets_minutes)
        if earliest < self.deadline_freeze_minutes:
            raise ValueError(
                f"schedule.pipeline_offsets_minutes has an offset at T-{earliest}m, inside the "
                f"{self.deadline_freeze_minutes}-minute deadline freeze (R-09)"
            )
        return self


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
    retention: RetentionConfig = RetentionConfig()
    backtest: BacktestConfig = BacktestConfig()
    decision: DecisionConfig = DecisionConfig()
    publish: PublishConfig = PublishConfig()
    schedule: ScheduleConfig = ScheduleConfig()
