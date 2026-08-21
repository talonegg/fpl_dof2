"""The component models, M1 through M8.

Each is a small, arguable object: it fits from history, predicts, and can say what it learned
(DP-10). None is a black box, and that is a deliberate trade — a gradient-boosted ensemble would
very likely score a little better and would remove the ability to look at a number and say why it
is what it is, which is the whole point of the transparency principles.

The models, and what each is for:

``M1`` minutes
    A distribution over ``{0, 1-59, 60+}``, not a point estimate. **The largest single source of
    forecast error**, so calibration here beats sophistication anywhere else: every other component
    is multiplied by it.

``M2`` team strength
    Attack and defence ratings, time-decayed, estimated from goals and expected goals. Feeds
    expected goals for and against per fixture.

``M3-M7`` player components
    Goal involvement, defensive contribution, clean sheets, saves, cards. Rates per 90, shrunk
    toward a position prior by how much evidence there is.

``M8`` bonus
    Expected BPS from expected actions, then the probability of finishing top three **within that
    match**. Structural rather than learned, because *no* season used the 2026/27 BPS matrix —
    training on historical bonus would bake in a scoring regime that no longer exists.

**M4 deserves its disproportionate attention.** Defensive Contribution is rate-driven and far more
stable week to week than goal involvement — the best signal-to-noise ratio in the model, and the
place where it most easily beats intuition, because most managers still price players as though the
component did not exist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fpl_dof.config.models import (
    AdaptiveShrinkageConfig,
    ForecastConfig,
    GoalkeeperConfig,
    MinutesV2Config,
)
from fpl_dof.forecast.duty import DutyTable
from fpl_dof.forecast.features import absence_feature_name, congestion_feature_name
from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import GameRules, Position

log = get_logger(__name__)

MINUTES_BANDS = ("none", "short", "long")


def _row_value(row: pd.Series, column: str) -> float:
    """A float from a feature row, or NaN when the column is unnamed, absent or null.

    NaN rather than a zero throughout: "this run does not compute that feature" and "the player
    played none of the window" are different claims, and only one of them should move a forecast.
    """
    if not column:
        return float("nan")
    value = row.get(column)
    if value is None or pd.isna(value):
        return float("nan")
    return float(value)


@dataclass(frozen=True, slots=True)
class MinutesDistribution:
    """P(no appearance), P(1-59), P(60+). Sums to one."""

    none: float
    short: float
    long: float

    @property
    def plays(self) -> float:
        return self.short + self.long

    @property
    def expected_minutes(self) -> float:
        # Midpoint of the short band and a typical full-match figure. Deliberately not 90: a
        # player who starts is routinely substituted.
        return self.short * 30.0 + self.long * 82.0


@dataclass
class MinutesModel:
    """M1. Beats the E0 status-flag haircut by using observed appearances rather than a guess.

    Fitted per position and per *recent-appearance band*, which is the feature that actually
    separates a nailed starter from a rotation option. The status flag is applied afterwards as a
    multiplier, because it is news rather than history and the two should not be conflated.
    """

    by_group: dict[tuple[str, int], tuple[float, float, float]] = field(default_factory=dict)
    population: tuple[float, float, float] = (0.4, 0.2, 0.4)
    appearance_bands: tuple[float, ...] = (0.25, 0.6, 0.85)

    v2: MinutesV2Config | None = None
    """E10-S1's candidate behaviour, or ``None`` for the graded default chain (DP-08, DL-47).

    ``None`` rather than a bool so the object cannot be half-configured: either the tunables are
    present and the adjustments run, or neither is true. With ``None`` this class computes exactly
    what it computed before E10-S1 existed, which is the regression guarantee the flag rests on."""

    congestion_column: str = ""
    absence_column: str = ""
    """Where :meth:`predict_row` finds the two v2 signals. Held here rather than looked up by each
    caller, because the names encode the configured windows and two callers spelling them
    separately is how the live path and the harness start reading different features."""

    def band(self, appearance_rate: float) -> int:
        if math.isnan(appearance_rate):
            return 0
        return int(sum(1 for edge in self.appearance_bands if appearance_rate >= edge))

    def fit(self, history: pd.DataFrame, long_play_minutes: int) -> MinutesModel:
        """Learn the three probabilities for each (position, appearance band).

        Training rows are (player, gameweek) observations with the appearance rate computed from
        *earlier* matches only — the caller supplies that; this model never looks at kickoff times
        itself, which keeps the leakage question in one place.
        """
        if history.empty:
            return self
        frame = history.dropna(subset=["position", "minutes"]).copy()
        # The 60-minute threshold is a scoring rule, so it arrives as an argument rather than
        # being written here (Invariant 2).
        frame["_band"] = frame["appearance_rate"].fillna(0.0).map(self.band)
        frame["_outcome"] = np.select(
            [frame["minutes"] <= 0, frame["minutes"] < long_play_minutes],
            ["none", "short"],
            default="long",
        )

        counts = frame.groupby(["position", "_band", "_outcome"]).size().unstack(fill_value=0)
        for band_name in MINUTES_BANDS:
            if band_name not in counts.columns:
                counts[band_name] = 0
        counts["_total"] = counts[list(MINUTES_BANDS)].sum(axis=1)
        for key, row in counts.iterrows():
            position, band = str(key[0]), as_int(key[1])  # type: ignore[index]
            total = as_float(row["_total"])
            if total < 10:
                # Too thin to be a rate. Left out so the population prior is used instead of a
                # confident-looking figure derived from four observations.
                continue
            self.by_group[(position, band)] = (
                as_float(row["none"]) / total,
                as_float(row["short"]) / total,
                as_float(row["long"]) / total,
            )

        overall = frame["_outcome"].value_counts(normalize=True)
        self.population = (
            float(overall.get("none", 0.34)),
            float(overall.get("short", 0.16)),
            float(overall.get("long", 0.5)),
        )
        return self

    def predict(
        self,
        position: str,
        appearance_rate: float,
        *,
        status_multiplier: float = 1.0,
        matches_in_window: float = float("nan"),
        recent_absence_share: float = float("nan"),
    ) -> MinutesDistribution:
        """The distribution, with availability news applied as a multiplier on playing at all.

        News is applied here rather than folded into the fitted rates because it is information of
        a completely different kind: history says what usually happens, the status flag says what
        is known about this week. Mixing them would make the model unable to react to an injury.

        ``matches_in_window`` and ``recent_absence_share`` are E10-S1's two signals and are read
        **only** when :attr:`v2` is set. Passing them with the flag off changes nothing, which is
        deliberate: the caller does not have to know which behaviour is configured.
        """
        none, short, long = self.by_group.get(
            (position, self.band(appearance_rate)), self.population
        )
        v2 = self.v2
        if v2 is not None:
            none, short, long = self._adjusted(
                none,
                short,
                long,
                v2,
                appearance_rate=appearance_rate,
                matches_in_window=matches_in_window,
                recent_absence_share=recent_absence_share,
            )
        if status_multiplier < 1.0:
            scale = max(0.0, min(1.0, status_multiplier))
            if v2 is None:
                short, long = short * scale, long * scale
            else:
                # P(play) stays exactly where the flag puts it; only its split moves. A doubtful
                # player who does feature is likelier to be eased in than to start and finish, and
                # scaling both states equally prices him as a full starter half the time.
                plays = (short + long) * scale
                penalty = 1.0 - v2.availability_start_penalty * (1.0 - scale)
                long = max(0.0, long * scale * penalty)
                short = max(0.0, plays - long)
            none = 1.0 - short - long
        total = none + short + long
        if total <= 0:
            return MinutesDistribution(1.0, 0.0, 0.0)
        return MinutesDistribution(none / total, short / total, long / total)

    def predict_row(
        self, row: pd.Series, position: str, *, status_multiplier: float = 1.0
    ) -> MinutesDistribution:
        """:meth:`predict`, given a feature row rather than loose floats.

        The call every scorer should use. It exists so that "which columns carry the minutes
        signals" is answered once, by the fitted model that knows how it was configured, rather
        than at each of the three call sites that would otherwise have to agree about it.
        """
        return self.predict(
            position,
            float(row.get("appearance_rate") or 0.0),
            status_multiplier=status_multiplier,
            matches_in_window=_row_value(row, self.congestion_column),
            recent_absence_share=_row_value(row, self.absence_column),
        )

    def _adjusted(
        self,
        none: float,
        short: float,
        long: float,
        v2: MinutesV2Config,
        *,
        appearance_rate: float,
        matches_in_window: float,
        recent_absence_share: float,
    ) -> tuple[float, float, float]:
        """E10-S1's two history-based adjustments, as one multiplier on the 60+ state.

        Both push the same way and are therefore composed rather than added: a congested run and a
        return from a spell out are separate reasons to doubt a full ninety, and a player with both
        deserves both doubts. Neither can move P(play), because neither is evidence of
        unavailability — they say how long he stays on, not whether he is picked at all.
        """
        scale = 1.0
        if not math.isnan(matches_in_window):
            excess = max(0.0, matches_in_window - v2.congestion_baseline_matches)
            scale *= max(0.0, 1.0 - v2.congestion_rotation_strength * excess)
        if (
            not math.isnan(recent_absence_share)
            and not math.isnan(appearance_rate)
            and appearance_rate >= v2.return_established_appearance_rate
        ):
            scale *= max(0.0, 1.0 - v2.return_ramp_strength * recent_absence_share)
        if scale >= 1.0:
            return none, short, long

        # The mass leaving the 60+ state is split across the other two in the proportion the
        # fitted population already exhibits — a rotated player is sometimes a cameo and sometimes
        # an unused substitute, and the population is the only evidence to hand about which.
        freed = long * (1.0 - scale)
        weight_none, weight_short = self.population[0], self.population[1]
        denominator = weight_none + weight_short
        if denominator <= 0:
            return none, short + freed, long * scale
        return (
            none + freed * weight_none / denominator,
            short + freed * weight_short / denominator,
            long * scale,
        )

    def describe(self) -> dict[str, object]:
        return {
            "groups": len(self.by_group),
            "population": {
                name: round(value, 4)
                for name, value in zip(MINUTES_BANDS, self.population, strict=True)
            },
            "appearance_bands": list(self.appearance_bands),
            # Named even when absent, so a model card never has to imply a candidate from silence.
            "minutes_v2": None if self.v2 is None else self.v2.model_dump(),
        }


@dataclass
class TeamStrengthModel:
    """M2. Attack and defence ratings, estimated from goals scored and conceded.

    Ratings are multiplicative around 1.0, so a fixture's expected goals is
    ``league_mean x attack(team) x defence(opponent) x home_advantage``. That form is chosen over an
    additive one because it composes correctly: a strong attack against a weak defence should
    multiply, not add, and the difference matters most in exactly the fixtures people plan around.
    """

    attack: dict[int, float] = field(default_factory=dict)
    defence: dict[int, float] = field(default_factory=dict)
    league_mean_goals: float = 1.4
    home_advantage: float = 1.12
    half_life_matches: float = 20.0

    def fit(self, matches: pd.DataFrame, *, current_season: str | None = None) -> TeamStrengthModel:
        """``matches``: one row per team per fixture, with goals for and against.

        Time-decayed by an exponential half-life, because a promoted side's September is weak
        evidence about their April, and a manager change makes last season nearly irrelevant.

        ``current_season``, when given, is the guard D-26 found missing (DL-52/DL-54): ``team_id``
        means the archive's stable club *code* in a prior season and the live feed's *season-local*
        id in the current one — two spaces that happen to share a column name. Grouping by
        ``team_id`` alone would silently blend two different clubs' goals wherever the numbers
        coincide. Pooling *within* the archive's own prior seasons is fine and intended — the code
        is stable across them by construction — so this only refuses the one combination that
        isn't: the current season sharing a frame with any other.
        """
        if matches.empty:
            return self
        if (
            current_season is not None
            and "season" in matches.columns
            and current_season in set(matches["season"])
            and set(matches["season"]) != {current_season}
        ):
            raise ValueError(
                f"team strength fit was handed {sorted(set(matches['season']))!r} alongside the "
                f"current season {current_season!r}: the current season's team_id is a "
                "season-local id and every other season's is the archive's stable club code "
                "(D-26) — pooling them silently attributes one club's goals to another wherever "
                "the numbers coincide. Fit the current season on its own (see forecast/live.py's "
                "this_season split), or fit the other seasons without it."
            )
        frame = matches.dropna(subset=["team_id", "goals_for", "goals_against"]).copy()
        if frame.empty:
            return self

        frame = frame.sort_values("kickoff_time")
        newest = frame["kickoff_time"].max()
        age_days = (newest - frame["kickoff_time"]).dt.total_seconds() / 86400.0
        # Half-life expressed in matches, converted through a nominal 7-day week.
        frame["_weight"] = 0.5 ** (age_days / (self.half_life_matches * 7.0))

        weighted_total = float((frame["goals_for"] * frame["_weight"]).sum())
        weight_total = float(frame["_weight"].sum())
        self.league_mean_goals = weighted_total / weight_total if weight_total > 0 else 1.4

        for team_id, group in frame.groupby("team_id"):
            weight = float(group["_weight"].sum())
            if weight <= 0:
                continue
            scored = float((group["goals_for"] * group["_weight"]).sum()) / weight
            conceded = float((group["goals_against"] * group["_weight"]).sum()) / weight
            mean = self.league_mean_goals or 1.0
            self.attack[as_int(team_id)] = scored / mean if mean else 1.0
            self.defence[as_int(team_id)] = conceded / mean if mean else 1.0
        return self

    def expected_goals(self, team_id: int, opponent_id: int, *, at_home: bool) -> float:
        attack = self.attack.get(int(team_id), 1.0)
        weakness = self.defence.get(int(opponent_id), 1.0)
        advantage = self.home_advantage if at_home else 1.0 / self.home_advantage
        return max(0.05, self.league_mean_goals * attack * weakness * advantage)

    def clean_sheet_probability(self, team_id: int, opponent_id: int, *, at_home: bool) -> float:
        """P(concede zero), from a Poisson on the opponent's expected goals.

        Poisson rather than a fitted rate because clean sheets are a *threshold* on a count, and
        modelling the count and then applying the threshold uses far more of the data than counting
        past clean sheets does.
        """
        conceded = self.expected_goals(opponent_id, team_id, at_home=not at_home)
        return float(math.exp(-conceded))

    def fixture_difficulty_ratio(self, team_id: int, opponent_id: int, *, at_home: bool) -> float:
        """How hard this fixture looks: goals expected against, over goals expected for.

        One scalar rather than two, because a breakdown split on attack and defence difficulty at
        once is a table nobody reads. **1.0 is a fixture the ratings and the venue make exactly
        even**, above 1 is harder, and the scale is multiplicative in the same way the ratings are,
        so halving and doubling are equal and opposite.

        Both halves come from :meth:`expected_goals`, which is the point: the number used to *band*
        a fixture cannot drift away from the ratings the forecast was actually scored under.
        """
        scored = self.expected_goals(team_id, opponent_id, at_home=at_home)
        conceded = self.expected_goals(opponent_id, team_id, at_home=not at_home)
        return conceded / scored if scored > 0 else float("nan")

    def describe(self) -> dict[str, object]:
        return {
            "teams": len(self.attack),
            "league_mean_goals": round(self.league_mean_goals, 4),
            "home_advantage": self.home_advantage,
            "half_life_matches": self.half_life_matches,
        }


@dataclass
class RateModel:
    """M3-M7. A per-90 rate, shrunk toward its position prior by how much evidence exists.

    One class for five components because they are the same estimator with a different column. A
    separate class each would produce five copies of the shrinkage arithmetic and, eventually, five
    slightly different versions of it.
    """

    column: str
    prior_by_position: dict[str, float] = field(default_factory=dict)
    population_prior: float = 0.0
    prior_minutes: float = 900.0
    prior_season_minutes: float = 900.0
    """Prior-season minutes at which a player's own prior-season ratio carries half the weight."""

    adaptive: AdaptiveShrinkageConfig | None = None
    """E10-S2's evidence-adaptive prior weight, or ``None`` for the graded default chain.

    ``None`` rather than a bool, for the same reason :attr:`MinutesModel.v2` is: either the
    tunables are present and the behaviour runs, or neither is true, and the object cannot be left
    half-configured. With ``None`` :meth:`predict` computes exactly what it computed before E10-S2
    existed, which is the regression guarantee the flag rests on (DP-08, DL-47)."""

    def fit(self, history: pd.DataFrame) -> RateModel:
        if history.empty or self.column not in history.columns:
            return self
        frame = history.dropna(subset=[self.column, "minutes", "position"])
        frame = frame[frame["minutes"] > 0]
        if frame.empty:
            return self

        for position, group in frame.groupby("position"):
            minutes = float(group["minutes"].sum())
            if minutes <= 0:
                continue
            self.prior_by_position[str(position)] = (
                float(pd.to_numeric(group[self.column], errors="coerce").sum()) / minutes * 90.0
            )
        total_minutes = float(frame["minutes"].sum())
        if total_minutes > 0:
            self.population_prior = (
                float(pd.to_numeric(frame[self.column], errors="coerce").sum())
                / total_minutes
                * 90.0
            )
        return self

    def predict(
        self,
        position: str,
        observed_rate: float,
        minutes_observed: float,
        *,
        prior_ratio: float = float("nan"),
        prior_ratio_minutes: float = 0.0,
    ) -> float:
        """Shrink the player's own rate toward the position prior.

        The weight is ``minutes / (minutes + prior_minutes)``, so a player with the prior's worth of
        evidence is weighted half on themselves. A player with none is the prior exactly, which is
        the right answer for a new signing and the wrong answer to invent from three appearances.

        ``prior_ratio`` moves *the prior itself*: a completed prior season saying this player did
        the thing twice as often as his position does raises what we expect of him before this
        season's evidence arrives, and fades out as that evidence accumulates. It is deliberately
        the same shrinkage arithmetic rather than a second mechanism — a player with no prior
        season lands on the position prior exactly, which is what happens today.
        """
        prior = self.prior_by_position.get(position, self.population_prior)
        prior *= self._prior_scale(prior_ratio, prior_ratio_minutes)
        if math.isnan(observed_rate) or minutes_observed <= 0:
            return prior
        prior_weight = self.prior_minutes * self._evidence_scale(minutes_observed)
        weight = minutes_observed / (minutes_observed + prior_weight)
        return weight * observed_rate + (1.0 - weight) * prior

    def prior_share(self, minutes_observed: float) -> float:
        """How much of this prediction comes from the position prior rather than from the player.

        ``1 - weight``, the other half of :meth:`predict`'s blend, exposed because the E10-S3 duty
        term needs exactly it: a taker's own fitted rate already contains his penalties, so the part
        of his duty the model has lost is the part shrinkage replaced with a prior that contains
        almost none. Returning it here rather than recomputing the weight at the scorer is what
        stops two versions of the shrinkage arithmetic existing.

        One for a player with no evidence, which is the honest answer — his prediction *is* the
        prior — and the case where a duty term is worth the most.
        """
        if minutes_observed <= 0:
            return 1.0
        prior_weight = self.prior_minutes * self._evidence_scale(minutes_observed)
        return float(prior_weight / (minutes_observed + prior_weight))

    def _evidence_scale(self, minutes_observed: float) -> float:
        """How much of the flat prior weight this much evidence is allowed to remove (E10-S2).

        One with the flag off, and one below the onset with it on, so the change is confined to the
        players it is *about*: shrinkage exists to stop three appearances being read as a rate, and
        nothing here relaxes that. Above the onset it ramps linearly down to ``1 - strength``.

        Not a smooth curve, because the shape is a claim about players and a reader has to be able
        to disagree with it in the terms it is stated in (DP-10). "Nothing changes below 600
        minutes, and by 1800 the prior counts for 40% of what it did" is a sentence you can argue
        with; a logistic in two fitted coefficients is not.
        """
        adaptive = self.adaptive
        if adaptive is None:
            return 1.0
        span = adaptive.full_minutes - adaptive.onset_minutes
        if span <= 0:
            # A degenerate range is a step at the threshold rather than a division by zero, and a
            # threshold is what the configuration was asking for by collapsing the two ends.
            ramp = 1.0 if minutes_observed >= adaptive.full_minutes else 0.0
        else:
            ramp = min(1.0, max(0.0, (minutes_observed - adaptive.onset_minutes) / span))
        return 1.0 - adaptive.strength * ramp

    def _prior_scale(self, ratio: float, minutes: float) -> float:
        """How far the position prior moves toward a player's prior-season ratio.

        One at both ends of the evidence range: no prior season means no adjustment, and a thin one
        means an almost neutral adjustment. Nothing here can turn a prior negative or to zero.
        """
        if math.isnan(ratio) or ratio <= 0 or minutes <= 0:
            return 1.0
        weight = minutes / (minutes + self.prior_season_minutes)
        return weight * ratio + (1.0 - weight)

    def describe(self) -> dict[str, object]:
        return {
            "column": self.column,
            "priors_per_90": {k: round(v, 4) for k, v in self.prior_by_position.items()},
            "population_prior": round(self.population_prior, 4),
            "prior_minutes": self.prior_minutes,
            "prior_season_minutes": self.prior_season_minutes,
            # Named even when absent, so a model card never has to imply a candidate from silence.
            "adaptive_shrinkage": None if self.adaptive is None else self.adaptive.model_dump(),
        }


@dataclass
class GoalkeeperSavesModel:
    """E10-S4's candidate: saves from the pressure M2 expects, not from a fixture-blind per-90.

    Fitted only when ``discrimination.gkp_v2`` is on, and absent otherwise, so with the flag off
    nothing in the chain knows this exists (DP-08, DL-47).

    **What it replaces and why.** Everything else a goalkeeper scores for already runs through M2 —
    the clean sheet is a Poisson on the opponent's expected goals, the concession penalty is that
    same expectation. Saves alone came from :class:`RateModel`, the generic estimator used for every
    outfield rate, which knows only what the keeper's own last six matches produced and applies it
    identically to a trip to the champions and a home game against the bottom club. That is the
    wrong shape for the statistic: **a save is a shot faced, and shots faced are the defence in
    front of him.**

    **Shots are not available and are not invented** — nothing on ``player_gameweek`` counts them.
    Expected goals conceded stands in, and is named as a proxy rather than passed off as the thing
    (DP-09): it is computed from shots upstream, so more of it means more shots faced, and the
    substitution is an argument a reader can reject on its own terms (DP-10).

    **The formulation, in one sentence.** A keeper's save rate is his shot-stopping volume times the
    defence he plays behind; divide out the defence he *has* played behind, shrink what is left
    toward the goalkeeper population, and multiply back the defence M2 says he will face this week.

    Both quantities enter as ratios to a league mean — his historical pressure against the keeper
    population's, the fixture's expectation against M2's own ``league_mean_goals`` — so the units
    cancel exactly and it does not matter that M2 is fitted on goals while the history is measured
    in expected goals. A keeper of average pressure facing an average fixture gets back precisely
    the number the old chain gave him, which is the property that makes the change a re-attribution
    rather than a rescaling.
    """

    config: GoalkeeperConfig
    prior_minutes: float = 900.0
    by_player: dict[int, float] = field(default_factory=dict)
    """Player code -> pressure-adjusted saves per 90, already shrunk toward the population."""

    population_per90: float = 0.0
    """The goalkeeper population's saves per 90. What an unseen keeper is worth, which is the right
    answer for a debutant and the wrong one to invent from two appearances."""

    pressure_column: str = ""
    """Which column measured the pressure faced. Recorded rather than assumed, because the fallback
    below changes what the ratio *means* and a card that did not say so would be describing a
    different model from the one that ran (DP-09, DP-15)."""

    keepers: int = 0

    def fit(self, history: pd.DataFrame) -> GoalkeeperSavesModel:
        """Learn each keeper's saves per 90 net of the pressure he faced.

        Falls back from expected goals conceded to *actual* goals conceded when the archive carries
        no expected figure, rather than declining to fit (DP-15). Actual goals are a far noisier
        measure of shots faced than expected goals, so the fallback is a worse model and not an
        equivalent one; it is recorded in :attr:`pressure_column` for exactly that reason.
        """
        if history.empty or not {"position", "minutes", "saves"} <= set(history.columns):
            return self
        frame = history[
            (history["position"] == Position.GKP.value) & (history["minutes"] > 0)
        ].dropna(subset=["saves", "minutes"])
        if frame.empty:
            return self

        column = next(
            (
                candidate
                for candidate in ("expected_goals_conceded", "goals_conceded")
                if candidate in frame.columns and frame[candidate].notna().any()
            ),
            "",
        )
        if not column:
            return self
        frame = frame.dropna(subset=[column])
        total_minutes = float(frame["minutes"].sum())
        total_pressure = float(pd.to_numeric(frame[column], errors="coerce").sum())
        if total_minutes <= 0 or total_pressure <= 0:
            return self

        self.pressure_column = column
        self.population_per90 = (
            float(pd.to_numeric(frame["saves"], errors="coerce").sum()) / total_minutes * 90.0
        )
        league_pressure_per90 = total_pressure / total_minutes * 90.0

        for player_code, group in frame.groupby("player_code"):
            minutes = float(group["minutes"].sum())
            pressure = float(pd.to_numeric(group[column], errors="coerce").sum())
            if minutes <= 0 or pressure <= 0:
                continue
            saves_per90 = float(pd.to_numeric(group["saves"], errors="coerce").sum())
            saves_per90 = saves_per90 / minutes * 90.0
            relative_pressure = (pressure / minutes * 90.0) / league_pressure_per90
            if relative_pressure <= 0:
                continue
            adjusted = saves_per90 / relative_pressure
            # The same shrinkage arithmetic as `RateModel`, deliberately: a normalised rate is
            # still a rate estimated from a finite sample, and inventing a second way to shrink one
            # is how two versions of the same idea end up disagreeing.
            weight = minutes / (minutes + self.prior_minutes)
            self.by_player[as_int(player_code)] = (
                weight * adjusted + (1.0 - weight) * self.population_per90
            )
        self.keepers = len(self.by_player)
        return self

    def fixture_factor(self, goals_conceded_mean: float, league_mean_goals: float) -> float:
        """How much harder than average this fixture is on the keeper, damped by the config weight.

        A straight line through the average fixture, so ``fixture_weight`` of 0 is exactly today's
        fixture-blind behaviour and 1 applies M2's ratio in full. Floored at zero because a factor
        cannot be negative; nothing else clips it, since a genuinely brutal fixture *should* read as
        a busy afternoon.
        """
        if league_mean_goals <= 0:
            return 1.0
        ratio = goals_conceded_mean / league_mean_goals
        return max(0.0, 1.0 + self.config.fixture_weight * (ratio - 1.0))

    def save_rate(
        self,
        player_code: float | None,
        fitted_rate: float,
        *,
        goals_conceded_mean: float,
        league_mean_goals: float,
    ) -> float:
        """The saves per 90 to score this keeper's fixture with.

        ``fitted_rate`` is what the generic chain would have said. It is the answer under the
        ``fixture_weighted`` arm, scaled to the fixture, and it is also the fallback under
        ``separate`` for a keeper this model never saw — a debutant has no pressure history to
        divide out, and substituting the population figure for him would discard the one thing the
        old chain did know about him.
        """
        factor = self.fixture_factor(goals_conceded_mean, league_mean_goals)
        if self.config.mode == "fixture_weighted" or not self.by_player:
            return fitted_rate * factor
        # `!= itself` rather than `pd.isna`: a missing player code is a NaN float here, and the
        # comparison is the one NaN test that does not need the value to be a pandas scalar.
        if player_code is None or player_code != player_code:
            return fitted_rate * factor
        level = self.by_player.get(as_int(player_code))
        if level is None:
            return fitted_rate * factor
        return level * factor

    def describe(self) -> dict[str, object]:
        return {
            "mode": self.config.mode,
            "fixture_weight": self.config.fixture_weight,
            "prior_minutes": self.prior_minutes,
            "keepers": self.keepers,
            "population_saves_per_90": round(self.population_per90, 4),
            # Named because the fallback is a *worse* model rather than an equivalent one, and a
            # card that reported neither would describe a model that did not run (DP-09, DP-15).
            "pressure_column": self.pressure_column or None,
        }


@dataclass
class BonusModel:
    """M8. Expected BPS from expected actions, then P(top three) within the match.

    **Structural, not learned.** No season has used the 2026/27 BPS matrix — it was revised for this
    season — so training on historical bonus would fit a scoring regime that no longer exists. The
    weights come from configuration, which is where the community's reconstruction of them lives,
    labelled as unverified.

    The probability is computed against the *distribution of the other 21 players in that match*,
    not against a league-wide mean. Bonus is a ranking inside one game: a 30-BPS performance is
    worth three points in a quiet match and nothing in a chaotic one.
    """

    bonus_points: tuple[int, ...] = (3, 2, 1)
    typical_bps_mean: float = 14.0
    typical_bps_sd: float = 9.0

    def fit(self, history: pd.DataFrame) -> BonusModel:
        """Learn only the *shape* of the BPS distribution, never the bonus mapping itself.

        Fitting the spread of BPS within a match is regime-independent enough to be worth doing:
        the weights changed, the fact that BPS is roughly bell-shaped across a match did not.
        """
        if history.empty or "bps" not in history.columns:
            return self
        played = history[history["minutes"] > 0]["bps"].dropna()
        if len(played) < 50:
            return self
        self.typical_bps_mean = float(played.mean())
        self.typical_bps_sd = max(1.0, float(played.std()))
        return self

    def expected_bonus(self, expected_bps: float, *, players_in_match: int = 22) -> float:
        """Expected bonus points for a player with this expected BPS.

        Approximates P(finishing in the top k of the match) with a normal tail. Approximate on
        purpose: the exact answer needs a joint distribution over 22 correlated players, and the
        error in *that* would dwarf the error in this.
        """
        if self.typical_bps_sd <= 0:
            return 0.0
        z = (expected_bps - self.typical_bps_mean) / self.typical_bps_sd
        # P(this player beats a randomly chosen other player in the same match).
        beats_one = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        others = max(1, players_in_match - 1)

        total = 0.0
        for rank, points in enumerate(self.bonus_points, start=1):
            # P(exactly rank-1 of the others beat this player), binomial.
            probability = (
                math.comb(others, rank - 1)
                * ((1 - beats_one) ** (rank - 1))
                * (beats_one ** (others - rank + 1))
            )
            total += points * probability
        return total

    def describe(self) -> dict[str, object]:
        return {
            "bonus_points": list(self.bonus_points),
            "typical_bps_mean": round(self.typical_bps_mean, 3),
            "typical_bps_sd": round(self.typical_bps_sd, 3),
            "regime_note": (
                "structural, not trained on historical bonus: no prior season used the 2026/27 "
                "BPS matrix"
            ),
        }


@dataclass
class ComponentModels:
    """Every component, fitted together so a model card can describe the whole forecast."""

    minutes: MinutesModel
    team_strength: TeamStrengthModel
    rates: dict[str, RateModel]
    bonus: BonusModel

    duty: DutyTable | None = None
    """E10-S3's committed penalty-duty table, or ``None`` for the graded default chain.

    ``None`` rather than an empty table, for the same reason :attr:`MinutesModel.v2` is not a bool:
    an empty table and a candidate that is switched off are different claims, and only one of them
    should be reported as "the model knows of no penalty takers" (DP-08, DP-15, DL-47)."""

    goalkeeper: GoalkeeperSavesModel | None = None
    """E10-S4's fixture-driven goalkeeper saves model, or ``None`` for the graded default chain.

    ``None`` rather than a mode of "off", for the same reason the two fields above it are optional:
    a model that ran and found no goalkeepers and a model that was never fitted are different
    claims, and the backtest card has to be able to tell them apart (DP-08, DP-15, DL-47)."""

    def describe(self) -> dict[str, object]:
        return {
            "M1_minutes": self.minutes.describe(),
            "M2_team_strength": self.team_strength.describe(),
            **{f"rate_{name}": model.describe() for name, model in self.rates.items()},
            "M8_bonus": self.bonus.describe(),
            # Named even when absent, so a model card never has to imply a candidate from silence.
            "duty": None if self.duty is None else self.duty.describe(),
            "goalkeeper": None if self.goalkeeper is None else self.goalkeeper.describe(),
        }


RATE_COMPONENTS = (
    "goals_scored",
    "assists",
    "defensive_contribution",
    "saves",
    "yellow_cards",
    "bps",
)


def fit_components(
    history: pd.DataFrame,
    matches: pd.DataFrame,
    config: ForecastConfig,
    rules: GameRules,
) -> ComponentModels:
    """Fit every component on the same training window.

    ``history`` must already be restricted to matches knowable before the deadline being predicted.
    This function does no filtering of its own, deliberately: one place decides what is knowable
    (the feature store), and every model trusts it. Two places deciding is how they disagree.
    """
    # A component may be fitted and observed through a different statistic than the one it scores —
    # goal involvement through expected goals rather than actual (ExpectedGoalsConfig, D-25). The
    # dict stays keyed by the scoring component; only the column the model *reads* moves, so nothing
    # downstream of `rates[...]` has to know which statistic informed it (Invariant 1).
    xg = config.expected_goals

    def observed_for(component: str) -> str:
        return xg.rate_sources.get(component, component) if xg.enabled else component

    # E10's candidate behaviours, or the graded default. Each flag decides whether its tunables
    # reach the model at all; nothing downstream of here can tell which, and nothing downstream has
    # to (DP-08, DL-47).
    discrimination = config.discrimination
    rates = {
        component: RateModel(
            column=observed_for(component),
            prior_minutes=config.shrinkage.rate_prior_minutes,
            prior_season_minutes=config.features.prior_season.prior_minutes,
            adaptive=(discrimination.shrinkage if discrimination.adaptive_shrinkage else None),
        ).fit(history)
        for component in RATE_COMPONENTS
    }
    minutes = MinutesModel(
        v2=discrimination.minutes if discrimination.minutes_v2 else None,
        congestion_column=congestion_feature_name(config.features),
        absence_column=absence_feature_name(config.features),
    )
    return ComponentModels(
        minutes=minutes.fit(history, rules.scoring.long_play_minutes),
        team_strength=TeamStrengthModel().fit(matches, current_season=rules.season),
        rates=rates,
        bonus=BonusModel(bonus_points=tuple(rules.scoring.bonus_points)).fit(history),
        # Not fitted — read. The duty table is curated knowledge and there is nothing in `history`
        # to learn it from; what the flag decides is whether the scorer sees it at all (DL-50).
        duty=(
            DutyTable(config.duty, discrimination.penalties) if discrimination.duty_term else None
        ),
        # Fitted on the same window as everything else, and only when the flag asks for it. The
        # goalkeeper population is a few dozen players, so this costs a groupby over 11% of the
        # rows and nothing downstream can tell it happened unless the flag is on (DL-47).
        goalkeeper=(
            GoalkeeperSavesModel(
                config=discrimination.goalkeeper,
                prior_minutes=discrimination.goalkeeper.prior_minutes,
            ).fit(history)
            if discrimination.gkp_v2
            else None
        ),
    )


def _positions() -> tuple[str, ...]:
    return tuple(position.value for position in Position)


__all__ = [
    "MINUTES_BANDS",
    "RATE_COMPONENTS",
    "BonusModel",
    "ComponentModels",
    "GoalkeeperSavesModel",
    "MinutesDistribution",
    "MinutesModel",
    "RateModel",
    "TeamStrengthModel",
    "fit_components",
]
