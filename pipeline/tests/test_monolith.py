"""E10-S5 — the blended monolith, as a permanent shadow benchmark.

The monolith exists to put a number on one question DP-10 otherwise leaves to faith: *what is the
component chain's explainability costing at the head of the ranking?* It is a benchmark and never
a candidate — [DL-53](../../docs/planning/00-decision-log.md) — so these tests are not about whether
it is any good. They are about the three ways a shadow benchmark goes silently wrong:

1. **It leaks.** A monolith fitted through its own training assembly is
   [DL-28](../../docs/planning/00-decision-log.md)'s trap with a second set of hands: it would
   report a gap that is entirely its own dishonesty, and the metrics would look *better*, not
   worse. Invariant 5, DP-13, and the reason the harness fits it through the same
   `training_rows`/`fold_rows` machinery the chain uses.
2. **It reaches something.** A benchmark that quietly informs the published ranking is no longer a
   benchmark. There is no flag to switch on and nothing downstream imports it, and both are asserted
   rather than intended.
3. **It becomes inert and reports a gap of zero**, which reads as *explainability is free* and means
   *nothing was measured*. DP-15's "degrade visibly" applied to a measurement rather than to a
   forecast.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import fpl_dof
from fpl_dof.config.models import (
    BacktestConfig,
    DiscriminationConfig,
    FeatureConfig,
    ForecastConfig,
    MonolithConfig,
)
from fpl_dof.forecast.backtest import (
    MODEL_COLUMN,
    MONOLITH_COLUMN,
    OUTCOME_COLUMNS,
    BacktestResult,
    walk_forward,
)
from fpl_dof.forecast.features import TARGET, input_features
from fpl_dof.forecast.monolith import (
    POSITION,
    MonolithPredictor,
    encoding_for,
    gap_by_position,
    gap_statement,
    head_gap,
)
from test_backtest import SEASON, RateFromFeatures, make_history

SRC = Path(fpl_dof.__file__).parent


def dense_history(**overrides: object) -> pd.DataFrame:
    """A history big enough that the monolith actually fits rather than degrading.

    ``make_history``'s default is two dozen players, which gives a fold about a hundred training
    rows — below ``MonolithConfig.minimum_training_rows``, so the monolith correctly falls back to
    a constant. A constant passes a look-ahead test trivially, which is the worst possible way for
    that test to pass, so anything asserting on the monolith's *behaviour* uses this instead. That
    the small fixture degrades is itself asserted, further down.
    """
    return make_history(players=80, gameweeks=12, **overrides)  # type: ignore[arg-type]


def _walk(history: pd.DataFrame) -> BacktestResult:
    return walk_forward(
        history,
        RateFromFeatures(),
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(minimum_training_matches=3),
        seasons=(SEASON,),
    )


def _fitted(history: pd.DataFrame | None = None) -> tuple[MonolithPredictor, pd.DataFrame]:
    """A monolith fitted on a frame shaped like the one the harness actually hands it.

    Built from the harness's own fixture rather than from a hand-written frame, because the thing
    most worth checking is what happens to *those* columns.
    """
    training = _training_frame(history if history is not None else dense_history())
    monolith = MonolithPredictor(config=MonolithConfig(), features=FeatureConfig())
    monolith.fit(training)
    return monolith, training


def _training_frame(history: pd.DataFrame) -> pd.DataFrame:
    """One fold's worth of training rows, assembled the way the harness assembles them."""
    from fpl_dof.forecast.backtest import fold_rows

    frames = [
        fold_rows(
            history,
            SEASON,
            gameweek,
            pd.Timestamp(history[history["gameweek"] == gameweek]["kickoff_time"].min()),
            ForecastConfig(),
        )
        for gameweek in range(2, 11)
    ]
    return pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)


# --- look-ahead: the failure that would look like a success -------------------------------------


def test_the_monoliths_feature_list_is_an_allow_list_of_declared_inputs() -> None:
    """Invariant 5 at the level it is enforced, which is a list rather than a habit.

    The monolith reads what the feature store *declares* as an input — every one of those stamped
    ``BEFORE_DEADLINE`` or ``AT_DEADLINE`` — plus the position. A deny-list would admit a new
    outcome column the day somebody added one, silently, and the backtest would improve.
    """
    monolith, _ = _fitted()
    assert monolith.encoding is not None
    permitted = {*input_features(FeatureConfig()), POSITION}
    assert set(monolith.encoding.columns) <= permitted
    assert monolith.encoding.columns, "the monolith read nothing at all"


def test_no_outcome_column_is_in_the_monoliths_feature_list() -> None:
    """The same claim stated against the harness's own list of what happened in the gameweek.

    ``_training_frame`` deliberately carries every outcome column, because that is what the real
    training frame carries — the component models fit on them. So this is not vacuous: the columns
    are present and must not have been selected.
    """
    monolith, training = _fitted()
    assert monolith.encoding is not None
    assert set(OUTCOME_COLUMNS) <= set(training.columns), "the fixture is not exercising anything"
    assert not set(monolith.encoding.columns) & set(OUTCOME_COLUMNS)
    assert TARGET not in monolith.encoding.columns


def test_attaching_the_outcome_to_a_scoring_frame_cannot_move_a_prediction() -> None:
    """The behavioural half. A column list can be right while the matrix builder reads elsewhere."""
    monolith, training = _fitted()
    scoring = training.drop(columns=list(OUTCOME_COLUMNS), errors="ignore")

    plain = monolith.predict(scoring)
    with_answers = monolith.predict(
        scoring.assign(**{TARGET: 100.0, "minutes": 90, "goals_scored": 5})
    )
    pd.testing.assert_series_equal(plain, with_answers)


def test_what_happens_after_a_deadline_cannot_change_that_folds_monolith() -> None:
    """**The look-ahead regression test.** The decisive property, through the real harness.

    A second training assembly is a second chance to leak, which is exactly what
    [DL-28](../../docs/planning/00-decision-log.md) warns about for a different piece of code — so
    the monolith is fitted by ``walk_forward`` on the same ``training_rows`` frame the chain gets.
    This asserts the consequence rather than the mechanism: gameweek 7's predictions are refitted
    against a history in which every later gameweek has been rewritten, and they must be
    *identical*. A leak of any size shows up here as a difference, and would show up nowhere else —
    the metrics would simply improve.
    """
    history = dense_history()
    tampered = history.copy()
    later = tampered["gameweek"] >= 8
    tampered.loc[later, TARGET] = 100.0
    tampered.loc[later, "goals_scored"] = 9
    tampered.loc[later, "minutes"] = 90

    def fold_seven(result: BacktestResult) -> pd.DataFrame:
        fold = next(fold for fold in result.folds if fold.gameweek == 7)
        return fold.predictions.sort_values("player_code").reset_index(drop=True)

    honest, rewritten = fold_seven(_walk(history)), fold_seven(_walk(tampered))

    assert not honest.empty
    pd.testing.assert_series_equal(
        honest[MONOLITH_COLUMN], rewritten[MONOLITH_COLUMN], check_names=False
    )
    # And the chain beside it, so a passing assertion above cannot be a monolith that predicts a
    # constant for reasons unrelated to look-ahead.
    pd.testing.assert_series_equal(honest[MODEL_COLUMN], rewritten[MODEL_COLUMN], check_names=False)
    assert honest[MONOLITH_COLUMN].std() > 0


def test_the_monolith_is_refitted_at_every_fold_rather_than_once() -> None:
    """Fitting once on everything and slicing is faster, scores better, and measures nothing.

    Checked by the training-row count moving: the harness's window grows one deadline at a time, so
    a monolith fitted once would report the same figure at every fold.
    """
    history = dense_history()
    counts: list[int] = []
    monolith = MonolithPredictor(config=MonolithConfig(), features=FeatureConfig())
    for gameweek in (6, 10):
        monolith.fit(_training_frame(history[history["gameweek"] < gameweek]))
        counts.append(monolith.training_rows)
    assert counts[0] < counts[1]


# --- shadow only: it reaches nothing ------------------------------------------------------------


def test_there_is_no_flag_that_could_promote_the_monolith() -> None:
    """E10-S5 is explicit: never promoted without an explicit DP-10 decision.

    Every other E10 story ships behind a `discrimination` bool a future review can flip (DL-47).
    This one has nothing to flip, and the absence is the design rather than an omission — so it is
    asserted, because an omission is exactly what somebody would later "fix".
    """
    fields = set(DiscriminationConfig.model_fields)
    assert not any("monolith" in name for name in fields), fields
    # It lives on the backtest instead, where nothing on the forecast or publish path can read it.
    assert "monolith" in BacktestConfig.model_fields
    assert "monolith" not in ForecastConfig.model_fields


#: Only the backtest may reach the monolith: the module that defines it and the harness that fits
#: it. **Two files, and the stage that writes the report is not one of them** — it reads
#: ``BacktestResult.monolith`` like any other metric set, so even the code that publishes the gap
#: cannot construct the model. That is a narrower blast radius than this test originally assumed,
#: and it is worth pinning at the narrower figure.
MONOLITH_READERS = ("forecast/monolith.py", "forecast/backtest.py")

#: What reaching it looks like in a diff. Deliberately not the bare word "monolith": that appears in
#: this project's prose about monolithic solvers and about this very trade-off, and a test that
#: fails on an English sentence gets deleted rather than heeded.
MONOLITH_REACHES = re.compile(
    r"from fpl_dof\.forecast\.monolith import"
    r"|import fpl_dof\.forecast\.monolith"
    r"|\bMonolithPredictor\b"
    r"|\bMONOLITH_COLUMN\b"
)


def test_nothing_outside_the_backtest_reaches_the_monolith() -> None:
    """The structural guarantee, scanned rather than intended.

    A text scan for the same reason `test_source_isolation.py` uses one: an import graph would miss
    the module being reached through a string or a config key. If `optimise`, the decision layer,
    the live forecast or the publisher ever imports this, the benchmark has become an input — which
    is the one thing E10-S5 says it must never be, permanently and not pending a gate.
    """
    permitted = {(SRC / relative).resolve() for relative in MONOLITH_READERS}
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in SRC.rglob("*.py")
        if path.resolve() not in permitted
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if MONOLITH_REACHES.search(line)
    ]
    assert not offenders, offenders


def test_the_scan_would_actually_catch_something() -> None:
    """Guards the test above against a pattern that matches nothing anywhere.

    A scan whose regex has stopped matching passes for the best-looking possible reason. So the
    permitted files are checked to contain what the ban is looking for.
    """
    for relative in MONOLITH_READERS[1:]:
        text = (SRC / relative).read_text(encoding="utf-8")
        assert MONOLITH_REACHES.search(text), relative


def test_the_decision_path_is_scanned_and_actually_exists() -> None:
    """Guards the test above against a path typo quietly making it vacuous."""
    for package in ("optimise", "squad", "week", "publish"):
        assert (SRC / package).is_dir(), package


def test_the_monolith_column_is_never_the_graded_prediction() -> None:
    """Two columns, two meanings. The report reads the chain's, always."""
    result = _walk(dense_history())
    assert MONOLITH_COLUMN in result.predictions.columns
    assert result.model.name != result.monolith.name
    assert not np.allclose(
        result.predictions[MODEL_COLUMN].to_numpy(),
        result.predictions[MONOLITH_COLUMN].to_numpy(),
    )


# --- it is reported, every run ------------------------------------------------------------------


def test_every_run_reports_the_gap_overall_and_per_position() -> None:
    """E10-S5's acceptance criterion, stated as the thing a reader can actually find.

    Overall *and* per position, because E10 §0 grades everything per position — a gap concentrated
    in one position is a statement about that position's formulation, not about interpretability.
    """
    result = _walk(dense_history())

    assert result.monolith.observations > 0
    published = result.as_dict()
    assert "monolith" in published
    gap = published["explainability_gap"]
    assert isinstance(gap, dict)
    assert set(gap) >= {
        "top_n_precision",
        "top_n_precision_by_position",
        "statement",
        "monolith_model",
        "never_promoted",
    }
    assert "never" in str(gap["never_promoted"]).lower()

    monolith = published["monolith"]
    assert isinstance(monolith, dict)
    for metric in ("mae", "spearman", "top_n_precision", "calibration_slope"):
        assert metric in monolith
    assert monolith["spearman_by_position"]
    assert monolith["calibration_slope_by_position"]


def test_the_report_names_the_library_and_the_feature_count() -> None:
    """An inert benchmark must be visible as inert, so what it was is recorded, not implied."""
    result = _walk(dense_history())
    described = result.monolith_description
    assert "HistGradientBoosting" in str(described["library"])
    features = described["features"]
    assert isinstance(features, list)
    assert features
    assert POSITION in features


def test_the_gap_is_measured_against_the_chain_rather_than_against_b0() -> None:
    """So its MAE skill column reads as skill over what we ship, with no subtraction to do."""
    result = _walk(dense_history())
    expected = 1.0 - (result.monolith.mae / result.model.mae)
    assert result.monolith.mae_skill_score == pytest.approx(expected)


# --- the arithmetic of the gap ------------------------------------------------------------------


def test_a_positive_gap_means_the_monolith_is_better() -> None:
    """The sign is the entire finding, so it is defined once and pinned here."""
    assert head_gap(0.12, 0.15) == pytest.approx(0.03)
    assert head_gap(0.15, 0.12) == pytest.approx(-0.03)
    assert np.isnan(head_gap(float("nan"), 0.15))


def test_the_statement_says_which_way_the_trade_went() -> None:
    """DP-10's requirement is that the trade is *visible*, which means readable in words."""
    costly = gap_statement(
        chain_precision=0.12,
        monolith_precision=0.20,
        chain_spearman=0.25,
        monolith_spearman=0.30,
        top_n=20,
    )
    assert "not** free" in costly or "not free" in costly
    assert "+0.080" in costly

    free = gap_statement(
        chain_precision=0.20,
        monolith_precision=0.12,
        chain_spearman=0.30,
        monolith_spearman=0.25,
        top_n=20,
    )
    assert "free at the head" in free


def test_an_unmeasured_gap_is_not_reported_as_no_gap() -> None:
    """ "Not measured" and "no cost" are opposite claims and must not print the same."""
    statement = gap_statement(
        chain_precision=float("nan"),
        monolith_precision=0.2,
        chain_spearman=0.25,
        monolith_spearman=0.3,
        top_n=20,
    )
    assert "not measured" in statement
    assert "free" not in statement


def test_the_per_position_gap_covers_only_positions_both_sides_measured() -> None:
    gaps = gap_by_position({"MID": 0.1, "FWD": 0.2}, {"MID": 0.15, "GKP": 0.4})
    assert gaps == {"MID": pytest.approx(0.05)}


# --- degradation, visibly -----------------------------------------------------------------------


def test_a_thin_training_window_degrades_to_a_constant_and_says_so() -> None:
    """Early folds legitimately have nothing to boost on. Reporting a confident number from a
    handful of rows would put noise in the gap; reporting a constant *quietly* would put a zero
    there, which reads as good news (DP-15)."""
    history = make_history(players=4, gameweeks=3)
    monolith = MonolithPredictor(config=MonolithConfig(), features=FeatureConfig())
    monolith.fit(_training_frame(history))

    assert monolith.degraded is not None
    assert monolith.describe()["degraded"] == monolith.degraded
    predicted = monolith.predict(_training_frame(history))
    assert predicted.nunique() == 1


def test_a_harness_run_that_degrades_warns_rather_than_reporting_a_silent_zero() -> None:
    result = walk_forward(
        make_history(players=4, gameweeks=8),
        RateFromFeatures(),
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(minimum_training_matches=3),
        seasons=(SEASON,),
    )
    assert any("shadow monolith degraded" in warning for warning in result.warnings)


def test_a_column_never_observed_is_dropped_rather_than_passed_as_nulls() -> None:
    """The D-26 condition: an archive resolving no fixture leaves three all-null columns.

    Nothing is lost by dropping them — a column with no observed value carries no information — and
    left in, the boosting library has no distinct value to place a bin edge between.
    """
    training = _training_frame(dense_history())
    training["price"] = np.nan
    encoding = encoding_for(training, FeatureConfig())
    assert "price" not in encoding.columns


def test_predicting_before_fitting_is_an_error_rather_than_a_zero() -> None:
    monolith = MonolithPredictor(config=MonolithConfig(), features=FeatureConfig())
    with pytest.raises(RuntimeError, match="before fit"):
        monolith.predict(pd.DataFrame({"price": [5.0]}))


# --- it can actually learn ----------------------------------------------------------------------


def test_the_monolith_beats_the_constant_baseline() -> None:
    """Sanity in the opposite direction, and it matters more here than anywhere else.

    A monolith that had quietly stopped learning would report a *small* gap, which is the most
    reassuring possible way for this benchmark to be broken: the report would say explainability
    costs nothing and mean that the benchmark measures nothing.
    """
    result = _walk(dense_history())
    assert result.monolith.mae < result.mean_baseline.mae
    assert result.predictions[MONOLITH_COLUMN].std() > 0


def test_two_runs_on_one_history_report_one_gap() -> None:
    """DP-11. The fit is otherwise deterministic, so the seed is the only channel that can vary."""
    first, second = _walk(dense_history()), _walk(dense_history())
    assert first.explainability_gap == pytest.approx(second.explainability_gap, nan_ok=True)
    pd.testing.assert_series_equal(
        first.predictions[MONOLITH_COLUMN], second.predictions[MONOLITH_COLUMN]
    )
