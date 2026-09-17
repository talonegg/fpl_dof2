"""DL-70: the published trailing-form ranking is the backtest's benchmark, by construction."""

from __future__ import annotations

import pandas as pd

from fpl_dof.forecast.baselines import trailing_form_prediction
from fpl_dof.forecast.form import FORM_COLUMN, RANK_COLUMN, form_by_player_id, trailing_form

AS_OF = pd.Timestamp("2026-09-17T00:00:00Z")


def _rows() -> pd.DataFrame:
    rows = []
    # Player 10 plays eight matches at 6 a match; player 20 plays two at 9; player 30 never plays.
    for gameweek in range(1, 9):
        kickoff = pd.Timestamp("2026-08-15T14:00:00Z") + pd.Timedelta(days=7 * (gameweek - 1))
        rows.append({"player_code": 10, "kickoff_time": kickoff, "total_points": 6, "minutes": 90})
        rows.append({"player_code": 30, "kickoff_time": kickoff, "total_points": 0, "minutes": 0})
        if gameweek <= 2:
            rows.append(
                {"player_code": 20, "kickoff_time": kickoff, "total_points": 9, "minutes": 70}
            )
    return pd.DataFrame(rows)


def test_form_is_points_per_match_over_the_last_six_appearances() -> None:
    form = trailing_form(_rows(), as_of=AS_OF).set_index("player_code")
    assert form.loc[10, FORM_COLUMN] == 6.0
    assert form.loc[20, FORM_COLUMN] == 9.0
    assert 30 not in form.index, "a player who never appeared has no form, not zero form"
    assert form.loc[20, RANK_COLUMN] == 1
    assert form.loc[10, RANK_COLUMN] == 2


def test_the_published_figure_is_the_benchmark_the_backtest_uses() -> None:
    frame = _rows()
    played = frame[frame["minutes"] > 0]
    benchmark = trailing_form_prediction(played, as_of=AS_OF).set_index("player_code")
    form = trailing_form(frame, as_of=AS_OF).set_index("player_code")
    for code in form.index:
        assert form.loc[code, FORM_COLUMN] == round(float(benchmark.loc[code, "prediction"]), 3)


def test_only_matches_before_as_of_count() -> None:
    early = pd.Timestamp("2026-08-16T00:00:00Z")
    form = trailing_form(_rows(), as_of=early).set_index("player_code")
    assert form.loc[10, FORM_COLUMN] == 6.0
    assert len(form) == 2


def test_no_history_means_no_form() -> None:
    assert trailing_form(None, as_of=AS_OF).empty
    assert trailing_form(pd.DataFrame(), as_of=AS_OF).empty
    assert form_by_player_id(pd.DataFrame(), pd.DataFrame()) == {}


def test_form_is_keyed_back_to_the_season_local_id() -> None:
    form = trailing_form(_rows(), as_of=AS_OF)
    players = pd.DataFrame(
        [{"player_id": 1, "player_code": 10}, {"player_id": 2, "player_code": 20}]
    )
    assert form_by_player_id(form, players) == {1: (6.0, 2), 2: (9.0, 1)}
