"""E10-S4 — a goalkeeper-specific formulation for saves.

GKP Spearman is 0.04 ([DL-21](../../docs/planning/00-decision-log.md)) — a whole position
essentially unranked. Everything a goalkeeper scores for already runs through M2 except **saves**,
which came from the generic shrunk per-90 used for every outfield rate stat and is therefore blind
to the thing that actually produces a save: a shot, and shots faced are the defence in front of him.

**Nothing in silver counts shots**, so expected goals conceded stands in for them. That
substitution is the story's most contestable choice and it is named rather than hidden (DP-09,
DP-10); the tests below pin its *arithmetic*, and the argument for it lives in
[DL-51](../../docs/planning/00-decision-log.md).

``discrimination.gkp_v2`` is a candidate, not a promotion (DP-08,
[DL-47](../../docs/planning/00-decision-log.md)). So these tests check the mechanism: the flag off
changes nothing at all, an average keeper in an average fixture gets back exactly the number the old
chain gave him, the defence a keeper has played behind is divided out of his own level, and only
goalkeepers are touched. The claim that it *improves* the model is the backtest's to make and is
recorded in DL-51, not asserted here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_dof.config.models import DiscriminationConfig, ForecastConfig, GoalkeeperConfig
from fpl_dof.forecast.models import GoalkeeperSavesModel, fit_components
from fpl_dof.forecast.xp_v1 import forecast_player, team_matches
from fpl_dof.rules.models import GameRules
from test_backtest import make_history

BUSY = 100_001
"""A keeper behind a leaky defence: a high save rate, most of which is not him."""

QUIET = 100_002
"""A keeper behind a good one, with the same shot-stopping and half the work."""

UNSEEN = 100_003


def _keeper_history() -> pd.DataFrame:
    """Two keepers with **identical shot-stopping** and very different defences in front of them.

    Two saves per expected goal conceded each, over the same minutes. The raw per-90 rates differ by
    a factor of two and say nothing about the keepers; that is the whole premise of the story, so it
    is built into the fixture rather than argued for in a comment.
    """
    rows = []
    for code, pressure in ((BUSY, 2.0), (QUIET, 1.0)):
        for match in range(20):
            rows.append(
                {
                    "season": "2025/26",
                    "gameweek": match + 1,
                    "player_code": code,
                    "position": "GKP",
                    "minutes": 90,
                    "saves": 2.0 * pressure,
                    "expected_goals_conceded": pressure,
                    "goals_conceded": pressure,
                }
            )
    return pd.DataFrame(rows)


def _fitted(**goalkeeper: object) -> GoalkeeperSavesModel:
    config = GoalkeeperConfig.model_validate(goalkeeper)
    return GoalkeeperSavesModel(config=config, prior_minutes=900.0).fit(_keeper_history())


def _training() -> pd.DataFrame:
    history = make_history(players=24, gameweeks=8)
    return history.assign(
        appearance_rate=history.groupby("player_code")["minutes"].transform(
            lambda values: (values > 0).mean()
        )
    )


# --- the flag is inert when it is off -----------------------------------------------------------


def test_the_flag_decides_whether_the_goalkeeper_model_is_fitted_at_all(
    game_rules: GameRules,
) -> None:
    """Off, the component models must not even hold the candidate.

    The same shape S1, S2 and S3 use, for the same reason: a model carrying the formulation but
    choosing not to read it is one edit away from silently reading it.
    """
    training = _training()
    matches = team_matches(training)

    off = fit_components(training, matches, ForecastConfig(), game_rules)
    assert off.goalkeeper is None

    on = fit_components(
        training,
        matches,
        ForecastConfig(discrimination=DiscriminationConfig(gkp_v2=True)),
        game_rules,
    )
    assert on.goalkeeper is not None


def test_the_model_card_names_the_candidate_even_when_it_is_absent(game_rules: GameRules) -> None:
    """A card must never imply a candidate from silence: absent is a value, not a missing key."""
    training = _training()
    described = fit_components(training, team_matches(training), ForecastConfig(), game_rules)
    assert "goalkeeper" in described.describe()
    assert described.describe()["goalkeeper"] is None


def test_with_the_flag_off_a_goalkeeper_scores_exactly_what_he_scored_before(
    game_rules: GameRules,
) -> None:
    """The regression guarantee DL-47 rests on, stated where the change actually lands.

    Scored twice under two *different* fixtures, because the candidate's whole effect is to make
    saves fixture-sensitive: a formulation that leaked through the flag would show up here as two
    numbers that no longer match a fixture-blind chain.
    """
    training = _training()
    matches = team_matches(training)
    models = fit_components(training, matches, ForecastConfig(), game_rules)
    row = _row()

    for conceded in (0.8, 2.2):
        forecast = forecast_player(
            row,
            models,
            game_rules,
            ForecastConfig(),
            clean_sheet_probability=0.3,
            goals_conceded_mean=conceded,
        )
        # Saves are the only component the candidate can reach, and with the flag off it is the
        # fitted per-90 scaled by minutes and nothing else — no fixture term anywhere in it.
        assert forecast.components["saves"] == pytest.approx(
            _fixture_blind_saves(models, row, game_rules)
        )


def _fixture_blind_saves(models: object, row: pd.Series, rules: GameRules) -> float:
    """What the pre-E10-S4 chain paid for saves, computed the long way round.

    Written out rather than compared against a recorded constant so the assertion survives a change
    to the fitted priors: what is being pinned is *that the fixture does not enter*, not a number.
    """
    from fpl_dof.forecast.xp_v1 import _rate

    config = ForecastConfig()
    rate = _rate(models, "saves", "GKP", row, config)  # type: ignore[arg-type]
    minutes = models.minutes.predict_row(row, "GKP")  # type: ignore[attr-defined]
    scoring = rules.scoring
    total = 0.0
    for probability, played in (
        (minutes.short, config.minutes.substitute_minutes),
        (minutes.long, config.minutes.starter_minutes),
    ):
        total += probability * (rate * played / 90.0) / scoring.saves_per_point * scoring.saves
    return total


def _row() -> pd.Series:
    return pd.Series(
        {
            "player_code": BUSY,
            "position": "GKP",
            "as_of": pd.Timestamp("2025-09-01", tz="UTC"),
            "minutes_mean_last6": 90.0,
            "matches_observed": 6,
            "saves_per90_last6": 3.0,
            "appearance_rate": 1.0,
        }
    )


# --- the fixture factor --------------------------------------------------------------------------


def test_an_average_fixture_returns_exactly_the_old_number() -> None:
    """The property that makes this a re-attribution rather than a rescaling.

    Both quantities enter as ratios to a league mean, so a keeper of average pressure facing an
    average fixture must land precisely where the fixture-blind chain left him. Without this the
    candidate would be moving the whole position's level as well as its order, and the backtest
    could not tell the two apart.
    """
    model = _fitted(mode="fixture_weighted")
    rate = model.save_rate(BUSY, 3.0, goals_conceded_mean=1.4, league_mean_goals=1.4)
    assert rate == pytest.approx(3.0)


def test_a_harder_fixture_raises_the_save_rate_and_an_easier_one_lowers_it() -> None:
    """The direction of the whole story, and the cheapest thing to get backwards."""
    model = _fitted(mode="fixture_weighted")
    easy = model.save_rate(BUSY, 3.0, goals_conceded_mean=0.7, league_mean_goals=1.4)
    hard = model.save_rate(BUSY, 3.0, goals_conceded_mean=2.8, league_mean_goals=1.4)
    assert easy < 3.0 < hard


def test_a_fixture_weight_of_zero_is_the_identity_and_reproduces_the_old_chain() -> None:
    """The `fixture_weighted` arm's own off switch, and it must be exact rather than close.

    A candidate whose neutral setting is only nearly neutral cannot be used to attribute a backtest
    difference to the thing being swept.
    """
    model = _fitted(mode="fixture_weighted", fixture_weight=0.0)
    for conceded in (0.4, 1.4, 3.5):
        assert model.save_rate(
            BUSY, 3.0, goals_conceded_mean=conceded, league_mean_goals=1.4
        ) == pytest.approx(3.0)


def test_damping_moves_the_rate_less_than_the_full_ratio_does() -> None:
    """`fixture_weight` is a share of M2's ratio, not a slope that runs away."""
    half = _fitted(mode="fixture_weighted", fixture_weight=0.5)
    full = _fitted(mode="fixture_weighted", fixture_weight=1.0)
    for conceded in (0.7, 2.8):
        moved_half = abs(
            half.save_rate(BUSY, 3.0, goals_conceded_mean=conceded, league_mean_goals=1.4) - 3.0
        )
        moved_full = abs(
            full.save_rate(BUSY, 3.0, goals_conceded_mean=conceded, league_mean_goals=1.4) - 3.0
        )
        assert moved_half == pytest.approx(moved_full / 2.0)


def test_a_brutal_fixture_can_never_produce_a_negative_save_rate() -> None:
    """A factor is floored at zero. Nothing else clips it — a hard fixture *should* read as busy."""
    model = _fitted(mode="fixture_weighted")
    assert model.save_rate(BUSY, 3.0, goals_conceded_mean=0.0, league_mean_goals=1.4) >= 0.0


# --- dividing out the defence --------------------------------------------------------------------


def test_two_keepers_with_the_same_shot_stopping_are_levelled() -> None:
    """The claim the `separate` arm makes, at the smallest scale it can be stated.

    Both keepers stop two shots per expected goal conceded. One faces twice the work, so his raw
    per-90 is twice the other's and the generic chain would rank him far above a keeper who is
    exactly as good. Net of the defence they must be equal.
    """
    model = _fitted(mode="separate")
    busy = model.save_rate(BUSY, 4.0, goals_conceded_mean=1.5, league_mean_goals=1.5)
    quiet = model.save_rate(QUIET, 2.0, goals_conceded_mean=1.5, league_mean_goals=1.5)
    assert busy == pytest.approx(quiet)


def test_the_separate_arm_ignores_the_fitted_per_90_it_is_handed() -> None:
    """`separate` is a *separate formulation*, not a blend, and that has to be visible.

    If the fitted rate still leaked into the answer the two arms would differ only in degree, and
    Q-15's falsifier — a fully separate model against the same chain re-weighted — would be
    grading one thing twice.
    """
    model = _fitted(mode="separate")
    for handed in (0.5, 3.0, 9.0):
        assert model.save_rate(
            BUSY, handed, goals_conceded_mean=1.5, league_mean_goals=1.5
        ) == pytest.approx(
            model.save_rate(BUSY, 3.0, goals_conceded_mean=1.5, league_mean_goals=1.5)
        )


def test_the_fixture_weighted_arm_keeps_the_fitted_per_90_and_only_scales_it() -> None:
    """The other half of Q-15: the existing chain re-weighted, the keeper's own level untouched."""
    model = _fitted(mode="fixture_weighted")
    factor = model.fixture_factor(2.1, 1.4)
    assert model.save_rate(
        BUSY, 3.0, goals_conceded_mean=2.1, league_mean_goals=1.4
    ) == pytest.approx(3.0 * factor)


def test_a_keeper_the_model_never_saw_keeps_what_the_old_chain_knew_about_him() -> None:
    """A debutant has no pressure history to divide out, so there is nothing to re-attribute.

    Substituting the population figure for him would *discard* information — his own fitted rate,
    thin as it is — which is a strictly worse answer than the one being replaced, and would make
    the candidate's effect on newcomers the opposite of its effect on everybody else.
    """
    model = _fitted(mode="separate")
    assert model.save_rate(
        UNSEEN, 3.0, goals_conceded_mean=1.4, league_mean_goals=1.4
    ) == pytest.approx(3.0)


def _history_with_an_outlier() -> pd.DataFrame:
    """The two levelled keepers, plus one who genuinely stops more than either of them.

    An outlier is needed to say anything about shrinkage at all: in the fixture above both keepers
    sit exactly on the population once the defence is divided out, which is the point being made
    there and useless here, because everything shrinks to where it already is.
    """
    history = _keeper_history()
    extra = [
        {
            "season": "2025/26",
            "gameweek": match + 1,
            "player_code": UNSEEN,
            "position": "GKP",
            "minutes": 90,
            "saves": 4.0,
            "expected_goals_conceded": 1.0,
            "goals_conceded": 1.0,
        }
        for match in range(10)
    ]
    return pd.concat([history, pd.DataFrame(extra)], ignore_index=True)


def test_shrinkage_still_pulls_a_keeper_toward_the_goalkeeper_population() -> None:
    """The same arithmetic as `RateModel`, and it has to behave like it.

    Shrinkage is not relaxed by this story; only the quantity being shrunk changes. So a heavier
    prior must leave a keeper nearer the population, and a prior of nothing must leave him exactly
    on his own pressure-adjusted rate — the two ends that fix the whole curve between them.
    """
    history = _history_with_an_outlier()
    levels = {}
    for prior in (1.0, 900.0, 90_000.0):
        model = GoalkeeperSavesModel(
            config=GoalkeeperConfig(mode="separate"), prior_minutes=prior
        ).fit(history)
        levels[prior] = (model.by_player[UNSEEN], model.population_per90)

    # The fixture's arithmetic, written out so the endpoints are claims rather than recordings.
    # 4500 minutes carrying 70 expected goals conceded is a league pressure of 1.4 per 90; the
    # outlier faced 1.0 of it and made four saves, so net of his defence he is worth 5.6, against a
    # population of 160 saves over 4500 minutes, or 3.2.
    population = levels[900.0][1]
    assert population == pytest.approx(3.2)
    assert levels[1.0][0] == pytest.approx(5.6, abs=0.01)
    assert levels[90_000.0][0] == pytest.approx(population, abs=0.05)
    distances = [abs(level - population) for level, _ in levels.values()]
    assert distances[0] > distances[1] > distances[2]


# --- degradation ---------------------------------------------------------------------------------


def test_without_expected_goals_the_model_falls_back_to_actual_and_says_so() -> None:
    """DP-15, and the half of it that matters: the fallback is *worse*, so it must be reported.

    Actual goals conceded is a far noisier measure of shots faced than expected goals. A card that
    reported the same model name for both would be describing a model that did not run.
    """
    history = _keeper_history().drop(columns=["expected_goals_conceded"])
    model = GoalkeeperSavesModel(config=GoalkeeperConfig(mode="separate"), prior_minutes=900.0).fit(
        history
    )
    assert model.pressure_column == "goals_conceded"
    assert model.describe()["pressure_column"] == "goals_conceded"


def test_with_no_pressure_measure_at_all_the_model_declines_to_re_attribute_anything() -> None:
    """Nothing to divide out means nothing is claimed: the fitted rate stands, scaled by fixture.

    An inert candidate must be *visibly* inert — `keepers` is zero and `pressure_column` is null on
    the card — because an inert candidate grades as *no effect* when it means *not measured*.
    """
    history = _keeper_history().drop(columns=["expected_goals_conceded", "goals_conceded"])
    model = GoalkeeperSavesModel(config=GoalkeeperConfig(mode="separate"), prior_minutes=900.0).fit(
        history
    )
    assert model.keepers == 0
    assert model.describe()["pressure_column"] is None
    assert model.save_rate(
        BUSY, 3.0, goals_conceded_mean=1.4, league_mean_goals=1.4
    ) == pytest.approx(3.0)


def test_an_empty_history_leaves_the_model_fitted_on_nothing_rather_than_raising() -> None:
    model = GoalkeeperSavesModel(config=GoalkeeperConfig(), prior_minutes=900.0).fit(pd.DataFrame())
    assert model.keepers == 0


# --- only goalkeepers ----------------------------------------------------------------------------


def test_an_outfield_player_is_untouched_by_the_candidate(game_rules: GameRules) -> None:
    """The blast radius, checked rather than assumed.

    The hook sits in a `position is GKP` branch, so a defender's forecast must be identical with
    the flag on and off. E10 §0 grades per position for exactly this reason: a change that quietly
    moved three positions to fix one would be reported as a gain in the aggregate.
    """
    training = _training()
    matches = team_matches(training)
    off_config = ForecastConfig()
    on_config = ForecastConfig(discrimination=DiscriminationConfig(gkp_v2=True))
    off = fit_components(training, matches, off_config, game_rules)
    on = fit_components(training, matches, on_config, game_rules)

    row = _row()
    row["position"] = "DEF"
    row["defensive_contribution_per90_last6"] = 2.0

    def points(models: object, config: ForecastConfig) -> float:
        return forecast_player(
            row,
            models,  # type: ignore[arg-type]
            game_rules,
            config,
            clean_sheet_probability=0.3,
            goals_conceded_mean=2.4,
        ).expected_points

    assert points(off, off_config) == pytest.approx(points(on, on_config))
