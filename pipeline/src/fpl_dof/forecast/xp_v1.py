"""Expected points v1: components combined, with a **modelled** variance.

This replaces E0's heuristic uncertainty band (debt D-09). The difference is not cosmetic. E0
multiplied the mean by a coefficient of variation chosen by hand, so the band said "this is roughly
how unsure we generally are". Here the variance is computed from the components, which means it
says something different and much more useful: *this particular player is unusually uncertain*.

**Where the variance actually comes from.** Not from the scoring events — from **minutes**. A player
with a 30% chance of not appearing has a large probability mass at exactly zero points, and that
binary contributes far more variance than any amount of scoring noise. Writing the total as a
mixture over the minutes bands captures that correctly, and it is why two players with the same
expected points can deserve very different bands.

For a mixture over minutes states, with points ``P`` and state ``S``:

    E[P]   = sum_s P(s) E[P|s]
    Var[P] = sum_s P(s) (Var[P|s] + E[P|s]^2) - E[P]^2

The second term is the one that matters: it is the spread *between* states, and dropping it — which
averaging conditional variances would do — throws away exactly the uncertainty the optimiser needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.features import (
    FIXTURE_AT_HOME,
    FIXTURE_OPPONENT,
    FIXTURE_TEAM,
    PRIOR_SEASON_MINUTES,
    PRIOR_SEASON_PREFIX,
)
from fpl_dof.forecast.models import FIT_AT_HOME, ComponentModels, MinutesDistribution
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import GameRules, Position

log = get_logger(__name__)

#: What this model calls itself wherever a published artefact has to say which model ran.
MODEL_NAME = "xp_v1"

#: Components reported in the decomposition, in the order the UI shows them.
COMPONENT_ORDER = (
    "appearance",
    "goals",
    "assists",
    "clean_sheet",
    "defensive_contribution",
    "saves",
    "bonus",
    "cards",
    "goals_conceded",
)


@dataclass(frozen=True, slots=True)
class PlayerForecast:
    player_code: int
    expected_points: float
    variance: float
    components: dict[str, float]
    minutes: MinutesDistribution

    @property
    def standard_deviation(self) -> float:
        return math.sqrt(max(0.0, self.variance))


@dataclass(frozen=True, slots=True)
class Opposition:
    """The fixture seam: everything about the other side a single-fixture forecast needs.

    Everything :func:`forecast_player` asks about an opponent, named as one object, so that the live
    horizon scorer and the backtest predictor are *told* about opposition in the same words rather
    than each computing it for itself — which is precisely how the shipped model and the graded
    model drift apart (D-25).
    """

    clean_sheet_probability: float
    goals_conceded_mean: float
    attacking_fixture_factor: float = 1.0
    """How much easier or harder M2 rates this fixture for the player's own attacking output
    (E11-S3): the opponent's defence and the venue, with the player's own team's attack rating
    deliberately excluded (see :meth:`TeamStrengthModel.attacking_fixture_factor`). 1.0 — neutral —
    when no specific opponent is known, matching the other two fields' fallback."""


def league_average_opposition(models: ComponentModels) -> Opposition:
    """Opposition with no identity — the honest assumption when the fixture is unknown.

    Inventing a specific opponent where none is known would add noise that looks like signal. Since
    E9-S2 this is a **fallback** rather than the backtest's normal condition: a fold row whose
    fixture the calendar cannot resolve is scored here, counted, and reported (DP-15). It remains
    the condition the E9-S1 parity test holds both paths to, because it is the one opposition both
    can be put under by construction.
    """
    mean = models.team_strength.league_mean_goals
    return Opposition(
        clean_sheet_probability=math.exp(-mean),
        goals_conceded_mean=mean,
        attacking_fixture_factor=1.0,
    )


def fixture_opposition(
    models: ComponentModels, *, team_id: int, opponent_id: int, at_home: bool
) -> Opposition:
    """Opposition for a real fixture, from M2's attack and defence ratings."""
    return Opposition(
        clean_sheet_probability=models.team_strength.clean_sheet_probability(
            team_id, opponent_id, at_home=at_home
        ),
        goals_conceded_mean=models.team_strength.expected_goals(
            opponent_id, team_id, at_home=not at_home
        ),
        attacking_fixture_factor=models.team_strength.attacking_fixture_factor(
            opponent_id, at_home=at_home
        ),
    )


def row_opposition(models: ComponentModels, row: pd.Series) -> Opposition | None:
    """The real fixture's opposition for one feature row, or ``None`` when it cannot be resolved.

    ``None`` rather than a quiet league-average default, so the caller has to decide what to do
    about it and can count how often it happened. A fallback nobody counts is a fallback that
    becomes the norm without anyone noticing.
    """
    team = row.get(FIXTURE_TEAM)
    opponent = row.get(FIXTURE_OPPONENT)
    at_home = row.get(FIXTURE_AT_HOME)
    if team is None or opponent is None or at_home is None:
        return None
    if pd.isna(team) or pd.isna(opponent) or pd.isna(at_home):
        return None
    return fixture_opposition(
        models, team_id=int(team), opponent_id=int(opponent), at_home=bool(at_home)
    )


def _poisson_survival(threshold: int, mean: float) -> float:
    """P(X >= threshold) for a Poisson. Used for Defensive Contribution, which is a threshold event.

    Modelling the count and applying the threshold uses far more information than counting past
    threshold crossings, which is what makes M4 the best signal-to-noise component in the model.
    """
    if threshold <= 0:
        return 1.0
    if mean <= 0:
        return 0.0
    below = 0.0
    term = math.exp(-mean)
    for k in range(threshold):
        if k > 0:
            term *= mean / k
        below += term
    return max(0.0, min(1.0, 1.0 - below))


def _evidence_minutes(row: pd.Series) -> float:
    """How much of this player the shrinkage considers itself to have seen.

    One definition, read by the rates and by the duty term, because two spellings of "how much do we
    know about this player" is how the shrinkage and the thing correcting for it drift apart.

    **A missing rate is zero evidence, not `nan`.** Before this function existed, the equivalent
    inline expression used `if minutes:` as its guard, which `nan` passes (`bool(nan)` is `True` in
    Python) — so a missing `minutes_mean_last6` used to produce `nan * matches_observed = nan`
    rather than `0.0`, silently propagating into `RateModel.predict`. The shipped feature store
    never actually emits that combination (a non-empty group always carries a real
    `minutes_mean_last6`), so this was dormant either way — recorded here so a future change to
    `build_features` doesn't quietly resurrect the old, worse behaviour.
    """
    minutes = row.get("minutes_mean_last6")
    if minutes is None or pd.isna(minutes):
        return 0.0
    return float(minutes) * float(row.get("matches_observed") or 0)


def _rate(
    models: ComponentModels,
    column: str,
    position: str,
    row: pd.Series,
    config: ForecastConfig,
) -> float:
    model = models.rates.get(column)
    if model is None:
        return 0.0
    # The model knows which statistic it observes: normally the component's own column, but the
    # expected-goals statistic when that component was fitted through xG (ExpectedGoalsConfig). Read
    # the rolling per-90 of exactly that column so fit and inference agree on the signal.
    observed = row.get(f"{model.column}_per90_last6")
    total_minutes = _evidence_minutes(row)
    value = float(observed) if observed is not None and not pd.isna(observed) else float("nan")
    ratio, ratio_minutes = _prior_season(row, column, config)
    return model.predict(
        position, value, total_minutes, prior_ratio=ratio, prior_ratio_minutes=ratio_minutes
    )


def _opponent_adjusted(rate: float, fixture_factor: float, config: ForecastConfig) -> float:
    """Scale a goal-involvement rate by M2's read of this fixture (E11-S3).

    Off (the shipped default) reproduces ``rate`` exactly — the flag decides whether the factor is
    even looked at, so a caller with the candidate off cannot see a behaviour change by construction
    (DP-08). On, the raw factor is damped toward 1.0 by ``weight`` and clipped, per
    ``OpponentAdjustmentConfig`` (DP-10): ``1 + w * (factor - 1)`` is a straight line through the
    neutral fixture, the same shape the goalkeeper model's ``fixture_weight`` already uses.
    """
    discrimination = config.discrimination
    if not discrimination.opponent_adjusted_rates:
        return rate
    tuning = discrimination.opponent_adjustment
    damped = 1.0 + tuning.weight * (fixture_factor - 1.0)
    damped = min(tuning.maximum_factor, max(tuning.minimum_factor, damped))
    return rate * damped


def _penalty_duty_points(
    models: ComponentModels,
    row: pd.Series,
    rules: GameRules,
    config: ForecastConfig,
    position: Position,
) -> float:
    """Points per full match from penalty duty that the fitted goal rate has lost (E10-S3, DL-50).

    Zero — a true no-op, not a small number — for every player the reference table has never heard
    of, for every row that cannot say which deadline it is being scored at, and whenever the
    candidate flag is off. Absence of an entry means *unknown*, so nothing is added and nothing is
    taken away.

    **The formulation, in one sentence you can disagree with** (DP-10): a club wins
    ``penalties_per_team_match`` penalties a match, its taker converts ``conversion_rate`` of them
    for the position's goal points and concedes the missed-penalty points on the rest, and the model
    is missing exactly the share of that which shrinkage replaced with a position prior containing
    almost no penalty duty at all.

    That last clause is the whole design. A taker's penalties are goals and M3 observes goals, so
    adding his full penalty return on top of his own fitted rate would count it twice and inflate
    precisely the players at the head of the ranking — the failure mode that looks like a win on
    top-20 precision and is a bias. Scaling by :meth:`RateModel.prior_share` means the term is
    largest for a **newly appointed** taker, whose record contains no penalties yet and whose duty
    is therefore genuinely new information, and smallest for one the model has watched take forty of
    them. That is where the information actually is.

    **What it still overstates**, recorded rather than hidden: the position prior is not
    penalty-free — it is every player's penalties smeared across the position — so the premium a
    taker holds over it is slightly less than his full penalty contribution. The effect is small —
    a score or so of takers among several hundred outfield players — and correcting it would need a
    penalty-free goal rate, which nothing in silver supplies.
    """
    table = models.duty
    if table is None:
        return 0.0
    code = row.get("player_code")
    if code is None or pd.isna(code):
        return 0.0
    assignment = table.penalty_duty(int(code), row.get("as_of"))
    if assignment is None or not assignment.contributes:
        return 0.0

    tuning = config.discrimination.penalties
    scoring = rules.scoring
    per_penalty = (
        tuning.conversion_rate * scoring.goals_scored[position]
        + (1.0 - tuning.conversion_rate) * scoring.penalties_missed
    )
    goals_model = models.rates.get("goals_scored")
    prior_share = 1.0 if goals_model is None else goals_model.prior_share(_evidence_minutes(row))
    return (
        tuning.strength
        * assignment.weight
        * prior_share
        * tuning.penalties_per_team_match
        * per_penalty
    )


def _prior_season(row: pd.Series, column: str, config: ForecastConfig) -> tuple[float, float]:
    """The prior-season ratio for this component, if the feature store supplied one.

    Which statistic informs which component is configuration, not knowledge held here: this
    function knows only that a component may have a prior-season signal attached to it, never what
    measured it (Invariant 1).
    """
    prior_season = config.features.prior_season
    if not prior_season.enabled:
        return float("nan"), 0.0
    stem = prior_season.component_priors.get(column)
    if stem is None:
        return float("nan"), 0.0
    ratio = row.get(f"{PRIOR_SEASON_PREFIX}{stem}_ratio")
    minutes = row.get(PRIOR_SEASON_MINUTES)
    return (
        float(ratio) if ratio is not None and not pd.isna(ratio) else float("nan"),
        float(minutes) if minutes is not None and not pd.isna(minutes) else 0.0,
    )


def forecast_player(
    row: pd.Series,
    models: ComponentModels,
    rules: GameRules,
    config: ForecastConfig,
    *,
    clean_sheet_probability: float,
    goals_conceded_mean: float,
    attacking_fixture_factor: float = 1.0,
    status_multiplier: float = 1.0,
) -> PlayerForecast:
    """One player's expected points and variance, decomposed.

    Conditioned on minutes throughout. Every per-90 rate is scaled by the minutes actually expected
    in that state, which is the difference between "a good rate" and "points on the board".
    """
    position = Position(str(row["position"]))
    scoring = rules.scoring
    minutes = models.minutes.predict_row(row, position.value, status_multiplier=status_multiplier)

    goal_rate = _opponent_adjusted(
        _rate(models, "goals_scored", position.value, row, config), attacking_fixture_factor, config
    )
    assist_rate = _opponent_adjusted(
        _rate(models, "assists", position.value, row, config), attacking_fixture_factor, config
    )
    defcon_rate = _rate(models, "defensive_contribution", position.value, row, config)
    save_rate = _rate(models, "saves", position.value, row, config)
    if position is Position.GKP and models.goalkeeper is not None:
        # E10-S4. The generic per-90 above is what the goalkeeper model is *given*, not what it
        # necessarily returns: under `separate` it uses its own pressure-adjusted level and keeps
        # the fitted rate only as the fallback for a keeper it has never seen. Either way the
        # fixture is what scales it, which is the whole point — a save is a shot faced, and how
        # many shots a keeper faces is the fixture rather than his own history (DL-51).
        save_rate = models.goalkeeper.save_rate(
            row.get("player_code"),
            save_rate,
            goals_conceded_mean=goals_conceded_mean,
            league_mean_goals=models.team_strength.league_mean_goals,
        )
    card_rate = _rate(models, "yellow_cards", position.value, row, config)
    bps_rate = _rate(models, "bps", position.value, row, config)
    duty_points_per_90 = _penalty_duty_points(models, row, rules, config, position)

    states: list[tuple[float, float, float, dict[str, float]]] = []
    for probability, played_minutes, appearance_points, long_play in (
        (minutes.none, 0.0, 0, False),
        (minutes.short, config.minutes.substitute_minutes, scoring.short_play, False),
        (minutes.long, config.minutes.starter_minutes, scoring.long_play, True),
    ):
        if probability <= 0:
            continue
        share = played_minutes / 90.0
        components: dict[str, float] = dict.fromkeys(COMPONENT_ORDER, 0.0)
        components["appearance"] = float(appearance_points)

        goals = goal_rate * share
        assists = assist_rate * share
        # Penalty duty lands **inside** the goals component rather than beside it, because a
        # penalty is a goal: a taker's decomposition should read as a larger goal threat, which is
        # what he has. A separate component would also be a change to the published web contract
        # for a candidate that is off by default, which is a poor trade (DP-04).
        duty_points = duty_points_per_90 * share
        components["goals"] = goals * scoring.goals_scored[position] + duty_points
        components["assists"] = assists * scoring.assists

        if long_play:
            # A clean sheet requires sixty minutes, so it only exists in the long state at all.
            components["clean_sheet"] = clean_sheet_probability * scoring.clean_sheets[position]

        threshold = scoring.defensive_contribution_threshold.get(position) or 0
        if threshold > 0:
            crossed = _poisson_survival(threshold, defcon_rate * share)
            components["defensive_contribution"] = (
                crossed * scoring.defensive_contribution[position]
            )

        if position is Position.GKP:
            saves = save_rate * share
            components["saves"] = saves / scoring.saves_per_point * scoring.saves

        conceded_points = scoring.goals_conceded.get(position) or 0
        if conceded_points:
            conceded = goals_conceded_mean * share
            components["goals_conceded"] = (
                conceded / scoring.goals_conceded_per_point * conceded_points
            )

        components["cards"] = card_rate * share * scoring.yellow_cards
        components["bonus"] = models.bonus.expected_bonus(bps_rate * share)

        mean = float(sum(components.values()))
        # Conditional variance: scoring events are counts, so a Poisson-like variance in points is
        # a reasonable stand-in. It is dominated by the between-state term below, which is the
        # point — this need not be precise to be far better than a fixed coefficient.
        conditional_variance = (
            goals * (scoring.goals_scored[position] ** 2)
            # Same Poisson stand-in as the line above it, written as mean-times-points because the
            # duty term is already in points: for a count `n` scoring `v`,
            # `n * v**2 == (n * v) * v`.
            # Invariant 6 — a component that moves the mean and not the band is a contract breach.
            + duty_points * scoring.goals_scored[position]
            + assists * (scoring.assists**2)
            + (clean_sheet_probability * (1 - clean_sheet_probability) if long_play else 0.0)
            * (scoring.clean_sheets[position] ** 2)
            + 1.0
        )
        states.append((probability, mean, conditional_variance, components))

    if not states:
        return PlayerForecast(
            player_code=int(row["player_code"]),
            expected_points=0.0,
            variance=0.0,
            components=dict.fromkeys(COMPONENT_ORDER, 0.0),
            minutes=minutes,
        )

    expected = sum(probability * mean for probability, mean, _, _ in states)
    second_moment = sum(
        probability * (variance + mean**2) for probability, mean, variance, _ in states
    )
    variance = max(0.0, second_moment - expected**2)

    blended = {
        name: float(sum(probability * parts[name] for probability, _, _, parts in states))
        for name in COMPONENT_ORDER
    }
    return PlayerForecast(
        player_code=int(row["player_code"]),
        expected_points=float(expected),
        variance=float(variance),
        components=blended,
        minutes=minutes,
    )


def score_player(
    row: pd.Series,
    models: ComponentModels,
    rules: GameRules,
    config: ForecastConfig,
    *,
    opposition: Opposition,
    status_multiplier: float = 1.0,
) -> PlayerForecast:
    """:func:`forecast_player`, told about the opponent as one object rather than two loose floats.

    The single call every caller outside this module should use. It exists so that "which
    opposition was this scored under" is a decision made once, by name, at each call site.
    """
    return forecast_player(
        row,
        models,
        rules,
        config,
        clean_sheet_probability=opposition.clean_sheet_probability,
        goals_conceded_mean=opposition.goals_conceded_mean,
        attacking_fixture_factor=opposition.attacking_fixture_factor,
        status_multiplier=status_multiplier,
    )


class ComponentPredictor:
    """Adapts the component models to the backtest's predictor interface.

    Thin on purpose. The harness must be able to score any predictor without knowing what is inside
    it, and the models must be usable outside a backtest; this is the only place the two meet.
    """

    name = "xp_v1"

    def __init__(self, config: ForecastConfig, rules: GameRules) -> None:
        self.config = config
        self.rules = rules
        self.models: ComponentModels | None = None

    @property
    def long_play_minutes(self) -> int:
        """The 60-minute threshold, from the rules this predictor was built with (Invariant 2).

        Exposed so the harness can band an *observation* the same way M1 bands a prediction,
        without the harness having to hold an opinion about a scoring rule.
        """
        return int(self.rules.scoring.long_play_minutes)

    @property
    def squad_composition(self) -> dict[str, int]:
        """How many of each position an FPL squad holds, from the rules this predictor was built
        with (Invariant 2).

        Exposed for the same reason as :attr:`long_play_minutes`: the harness splits its
        head-of-ranking metrics per position and needs to know how deep each position's head goes,
        and "two goalkeepers in fifteen" is a rule rather than something a metric may assume.
        """
        return {position.value: count for position, count in self.rules.squad.composition.items()}

    def minutes_probabilities(self, features: pd.DataFrame) -> pd.DataFrame:
        """M1's distribution for each row — the same one :meth:`predict` scored through.

        Recomputed rather than stashed during :meth:`predict`. Stashing would be marginally faster
        and would make the reported calibration depend on the order the harness happened to call
        two methods in; recomputing is a dictionary lookup per row and cannot go stale.
        """
        if self.models is None:
            raise RuntimeError("minutes_probabilities() called before fit()")
        rows = [
            self.models.minutes.predict_row(row, str(row["position"]))
            for _, row in features.iterrows()
        ]
        return pd.DataFrame(
            {
                "none": [row.none for row in rows],
                "short": [row.short for row in rows],
                "long": [row.long for row in rows],
            },
            index=features.index,
        )

    def fit(self, training: pd.DataFrame) -> None:
        from fpl_dof.forecast.models import fit_components

        matches = _team_matches(training, use_xg=self.config.expected_goals.team_strength_from_xg)
        self.models = fit_components(training, matches, self.config, self.rules)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        if self.models is None:
            raise RuntimeError("predict() called before fit(); the harness always fits first")
        models = self.models

        # Each row is scored against **its own** fixture, which is what puts M2's attack and
        # defence ratings into a graded prediction at all (E9-S2). A row the calendar cannot place
        # falls back to league-average opposition — the honest assumption when the fixture is
        # unknown — and the fallback is counted and logged rather than absorbed (DP-15).
        default = league_average_opposition(models)
        predictions = []
        unresolved = 0
        for _, row in features.iterrows():
            opposition = row_opposition(models, row)
            if opposition is None:
                unresolved += 1
                opposition = default
            forecast = score_player(
                row,
                models,
                self.rules,
                self.config,
                opposition=opposition,
            )
            predictions.append(forecast.expected_points)
        if unresolved:
            log.info(
                "xp_v1.league_average_fallback",
                extra={"rows": len(features), "unresolved": unresolved},
            )
        return pd.Series(predictions, index=features.index, dtype=float)


def _team_matches(history: pd.DataFrame, *, use_xg: bool = False) -> pd.DataFrame:
    """Per-team, per-fixture goals for and against, reconstructed from player rows.

    The archive has no team-level table, and ``goals_conceded`` is recorded per player, so the
    team's figure is the maximum across its players in that fixture rather than the sum — summing
    would multiply one goal by eleven.

    With ``use_xg``, the same reconstruction runs on ``expected_goals`` and
    ``expected_goals_conceded`` instead (ExpectedGoalsConfig, M2). Expected goals sum across a
    team's players the same way real goals do, and every player in a fixture carries the same team
    expected-goals-conceded figure, so the sum/max reconstruction holds unchanged. Falls back to
    actual goals when the xG columns are
    absent, which keeps a partial archive working (DP-15).

    **A fixture is identified by season as well as number.** The archive numbers fixtures 1..380
    within a season, so ``fixture_id`` 12 exists once per season and grouping without the season
    merges two different matches into one — summing a club's goals across both and halving its
    match count. The defect was inert only for as long as ``team_id`` was null and every row was
    dropped here (D-26); repairing the club made it reachable, so the key is repaired with it.
    """
    for_column, against_column = (
        ("expected_goals", "expected_goals_conceded")
        if use_xg
        else ("goals_scored", "goals_conceded")
    )
    needed = {"season", "team_id", "fixture_id", for_column, against_column, "kickoff_time"}
    empty = pd.DataFrame(
        columns=[
            "season",
            "team_id",
            "fixture_id",
            "goals_for",
            "goals_against",
            "kickoff_time",
            FIT_AT_HOME,
        ]
    )
    if history.empty or not needed <= set(history.columns):
        # xG requested but not in this archive: fall back rather than return nothing, so M2 still
        # fits on actual goals (DP-15). A genuinely empty history still returns empty.
        if (
            use_xg
            and not history.empty
            and not {for_column, against_column} <= set(history.columns)
        ):
            return _team_matches(history, use_xg=False)
        if not history.empty:
            # Not a degradation worth absorbing quietly: with no matches the team-strength model is
            # unfitted and every fixture becomes league-average, which is the exact condition D-26
            # left in place unnoticed for the whole of E10.
            log.warning(
                "xp_v1.team_matches_unavailable",
                extra={"missing": sorted(needed - set(history.columns))},
            )
        return empty
    played = history[history["minutes"] > 0]
    if played.empty:
        return empty
    # Venue carried through only when history has it: it is what M2 fits home advantage from
    # (E11-S2), and an archive without it loses that one estimate and nothing else (DP-15). Every
    # row of a team in a fixture agrees on it, so "max" is picking the single value, not reducing.
    aggregations: dict[str, tuple[str, str]] = {
        "goals_for": (for_column, "sum"),
        "goals_against": (against_column, "max"),
        "kickoff_time": ("kickoff_time", "min"),
    }
    if "was_home" in played.columns:
        aggregations[FIT_AT_HOME] = ("was_home", "max")
    grouped = played.groupby(["season", "team_id", "fixture_id"], dropna=True).agg(**aggregations)
    return grouped.reset_index()


def to_frame(forecasts: list[PlayerForecast]) -> pd.DataFrame:
    """The published shape: mean, standard deviation, and every component (Invariant 6, DP-09)."""
    rows = []
    for forecast in forecasts:
        row: dict[str, object] = {
            "player_code": forecast.player_code,
            "xp_next": round(forecast.expected_points, 4),
            "xp_next_sd": round(forecast.standard_deviation, 4),
            "p_no_appearance": round(forecast.minutes.none, 4),
            "p_short_appearance": round(forecast.minutes.short, 4),
            "p_long_appearance": round(forecast.minutes.long, 4),
            "expected_minutes": round(forecast.minutes.expected_minutes, 2),
        }
        row.update(
            {f"component_{name}": round(value, 4) for name, value in forecast.components.items()}
        )
        rows.append(row)
    if not rows:
        return pd.DataFrame(
            columns=[
                "player_code",
                "xp_next",
                "xp_next_sd",
                *[f"component_{c}" for c in COMPONENT_ORDER],
            ]
        )
    return pd.DataFrame(rows)


def team_matches(history: pd.DataFrame, *, use_xg: bool = False) -> pd.DataFrame:
    """One row per team per fixture, with goals for and against — what M2 fits on.

    A public name for :func:`_team_matches`, because the fixture ticker (DL-37) needs the same
    reconstruction and reaching into another module's private is how a second, subtly different
    copy of it eventually appears. There is already one such copy in the chip replay.
    """
    return _team_matches(history, use_xg=use_xg)


__all__ = [
    "COMPONENT_ORDER",
    "ComponentPredictor",
    "Opposition",
    "PlayerForecast",
    "fixture_opposition",
    "forecast_player",
    "league_average_opposition",
    "row_opposition",
    "score_player",
    "team_matches",
    "to_frame",
]
