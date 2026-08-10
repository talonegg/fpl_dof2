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
    PLAYER_GAMEWEEK = "player_gameweek"
    CHIP = "chip"
    SET_PIECE_NOTE = "set_piece_note"
    PRICE_HISTORY = "price_history"
    ENTRY = "entry"
    ENTRY_PICK = "entry_pick"
    ENTRY_TRANSFER = "entry_transfer"
    ENTRY_CHIP = "entry_chip"


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


class PlayerGameweekSchema(pa.DataFrameModel):
    """One row per player per gameweek appearance. The unit a backtest walks forward over.

    ``player_code`` is the join key across seasons and is not the same thing as ``player_id``:
    FPL reassigns element IDs every season, so joining history on ``player_id`` attributes one
    player's past to whoever inherited their number. The code is stable for the player's career.

    The Defensive Contribution columns are **nullable, and null means not measured**. Before
    2025/26 the component did not exist; writing zero would say the player did no defending, which
    is the absence-of-measurement trap DL-18 records. A model that reads null cannot make that
    mistake by accident, and one that reads zero eventually will.
    """

    season: Series[str]
    gameweek: Series[int] = pa.Field(ge=1, le=38)
    player_code: Series[int] = pa.Field(ge=1)
    player_id: Series[int] = pa.Field(ge=1)
    web_name: Series[str]
    position: Series[str] = pa.Field(isin=POSITIONS)
    team_id: Series[int] = pa.Field(ge=1, nullable=True)
    opponent_team_id: Series[int] = pa.Field(ge=1, nullable=True)
    fixture_id: Series[int] = pa.Field(nullable=True)
    kickoff_time: Series[pd.DatetimeTZDtype] = pa.Field(
        dtype_kwargs={"unit": "ns", "tz": "UTC"}, nullable=True
    )
    """The knowability boundary. A feature computed for this gameweek may use no row whose kickoff
    is at or after this one (Invariant 5), and this column is what makes that checkable."""

    was_home: Series[bool]
    minutes: Series[int] = pa.Field(ge=0, le=120)
    starts: Series[int] = pa.Field(ge=0, nullable=True)
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
    defensive_contribution: Series[int] = pa.Field(ge=0, nullable=True)
    tackles: Series[int] = pa.Field(ge=0, nullable=True)
    recoveries: Series[int] = pa.Field(ge=0, nullable=True)
    clearances_blocks_interceptions: Series[int] = pa.Field(ge=0, nullable=True)
    expected_goals: Series[float] = pa.Field(ge=0, nullable=True)
    expected_assists: Series[float] = pa.Field(ge=0, nullable=True)
    expected_goals_conceded: Series[float] = pa.Field(ge=0, nullable=True)
    price: Series[float] = pa.Field(gt=0)
    selected_by: Series[int] = pa.Field(ge=0, nullable=True)
    total_points: Series[int]

    class Config:
        strict = True
        coerce = True
        unique = [  # noqa: RUF012 - pandera Config, not a dataclass
            "season",
            "gameweek",
            "player_code",
            "fixture_id",
        ]


class ChipSchema(pa.DataFrameModel):
    """Chips as the game publishes them, with their own expiry windows.

    ``stop_event`` is read, never assumed. "Set one expires at GW19" is true this season and is
    exactly the sort of fact that quietly stops being true (Invariant 2).
    """

    chip_id: Series[int] = pa.Field(unique=True)
    name: Series[str]
    chip_type: Series[str]
    start_event: Series[int] = pa.Field(ge=1, le=38)
    stop_event: Series[int] = pa.Field(ge=1, le=38)

    class Config:
        strict = True
        coerce = True


class SetPieceNoteSchema(pa.DataFrameModel):
    team_id: Series[int] = pa.Field(ge=1)
    info_message: Series[str]
    source_link: Series[str] = pa.Field(nullable=True)
    external_link: Series[bool]

    class Config:
        strict = True
        coerce = True


class PriceHistorySchema(pa.DataFrameModel):
    """One row per player per observation day. Accumulates; never overwritten in place.

    FPL publishes only the *current* price and ownership, so history exists only if something
    records it daily. Nothing can reconstruct the days nobody watched.
    """

    observed_at: Series[pd.DatetimeTZDtype] = pa.Field(dtype_kwargs={"unit": "ns", "tz": "UTC"})
    player_id: Series[int] = pa.Field(ge=1)
    player_code: Series[int] = pa.Field(ge=1)
    price: Series[float] = pa.Field(gt=0, le=25.0)
    selected_by_percent: Series[float] = pa.Field(ge=0, le=100)
    transfers_in_event: Series[int] = pa.Field(ge=0)
    transfers_out_event: Series[int] = pa.Field(ge=0)
    cost_change_event: Series[float]
    cost_change_start: Series[float]

    class Config:
        strict = True
        coerce = True
        unique = ["observed_at", "player_id"]  # noqa: RUF012 - pandera Config


class EntrySchema(pa.DataFrameModel):
    """The owner's team as the game reports it. At most one row."""

    entry_id: Series[int] = pa.Field(unique=True, ge=1)
    name: Series[str]
    started_event: Series[int] = pa.Field(ge=1, le=38, nullable=True)
    current_event: Series[int] = pa.Field(ge=1, le=38, nullable=True)
    bank: Series[float] = pa.Field(ge=0, nullable=True)
    squad_value: Series[float] = pa.Field(ge=0, nullable=True)
    total_transfers: Series[int] = pa.Field(ge=0)
    summary_overall_points: Series[int] = pa.Field(nullable=True)
    summary_overall_rank: Series[int] = pa.Field(nullable=True)

    class Config:
        strict = True
        coerce = True


class EntryPickSchema(pa.DataFrameModel):
    entry_id: Series[int] = pa.Field(ge=1)
    gameweek: Series[int] = pa.Field(ge=1, le=38)
    player_id: Series[int] = pa.Field(ge=1)
    slot: Series[int] = pa.Field(ge=1, le=15, description="1-11 start, 12-15 bench, in order.")
    multiplier: Series[int] = pa.Field(ge=0, le=3)
    is_captain: Series[bool]
    is_vice_captain: Series[bool]
    purchase_price: Series[float] = pa.Field(gt=0, nullable=True)
    selling_price: Series[float] = pa.Field(gt=0, nullable=True)

    class Config:
        strict = True
        coerce = True
        unique = ["entry_id", "gameweek", "slot"]  # noqa: RUF012 - pandera Config


class EntryTransferSchema(pa.DataFrameModel):
    entry_id: Series[int] = pa.Field(ge=1)
    gameweek: Series[int] = pa.Field(ge=1, le=38)
    player_in_id: Series[int] = pa.Field(ge=1)
    player_in_cost: Series[float] = pa.Field(gt=0)
    player_out_id: Series[int] = pa.Field(ge=1)
    player_out_cost: Series[float] = pa.Field(gt=0)
    made_at: Series[pd.DatetimeTZDtype] = pa.Field(
        dtype_kwargs={"unit": "ns", "tz": "UTC"}, nullable=True
    )

    class Config:
        strict = True
        coerce = True


class EntryChipSchema(pa.DataFrameModel):
    entry_id: Series[int] = pa.Field(ge=1)
    name: Series[str]
    gameweek: Series[int] = pa.Field(ge=1, le=38)

    class Config:
        strict = True
        coerce = True


SCHEMAS: dict[Table, type[pa.DataFrameModel]] = {
    Table.PLAYER: PlayerSchema,
    Table.TEAM: TeamSchema,
    Table.FIXTURE: FixtureSchema,
    Table.GAMEWEEK: GameweekSchema,
    Table.PLAYER_SEASON_HISTORY: PlayerSeasonHistorySchema,
    Table.PLAYER_GAMEWEEK: PlayerGameweekSchema,
    Table.CHIP: ChipSchema,
    Table.SET_PIECE_NOTE: SetPieceNoteSchema,
    Table.PRICE_HISTORY: PriceHistorySchema,
    Table.ENTRY: EntrySchema,
    Table.ENTRY_PICK: EntryPickSchema,
    Table.ENTRY_TRANSFER: EntryTransferSchema,
    Table.ENTRY_CHIP: EntryChipSchema,
}

#: Tables that only exist when the owner has configured a team ID, or when the season has started.
#: Their absence is normal, not a failure — the pipeline degrades rather than breaks (DP-15).
OPTIONAL_TABLES: frozenset[Table] = frozenset(
    {
        Table.PLAYER_GAMEWEEK,
        Table.SET_PIECE_NOTE,
        Table.PRICE_HISTORY,
        Table.ENTRY,
        Table.ENTRY_PICK,
        Table.ENTRY_TRANSFER,
        Table.ENTRY_CHIP,
    }
)


def columns_for(table: Table) -> list[str]:
    """The column names a table's schema declares, in order.

    Sources use this to build an empty frame that still has the right shape. An empty frame with
    no columns fails validation for the wrong reason, and the resulting error says nothing about
    the actual problem, which is that there were no rows.
    """
    return list(SCHEMAS[table].to_schema().columns.keys())


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
