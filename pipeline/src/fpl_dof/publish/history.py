"""The per-player trend payload. E6-S3 and E6-S5, FR-29, DL-37.

Two series per player, from two silver tables, because FPL publishes them differently:

* ``gameweeks`` — what the player did, from ``player_gameweek``. One entry per fixture, so a double
  gameweek is two entries sharing a ``gw``.
* ``prices`` — price and ownership, from ``price_history``, the daily accumulator. The per-gameweek
  table carries a ``selected_by`` **count**, not a percentage, and only for gameweeks that have been
  played; ownership is therefore published from one table only, always as a percentage.

**Current season only** (DL-37). Deep history exists in silver and reaches the model as a
prior-season feature (DL-31), which is the honest place for it: a chart that puts two scoring
regimes on one axis is a chart that misleads. Before the first gameweek is scored this artefact is
empty, which is the same normal preseason state as ``week.json`` and ``plan.json`` (DL-20) — the
payload says so in ``gameweeks_played`` rather than leaving a view to infer it from an empty array.

**Measured, not forecast.** Invariant 6 requires a mean to carry its uncertainty; that applies to
expected points, which this artefact does not contain. Attaching an error bar to a goal that was
actually scored would be inventing one, and a fabricated interval is worse than none (DP-09).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from fpl_dof.config.models import HistoryArtefactConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.scoring import StatLine, defensive_contribution_points


def build_history(
    *,
    player_gameweek: pd.DataFrame | None,
    price_history: pd.DataFrame | None,
    players: pd.DataFrame,
    season: str,
    rules: GameRules,
    config: HistoryArtefactConfig,
    contract_version: int,
) -> dict[str, Any]:
    """The whole ``history.json`` payload. Pure: no I/O, no clock, no config loading (DP-03)."""
    gameweeks = _current_season(player_gameweek, season)
    prices = price_history if price_history is not None else _empty_prices()

    by_player = _gameweek_series(gameweeks, rules)
    price_series = _price_series(prices, config)

    known = {as_int(row.player_id) for row in players.itertuples()}
    entries = [
        {
            "id": player_id,
            "gameweeks": by_player.get(player_id, []),
            "prices": price_series.get(player_id, []),
        }
        for player_id in sorted(known)
    ]
    # A player with neither series carries no information and is a third of the payload preseason.
    # Dropped rather than published empty; a view joins on `id` and treats a missing entry the same
    # way it treats an empty one.
    entries = [entry for entry in entries if entry["gameweeks"] or entry["prices"]]

    played = int(gameweeks["gameweek"].max()) if not gameweeks.empty else 0
    observed = _observed_window(prices)
    return {
        "contract_version": contract_version,
        "season": season,
        "gameweeks_played": played,
        "observed_from": observed[0],
        "observed_to": observed[1],
        "players": entries,
    }


def _empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=["observed_at", "player_id", "price", "selected_by_percent"])


def _current_season(frame: pd.DataFrame | None, season: str) -> pd.DataFrame:
    """Restrict to the season being published.

    The silver table holds the backfilled prior seasons alongside the current one, and
    ``player_id`` is **reassigned between seasons** — so a series that quietly spanned seasons would
    attribute one player's past to whoever inherited their number (the R-10 failure, in chart form).
    The season filter is what makes joining on ``player_id`` safe here at all.
    """
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["player_id", "gameweek"])
    return frame[frame["season"] == season]


def _observed_window(prices: pd.DataFrame) -> tuple[str | None, str | None]:
    if prices.empty:
        return (None, None)
    stamps = pd.to_datetime(prices["observed_at"], utc=True)
    return (_date(stamps.min()), _date(stamps.max()))


def _date(value: pd.Timestamp) -> str:
    return str(pd.Timestamp(value).tz_convert("UTC").date())


def _gameweek_series(frame: pd.DataFrame, rules: GameRules) -> dict[int, list[dict[str, Any]]]:
    """Per-player performance entries, ascending by gameweek."""
    series: dict[int, list[dict[str, Any]]] = {}
    if frame.empty:
        return series

    ordered = frame.sort_values(["player_id", "gameweek", "kickoff_time"], na_position="last")
    for row in ordered.to_dict(orient="records"):
        record = {str(key): value for key, value in row.items()}
        player_id = as_int(record["player_id"])
        series.setdefault(player_id, []).append(_point(record, rules))
    return series


def _point(record: dict[str, Any], rules: GameRules) -> dict[str, Any]:
    point: dict[str, Any] = {
        "gw": as_int(record["gameweek"]),
        "pts": as_int(record["total_points"]),
        "mins": as_int(record["minutes"]),
        "goals": as_int(record["goals_scored"]),
        "assists": as_int(record["assists"]),
        "price": round(as_float(record["price"]), 1),
    }

    # Absent means not measured, which is a different claim from zero (DL-18). Emitting these only
    # when the source has a value is what keeps a chart from plotting an unmeasured gameweek as a
    # nil return — and it is what makes the omission checkable rather than a convention.
    for key, column in (("xg", "expected_goals"), ("xa", "expected_assists")):
        value = record.get(column)
        if value is not None and not pd.isna(value):
            point[key] = round(as_float(value), 3)

    actions = record.get("defensive_contribution")
    if actions is not None and not pd.isna(actions):
        count = as_int(actions)
        point["dc"] = count
        point["dc_pts"] = _defensive_points(count, str(record["position"]), rules)
    return point


def _defensive_points(actions: int, position: str, rules: GameRules) -> int:
    """The award actually earned, from the rules configuration rather than a literal (Invariant 2).

    The threshold differs by position and has changed between seasons; recomputing it here from a
    hardcoded number would be the same bug as a literal ``4`` for a forward's goal, one language
    over from where that rule is usually broken.
    """
    return defensive_contribution_points(
        StatLine(defensive_actions=actions), Position(position), rules
    )


def _price_series(
    prices: pd.DataFrame, config: HistoryArtefactConfig
) -> dict[int, list[dict[str, Any]]]:
    """Per-player price and ownership, emitted on change.

    A daily observation per player is roughly 176,000 points over a season, the vast majority
    identical to the one before. Both quantities are step functions, so emitting the first
    observation, the last, and every change in between is close to lossless at a fraction of the
    size — a consumer carries the last value forward to fill the gaps, which the schema says.
    """
    series: dict[int, list[dict[str, Any]]] = {}
    if prices.empty:
        return series

    frame = prices.copy()
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    ordered = frame.sort_values(["player_id", "observed_at"])

    threshold = config.ownership_change_threshold
    for player_id, group in ordered.groupby("player_id"):
        points: list[dict[str, Any]] = []
        last: dict[str, Any] | None = None
        records = group.to_dict(orient="records")
        for index, record in enumerate(records):
            point = {
                "on": _date(record["observed_at"]),
                "price": round(as_float(record["price"]), 1),
                "owned": round(as_float(record["selected_by_percent"]), 1),
            }
            # The first and last observations always land, so the series starts where the record
            # does and ends at today's value rather than at whenever it last moved — a trend line
            # that stops short reads as a player who stopped existing.
            is_edge = index == 0 or index == len(records) - 1
            keep = is_edge or last is None or _changed(last, point, threshold)
            duplicate = bool(points) and points[-1]["on"] == point["on"]
            if keep and not duplicate:
                points.append(point)
                last = point
        series[as_int(player_id)] = points
    return series


def _changed(last: dict[str, Any], point: dict[str, Any], threshold: float) -> bool:
    if last["price"] != point["price"]:
        return True
    return bool(abs(as_float(last["owned"]) - as_float(point["owned"])) >= threshold)


__all__ = ["build_history"]
