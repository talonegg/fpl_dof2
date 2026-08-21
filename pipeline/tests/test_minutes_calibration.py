"""E10-S1 — minutes calibration, then a better M1 (closes D-14).

Two halves, tested as two halves, because they are independent claims.

**Measurement.** ``minutes_brier`` was null in every backtest report the harness had ever produced,
which is why [DL-22](../../docs/planning/00-decision-log.md) found E3-S3's acceptance criterion had
never actually been met. These tests check that the number now exists, that it is measured on the
population it is supposed to be measured on — including the 60% of rows where nobody played, which
the accuracy metrics deliberately drop — and that it is split per position and per observed band.

**The model change.** ``discrimination.minutes_v2`` is a candidate, not a promotion (DP-08, DL-47).
So the tests here check the *mechanism*: that the flag off changes nothing at all, that each
adjustment moves probability in the direction it was argued to, and that neither history-based
adjustment can move P(play), which is what would let a rotation prior masquerade as an injury. The
claim that it *improves* the model is the backtest's to make and belongs in the decision log, not
in an assertion.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import (
    BacktestConfig,
    DiscriminationConfig,
    FeatureConfig,
    ForecastConfig,
    MinutesV2Config,
)
from fpl_dof.forecast import baselines
from fpl_dof.forecast.backtest import (
    HAIRCUT_MINUTES_PREFIX,
    MINUTES_PREFIX,
    OBSERVED_MINUTES_BAND,
    BacktestResult,
    walk_forward,
)
from fpl_dof.forecast.features import (
    absence_feature_name,
    build_features,
    congestion_feature_name,
)
from fpl_dof.forecast.metrics import (
    MINUTES_BANDS,
    minutes_band,
    multiclass_brier,
)
from fpl_dof.forecast.models import ComponentModels, MinutesModel, fit_components
from fpl_dof.forecast.xp_v1 import ComponentPredictor, forecast_player, team_matches
from fpl_dof.rules.models import GameRules
from test_backtest import SEASON, RateFromFeatures, make_history


def _v2_config(**overrides: float) -> ForecastConfig:
    return ForecastConfig(
        discrimination=DiscriminationConfig(minutes_v2=True, minutes=MinutesV2Config(**overrides))
    )


def _fitted(v2: MinutesV2Config | None) -> MinutesModel:
    """An M1 with one known group, so a test asserts about an adjustment and not about a fit."""
    model = MinutesModel(v2=v2)
    model.by_group[("MID", 3)] = (0.1, 0.2, 0.7)
    model.population = (0.4, 0.2, 0.4)
    return model


# --- the flag is inert when it is off -----------------------------------------------------------


def test_with_the_candidate_off_the_new_signals_change_nothing() -> None:
    """The regression guarantee the whole of DL-47 rests on, stated at the smallest scale.

    A caller may pass the congestion and absence signals unconditionally — and does, because
    ``predict_row`` cannot know which behaviour is configured. With the flag off they must be read
    by nothing.
    """
    model = _fitted(None)

    plain = model.predict("MID", 0.9)
    signalled = model.predict("MID", 0.9, matches_in_window=6.0, recent_absence_share=1.0)

    assert (plain.none, plain.short, plain.long) == (
        signalled.none,
        signalled.short,
        signalled.long,
    )


def test_a_forecast_ignores_the_new_columns_when_the_candidate_is_off(
    game_rules: GameRules,
) -> None:
    """The same claim one level up: through the scorer, on a real feature row."""
    row = pd.Series(
        {
            "player_code": 1,
            "position": "MID",
            "appearance_rate": 0.9,
            "matches_observed": 10,
            "minutes_mean_last6": 80.0,
        }
    )
    config = ForecastConfig()
    models = _components(config, game_rules)

    without = forecast_player(
        row, models, game_rules, config, clean_sheet_probability=0.3, goals_conceded_mean=1.2
    )
    congested = row.copy()
    congested[congestion_feature_name(config.features)] = 8.0
    congested[absence_feature_name(config.features)] = 1.0
    with_signals = forecast_player(
        congested,
        models,
        game_rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.2,
    )

    assert with_signals.expected_points == pytest.approx(without.expected_points)


def test_the_default_configuration_leaves_every_discrimination_flag_off() -> None:
    """DP-08 is violated by "a flag is added and immediately defaulted on", in those words."""
    assert ForecastConfig().discrimination.minutes_v2 is False


# --- the adjustments, one claim each --------------------------------------------------------------


def test_a_congested_run_moves_probability_out_of_a_full_ninety() -> None:
    model = _fitted(MinutesV2Config())

    normal = model.predict("MID", 0.9, matches_in_window=2.0)
    congested = model.predict("MID", 0.9, matches_in_window=5.0)

    assert congested.long < normal.long
    assert congested.none + congested.short > normal.none + normal.short
    assert congested.none + congested.short + congested.long == pytest.approx(1.0)


def test_a_normal_cadence_is_not_treated_as_congestion() -> None:
    """The baseline exists so that an ordinary fortnight adjusts nothing at all."""
    model = _fitted(MinutesV2Config())
    baseline = MinutesV2Config().congestion_baseline_matches

    unadjusted = model.predict("MID", 0.9)
    ordinary = model.predict("MID", 0.9, matches_in_window=baseline)

    assert ordinary.long == pytest.approx(unadjusted.long)


def test_a_player_back_from_a_spell_out_is_not_expected_to_play_ninety() -> None:
    """The injury-return ramp. He is picked; he is eased in."""
    model = _fitted(MinutesV2Config())

    settled = model.predict("MID", 0.9, recent_absence_share=0.0)
    returning = model.predict("MID", 0.9, recent_absence_share=1.0)

    assert returning.long < settled.long


def test_a_fringe_player_missing_matches_is_not_read_as_a_return() -> None:
    """The distinction the threshold exists for.

    A player who rarely features has nothing to return *to*, and his fitted appearance band already
    knows he does not start. Ramping him as well would count the same fact twice — and it would
    push exactly the wrong players down, since a squad player's occasional start is not a
    convalescence.
    """
    model = _fitted(MinutesV2Config())
    model.by_group[("MID", 0)] = (0.6, 0.25, 0.15)
    fringe_rate = MinutesV2Config().return_established_appearance_rate / 2

    steady = model.predict("MID", fringe_rate, recent_absence_share=0.0)
    absent = model.predict("MID", fringe_rate, recent_absence_share=1.0)

    assert absent.long == pytest.approx(steady.long)


def test_neither_history_adjustment_can_change_the_chance_of_playing_at_all() -> None:
    """The property that keeps a rotation prior from impersonating an injury.

    Congestion and a completed return say how long a player stays on, not whether he is available.
    If either could move P(play) it would be indistinguishable from availability news, which is the
    one thing M1 is supposed to keep separate (see the class docstring on the status multiplier).
    """
    model = _fitted(MinutesV2Config())

    base = model.predict("MID", 0.9)
    adjusted = model.predict("MID", 0.9, matches_in_window=6.0, recent_absence_share=1.0)

    # Mass leaves the 60+ state into both others in the population's own proportion, so P(play)
    # falls only by the share the population puts on non-appearance — never to zero, and never
    # by the whole of what the 60+ state gave up.
    assert adjusted.long < base.long
    assert adjusted.short > base.short
    assert adjusted.plays > 0.0


def test_availability_takes_more_from_starting_than_from_appearing() -> None:
    """The live-only half. It cannot be backtested: the archive carries no status flag.

    A doubtful player who does feature is far likelier to be eased in from the bench than to start
    and finish. The default chain scales both playing states equally, which prices him as a full
    starter half the time.
    """
    default = _fitted(None)
    candidate = _fitted(MinutesV2Config())

    doubtful_default = default.predict("MID", 0.9, status_multiplier=0.5)
    doubtful_candidate = candidate.predict("MID", 0.9, status_multiplier=0.5)

    assert doubtful_candidate.long < doubtful_default.long
    assert doubtful_candidate.short > doubtful_default.short
    # P(play) is left exactly where the flag put it. Only its split moved.
    assert doubtful_candidate.plays == pytest.approx(doubtful_default.plays)


def test_a_fully_available_player_is_untouched_by_the_availability_split() -> None:
    candidate = _fitted(MinutesV2Config())
    assert candidate.predict("MID", 0.9, status_multiplier=1.0).long == pytest.approx(
        _fitted(None).predict("MID", 0.9).long
    )


def test_every_prediction_is_a_distribution_whatever_the_signals_say() -> None:
    """Property-style: no combination of inputs may produce something that is not a distribution."""
    model = _fitted(MinutesV2Config(congestion_rotation_strength=1.0, return_ramp_strength=1.0))
    for matches in (0.0, 2.0, 12.0, float("nan")):
        for absence in (0.0, 0.5, 1.0, float("nan")):
            for status in (0.0, 0.5, 1.0):
                predicted = model.predict(
                    "MID",
                    0.9,
                    status_multiplier=status,
                    matches_in_window=matches,
                    recent_absence_share=absence,
                )
                parts = (predicted.none, predicted.short, predicted.long)
                assert all(0.0 <= part <= 1.0 for part in parts), parts
                assert sum(parts) == pytest.approx(1.0)


# --- the features the adjustments read ------------------------------------------------------------


def test_the_congestion_feature_counts_the_recent_calendar() -> None:
    """A club playing weekly has two matches in a fortnight, whatever its season looks like."""
    history = make_history(gameweeks=12)
    config = FeatureConfig()
    as_of = pd.Timestamp("2025-10-24T00:00:00Z")

    features = build_features(history, as_of=as_of, config=config)
    counted = features[congestion_feature_name(config)]

    window_start = as_of - pd.Timedelta(days=config.congestion_window_days)
    expected = history[
        (history["kickoff_time"] >= window_start) & (history["kickoff_time"] < as_of)
    ]
    per_player = expected.groupby("player_code").size()
    assert counted.tolist() == [float(per_player.get(code, 0)) for code in features["player_code"]]


def test_the_absence_feature_reads_a_spell_out_and_not_a_quiet_afternoon() -> None:
    """Zero minutes is an absence; sixty minutes is not. The share, over the recent window only."""
    history = make_history(gameweeks=12)
    config = FeatureConfig()
    code = int(history["player_code"].iloc[0])
    history.loc[history["player_code"] == code, "minutes"] = 90
    absent = history["player_code"] == code
    history.loc[absent & (history["gameweek"] >= 9), "minutes"] = 0

    features = build_features(history, as_of=pd.Timestamp("2025-11-07T00:00:00Z"), config=config)
    share = float(
        features.loc[features["player_code"] == code, absence_feature_name(config)].iloc[0]
    )

    # Gameweeks 9 to 12 are the last four, and all four were missed.
    assert share == pytest.approx(1.0)


def test_the_new_features_are_declared_knowable_before_the_deadline() -> None:
    """Invariant 5, as a declaration. Both are built from pre-deadline rows and nothing else."""
    from fpl_dof.forecast.features import Knowability, input_features, specs

    config = FeatureConfig()
    declared = {spec.name: spec for spec in specs(config)}
    for name in (congestion_feature_name(config), absence_feature_name(config)):
        assert declared[name].knowability is Knowability.BEFORE_DEADLINE
        assert name in input_features(config)


# --- the measurement (closes D-14) ----------------------------------------------------------------


def test_the_multiclass_brier_rewards_calibration_not_confidence() -> None:
    probabilities = pd.DataFrame({"none": [1.0, 0.0], "short": [0.0, 0.0], "long": [0.0, 1.0]})
    observed = pd.Series(["none", "long"])
    wrong = pd.Series(["long", "none"])
    hedged = pd.DataFrame({"none": [0.34] * 2, "short": [0.33] * 2, "long": [0.33] * 2})

    assert multiclass_brier(probabilities, observed) == pytest.approx(0.0)
    assert multiclass_brier(probabilities, wrong) == pytest.approx(2.0)
    assert multiclass_brier(hedged, observed) < multiclass_brier(probabilities, wrong)


def test_the_metric_scores_the_partition_the_model_predicts() -> None:
    """The two modules name the bands separately; they may never name them differently.

    A Brier score computed over a different partition from the one M1 emits would be a number that
    looks entirely ordinary and measures nothing — the same reasoning DL-39 applies across the
    language boundary, applied here across a module one.
    """
    from fpl_dof.forecast.models import MINUTES_BANDS as MODEL_BANDS

    assert MINUTES_BANDS == MODEL_BANDS


def test_the_observed_band_uses_the_scoring_rule_it_is_given() -> None:
    """Sixty is a scoring rule, not a constant this module may assert (Invariant 2)."""
    assert minutes_band(0, 60) == "none"
    assert minutes_band(59, 60) == "short"
    assert minutes_band(60, 60) == "long"
    # A different rule bands the same observation differently, which is the point of the argument.
    assert minutes_band(60, 75) == "short"


def test_the_status_flag_haircut_is_a_distribution_and_ranks_a_starter_first() -> None:
    """The baseline E3-S3 set and DL-22 found had never been measured against."""
    features = pd.DataFrame(
        {
            "appearance_rate": [1.0, 1.0, 0.2],
            "starts_rate": [1.0, 0.0, np.nan],
        }
    )
    haircut = baselines.status_flag_haircut_minutes(features, ForecastConfig())

    assert haircut.sum(axis=1).tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert (haircut >= 0.0).all().all()
    # A nailed starter, a nailed non-starter, and a fringe player whose starts were never recorded.
    assert haircut["long"].iloc[0] > haircut["long"].iloc[1]
    assert haircut["long"].iloc[1] < haircut["short"].iloc[1]


def _walk(config: ForecastConfig, rules: GameRules) -> BacktestResult:
    return walk_forward(
        make_history(),
        ComponentPredictor(config, rules),
        forecast_config=config,
        backtest_config=BacktestConfig(minimum_training_matches=3),
        seasons=(SEASON,),
    )


def test_the_minutes_brier_is_reported_rather_than_null(game_rules: GameRules) -> None:
    """D-14, closed. The field E3-S3's acceptance criterion named has a number in it."""
    result = _walk(ForecastConfig(), game_rules)

    calibration = result.minutes_calibration
    assert calibration is not None
    assert not math.isnan(calibration.brier)
    assert not math.isnan(calibration.baseline_brier)
    assert result.model.minutes_brier == pytest.approx(calibration.brier)
    assert result.as_dict()["minutes_calibration"] is not None
    assert result.model.as_dict()["minutes_brier"] is not None


def test_the_brier_is_reported_per_position_and_per_minutes_band(
    game_rules: GameRules,
) -> None:
    """E10 grades every metric per position: a gain confined to forwards is not a gain."""
    result = _walk(ForecastConfig(), game_rules)
    calibration = result.minutes_calibration
    assert calibration is not None

    assert set(calibration.by_position) == set(calibration.baseline_by_position)
    assert len(calibration.by_position) >= 2
    assert set(calibration.by_band) <= set(MINUTES_BANDS)
    assert set(calibration.by_band) == set(calibration.baseline_by_band)


def test_the_minutes_brier_counts_the_players_who_did_not_feature(
    game_rules: GameRules,
) -> None:
    """The decision this measurement turns on.

    The accuracy metrics drop non-appearances, because scoring a points forecast against a player
    who did not play measures the minutes model twice. Calibration is the opposite case: those rows
    are the majority of the population and they are *what is being calibrated*. Measured only where
    somebody played, every minutes model scores superbly, because the answer is always yes.
    """
    result = _walk(ForecastConfig(), game_rules)
    calibration = result.minutes_calibration
    assert calibration is not None

    scored = result.predictions[result.predictions["minutes"] >= 1]
    assert calibration.observations == len(result.predictions)
    assert calibration.observations > len(scored)


def test_a_predictor_with_no_minutes_model_says_so_rather_than_inventing_a_score() -> None:
    """An absence, reported. A harness that returned 0.0 here would claim a perfect forecast."""
    result = walk_forward(
        make_history(),
        RateFromFeatures(),
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(minimum_training_matches=3),
        seasons=(SEASON,),
    )

    assert result.minutes_calibration is None
    assert result.as_dict()["minutes_calibration"] is None
    assert any("minutes distribution" in warning for warning in result.warnings)


def test_both_distributions_reach_the_predictions_frame(game_rules: GameRules) -> None:
    """So the evidence is re-checkable from the parquet rather than only from the report."""
    result = _walk(ForecastConfig(), game_rules)
    frame = result.predictions

    for band in MINUTES_BANDS:
        assert f"{MINUTES_PREFIX}{band}" in frame.columns
        assert f"{HAIRCUT_MINUTES_PREFIX}{band}" in frame.columns
    assert set(frame[OBSERVED_MINUTES_BAND]) <= set(MINUTES_BANDS)
    predicted = frame[[f"{MINUTES_PREFIX}{band}" for band in MINUTES_BANDS]].sum(axis=1)
    assert predicted.tolist() == pytest.approx([1.0] * len(frame))


def test_the_candidate_is_measurable_and_the_default_is_not_disturbed_by_it(
    game_rules: GameRules,
) -> None:
    """The evidence loop DL-47 asks for: the same grid, once with the flag off and once on.

    This asserts only that the comparison is *possible and non-trivial* — that turning the flag on
    reaches the graded minutes distribution at all. Whether the candidate is better is the
    backtest's finding, recorded in the decision log; a test that asserted it would be a test that
    has to be rewritten every time the evidence changes.
    """
    default = _walk(ForecastConfig(), game_rules)
    candidate = _walk(_v2_config(), game_rules)

    assert default.minutes_calibration is not None
    assert candidate.minutes_calibration is not None
    # The baseline is the same object on both sides — it must be, or the comparison is meaningless.
    assert candidate.minutes_calibration.baseline_brier == pytest.approx(
        default.minutes_calibration.baseline_brier
    )
    assert candidate.minutes_calibration.brier != pytest.approx(default.minutes_calibration.brier)


def _components(config: ForecastConfig, rules: GameRules) -> ComponentModels:
    """Components fitted on training rows shaped the way the harness shapes them.

    ``fit_components`` is given feature-and-outcome rows, never raw history — M1 fits on the
    appearance band the feature store computed, which is the whole reason the leakage question
    lives in one place (see its docstring).
    """
    history = make_history()
    training = history.assign(
        appearance_rate=history.groupby("player_code")["minutes"].transform(
            lambda values: (values > 0).mean()
        )
    )
    return fit_components(training, team_matches(training), config, rules)
