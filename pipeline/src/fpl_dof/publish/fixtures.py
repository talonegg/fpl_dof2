"""The fixture ticker payload — a team-by-gameweek difficulty grid. E6-S8, FR-30, DL-37.

FPL's own fixture difficulty is a static integer set before a ball is kicked and never revised.
Beating it is the entire point of the story, and the signal to beat it with already exists:
:class:`~fpl_dof.forecast.models.TeamStrengthModel` (M2) fits multiplicative attack and defence
ratings, so a fixture's expected goals is ``league_mean x attack x opponent_weakness x home``.

**Why it is legitimate to read M2 here while it stays dark in the model.** DL-34 left M2's xG
variant unpromoted because the backtest scores every fixture at league-average opposition and
therefore cannot measure it — enabling it in the forecast would be acting on faith (DP-12). That
gating is about a change that alters a *recommendation*. This alters none: the optimiser, the plan
and ``players.json`` are untouched, and what is published is a **descriptive label on a fixture**
that the reader can check against their own eyes every weekend. DL-37 records the reasoning.

This module lives in ``publish/`` rather than ``forecast/`` because it needs both a component model
and :func:`~fpl_dof.optimise.chips.gameweek_shapes`, and the writer at the seam is the one place
downstream of both. Reusing that function rather than counting fixtures again is deliberate: a
second answer to "does this club play twice in GW24" is a second answer that can disagree.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from fpl_dof.config.models import FixtureTickerConfig
from fpl_dof.forecast.models import TeamStrengthModel
from fpl_dof.frames import as_int
from fpl_dof.optimise.chips import GameweekShape, gameweek_shapes

MODEL_NAME = "M2_team_strength"


def difficulty_scale(config: FixtureTickerConfig) -> dict[str, Any]:
    """The published description of what a difficulty number means (DP-10)."""
    return {
        "minimum": config.minimum,
        "neutral": config.neutral,
        "maximum": config.maximum,
        "anchor_ratio": config.difficulty_anchor_ratio,
        "description": (
            f"{config.neutral:g} is a fixture the model rates exactly league-average; lower is "
            f"easier. Attack difficulty falls as the goals the model expects this club to score "
            f"rise above the league mean, defence difficulty rises as the goals it expects them to "
            f"concede do, and the overall score is the mean of the two. A club expected to score "
            f"{config.difficulty_anchor_ratio:g}x the league mean scores {config.minimum:g} for "
            f"attack. Scores are clipped to {config.minimum:g}-{config.maximum:g}."
        ),
    }


def _steepness(config: FixtureTickerConfig) -> float:
    """``k`` in ``neutral -+ k x ln(ratio)``, derived from the anchor rather than set separately.

    Two tunables that must agree is one tunable and a bug waiting to happen, so the steepness is
    solved for: at the anchor ratio the score lands exactly on the end of the scale.
    """
    span = config.neutral - config.minimum
    return span / math.log(config.difficulty_anchor_ratio)


def _score(ratio: float, config: FixtureTickerConfig, *, harder_when_larger: bool) -> float:
    """Turn a ratio-to-league-mean into a point on the difficulty scale.

    Logarithmic because the ratings are multiplicative: halving and doubling the league mean are
    equal and opposite departures from average, and a linear map would not make them so.
    """
    if ratio <= 0:
        ratio = 1e-6
    shift = _steepness(config) * math.log(ratio)
    value = config.neutral + shift if harder_when_larger else config.neutral - shift
    return round(min(config.maximum, max(config.minimum, value)), 2)


def _mean(values: Sequence[float]) -> float | None:
    """Mean over the fixtures actually scheduled. A blank contributes nothing, and is flagged."""
    return round(sum(values) / len(values), 2) if values else None


def build_fixtures(
    *,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    model: TeamStrengthModel,
    from_gameweek: int,
    to_gameweek: int,
    config: FixtureTickerConfig,
    contract_version: int,
) -> dict[str, Any]:
    """The whole ``fixtures.json`` payload. Pure: no I/O, no clock, no config loading (DP-03)."""
    team_ids = [as_int(row.team_id) for row in teams.itertuples()]
    short = {as_int(row.team_id): str(row.short_name) for row in teams.itertuples()}
    full = {as_int(row.team_id): str(row.name) for row in teams.itertuples()}

    window = list(range(from_gameweek, to_gameweek + 1))
    shapes = gameweek_shapes(fixtures, team_ids)
    scheduled = _by_team_and_gameweek(fixtures, window)

    payload_teams = [
        _team(
            team_id=team_id,
            short=short,
            full=full,
            window=window,
            shapes=shapes,
            scheduled=scheduled,
            model=model,
            config=config,
        )
        for team_id in sorted(team_ids)
    ]

    return {
        "contract_version": contract_version,
        "from_gameweek": from_gameweek,
        "to_gameweek": to_gameweek,
        "scale": difficulty_scale(config),
        "model": {
            "name": MODEL_NAME,
            "league_mean_goals": round(model.league_mean_goals, 4),
            "home_advantage": round(model.home_advantage, 4),
            # Zero means the model has no ratings at all — preseason, before any fixture of this
            # season has been played. Every difficulty is then the neutral score, which is the
            # honest answer and is visible rather than silent (DP-15).
            "teams_rated": len(model.attack),
        },
        "teams": payload_teams,
    }


def _by_team_and_gameweek(
    fixtures: pd.DataFrame, window: Sequence[int]
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """Index the fixture table by (club, gameweek), from each club's own perspective.

    Each fixture is indexed twice, once per side, because the grid is read a row at a time and a
    club's row wants the opponent, not the pairing.
    """
    index: dict[tuple[int, int], list[dict[str, Any]]] = {}
    if fixtures.empty:
        return index

    weeks = set(window)
    for row in fixtures.itertuples():
        # A fixture with no gameweek is one the game has not scheduled yet — real, and common for
        # rearranged games. `bool(...)` because `pd.isna` narrows its argument type and would
        # otherwise convince the checker this branch cannot be taken.
        if bool(pd.isna(row.gameweek)):
            continue
        gameweek = as_int(row.gameweek)
        if gameweek not in weeks:
            continue
        home, away = as_int(row.home_team_id), as_int(row.away_team_id)
        kickoff = _iso(getattr(row, "kickoff_time", None))
        index.setdefault((home, gameweek), []).append(
            {"opponent_id": away, "at_home": True, "kickoff_utc": kickoff}
        )
        index.setdefault((away, gameweek), []).append(
            {"opponent_id": home, "at_home": False, "kickoff_utc": kickoff}
        )
    return index


def _iso(value: Any) -> str | None:
    if value is None or bool(pd.isna(value)):
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC").to_pydatetime().isoformat().replace("+00:00", "Z")


def _team(
    *,
    team_id: int,
    short: Mapping[int, str],
    full: Mapping[int, str],
    window: Sequence[int],
    shapes: Mapping[int, GameweekShape],
    scheduled: Mapping[tuple[int, int], list[dict[str, Any]]],
    model: TeamStrengthModel,
    config: FixtureTickerConfig,
) -> dict[str, Any]:
    weeks: list[dict[str, Any]] = []
    overall: list[float] = []
    attack: list[float] = []
    defence: list[float] = []

    for gameweek in window:
        entries = []
        for fixture in scheduled.get((team_id, gameweek), []):
            entry = _entry(team_id, fixture, short, model, config)
            entries.append(entry)
            overall.append(entry["difficulty"])
            attack.append(entry["attack_difficulty"])
            defence.append(entry["defence_difficulty"])

        # Taken from the shared shape rather than from `len(entries)`, so the ticker and the chip
        # calendar cannot disagree about what a double gameweek is. Falls back to the local count
        # when the fixture table carries no rows for this gameweek at all.
        shape = shapes.get(gameweek)
        count = shape.fixtures_by_team.get(team_id, 0) if shape else len(entries)
        weeks.append(
            {
                "gameweek": gameweek,
                "is_double": count >= 2,
                "is_blank": count == 0,
                "fixtures": entries,
            }
        )

    return {
        "team_id": team_id,
        "team": short.get(team_id, str(team_id)),
        "name": full.get(team_id, str(team_id)),
        "mean_difficulty": _mean(overall),
        "mean_attack_difficulty": _mean(attack),
        "mean_defence_difficulty": _mean(defence),
        "gameweeks": weeks,
    }


def _entry(
    team_id: int,
    fixture: Mapping[str, Any],
    short: Mapping[int, str],
    model: TeamStrengthModel,
    config: FixtureTickerConfig,
) -> dict[str, Any]:
    opponent = int(fixture["opponent_id"])
    at_home = bool(fixture["at_home"])

    goals_for = model.expected_goals(team_id, opponent, at_home=at_home)
    goals_against = model.expected_goals(opponent, team_id, at_home=not at_home)
    mean = model.league_mean_goals or 1.0

    attack = _score(goals_for / mean, config, harder_when_larger=False)
    defence = _score(goals_against / mean, config, harder_when_larger=True)
    return {
        "opponent_id": opponent,
        "opponent": short.get(opponent, str(opponent)),
        "at_home": at_home,
        "kickoff_utc": fixture.get("kickoff_utc"),
        # The derivation, published next to the score so the score is checkable rather than
        # asserted (DP-09). A reader who disagrees with a 4.6 can see which half produced it.
        "expected_goals_for": round(goals_for, 3),
        "expected_goals_against": round(goals_against, 3),
        "difficulty": round((attack + defence) / 2, 2),
        "attack_difficulty": attack,
        "defence_difficulty": defence,
    }


__all__ = ["MODEL_NAME", "build_fixtures", "difficulty_scale"]
