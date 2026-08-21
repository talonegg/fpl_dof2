"""E10-S3 and E12-S2 — penalty duty as a committed reference table and an explicit additive term.

Two halves, and again because they are independent claims.

**The table** (E12-S2) is curated knowledge, hand-maintained, and therefore wrong in a way a feed
cannot be: it is written in the present and read in the past. So the tests that matter most here are
not about lookup, they are about *time*. A spell that had not started yet must not be visible at an
earlier deadline, because a hand-written table applied backwards is Invariant 5 broken by a config
file rather than by a feature — the same fatal error wearing different clothes, and the one nothing
in the metrics would show.

**The term** (E10-S3) is a candidate, not a promotion (DP-08,
[DL-47](../../docs/planning/00-decision-log.md)). So these tests pin the *mechanism*: the flag off
changes nothing at all, a player the table has never heard of is untouched rather than penalised,
confidence scales rather than gates, and the term cannot re-add penalty return that a
well-observed player's own fitted rate already carries. The claim that it *improves* the model is
the backtest's to make and is recorded in [DL-50](../../docs/planning/00-decision-log.md), not
asserted here.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from fpl_dof.config.models import (
    Config,
    DiscriminationConfig,
    DutyConfig,
    DutyEntryConfig,
    ForecastConfig,
    PenaltyDutyConfig,
)
from fpl_dof.forecast.duty import DutyTable
from fpl_dof.forecast.models import RateModel, fit_components
from fpl_dof.forecast.xp_v1 import forecast_player, team_matches
from fpl_dof.paths import DataLayout
from fpl_dof.rules.models import GameRules
from test_backtest import make_history

TAKER = 223340
NOBODY = 999999


def _entry(**overrides: object) -> DutyEntryConfig:
    fields: dict[str, object] = {
        "player_code": TAKER,
        "name": "A Taker",
        "club": "A Club",
        "duty": "penalties",
        "order": 1,
        "known_from": dt.date(2025, 8, 1),
        "confidence": "confirmed",
        "basis": "test",
    }
    fields.update(overrides)
    return DutyEntryConfig.model_validate(fields)


def _table(*entries: DutyEntryConfig) -> DutyTable:
    return DutyTable(DutyConfig(entries=entries), PenaltyDutyConfig())


def _config(**discrimination: object) -> ForecastConfig:
    return ForecastConfig(
        duty=DutyConfig(entries=(_entry(),)),
        discrimination=DiscriminationConfig.model_validate(discrimination),
    )


# --- the table is a claim about a moment, not about a player ------------------------------------


def test_a_spell_is_invisible_before_the_date_it_became_knowable() -> None:
    """The whole reason the file carries dates (Invariant 5).

    A duty table is written today and a backtest runs in 2024. If the lookup ignored the date,
    every historical fold would be scored with knowledge nobody had at the time, the backtest would
    improve, and the improvement would be worthless — the single easiest way to waste a season.
    """
    table = _table(_entry(known_from=dt.date(2025, 8, 1)))
    assert table.penalty_duty(TAKER, dt.date(2025, 7, 31)) is None
    assert table.penalty_duty(TAKER, dt.date(2025, 8, 1)) is not None


def test_a_lapsed_spell_stops_at_its_end_date_and_the_window_is_half_open() -> None:
    """Half-open ``[from, until)``: a handover on one date needs no gap and creates no overlap."""
    table = _table(_entry(known_from=dt.date(2024, 8, 1), known_until=dt.date(2025, 8, 1)))
    assert table.penalty_duty(TAKER, dt.date(2025, 7, 31)) is not None
    assert table.penalty_duty(TAKER, dt.date(2025, 8, 1)) is None


def test_a_row_that_cannot_say_when_it_is_being_scored_gets_no_duty() -> None:
    """A missing date is not permission to apply an undated assertion to an unknown moment.

    Failing open here would mean the one path with no date check is the one a future caller reaches
    by forgetting to pass ``as_of`` — and it would fail silently, which is the whole of DP-13.
    """
    table = _table(_entry())
    assert table.penalty_duty(TAKER, None) is None
    assert table.penalty_duty(TAKER, pd.NaT) is None


def test_a_player_with_no_entry_is_unknown_rather_than_dutiless() -> None:
    table = _table(_entry())
    assert table.penalty_duty(NOBODY, dt.date(2025, 9, 1)) is None


def test_only_the_first_taker_and_only_penalties_are_consumed() -> None:
    """The table accepts more than the model reads, and reading the rest by accident is the risk.

    A second taker takes some share of a club's penalties and nothing here knows what share; corners
    and free kicks have no volume anywhere in silver. Both are recorded and neither may contribute.
    """
    table = _table(
        _entry(order=2),
        _entry(player_code=TAKER + 1, duty="corners"),
        _entry(player_code=TAKER + 2, duty="direct_free_kicks"),
    )
    for code in (TAKER, TAKER + 1, TAKER + 2):
        assert table.penalty_duty(code, dt.date(2025, 9, 1)) is None


def test_confidence_scales_the_entry_rather_than_gating_it() -> None:
    """The tier is what lets the owner record a doubtful assignment instead of staying silent."""
    for confidence, expected in (("confirmed", 1.0), ("likely", 0.6), ("unconfirmed", 0.25)):
        table = _table(_entry(confidence=confidence))
        assignment = table.penalty_duty(TAKER, dt.date(2025, 9, 1))
        assert assignment is not None
        assert assignment.weight == pytest.approx(expected)
        assert assignment.contributes


def test_a_tier_nobody_has_priced_contributes_nothing() -> None:
    """An unknown tier weighs zero: not being in the mapping is not a licence to assume full."""
    table = DutyTable(
        DutyConfig(entries=(_entry(confidence="likely"),)),
        PenaltyDutyConfig(confidence_weights={"confirmed": 1.0}),
    )
    assignment = table.penalty_duty(TAKER, dt.date(2025, 9, 1))
    assert assignment is not None
    assert not assignment.contributes


def test_overlapping_spells_for_one_player_are_rejected_at_load() -> None:
    """Two answers to one question would make the result depend on file order — silently."""
    with pytest.raises(ValueError, match="overlap"):
        DutyConfig(
            entries=(
                _entry(known_from=dt.date(2024, 8, 1), known_until=dt.date(2026, 1, 1)),
                _entry(known_from=dt.date(2025, 8, 1)),
            )
        )


def test_a_spell_that_ends_before_it_starts_is_rejected_at_load() -> None:
    with pytest.raises(ValueError, match="ends on or before it starts"):
        _entry(known_from=dt.date(2025, 8, 1), known_until=dt.date(2025, 8, 1))


def test_an_empty_table_is_a_valid_table() -> None:
    """DP-15. The owner emptying the file must degrade the term to nothing, not raise."""
    table = _table()
    assert table.penalty_duty(TAKER, dt.date(2025, 9, 1)) is None
    assert table.describe()["entries"] == 0


def test_the_committed_table_loads_and_is_seeded(config: Config) -> None:
    """E12-S2's acceptance, checked rather than asserted: the file exists and reaches the model.

    Also the guard against the failure this whole design is exposed to — a table that has quietly
    emptied through a bad override produces a candidate that is inert for a reason nothing else in a
    backtest report would show.
    """
    entries = config.forecast.duty.entries
    assert entries, "the committed duty table is empty; E12-S2's single source has gone missing"
    assert all(entry.basis for entry in entries), "every entry must say where it came from (DP-09)"
    assert {entry.confidence for entry in entries} <= {"confirmed", "likely", "unconfirmed"}


# --- the flag is inert when it is off -----------------------------------------------------------


def test_the_flag_decides_whether_the_table_reaches_the_model_at_all(
    game_rules: GameRules,
) -> None:
    """Off, the component models must not even hold the table.

    Half-configuration is the failure this shape exists to prevent, exactly as for S1's minutes
    tunables and S2's shrinkage: a model carrying the table but choosing not to read it is one edit
    away from silently reading it.
    """
    history = make_history(players=24, gameweeks=8)
    training = history.assign(
        appearance_rate=history.groupby("player_code")["minutes"].transform(
            lambda values: (values > 0).mean()
        )
    )
    matches = team_matches(training)

    off = fit_components(training, matches, _config(duty_term=False), game_rules)
    assert off.duty is None

    on = fit_components(training, matches, _config(duty_term=True), game_rules)
    assert on.duty is not None
    assert on.duty.describe()["penalty_takers"] == 1


def test_the_model_card_names_the_candidate_even_when_it_is_absent(game_rules: GameRules) -> None:
    """A card must never imply a candidate from silence: absent is a value, not a missing key."""
    history = make_history(players=24, gameweeks=8)
    training = history.assign(
        appearance_rate=history.groupby("player_code")["minutes"].transform(
            lambda values: (values > 0).mean()
        )
    )
    described = fit_components(training, team_matches(training), ForecastConfig(), game_rules)
    assert "duty" in described.describe()
    assert described.describe()["duty"] is None


# --- the term ------------------------------------------------------------------------------------


def _row(*, code: int, minutes_mean: float, matches: int) -> pd.Series:
    return pd.Series(
        {
            "player_code": code,
            "position": "MID",
            "as_of": pd.Timestamp("2025-09-01", tz="UTC"),
            "minutes_mean_last6": minutes_mean,
            "matches_observed": matches,
            "goals_scored_per90_last6": 0.4,
            "assists_per90_last6": 0.2,
            "appearance_rate": 1.0,
        }
    )


def _fitted(config: ForecastConfig, rules: GameRules) -> object:
    history = make_history(players=24, gameweeks=8)
    training = history.assign(
        appearance_rate=history.groupby("player_code")["minutes"].transform(
            lambda values: (values > 0).mean()
        )
    )
    return fit_components(training, team_matches(training), config, rules)


def _points(config: ForecastConfig, rules: GameRules, row: pd.Series) -> float:
    models = _fitted(config, rules)
    forecast = forecast_player(
        row,
        models,  # type: ignore[arg-type]
        rules,
        config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.3,
    )
    return forecast.expected_points


def test_with_the_candidate_off_a_penalty_taker_scores_what_he_always_did(
    game_rules: GameRules,
) -> None:
    """The regression guarantee DL-47 rests on, stated where this story could break it."""
    row = _row(code=TAKER, minutes_mean=80.0, matches=10)
    assert _points(_config(duty_term=False), game_rules, row) == pytest.approx(
        _points(ForecastConfig(), game_rules, row)
    )


def test_a_player_the_table_has_never_heard_of_is_untouched_by_the_candidate(
    game_rules: GameRules,
) -> None:
    """Absence means unknown. An additive term must add nothing, not subtract a duty premium."""
    row = _row(code=NOBODY, minutes_mean=80.0, matches=10)
    assert _points(_config(duty_term=True), game_rules, row) == pytest.approx(
        _points(_config(duty_term=False), game_rules, row)
    )


def test_a_penalty_taker_is_worth_more_with_the_candidate_on(game_rules: GameRules) -> None:
    """The direction of the whole story, and the smallest statement of it."""
    row = _row(code=TAKER, minutes_mean=80.0, matches=10)
    assert _points(_config(duty_term=True), game_rules, row) > _points(
        _config(duty_term=False), game_rules, row
    )


def test_the_uplift_lands_in_the_goals_component_and_widens_the_band(
    game_rules: GameRules,
) -> None:
    """A penalty is a goal, and Invariant 6: a term that moves the mean must move the variance.

    A component that quietly raised expected points while leaving the uncertainty band alone would
    hand the optimiser a player who looks both better and *safer* than he is.
    """
    row = _row(code=TAKER, minutes_mean=80.0, matches=10)
    on_config, off_config = _config(duty_term=True), _config(duty_term=False)
    on = forecast_player(
        row,
        _fitted(on_config, game_rules),  # type: ignore[arg-type]
        game_rules,
        on_config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.3,
    )
    off = forecast_player(
        row,
        _fitted(off_config, game_rules),  # type: ignore[arg-type]
        game_rules,
        off_config,
        clean_sheet_probability=0.3,
        goals_conceded_mean=1.3,
    )
    assert on.components["goals"] > off.components["goals"]
    assert on.variance > off.variance
    # And nowhere else: every other component is the same forecast it was.
    for name, value in off.components.items():
        if name != "goals":
            assert on.components[name] == pytest.approx(value)


def test_the_term_is_largest_where_the_model_knows_the_player_least(
    game_rules: GameRules,
) -> None:
    """The formulation's central claim, and the one worth falsifying (DP-10).

    The term restores the share of a taker's penalty return that shrinkage replaced with a position
    prior. A newly appointed taker has no penalty record for the model to have seen, so his duty is
    genuinely new information; a taker the model has watched for two seasons already carries most of
    it in his own fitted rate, and adding it again would count it twice.
    """
    config, off = _config(duty_term=True), _config(duty_term=False)
    thin = _row(code=TAKER, minutes_mean=80.0, matches=2)
    thick = _row(code=TAKER, minutes_mean=80.0, matches=60)
    thin_uplift = _points(config, game_rules, thin) - _points(off, game_rules, thin)
    thick_uplift = _points(config, game_rules, thick) - _points(off, game_rules, thick)
    assert thin_uplift > thick_uplift > 0.0


def test_a_taker_with_no_history_at_all_gets_the_whole_contribution() -> None:
    """The boundary of the same claim, stated on the shrinkage rather than through a forecast.

    With no evidence the prediction *is* the position prior, so the prior's share is all of it and
    none of the penalty return is already priced in.
    """
    model = RateModel(column="goals_scored", prior_minutes=900.0)
    assert model.prior_share(0.0) == pytest.approx(1.0)
    assert model.prior_share(900.0) == pytest.approx(0.5)
    assert model.prior_share(2700.0) == pytest.approx(0.25)


def test_zero_strength_reproduces_the_flag_being_off(game_rules: GameRules) -> None:
    """The sweep's own control arm, as S2's has: ``strength=0`` and the flag off are one model."""
    row = _row(code=TAKER, minutes_mean=80.0, matches=10)
    inert = ForecastConfig(
        duty=DutyConfig(entries=(_entry(),)),
        discrimination=DiscriminationConfig(
            duty_term=True, penalties=PenaltyDutyConfig(strength=0.0)
        ),
    )
    assert _points(inert, game_rules, row) == pytest.approx(
        _points(_config(duty_term=False), game_rules, row)
    )


def test_the_uplift_is_bounded_by_what_a_penalty_is_actually_worth(game_rules: GameRules) -> None:
    """A sanity bound, because the failure mode here is a plausible-looking number that is wrong.

    A club wins about an eighth of a penalty a match. Even at full weight and full prior share,
    the term cannot be worth more than one penalty's points per match — if it ever is, the
    arithmetic has picked up a factor from somewhere and nothing else would catch it.
    """
    row = _row(code=TAKER, minutes_mean=90.0, matches=1)
    uplift = _points(_config(duty_term=True), game_rules, row) - _points(
        _config(duty_term=False), game_rules, row
    )
    ceiling = game_rules.scoring.goals_scored[
        next(p for p in game_rules.scoring.goals_scored if p.value == "MID")
    ]
    assert 0.0 < uplift < float(ceiling)


def test_the_backtest_card_names_the_duty_candidate_and_its_table(
    game_rules: GameRules, config: Config, layout: DataLayout
) -> None:
    """The card is what a human reads before a deadline (DP-09).

    The entry count is on it deliberately: a candidate that is inert because its table emptied
    grades as *no effect* and means *not measured*, and only the count separates the two.
    """
    from fpl_dof.config.models import BacktestConfig
    from fpl_dof.forecast.backtest import walk_forward
    from fpl_dof.forecast.xp_v1 import ComponentPredictor
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
    assert "`discrimination.duty_term` is **off**" in text
    assert f"**{len(config.forecast.duty.entries)}** entries" in text
