"""Scoring the component chain over a fixture horizon. The seam D-25 named.

``xp_v1`` forecasts **one player against one fixture**. Everything downstream of the forecast — the
squad MILP, the multi-gameweek plan, the published contract — wants one row per player carrying a
number for each gameweek of a horizon, a total across it, and a standard deviation for both
(Invariant 6). Nothing bridged the two, which is why the pipeline went on publishing ``xp_v0``
while the backtest graded ``xp_v1``: the improved model had no way to reach the app (D-25, DL-46).

This module is that bridge, and it is deliberately the **only** copy of it. The chip replay built
one first, for its own purposes; a second copy on the live path would be two implementations of the
same arithmetic drifting apart in exactly the way the parity test exists to catch, so the replay now
imports this one.

Two things it is careful about:

* **The fixture calendar decides who plays, not the player list.** A blank gameweek scores nothing
  and a double scores twice, and both facts come from the calendar — which is published weeks ahead
  and is genuinely knowable at the deadline — never from whether a given player happens to have a
  row (Invariant 5).
* **Variance is carried, not reconstructed.** Means add across a gameweek's fixtures and so do
  variances, which treats a double gameweek's two matches as independent. That is very nearly true
  and errs toward understating the spread rather than overstating it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.models import ComponentModels, MinutesDistribution
from fpl_dof.forecast.xp_v1 import COMPONENT_ORDER, fixture_opposition, score_player
from fpl_dof.frames import as_int, gameweek_column, gameweek_sd_column
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import GameRules

log = get_logger(__name__)

#: ``(club, gameweek)`` -> the fixtures that club plays, each as ``(opponent, at_home)``.
#:
#: A tuple rather than a single fixture because a gameweek is not guaranteed to hold exactly one:
#: zero is a blank and two is a double, and a type that cannot express those makes them special
#: cases somebody eventually forgets.
FixtureIndex = Mapping[tuple[int, int], tuple[tuple[int, bool], ...]]


@dataclass(frozen=True, slots=True)
class WeekForecast:
    """One player, one gameweek, summed over however many fixtures that gameweek holds."""

    mean: float
    variance: float
    components: dict[str, float]

    @property
    def standard_deviation(self) -> float:
        return math.sqrt(max(0.0, self.variance))


def fixture_index_from_fixtures(fixtures: pd.DataFrame, horizon: Sequence[int]) -> FixtureIndex:
    """The live calendar, from the silver ``fixture`` table.

    Read from the fixture rows themselves, which is what makes a blank gameweek a real absence
    rather than an accident of which players happen to be in the frame.
    """
    index: dict[tuple[int, int], set[tuple[int, bool]]] = {}
    if fixtures.empty:
        return {}
    wanted = fixtures[fixtures["gameweek"].isin(list(horizon))].dropna(
        subset=["gameweek", "home_team_id", "away_team_id"]
    )
    for row in wanted.itertuples():
        gameweek = as_int(row.gameweek)
        home, away = as_int(row.home_team_id), as_int(row.away_team_id)
        index.setdefault((home, gameweek), set()).add((away, True))
        index.setdefault((away, gameweek), set()).add((home, False))
    return {key: tuple(sorted(value)) for key, value in index.items()}


def fixture_index_from_history(
    history: pd.DataFrame, season: str, horizon: Sequence[int]
) -> FixtureIndex:
    """The same calendar, reconstructed from an archive that has no fixture table.

    Read from the *fixture* columns of the archive, never from whether a given player has a row:
    the calendar is published weeks ahead and is knowable at the deadline, whereas who was picked
    is not.
    """
    if history.empty:
        return {}
    window = history[(history["season"] == season) & (history["gameweek"].isin(list(horizon)))]
    index: dict[tuple[int, int], set[tuple[int, bool]]] = {}
    for row in window.dropna(subset=["team_id", "opponent_team_id"]).itertuples():
        key = (as_int(row.team_id), as_int(row.gameweek))
        index.setdefault(key, set()).add((as_int(row.opponent_team_id), bool(row.was_home)))
    return {key: tuple(sorted(value)) for key, value in index.items()}


def week_forecast(
    feature_row: pd.Series,
    fixtures: Sequence[tuple[int, bool]],
    *,
    team_id: int,
    models: ComponentModels,
    rules: GameRules,
    config: ForecastConfig,
    status_multiplier: float = 1.0,
) -> WeekForecast:
    """One player, one gameweek. A blank scores nothing; a double is two fixtures added."""
    components = dict.fromkeys(COMPONENT_ORDER, 0.0)
    if not fixtures:
        return WeekForecast(mean=0.0, variance=0.0, components=components)
    mean = 0.0
    variance = 0.0
    for opponent_id, at_home in fixtures:
        forecast = score_player(
            feature_row,
            models,
            rules,
            config,
            opposition=fixture_opposition(
                models, team_id=team_id, opponent_id=opponent_id, at_home=at_home
            ),
            status_multiplier=status_multiplier,
        )
        mean += forecast.expected_points
        variance += forecast.variance
        for name, value in forecast.components.items():
            components[name] += value
    return WeekForecast(mean=mean, variance=variance, components=components)


def minutes_for(
    feature_row: pd.Series,
    models: ComponentModels,
    *,
    status_multiplier: float = 1.0,
) -> MinutesDistribution:
    """M1's distribution for this player, independent of any fixture.

    Asked of the model directly rather than read off a scored fixture, because a player whose club
    has a blank gameweek still has expected minutes — his club simply is not playing.
    """
    return models.minutes.predict_row(
        feature_row, str(feature_row["position"]), status_multiplier=status_multiplier
    )


def horizon_frame(
    features: pd.DataFrame,
    *,
    identity: pd.DataFrame,
    horizon: Sequence[int],
    fixtures: FixtureIndex,
    models: ComponentModels,
    rules: GameRules,
    config: ForecastConfig,
    status_multipliers: Mapping[int, float] | None = None,
    discount: float = 1.0,
) -> pd.DataFrame:
    """One row per player, scored against each horizon gameweek's real fixture.

    ``identity`` is indexed by ``player_code`` and its columns are copied onto every output row
    verbatim. That is how one scorer serves both callers: the live path attaches the published
    player record, the replay attaches a reconstructed one, and neither has to teach this function
    what a player is. It must carry ``team_id``; a player without one cannot be given a fixture and
    is dropped.

    ``discount`` compounds per gameweek into the horizon **total only** — the per-gameweek columns
    stay undiscounted, because the multi-gameweek optimiser applies its own discount to them and
    two discounts silently multiplied is a number nobody can argue with (DP-10).
    """
    weeks = list(horizon)
    if not weeks:
        raise ValueError("a horizon of no gameweeks cannot be scored")
    multipliers = status_multipliers or {}

    rows: list[dict[str, object]] = []
    for _, feature_row in features.iterrows():
        code = as_int(feature_row["player_code"])
        if code not in identity.index:
            continue
        known = identity.loc[code]
        if bool(pd.isna(known["team_id"])):
            continue
        team_id = as_int(known["team_id"])
        status_multiplier = float(multipliers.get(code, 1.0))
        row: dict[str, object] = {"player_code": code}
        row.update({str(name): value for name, value in known.items()})

        minutes = minutes_for(feature_row, models, status_multiplier=status_multiplier)
        row["expected_minutes"] = round(minutes.expected_minutes, 2)
        row["p_no_appearance"] = round(minutes.none, 4)
        row["p_short_appearance"] = round(minutes.short, 4)
        row["p_long_appearance"] = round(minutes.long, 4)

        total_mean = 0.0
        total_variance = 0.0
        for offset, week in enumerate(weeks):
            scored = week_forecast(
                feature_row,
                fixtures.get((team_id, week), ()),
                team_id=team_id,
                models=models,
                rules=rules,
                config=config,
                status_multiplier=status_multiplier,
            )
            row[gameweek_column(week)] = round(scored.mean, 4)
            row[gameweek_sd_column(week)] = round(scored.standard_deviation, 4)
            if offset == 0:
                # The decomposition published beside the ranking describes the gameweek being
                # decided, which is the next one. A horizon-wide decomposition would be a different
                # quantity presented under the same name.
                for name, value in scored.components.items():
                    row[f"component_{name}"] = round(value, 4)
            weight = discount**offset
            total_mean += scored.mean * weight
            total_variance += scored.variance * weight**2

        row["xp_next"] = row[gameweek_column(weeks[0])]
        row["xp_next_sd"] = row[gameweek_sd_column(weeks[0])]
        row["xp_horizon"] = round(total_mean, 4)
        row["xp_horizon_sd"] = round(math.sqrt(max(0.0, total_variance)), 4)
        rows.append(row)

    if not rows:
        columns = [
            "player_code",
            *identity.columns,
            "xp_next",
            "xp_next_sd",
            "xp_horizon",
            "xp_horizon_sd",
            *[f"component_{name}" for name in COMPONENT_ORDER],
        ]
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows)


__all__ = [
    "FixtureIndex",
    "WeekForecast",
    "fixture_index_from_fixtures",
    "fixture_index_from_history",
    "horizon_frame",
    "minutes_for",
    "week_forecast",
]
