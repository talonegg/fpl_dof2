"""E10-S2 — reduce over-shrinkage at the head, and measure the head at all.

Two halves again, and again because they are independent claims.

**The measurement.** [DL-21](../../docs/planning/00-decision-log.md) named top-20 precision as the
metric E10 exists to move, and the harness reported 0.00 for it in every run it had ever produced.
That was not the model: it was the metric, pooled across 72 gameweeks, where the twenty highest
*observed* scores are twenty individual 20-point hauls and no calibrated expectation can reach
them. A metric pinned at zero for every model that could ever exist grades nothing, so these tests
pin the fix: one gameweek is one ranking, gameweeks are averaged rather than pooled, each position
gets a head as deep as that position goes into a squad, and the pooled form really is degenerate.

**The model change.** ``discrimination.adaptive_shrinkage`` is a candidate, not a promotion (DP-08,
[DL-47](../../docs/planning/00-decision-log.md)). So the tests here check the *mechanism*: the flag
off changes nothing at all, thin evidence is shrunk exactly as hard as it was before, and the
relaxation is monotone in evidence and bounded by ``strength``. The claim that it *improves* the
model is the backtest's to make and is recorded in DL-49, not asserted here.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from fpl_dof.config.models import (
    AdaptiveShrinkageConfig,
    Config,
    DiscriminationConfig,
    ForecastConfig,
)
from fpl_dof.forecast.metrics import (
    evaluate,
    head_size_by_position,
    per_gameweek_mean,
    top_n_precision,
)
from fpl_dof.forecast.models import RateModel, fit_components
from fpl_dof.forecast.xp_v1 import ComponentPredictor, team_matches
from fpl_dof.paths import DataLayout
from fpl_dof.rules.models import GameRules
from test_backtest import make_history


def _rate_model(adaptive: AdaptiveShrinkageConfig | None) -> RateModel:
    """A fitted-looking M3 with one known prior, so a test asserts about shrinkage and not a fit."""
    model = RateModel(column="goals_scored", prior_minutes=900.0, adaptive=adaptive)
    model.prior_by_position["MID"] = 0.2
    model.population_prior = 0.2
    return model


def _weight_on_own_rate(model: RateModel, minutes: float) -> float:
    """How much of the prediction came from the player rather than from his position.

    Recovered from the prediction rather than read off an internal, because the weight is only
    meaningful as the thing that actually moves the number.
    """
    prior, observed = 0.2, 1.0
    return (model.predict("MID", observed, minutes) - prior) / (observed - prior)


# --- the flag is inert when it is off -----------------------------------------------------------


def test_with_the_candidate_off_shrinkage_is_the_flat_prior_it_always_was() -> None:
    """The regression guarantee DL-47 rests on, at the smallest scale it can be stated.

    Evidence equal to ``prior_minutes`` must weight a player exactly half on himself — the property
    :meth:`RateModel.predict` has documented since E3 — no matter how much evidence there is.
    """
    model = _rate_model(None)
    assert _weight_on_own_rate(model, 900.0) == pytest.approx(0.5)
    for minutes in (100.0, 600.0, 1800.0, 5000.0):
        expected = minutes / (minutes + 900.0)
        assert _weight_on_own_rate(model, minutes) == pytest.approx(expected)


def test_the_flag_decides_whether_the_tunables_reach_the_model_at_all(
    game_rules: GameRules,
) -> None:
    """Off, the component models must not even hold the candidate's configuration.

    Half-configuration is the failure this shape exists to prevent: a model carrying the tunables
    but choosing not to read them is one edit away from silently reading them.
    """
    history = make_history(players=24, gameweeks=8)
    # Shaped the way the harness shapes training rows: features and outcomes, never raw history.
    training = history.assign(
        appearance_rate=history.groupby("player_code")["minutes"].transform(
            lambda values: (values > 0).mean()
        )
    )
    matches = team_matches(training)

    off = fit_components(training, matches, ForecastConfig(), game_rules)
    assert all(model.adaptive is None for model in off.rates.values())

    on = fit_components(
        training,
        matches,
        ForecastConfig(discrimination=DiscriminationConfig(adaptive_shrinkage=True)),
        game_rules,
    )
    assert all(model.adaptive is not None for model in on.rates.values())


# --- the mechanism ------------------------------------------------------------------------------


def test_thin_evidence_is_shrunk_exactly_as_hard_as_before() -> None:
    """Below the onset the candidate changes nothing, which is the point of having an onset.

    Shrinkage exists so that three appearances are not read as a rate. Relaxing *that* would not be
    reducing over-shrinkage at the head, it would be removing the mechanism.
    """
    adaptive = AdaptiveShrinkageConfig(strength=0.6, onset_minutes=600.0, full_minutes=1800.0)
    on, off = _rate_model(adaptive), _rate_model(None)
    for minutes in (0.0, 90.0, 300.0, 600.0):
        assert _weight_on_own_rate(on, minutes) == pytest.approx(_weight_on_own_rate(off, minutes))


def test_evidence_above_the_onset_is_shrunk_less_and_never_more() -> None:
    """The direction of the whole story: more evidence buys more of your own rate."""
    adaptive = AdaptiveShrinkageConfig(strength=0.6, onset_minutes=600.0, full_minutes=1800.0)
    on, off = _rate_model(adaptive), _rate_model(None)
    for minutes in (900.0, 1200.0, 1800.0, 4000.0):
        assert _weight_on_own_rate(on, minutes) > _weight_on_own_rate(off, minutes)


def test_the_relaxation_is_monotone_in_evidence() -> None:
    """A player with more evidence is never shrunk harder than one with less.

    Cheap to state and the thing most likely to break silently if the ramp is ever rewritten: a
    non-monotone shrinkage would reorder players for reasons nothing in the model claims.
    """
    model = _rate_model(
        AdaptiveShrinkageConfig(strength=0.6, onset_minutes=600.0, full_minutes=1800.0)
    )
    weights = [_weight_on_own_rate(model, minutes) for minutes in range(0, 5000, 100)]
    assert all(later >= earlier for earlier, later in pairwise(weights))


def test_the_relaxation_is_bounded_by_strength_and_stops_at_full_evidence() -> None:
    """``strength`` is a share of the prior removed, not a slope that runs away.

    At and beyond ``full_minutes`` the prior weight must sit at exactly ``1 - strength`` of what it
    was, so a player with ten seasons behind him is treated the same as one with two — past a
    point, more evidence is not more knowledge.
    """
    adaptive = AdaptiveShrinkageConfig(strength=0.6, onset_minutes=600.0, full_minutes=1800.0)
    model = _rate_model(adaptive)
    for minutes in (1800.0, 3600.0, 20_000.0):
        expected = minutes / (minutes + 900.0 * 0.4)
        assert _weight_on_own_rate(model, minutes) == pytest.approx(expected)


def test_zero_strength_reproduces_the_flat_prior_even_with_the_flag_on() -> None:
    """The sweep's own control arm. ``strength=0`` and the flag off must be the same model."""
    on = _rate_model(AdaptiveShrinkageConfig(strength=0.0))
    off = _rate_model(None)
    for minutes in (0.0, 700.0, 1800.0, 9000.0):
        assert _weight_on_own_rate(on, minutes) == pytest.approx(_weight_on_own_rate(off, minutes))


def test_a_collapsed_range_is_a_threshold_rather_than_a_division_by_zero() -> None:
    """Configuration that sets both ends to one number is asking for a step, and gets one."""
    model = _rate_model(
        AdaptiveShrinkageConfig(strength=0.5, onset_minutes=1000.0, full_minutes=1000.0)
    )
    assert _weight_on_own_rate(model, 999.0) == pytest.approx(999.0 / (999.0 + 900.0))
    assert _weight_on_own_rate(model, 1001.0) == pytest.approx(1001.0 / (1001.0 + 450.0))


def test_a_player_with_no_evidence_is_still_the_position_prior_exactly() -> None:
    """No amount of adaptivity may invent a rate for somebody nobody has observed."""
    model = _rate_model(AdaptiveShrinkageConfig(strength=1.0))
    assert model.predict("MID", float("nan"), 0.0) == pytest.approx(0.2)
    assert model.predict("MID", 5.0, 0.0) == pytest.approx(0.2)


# --- the metric the acceptance is stated in -----------------------------------------------------


def _ranking(gameweek: int, predicted: list[float], actual: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": "2025/26",
            "gameweek": gameweek,
            "position": "MID",
            "p": predicted,
            "a": actual,
        }
    )


def test_pooling_the_head_metric_across_gameweeks_is_degenerate() -> None:
    """The defect DL-49 records, reproduced rather than described.

    Two gameweeks. In each one the model ranks perfectly, so the per-gameweek answer is 1.0. Pooled,
    the four highest observed scores all come from gameweek two — real gameweeks differ wildly in
    how many points are available — and the model, being a calibrated expectation, never predicts
    anything near them. Precision reads 0.00 for a model that got every ranking exactly right.
    """
    first = _ranking(1, [3.0, 2.0, 1.0, 0.5], [4.0, 3.0, 2.0, 1.0])
    second = _ranking(2, [3.1, 2.1, 1.1, 0.6], [40.0, 30.0, 20.0, 10.0])
    both = pd.concat([first, second], ignore_index=True)

    assert top_n_precision(both, n=4, predicted="p", actual="a") == pytest.approx(0.5)
    assert per_gameweek_mean(
        both,
        ("season", "gameweek"),
        lambda rows: top_n_precision(rows, n=4, predicted="p", actual="a"),
    ) == pytest.approx(1.0)


def test_a_gameweek_too_small_to_rank_is_skipped_rather_than_scored_zero() -> None:
    """Skipped, not scored zero: not measurable here is a different claim from got none right."""
    big = _ranking(1, [3.0, 2.0, 1.0], [3.0, 2.0, 1.0])
    tiny = _ranking(2, [1.0], [1.0])
    both = pd.concat([big, tiny], ignore_index=True)
    assert per_gameweek_mean(
        both,
        ("season", "gameweek"),
        lambda rows: top_n_precision(rows, n=3, predicted="p", actual="a"),
    ) == pytest.approx(1.0)


def test_evaluate_averages_the_head_metrics_over_rankings_when_told_what_a_ranking_is() -> None:
    first = _ranking(1, [3.0, 2.0, 1.0, 0.5], [4.0, 3.0, 2.0, 1.0])
    second = _ranking(2, [3.1, 2.1, 1.1, 0.6], [40.0, 30.0, 20.0, 10.0])
    both = pd.concat([first, second], ignore_index=True)

    grouped = evaluate(
        both, name="m", predicted="p", actual="a", top_n=4, group=("season", "gameweek")
    )
    pooled = evaluate(both, name="m", predicted="p", actual="a", top_n=4)
    assert grouped.top_n_precision == pytest.approx(1.0)
    assert grouped.captaincy_hit_rate == pytest.approx(1.0)
    assert pooled.top_n_precision == pytest.approx(0.5)
    assert pooled.captaincy_hit_rate == pytest.approx(1.0)


def test_each_position_gets_a_head_as_deep_as_it_goes_into_a_squad() -> None:
    """Twenty goalkeepers is every goalkeeper who played. Two is a head."""
    composition = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert head_size_by_position(20, composition) == {"GKP": 3, "DEF": 7, "MID": 7, "FWD": 4}
    # Never zero: a position nobody ranks is not a position that has been graded.
    assert head_size_by_position(2, composition)["GKP"] == 1
    assert head_size_by_position(0, composition) == {}
    assert head_size_by_position(20, {}) == {}


def test_the_harness_reports_the_head_per_position(game_rules: GameRules) -> None:
    """End to end: a real predictor, a real walk, and a per-position split that is populated.

    E10's definition of done requires every metric in the epic to be reported per position, and a
    breakdown that silently comes back empty would satisfy nothing while looking like it did.
    """
    from fpl_dof.config.models import BacktestConfig
    from fpl_dof.forecast.backtest import walk_forward

    history = make_history(players=40, gameweeks=10)
    result = walk_forward(
        history,
        ComponentPredictor(ForecastConfig(), game_rules),
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(top_n_precision=8),
        seasons=None,
    )
    assert set(result.model.top_n_precision_by_position) == {"GKP", "DEF", "MID", "FWD"}
    assert set(result.model.calibration_slope_by_position) == {"GKP", "DEF", "MID", "FWD"}
    # And the aggregate is a real number rather than the pinned zero it used to be.
    assert not np.isnan(result.model.top_n_precision)


def test_the_backtest_card_reports_the_head_of_the_ranking(
    game_rules: GameRules, config: Config, layout: DataLayout
) -> None:
    """The card is what a human reads before a deadline, so a section that silently renders empty
    is worse than one that is absent — it looks like a measurement (DP-13, DP-09).

    E10 is graded on this section. If the per-position table ever comes back as a row of dashes,
    the epic's definition of done is being satisfied by a heading rather than by numbers.
    """
    from fpl_dof.config.models import BacktestConfig
    from fpl_dof.forecast.backtest import walk_forward
    from fpl_dof.pipeline import StageContext
    from fpl_dof.stages.backtest import _card

    history = make_history(players=40, gameweeks=10)
    result = walk_forward(
        history,
        ComponentPredictor(ForecastConfig(), game_rules),
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(top_n_precision=8),
        seasons=None,
    )
    text = _card(result, StageContext(config=config, layout=layout, run_id="r"))

    assert "## The head of the ranking (E10)" in text
    assert "`discrimination.adaptive_shrinkage` is **off**" in text
    # Every position is named with a number beside it, not a dash.
    head = text.split("### Per position", 1)[1]
    for position in ("GKP", "DEF", "MID", "FWD"):
        row = next(line for line in head.splitlines() if line.startswith(f"| {position} "))
        assert "—" not in row, row
