"""The model-free trailing-form ranking, for publication beside the forecast (DL-70).

The backtest grades ``xp_v1`` against a benchmark that uses no model at all: points per match over
a player's last six appearances. At the head of the ranking that benchmark still wins (DL-21), and
the owner is told to treat the forecast's ordering as a prompt to look rather than a reason to act.
Publishing only the model's side of that disagreement would hide the number the model card says
matters. This module produces the other side, **from the same function the harness uses**, so the
two views agree by construction (DP-12) and the published figure carries its provenance (DP-09).

Pure: a frame in, a frame out (DP-03).
"""

from __future__ import annotations

import pandas as pd

from fpl_dof.forecast.baselines import trailing_form_prediction

FORM_COLUMN = "form_points_per_match"
RANK_COLUMN = "form_rank"


def trailing_form(player_gameweek: pd.DataFrame | None, *, as_of: pd.Timestamp) -> pd.DataFrame:
    """Per ``player_code``: points per match over the last six appearances, and the rank on it.

    Only matches kicked off before ``as_of`` count, which is the same knowability rule the
    harness applies at a deadline (Invariant 5). A player with no appearance has no row here —
    the caller publishes ``null``, not zero: "has not played" is not "scores nothing".
    """
    empty = pd.DataFrame(columns=["player_code", FORM_COLUMN, RANK_COLUMN])
    if player_gameweek is None or player_gameweek.empty:
        return empty
    needed = {"player_code", "kickoff_time", "total_points"}
    if not needed.issubset(player_gameweek.columns):
        return empty
    played = player_gameweek
    if "minutes" in played.columns:
        played = played[played["minutes"] > 0]
    played = played.dropna(subset=["player_code", "kickoff_time"])
    if played.empty:
        return empty

    form = trailing_form_prediction(played, as_of=as_of)
    if form.empty:
        return empty
    form = form.rename(columns={"prediction": FORM_COLUMN})
    form[FORM_COLUMN] = form[FORM_COLUMN].astype(float).round(3)
    # "min" so equal form shares a rank rather than being ordered by an accident of sorting.
    form[RANK_COLUMN] = form[FORM_COLUMN].rank(ascending=False, method="min").astype(int)
    form["player_code"] = form["player_code"].astype(int)
    return form[["player_code", FORM_COLUMN, RANK_COLUMN]].reset_index(drop=True)


def form_by_player_id(
    form: pd.DataFrame, players: pd.DataFrame
) -> dict[int, tuple[float | None, int | None]]:
    """``player_id -> (form, rank)``, for consumers keyed on the season-local id."""
    if form.empty or "player_code" not in players.columns:
        return {}
    codes = players[["player_id", "player_code"]].dropna()
    merged = codes.merge(form, on="player_code", how="inner")
    return {
        int(str(row.player_id)): (
            float(str(getattr(row, FORM_COLUMN))),
            int(str(getattr(row, RANK_COLUMN))),
        )
        for row in merged.itertuples()
    }
