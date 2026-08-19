"""E3-S1 and E3-S2 — the backtest harness, the baselines, and the leakage guard.

**The leakage tests are the ones that matter.** Everything else here checks that a number is
computed correctly; those check that the number means anything at all. A leaked feature produces a
model that scores brilliantly in the backtest and is worthless in the season, and there is no way to
notice from the metrics — they look *better*, not worse. That is precisely the "wrong invisibly"
case DP-13 says to test hardest.

The construction used throughout: a synthetic history where **each player's points are fixed by
their identity**, so a correct model must be able to learn them and a leaking one is caught by a
targeted probe rather than by a suspicious-looking score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import BacktestConfig, FeatureConfig, ForecastConfig
from fpl_dof.forecast import baselines
from fpl_dof.forecast.backtest import (
    B0_COLUMN,
    FORM_COLUMN,
    MODEL_COLUMN,
    OUTCOME_COLUMNS,
    BacktestResult,
    Predictor,
    deadlines_for,
    walk_forward,
)
from fpl_dof.forecast.features import (
    FIXTURE_AT_HOME,
    FIXTURE_COLUMNS,
    FIXTURE_OPPONENT,
    FIXTURE_TEAM,
    TARGET,
    Knowability,
    build_features,
    input_features,
    specs,
)
from fpl_dof.forecast.metrics import (
    UNRESOLVED_FIXTURE_BAND,
    brier_score,
    calibration_slope,
    captaincy_hit_rate,
    evaluate,
    fixture_difficulty_band,
    spearman,
    top_n_precision,
)
from fpl_dof.forecast.models import RATE_COMPONENTS
from fpl_dof.forecast.xp_v1 import ComponentPredictor
from fpl_dof.frames import as_float, as_int
from fpl_dof.rules.models import GameRules

SEASON = "2025/26"
POSITIONS = ("GKP", "DEF", "MID", "FWD")
TEAMS = (1, 2, 3, 4, 5, 6)


def round_robin(gameweek: int) -> dict[int, tuple[int, bool, int]]:
    """A **coherent** calendar: club -> (opponent, at home, fixture id), one fixture each.

    Worth the twelve lines. The fixture this file used before E9-S2 derived the opponent from the
    *player* rather than the club, so two players of the same side could face different opponents
    in the same gameweek — a calendar that cannot exist, and one that would let a fixture join look
    like it worked while joining nothing real. A harness test built on an impossible schedule
    grades the join, not the fixture.
    """
    fixed, rotating = TEAMS[0], list(TEAMS[1:])
    shift = (gameweek - 1) % len(rotating)
    order = rotating[shift:] + rotating[:shift]
    half = len(TEAMS) // 2
    left = [fixed, *order[: half - 1]]
    right = list(reversed(order[half - 1 :]))

    schedule: dict[int, tuple[int, bool, int]] = {}
    for home, away in zip(left, right, strict=True):
        # Venues alternate by gameweek so every club is measured both home and away.
        if gameweek % 2 == 0:
            home, away = away, home
        fixture_id = gameweek * 100 + min(home, away)
        schedule[home] = (away, True, fixture_id)
        schedule[away] = (home, False, fixture_id)
    return schedule


def make_history(
    *, players: int = 24, gameweeks: int = 12, seed: int = 7, season: str = SEASON
) -> pd.DataFrame:
    """Per-gameweek history where each player has a fixed underlying scoring rate.

    Real enough to exercise the harness, and simple enough that a leak is detectable: a model with
    access to the outcome can predict it exactly, and one without cannot.
    """
    rng = np.random.default_rng(seed)
    rows = []
    start = pd.Timestamp("2025-08-15T18:00:00Z")
    calendar = {gameweek: round_robin(gameweek) for gameweek in range(1, gameweeks + 1)}
    for player in range(1, players + 1):
        rate = 2.0 + (player % 8)
        team = (player % 6) + 1
        for gameweek in range(1, gameweeks + 1):
            kickoff = start + pd.Timedelta(days=7 * (gameweek - 1))
            minutes = int(rng.integers(0, 91))
            opponent, at_home, fixture_id = calendar[gameweek][team]
            rows.append(
                {
                    "season": season,
                    "gameweek": gameweek,
                    "player_code": 100_000 + player,
                    "player_id": player,
                    "web_name": f"P{player}",
                    "position": POSITIONS[player % 4],
                    "team_id": team,
                    "opponent_team_id": opponent,
                    "fixture_id": fixture_id,
                    "kickoff_time": kickoff,
                    "was_home": at_home,
                    "minutes": minutes,
                    "starts": 1 if minutes >= 60 else 0,
                    # A deterministic per-club offset on top of the noise, so M2 has real attack
                    # and defence ratings to contribute and a fixture is genuinely easier or
                    # harder than another rather than only different.
                    "goals_scored": int(rng.integers(0, 2)) + (1 if team >= 5 else 0),
                    "assists": int(rng.integers(0, 2)),
                    "clean_sheets": int(rng.integers(0, 2)),
                    "goals_conceded": int(rng.integers(0, 3)) + (6 - team) // 2,
                    "own_goals": 0,
                    "penalties_saved": 0,
                    "penalties_missed": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "saves": int(rng.integers(0, 4)),
                    "bonus": 0,
                    "bps": int(rng.integers(0, 40)),
                    "defensive_contribution": int(rng.integers(0, 3)),
                    "tackles": 1,
                    "recoveries": 1,
                    "clearances_blocks_interceptions": 1,
                    "expected_goals": 0.1,
                    "expected_assists": 0.1,
                    "expected_goals_conceded": 1.0,
                    "price": 4.0 + (player % 8) * 0.7,
                    "selected_by": 1000,
                    "total_points": float(rate + rng.normal(0, 0.5)),
                }
            )
    return pd.DataFrame(rows)


class RateFromFeatures:
    """A predictor that learns from features only. What a correct model looks like."""

    def __init__(self) -> None:
        self.by_code: dict[int, float] = {}
        self.fallback = 0.0

    def fit(self, training: pd.DataFrame) -> None:
        grouped = training.groupby("player_code")[TARGET].mean()
        self.by_code = {as_int(code): as_float(value) for code, value in grouped.items()}
        self.fallback = float(training[TARGET].mean())

    def predict(self, features: pd.DataFrame) -> pd.Series:
        return features["player_code"].map(self.by_code).fillna(self.fallback).astype(float)


class Cheater:
    """A predictor that returns the target. Only possible if the target reached it.

    Not a strawman: this is exactly the shape of a real leak — a merge that pulled the outcome
    column into the feature frame, which looks entirely ordinary in a diff.
    """

    def fit(self, training: pd.DataFrame) -> None:
        pass

    def predict(self, features: pd.DataFrame) -> pd.Series:
        if TARGET in features.columns:
            return features[TARGET].astype(float)
        raise AssertionError(
            "the outcome column reached the predictor: the harness handed a model the answer"
        )


# --- feature store (E3-S2) --------------------------------------------------------------------


def test_features_use_only_matches_that_had_finished() -> None:
    """Invariant 5, at the level it is actually enforced."""
    history = make_history()
    cutoff = pd.Timestamp("2025-09-05T00:00:00Z")

    features = build_features(history, as_of=cutoff, config=FeatureConfig())

    assert not features.empty
    assert (pd.to_datetime(features["as_of"], utc=True) == cutoff).all()

    # Recompute one player's window by hand from rows strictly before the cutoff.
    code = int(features["player_code"].iloc[0])
    visible = history[(history["player_code"] == code) & (history["kickoff_time"] < cutoff)]
    assert int(features.loc[features["player_code"] == code, "matches_observed"].iloc[0]) == len(
        visible
    )


def test_adding_future_matches_cannot_change_a_feature() -> None:
    """The decisive property: what happens after the deadline must not alter what came before.

    Stronger than checking a filter exists, because it holds whatever the implementation does — and
    it is exactly what a shifted-window optimisation would break.
    """
    history = make_history()
    cutoff = pd.Timestamp("2025-09-05T00:00:00Z")
    config = FeatureConfig()

    before = build_features(history[history["kickoff_time"] < cutoff], as_of=cutoff, config=config)
    with_future = build_features(history, as_of=cutoff, config=config)

    pd.testing.assert_frame_equal(
        before.sort_values("player_code").reset_index(drop=True),
        with_future.sort_values("player_code").reset_index(drop=True),
    )


def test_the_target_is_never_an_input() -> None:
    """A feature list that includes the outcome is the leak, stated as a list."""
    config = FeatureConfig()
    assert TARGET not in input_features(config)
    target_spec = next(spec for spec in specs(config) if spec.name == TARGET)
    assert target_spec.knowability is Knowability.AFTER_KICKOFF
    assert not target_spec.is_input


def test_an_unmeasured_column_is_null_not_zero() -> None:
    """DL-18's trap, at feature level. Zero would say "did none of it"."""
    history = make_history()
    history["defensive_contribution"] = pd.NA

    features = build_features(
        history, as_of=pd.Timestamp("2025-10-01T00:00:00Z"), config=FeatureConfig()
    )
    assert features["defensive_contribution_per90_last6"].isna().all()


def test_features_before_any_match_are_empty_rather_than_invented() -> None:
    history = make_history()
    features = build_features(
        history, as_of=pd.Timestamp("2025-01-01T00:00:00Z"), config=FeatureConfig()
    )
    assert features.empty


# --- the harness (E3-S1) ----------------------------------------------------------------------


def test_deadlines_are_ordered_and_one_per_gameweek() -> None:
    history = make_history(gameweeks=5)
    schedule = deadlines_for(history)

    assert [gameweek for _, gameweek, _ in schedule] == [1, 2, 3, 4, 5]
    times = [deadline for _, _, deadline in schedule]
    assert times == sorted(times)


def _walk(predictor: Predictor) -> BacktestResult:
    return walk_forward(
        make_history(),
        predictor,
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(minimum_training_matches=3),
        seasons=(SEASON,),
    )


def test_the_walk_produces_folds_and_every_baseline() -> None:
    result = _walk(RateFromFeatures())

    assert len(result.folds) > 0
    predictions = result.predictions
    for column in (MODEL_COLUMN, B0_COLUMN, FORM_COLUMN):
        assert column in predictions.columns
    assert result.b0.observations > 0
    assert result.model_free.observations > 0


def test_the_harness_never_hands_a_model_the_answer() -> None:
    """The leakage test that matters most.

    A predictor that simply returns the target column can only succeed if the harness gave it the
    target. It must not be able to.
    """
    with pytest.raises(AssertionError, match="handed a model the answer"):
        _walk(Cheater())


class ColumnRecorder:
    """A predictor that records exactly what it was shown."""

    def __init__(self) -> None:
        self.fitted: set[str] = set()
        self.seen: set[str] = set()

    def fit(self, training: pd.DataFrame) -> None:
        self.fitted |= set(training.columns)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        self.seen |= set(features.columns)
        return pd.Series(0.0, index=features.index, dtype=float)


def test_no_outcome_column_of_any_kind_reaches_a_prediction() -> None:
    """Not just the target: every column describing the gameweek being predicted.

    Widened when D-24 was found. The fold frame now carries the raw per-gameweek statistics so the
    component models can actually fit on them, which makes the drop list the only thing standing
    between a fitted model and a leaking one — so it is asserted rather than assumed.
    """
    recorder = ColumnRecorder()
    _walk(recorder)

    assert not recorder.seen & set(OUTCOME_COLUMNS)


def test_the_training_frame_carries_the_statistics_the_components_fit_on() -> None:
    """D-24. Without these columns ``RateModel.fit`` silently fits nothing.

    The failure it guards against is invisible in every metric: the models still predict, the
    backtest still runs, and every rate is shrunk toward zero rather than toward a position prior.
    """
    recorder = ColumnRecorder()
    _walk(recorder)

    for column in RATE_COMPONENTS:
        assert column in recorder.fitted


def test_the_components_actually_fit_a_position_prior_in_the_harness(
    game_rules: GameRules,
) -> None:
    """The end-to-end version of the check above, through the real predictor.

    Asserting on the fitted object rather than on its inputs, because "the column was present" and
    "the model learned from it" are different claims and D-24 was the gap between them.
    """
    predictor = ComponentPredictor(ForecastConfig(), game_rules)
    result = _walk(predictor)

    assert result.model.observations > 0
    assert predictor.models is not None
    for column in RATE_COMPONENTS:
        assert predictor.models.rates[column].prior_by_position, column
    assert predictor.models.team_strength.attack


def test_every_fold_is_stamped_at_its_own_deadline() -> None:
    """Each fold's features must claim to have been knowable exactly at that fold's deadline.

    A fold carrying a stamp from another deadline is the signature of a cached feature frame being
    reused across folds, which is the most plausible way this harness could start leaking.
    """
    result = _walk(RateFromFeatures())
    deadlines = set()
    for fold in result.folds:
        stamps = pd.to_datetime(fold.predictions["as_of"], utc=True)
        assert (stamps == fold.deadline).all()
        deadlines.add(fold.deadline)
    assert len(deadlines) == len(result.folds)


# --- fixtures in the fold frames (E9-S2) ------------------------------------------------------


def test_every_fold_row_carries_the_fixture_it_was_played_under() -> None:
    """E9-S2's premise. Without this the harness cannot see M2 at all.

    Checked against the calendar rather than against itself: the opponent on the row must be the
    opponent that club actually faced in that gameweek, and the venue must be the one the fixture
    gave the two sides opposite answers to.
    """
    result = _walk(RateFromFeatures())
    predictions = result.predictions

    for column in FIXTURE_COLUMNS:
        assert column in predictions.columns
    assert predictions[FIXTURE_OPPONENT].notna().all()
    assert result.fixture_coverage == pytest.approx(1.0)

    for row in predictions.itertuples():
        team = as_int(getattr(row, FIXTURE_TEAM))
        opponent, at_home, _ = round_robin(as_int(row.gameweek))[team]
        assert as_int(getattr(row, FIXTURE_OPPONENT)) == opponent
        assert bool(getattr(row, FIXTURE_AT_HOME)) is at_home
        assert team != opponent


def test_the_fixture_columns_are_declared_knowable_at_the_deadline() -> None:
    """Invariant 5, stated as a declaration rather than left to a comment.

    The calendar is published weeks ahead, so ``AT_DEADLINE`` is the truthful stamp — but only
    because these columns are built from the fixture calendar. Reading them off "did this player
    have a row" would be a different, unknowable question wearing the same name.
    """
    declared = {spec.name: spec for spec in specs(FeatureConfig())}
    for column in FIXTURE_COLUMNS:
        assert declared[column].knowability is Knowability.AT_DEADLINE
        assert declared[column].is_input
        assert column in input_features(FeatureConfig())

    # The pre-existing rolling `was_home` means the *previous* match and is a different feature.
    assert "was_home" not in FIXTURE_COLUMNS


def test_the_fixture_columns_reach_the_predictor_and_the_outcome_still_does_not() -> None:
    """The two halves of the same claim: the fixture is an input, the result is never one."""
    recorder = ColumnRecorder()
    _walk(recorder)

    assert set(FIXTURE_COLUMNS) <= recorder.seen
    assert not recorder.seen & set(OUTCOME_COLUMNS)
    # `team_id` stays an outcome column and stays stripped; the alias is what survives.
    assert "team_id" not in recorder.seen


def test_a_double_gameweek_is_scored_once_per_fixture() -> None:
    """The deliberate choice: one prediction per fixture, not one per gameweek.

    Each fold row already owns exactly one outcome — the points scored in *that* match — so scoring
    per fixture compares like with like. Aggregating to a gameweek total would need the outcomes
    summed too, and would grade a double against a number no single fixture produced.
    """
    history = make_history()
    extra = history[(history["gameweek"] == 6) & (history["team_id"] == 1)].copy()
    extra["fixture_id"] = 9_999
    extra["opponent_team_id"] = 3
    extra["was_home"] = False
    extra["kickoff_time"] = extra["kickoff_time"] + pd.Timedelta(days=2)
    doubled = pd.concat([history, extra], ignore_index=True)

    result = walk_forward(
        doubled,
        RateFromFeatures(),
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(minimum_training_matches=3),
        seasons=(SEASON,),
    )
    fold = next(fold for fold in result.folds if fold.gameweek == 6)
    rows = fold.predictions
    team_one = rows[rows[FIXTURE_TEAM] == 1]
    counted = team_one.groupby("player_code").size()
    assert (counted == 2).all()
    # Two fixtures, two different opponents, each with its own outcome to be graded against.
    assert set(team_one[FIXTURE_OPPONENT].dropna().astype(int)) == {
        round_robin(6)[1][0],
        3,
    }
    assert rows[FIXTURE_OPPONENT].notna().all()


def test_real_opposition_moves_the_prediction(game_rules: GameRules) -> None:
    """The companion to E9-S1's "the parity test can fail".

    A fixture join that reached the frame but never reached the arithmetic would pass every test
    above and change nothing. So: the same players, the same fitted components, two fixtures — the
    numbers must differ, and in the direction the ratings imply.
    """
    predictor = ComponentPredictor(ForecastConfig(), game_rules)
    _walk(predictor)
    models = predictor.models
    assert models is not None
    models.team_strength.attack[1] = 2.0
    models.team_strength.defence[2] = 2.0

    history = make_history()
    deadline = pd.Timestamp("2025-10-01T00:00:00Z")
    past = history[history["kickoff_time"] < deadline]
    features = build_features(
        past,
        as_of=deadline,
        config=FeatureConfig(),
        positions=past[["player_code", "position"]],
    )

    league_average = predictor.predict(features)
    easy = predictor.predict(
        features.assign(
            **{FIXTURE_TEAM: 1, FIXTURE_OPPONENT: 2, FIXTURE_AT_HOME: True},
        )
    )
    hard = predictor.predict(
        features.assign(
            **{FIXTURE_TEAM: 2, FIXTURE_OPPONENT: 1, FIXTURE_AT_HOME: False},
        )
    )

    assert not np.allclose(easy.to_numpy(), league_average.to_numpy())
    assert float(easy.sum()) > float(hard.sum())


def test_the_report_carries_a_fixture_conditioned_breakdown() -> None:
    """E9-S2's acceptance criterion, and the gate E11 depends on."""
    result = _walk(RateFromFeatures())

    bands = result.model.spearman_by_fixture_band
    assert len(bands) >= 2, bands
    assert UNRESOLVED_FIXTURE_BAND not in bands
    assert set(result.model.calibration_by_fixture_band) == set(bands)
    assert any(not np.isnan(value) for value in bands.values())

    published = result.model.as_dict()
    assert published["spearman_by_fixture_band"] == {
        band: (None if np.isnan(value) else round(value, 5)) for band, value in bands.items()
    }
    assert "calibration_by_fixture_band" in published
    assert result.as_dict()["fixture_coverage"] == pytest.approx(1.0)


def test_the_bands_cut_at_the_configured_ratio_and_its_reciprocal() -> None:
    """DP-06: one named, defaulted, justified tunable — not two edges free to disagree."""
    ratio = BacktestConfig().fixture_difficulty_band_ratio
    assert fixture_difficulty_band(1.0, ratio) == "average"
    assert fixture_difficulty_band(ratio * 1.01, ratio) == "hard"
    assert fixture_difficulty_band(1.0 / ratio * 0.99, ratio) == "easy"
    assert fixture_difficulty_band(float("nan"), ratio) == UNRESOLVED_FIXTURE_BAND


def test_an_unresolvable_fixture_falls_back_visibly_rather_than_silently() -> None:
    """DP-15. Degrading to league-average opposition is allowed; doing it quietly is not."""
    history = make_history()
    history["opponent_team_id"] = pd.NA

    result = walk_forward(
        history,
        RateFromFeatures(),
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(minimum_training_matches=3),
        seasons=(SEASON,),
    )
    assert result.fixture_coverage == pytest.approx(0.0)
    assert any("league-average opposition" in warning for warning in result.warnings)
    assert set(result.model.spearman_by_fixture_band) == {UNRESOLVED_FIXTURE_BAND}


def test_a_model_with_real_signal_beats_the_constant_baseline() -> None:
    """Sanity in the opposite direction: the harness must be *able* to detect an edge.

    Without this, the leakage tests above would pass on a harness that returns noise for everyone.
    """
    result = _walk(RateFromFeatures())
    assert result.model.mae < result.mean_baseline.mae


def test_the_verdict_names_the_finding_rather_than_a_score() -> None:
    result = _walk(RateFromFeatures())
    verdict = result.verdict()
    assert isinstance(verdict, str) and verdict
    assert ("B0" in verdict) or ("model-free" in verdict)


def test_too_little_history_measures_nothing_and_says_so() -> None:
    """Distinct from measuring a poor model, and the difference is the whole point."""
    history = make_history(gameweeks=2)
    with pytest.raises(ValueError, match="measured nothing"):
        walk_forward(
            history,
            RateFromFeatures(),
            forecast_config=ForecastConfig(),
            backtest_config=BacktestConfig(minimum_training_matches=10),
            seasons=(SEASON,),
        )


# --- baselines --------------------------------------------------------------------------------


def test_b0_uses_only_price_and_position() -> None:
    """If B0 could see anything else it would stop being the comparison the thresholds rest on."""
    training = make_history()
    fitted = baselines.fit_b0(training, TARGET)

    frame = pd.DataFrame(
        {"position": ["MID", "FWD"], "price": [5.0, 9.0], "irrelevant": [999.0, -999.0]}
    )
    predicted = fitted.predict(frame)
    frame["irrelevant"] = [0.0, 0.0]
    assert (predicted == fitted.predict(frame)).all()


def test_b0_fits_a_separate_line_per_position() -> None:
    training = make_history()
    fitted = baselines.fit_b0(training, TARGET)
    assert set(fitted.slope_by_position) == set(POSITIONS)


def test_b0_falls_back_rather_than_refusing_to_predict() -> None:
    """A baseline that returns NaN cannot be beaten, which defeats the point of having one."""
    fitted = baselines.fit_b0(make_history(), TARGET)
    unseen = pd.DataFrame({"position": ["XXX"], "price": [6.0]})
    assert fitted.predict(unseen).notna().all()


def test_the_model_free_benchmark_uses_no_model() -> None:
    """Its independence is its whole value: it cannot be flattered by a poor forecast."""
    history = make_history()
    cutoff = pd.Timestamp("2025-10-01T00:00:00Z")
    form = baselines.trailing_form_prediction(history, as_of=cutoff)

    assert not form.empty
    assert set(form.columns) == {"player_code", "prediction"}

    # Changing anything after the cutoff cannot change it.
    tampered = history.copy()
    tampered.loc[tampered["kickoff_time"] >= cutoff, "total_points"] = 100.0
    pd.testing.assert_frame_equal(form, baselines.trailing_form_prediction(tampered, as_of=cutoff))


# --- metrics ----------------------------------------------------------------------------------


def test_skill_score_is_zero_when_the_model_equals_the_baseline() -> None:
    """The property that makes the number readable: zero means "no better than the baseline"."""
    frame = pd.DataFrame(
        {
            "predicted": [1.0, 2.0, 3.0],
            "base": [1.0, 2.0, 3.0],
            "actual": [1.5, 2.5, 2.5],
            "position": ["MID"] * 3,
            "price": [5.0] * 3,
        }
    )
    metrics = evaluate(frame, name="m", predicted="predicted", actual="actual", baseline="base")
    assert metrics.mae_skill_score == pytest.approx(0.0)


def test_skill_score_is_negative_when_the_model_is_worse() -> None:
    # The baseline is imperfect but close; the model is far out. A *perfect* baseline would make
    # skill undefined rather than infinitely negative, which is deliberate and tested separately.
    frame = pd.DataFrame(
        {
            "predicted": [10.0, 10.0, 10.0],
            "base": [1.2, 2.2, 3.2],
            "actual": [1.0, 2.0, 3.0],
            "position": ["MID"] * 3,
            "price": [5.0] * 3,
        }
    )
    metrics = evaluate(frame, name="m", predicted="predicted", actual="actual", baseline="base")
    assert metrics.mae_skill_score < 0


def test_a_perfect_baseline_makes_skill_undefined_rather_than_infinite() -> None:
    """It has never happened and would mean the target leaked into the baseline."""
    frame = pd.DataFrame(
        {
            "predicted": [1.0, 2.0, 3.0],
            "base": [1.0, 2.0, 3.0],
            "actual": [1.0, 2.0, 3.0],
            "position": ["MID"] * 3,
            "price": [5.0] * 3,
        }
    )
    metrics = evaluate(frame, name="m", predicted="predicted", actual="actual", baseline="base")
    assert np.isnan(metrics.mae_skill_score)


def test_spearman_is_undefined_rather_than_zero_when_it_cannot_be_computed() -> None:
    """Zero would be a claim of "no relationship". NaN is the absence of one."""
    flat = pd.Series([1.0, 1.0, 1.0])
    assert np.isnan(spearman(flat, pd.Series([1.0, 2.0, 3.0])))
    assert np.isnan(spearman(pd.Series([1.0]), pd.Series([1.0])))


def test_perfect_ranking_scores_one() -> None:
    assert spearman(pd.Series([1.0, 2.0, 3.0]), pd.Series([10.0, 20.0, 30.0])) == pytest.approx(1.0)


def test_calibration_slope_is_one_when_predictions_are_calibrated() -> None:
    values = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert calibration_slope(values, values) == pytest.approx(1.0)


def test_top_n_precision_counts_the_overlap_at_the_head() -> None:
    frame = pd.DataFrame({"p": [5.0, 4.0, 3.0, 2.0], "a": [5.0, 4.0, 1.0, 9.0]})
    assert top_n_precision(frame, n=2, predicted="p", actual="a") == pytest.approx(0.5)


def test_captaincy_hit_rate_is_all_or_nothing() -> None:
    """Harsh by design: captaincy concentrates the cost of being wrong on one player."""
    right = pd.DataFrame({"p": [9.0, 1.0], "a": [9.0, 1.0]})
    wrong = pd.DataFrame({"p": [9.0, 1.0], "a": [1.0, 9.0]})
    assert captaincy_hit_rate(right, predicted="p", actual="a") == 1.0
    assert captaincy_hit_rate(wrong, predicted="p", actual="a") == 0.0


def test_brier_score_rewards_calibration_not_confidence() -> None:
    confident_and_right = brier_score(pd.Series([1.0, 0.0]), pd.Series([1.0, 0.0]))
    confident_and_wrong = brier_score(pd.Series([1.0, 0.0]), pd.Series([0.0, 1.0]))
    hedged = brier_score(pd.Series([0.5, 0.5]), pd.Series([1.0, 0.0]))

    assert confident_and_right == pytest.approx(0.0)
    assert hedged < confident_and_wrong
