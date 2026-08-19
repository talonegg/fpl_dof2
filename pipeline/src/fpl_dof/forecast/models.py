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

from fpl_dof.config.models import ForecastConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import GameRules, Position

log = get_logger(__name__)

MINUTES_BANDS = ("none", "short", "long")


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
        self, position: str, appearance_rate: float, *, status_multiplier: float = 1.0
    ) -> MinutesDistribution:
        """The distribution, with availability news applied as a multiplier on playing at all.

        News is applied here rather than folded into the fitted rates because it is information of
        a completely different kind: history says what usually happens, the status flag says what
        is known about this week. Mixing them would make the model unable to react to an injury.
        """
        none, short, long = self.by_group.get(
            (position, self.band(appearance_rate)), self.population
        )
        if status_multiplier < 1.0:
            scale = max(0.0, min(1.0, status_multiplier))
            short, long = short * scale, long * scale
            none = 1.0 - short - long
        total = none + short + long
        if total <= 0:
            return MinutesDistribution(1.0, 0.0, 0.0)
        return MinutesDistribution(none / total, short / total, long / total)

    def describe(self) -> dict[str, object]:
        return {
            "groups": len(self.by_group),
            "population": {
                name: round(value, 4)
                for name, value in zip(MINUTES_BANDS, self.population, strict=True)
            },
            "appearance_bands": list(self.appearance_bands),
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

    def fit(self, matches: pd.DataFrame) -> TeamStrengthModel:
        """``matches``: one row per team per fixture, with goals for and against.

        Time-decayed by an exponential half-life, because a promoted side's September is weak
        evidence about their April, and a manager change makes last season nearly irrelevant.
        """
        if matches.empty:
            return self
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
        weight = minutes_observed / (minutes_observed + self.prior_minutes)
        return weight * observed_rate + (1.0 - weight) * prior

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

    def describe(self) -> dict[str, object]:
        return {
            "M1_minutes": self.minutes.describe(),
            "M2_team_strength": self.team_strength.describe(),
            **{f"rate_{name}": model.describe() for name, model in self.rates.items()},
            "M8_bonus": self.bonus.describe(),
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

    rates = {
        component: RateModel(
            column=observed_for(component),
            prior_minutes=config.shrinkage.rate_prior_minutes,
            prior_season_minutes=config.features.prior_season.prior_minutes,
        ).fit(history)
        for component in RATE_COMPONENTS
    }
    return ComponentModels(
        minutes=MinutesModel().fit(history, rules.scoring.long_play_minutes),
        team_strength=TeamStrengthModel().fit(matches),
        rates=rates,
        bonus=BonusModel(bonus_points=tuple(rules.scoring.bonus_points)).fit(history),
    )


def _positions() -> tuple[str, ...]:
    return tuple(position.value for position in Position)


__all__ = [
    "MINUTES_BANDS",
    "RATE_COMPONENTS",
    "BonusModel",
    "ComponentModels",
    "MinutesDistribution",
    "MinutesModel",
    "RateModel",
    "TeamStrengthModel",
    "fit_components",
]
