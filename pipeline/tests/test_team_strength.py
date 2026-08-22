"""M2's home advantage is fitted, not assumed (E11-S2).

Where being wrong here is invisible (DP-13): a fit that silently returns the prior looks identical
to a fit that measured nothing, and a fit with no floor could invert home and away without anything
downstream noticing. So the tests are about the fit's edges, not its happy path alone — degrading
cleanly when the evidence is missing (DP-15), shrinking rather than jumping as evidence grows, and
telling the model card the difference between a measurement and an assumption (DP-09).
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fpl_dof.config.models import TeamStrengthConfig
from fpl_dof.forecast.models import FIT_AT_HOME, TeamStrengthModel

SEASON = "2026/27"


def _matches(rows: list[tuple[int, str, float, float, bool, str]]) -> pd.DataFrame:
    """``rows``: ``(team_id, fixture_id, goals_for, goals_against, at_home, kickoff)``."""
    return pd.DataFrame(
        [
            {
                "season": SEASON,
                "team_id": team_id,
                "fixture_id": fixture_id,
                "goals_for": goals_for,
                "goals_against": goals_against,
                FIT_AT_HOME: at_home,
                "kickoff_time": pd.Timestamp(kickoff),
            }
            for team_id, fixture_id, goals_for, goals_against, at_home, kickoff in rows
        ]
    )


def _balanced_matches(*, home_goals: float, away_goals: float, n: int = 20) -> pd.DataFrame:
    """``n`` fixtures, each team home and away equally often, so nothing but venue differs."""
    rows: list[tuple[int, str, float, float, bool, str]] = []
    for i in range(n):
        kickoff = f"2026-08-{(i % 28) + 1:02d}T15:00:00Z"
        rows.append((1, f"f{i}a", home_goals, away_goals, True, kickoff))
        rows.append((2, f"f{i}a", away_goals, home_goals, False, kickoff))
        rows.append((2, f"f{i}b", home_goals, away_goals, True, kickoff))
        rows.append((1, f"f{i}b", away_goals, home_goals, False, kickoff))
    return _matches(rows)


def test_the_fit_recovers_the_ratio_of_home_to_away_goals() -> None:
    matches = _balanced_matches(home_goals=1.6, away_goals=1.2, n=40)
    model = TeamStrengthModel(config=TeamStrengthConfig(home_advantage_prior_matches=1.0)).fit(
        matches
    )

    assert model.home_advantage == pytest.approx(math.sqrt(1.6 / 1.2), rel=0.02)
    assert model.home_advantage_is_fitted


def test_with_no_venue_column_the_prior_stands_and_nothing_claims_to_be_fitted() -> None:
    matches = _balanced_matches(home_goals=2.0, away_goals=1.0, n=40).drop(columns=[FIT_AT_HOME])
    config = TeamStrengthConfig(home_advantage_prior=1.09)
    model = TeamStrengthModel(config=config).fit(matches)

    assert model.home_advantage == pytest.approx(1.09)
    assert not model.home_advantage_is_fitted
    assert model.home_advantage_matches == 0.0


def test_a_lopsided_fixture_list_with_no_away_rows_degrades_to_the_prior() -> None:
    rows = [
        (1, "f1", 3.0, 0.0, True, "2026-08-10T15:00:00Z"),
        (2, "f2", 2.0, 1.0, True, "2026-08-11T15:00:00Z"),
    ]
    config = TeamStrengthConfig(home_advantage_prior=1.09)
    model = TeamStrengthModel(config=config).fit(_matches(rows))

    assert model.home_advantage == pytest.approx(1.09)
    assert not model.home_advantage_is_fitted


def test_thin_evidence_shrinks_toward_the_prior_rather_than_snapping_to_the_fit() -> None:
    matches = _balanced_matches(home_goals=3.0, away_goals=1.0, n=1)
    config = TeamStrengthConfig(home_advantage_prior=1.09, home_advantage_prior_matches=500.0)
    model = TeamStrengthModel(config=config).fit(matches)

    fitted = math.sqrt(3.0)
    # Barely moved off the prior: with far more prior weight than evidence, the shrunk value sits
    # close to the prior and nowhere near the raw fit.
    assert abs(model.home_advantage - config.home_advantage_prior) < abs(
        model.home_advantage - fitted
    )
    assert model.home_advantage_is_fitted


def test_the_fit_is_clipped_to_the_configured_range() -> None:
    matches = _balanced_matches(home_goals=10.0, away_goals=0.1, n=40)
    config = TeamStrengthConfig(
        home_advantage_prior_matches=1.0, home_advantage_maximum=1.30, home_advantage_minimum=1.0
    )
    model = TeamStrengthModel(config=config).fit(matches)

    assert model.home_advantage == pytest.approx(1.30)


def test_describe_reports_the_fit_source_and_the_configured_prior() -> None:
    matches = _balanced_matches(home_goals=2.0, away_goals=1.0, n=40)
    config = TeamStrengthConfig(home_advantage_prior=1.09, home_advantage_prior_matches=1.0)
    model = TeamStrengthModel(config=config).fit(matches)

    description = model.describe()
    assert description["home_advantage_source"] == "fitted"
    assert description["home_advantage_prior"] == 1.09
    assert float(description["home_advantage_matches"]) > 0  # type: ignore[arg-type]

    unfitted = TeamStrengthModel(config=config)
    assert unfitted.describe()["home_advantage_source"] == "prior"
    assert unfitted.describe()["home_advantage"] == pytest.approx(1.09)


def test_expected_goals_still_applies_the_venue_multiplier_and_its_reciprocal() -> None:
    model = TeamStrengthModel(attack={1: 1.0, 2: 1.0}, defence={1: 1.0, 2: 1.0}, home_advantage=1.2)
    home = model.expected_goals(1, 2, at_home=True)
    away = model.expected_goals(2, 1, at_home=False)
    assert home == pytest.approx(away * 1.2 * 1.2)


# --- E11-S4: rating shrinkage and widened priors for named clubs -------------------------------


def _lopsided_matches(*, team_scores: float, team_concedes: float, n: int) -> pd.DataFrame:
    """``n`` matches for team 1 against a rotating cast of opponents, all on one day (no decay)."""
    rows: list[tuple[int, str, float, float, bool, str]] = []
    for i in range(n):
        opponent = 100 + i
        rows.append((1, f"f{i}", team_scores, team_concedes, i % 2 == 0, "2026-08-15T15:00:00Z"))
        rows.append(
            (opponent, f"f{i}", team_concedes, team_scores, i % 2 != 0, "2026-08-15T15:00:00Z")
        )
    return _matches(rows)


def test_the_shipped_zero_prior_leaves_ratings_unshrunk() -> None:
    matches = _lopsided_matches(team_scores=3.0, team_concedes=0.0, n=1)
    model = TeamStrengthModel(config=TeamStrengthConfig()).fit(matches)
    mean = model.league_mean_goals
    assert model.attack[1] == pytest.approx(3.0 / mean)


def test_a_thin_sample_shrinks_toward_the_league_neutral_rating() -> None:
    matches = _lopsided_matches(team_scores=3.0, team_concedes=0.0, n=1)
    config = TeamStrengthConfig(rating_prior_matches=10.0)
    model = TeamStrengthModel(config=config).fit(matches)

    mean = model.league_mean_goals
    unshrunk = 3.0 / mean
    assert 1.0 < model.attack[1] < unshrunk


def test_a_named_club_shrinks_harder_than_an_otherwise_identical_one() -> None:
    matches = _lopsided_matches(team_scores=3.0, team_concedes=0.0, n=3)
    config = TeamStrengthConfig(rating_prior_matches=5.0, promoted_prior_matches=50.0)

    established = TeamStrengthModel(config=config).fit(matches)
    promoted = TeamStrengthModel(config=config, promoted_teams=frozenset({1})).fit(matches)

    mean = established.league_mean_goals
    unshrunk_distance = abs(3.0 / mean - 1.0)
    established_distance = abs(established.attack[1] - 1.0)
    promoted_distance = abs(promoted.attack[1] - 1.0)
    assert 0 < promoted_distance < established_distance < unshrunk_distance


def test_ample_evidence_overwhelms_even_a_widened_prior() -> None:
    matches = _lopsided_matches(team_scores=3.0, team_concedes=0.0, n=80)
    config = TeamStrengthConfig(rating_prior_matches=5.0, promoted_prior_matches=20.0)
    promoted = TeamStrengthModel(config=config, promoted_teams=frozenset({1})).fit(matches)

    mean = promoted.league_mean_goals
    unshrunk = 3.0 / mean
    # 80 matches' worth of weight against a 20-match prior leaves the shrink factor at 0.8 in log
    # space — most of the way to the raw ratio, not all of it. "Close", not "identical".
    assert math.log(promoted.attack[1]) == pytest.approx(0.8 * math.log(unshrunk), rel=1e-6)


def test_describe_reports_the_shrinkage_configuration_and_named_clubs() -> None:
    config = TeamStrengthConfig(rating_prior_matches=8.0, promoted_prior_matches=20.0)
    model = TeamStrengthModel(config=config, promoted_teams=frozenset({3, 1}))
    description = model.describe()

    assert description["rating_prior_matches"] == 8.0
    assert description["promoted_prior_matches"] == 20.0
    assert description["promoted_teams"] == [1, 3]
