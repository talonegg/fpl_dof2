"""The conformed silver model — the contract between sources and everything downstream.

These four tables are what the rest of the pipeline is allowed to know about. They carry no source
identifiers, no source-specific field names and no source-specific units: prices are £m, times are
timezone-aware UTC, positions are the four canonical codes.

Validation is not advisory. A schema violation fails the run rather than passing bad data through
(Invariant 7): silently wrong data is the failure mode this project can least afford, because it
produces a squad that looks perfectly reasonable and is not.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

from fpl_dof.rules.models import Position

POSITIONS = tuple(p.value for p in Position)


class Table(StrEnum):
    """Canonical table names. Nothing constructs a silver filename by hand."""

    PLAYER = "player"
    TEAM = "team"
    FIXTURE = "fixture"
    GAMEWEEK = "gameweek"
    PLAYER_SEASON_HISTORY = "player_season_history"


class TeamSchema(pa.DataFrameModel):
    team_id: Series[int] = pa.Field(unique=True, ge=1)
    name: Series[str]
    short_name: Series[str]
    strength_overall_home: Series[int] = pa.Field(ge=0, le=5)
    strength_overall_away: Series[int] = pa.Field(ge=0, le=5)

    class Config:
        strict = True
        coerce = True


class PlayerSchema(pa.DataFrameModel):
    player_id: Series[int] = pa.Field(unique=True, ge=1)
    code: Series[int]
    web_name: Series[str]
    full_name: Series[str]
    position: Series[str] = pa.Field(isin=POSITIONS)
    team_id: Series[int] = pa.Field(ge=1)
    price: Series[float] = pa.Field(gt=0, le=25.0)
    """In £m. Converted from tenths once, at the ingestion boundary, and never again."""
    status: Series[str]
    chance_of_playing_next_round: Series[float] = pa.Field(ge=0, le=100, nullable=True)
    selected_by_percent: Series[float] = pa.Field(ge=0, le=100)
    news: Series[str] = pa.Field(nullable=True)

    class Config:
        strict = True
        coerce = True


class FixtureSchema(pa.DataFrameModel):
    fixture_id: Series[int] = pa.Field(unique=True)
    gameweek: Series[int] = pa.Field(ge=1, le=38, nullable=True)
    kickoff_time: Series[pd.DatetimeTZDtype] = pa.Field(
        dtype_kwargs={"unit": "ns", "tz": "UTC"}, nullable=True
    )
    home_team_id: Series[int] = pa.Field(ge=1)
    away_team_id: Series[int] = pa.Field(ge=1)
    home_difficulty: Series[int] = pa.Field(ge=1, le=5)
    away_difficulty: Series[int] = pa.Field(ge=1, le=5)
    finished: Series[bool]

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def teams_differ(cls, df: pd.DataFrame) -> Any:  # type: ignore[misc]  # noqa: N805
        return df["home_team_id"] != df["away_team_id"]


class GameweekSchema(pa.DataFrameModel):
    gameweek: Series[int] = pa.Field(unique=True, ge=1, le=38)
    name: Series[str]
    deadline_time: Series[pd.DatetimeTZDtype] = pa.Field(dtype_kwargs={"unit": "ns", "tz": "UTC"})
    finished: Series[bool]
    is_next: Series[bool]

    class Config:
        strict = True
        coerce = True


class PlayerSeasonHistorySchema(pa.DataFrameModel):
    """One row per player per prior season. The entire evidence base for the cold-start model."""

    player_id: Series[int] = pa.Field(ge=1)
    season_name: Series[str]
    minutes: Series[int] = pa.Field(ge=0)
    starts: Series[int] = pa.Field(ge=0)
    goals_scored: Series[int] = pa.Field(ge=0)
    assists: Series[int] = pa.Field(ge=0)
    clean_sheets: Series[int] = pa.Field(ge=0)
    goals_conceded: Series[int] = pa.Field(ge=0)
    own_goals: Series[int] = pa.Field(ge=0)
    penalties_saved: Series[int] = pa.Field(ge=0)
    penalties_missed: Series[int] = pa.Field(ge=0)
    yellow_cards: Series[int] = pa.Field(ge=0)
    red_cards: Series[int] = pa.Field(ge=0)
    saves: Series[int] = pa.Field(ge=0)
    bonus: Series[int] = pa.Field(ge=0)
    bps: Series[int]
    defensive_contribution: Series[int] = pa.Field(ge=0)
    tackles: Series[int] = pa.Field(ge=0)
    recoveries: Series[int] = pa.Field(ge=0)
    clearances_blocks_interceptions: Series[int] = pa.Field(ge=0)
    expected_goals: Series[float] = pa.Field(ge=0)
    expected_assists: Series[float] = pa.Field(ge=0)
    start_cost: Series[float] = pa.Field(gt=0)
    end_cost: Series[float] = pa.Field(gt=0)
    total_points: Series[int]

    class Config:
        strict = True
        coerce = True
        unique = ["player_id", "season_name"]  # noqa: RUF012 - pandera Config, not a dataclass


SCHEMAS: dict[Table, type[pa.DataFrameModel]] = {
    Table.PLAYER: PlayerSchema,
    Table.TEAM: TeamSchema,
    Table.FIXTURE: FixtureSchema,
    Table.GAMEWEEK: GameweekSchema,
    Table.PLAYER_SEASON_HISTORY: PlayerSeasonHistorySchema,
}


class SchemaViolationError(RuntimeError):
    """A conformed table did not match its schema. The run stops here."""


def validate(table: Table, frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and return the frame, raising :class:`SchemaViolationError` on any failure.

    ``lazy=True`` so the error names every problem at once rather than only the first — the same
    reasoning as the squad validator returning all violations.
    """
    schema = SCHEMAS[table]
    try:
        return schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise SchemaViolationError(
            f"silver table {table.value!r} failed validation:\n{exc}"
        ) from exc
