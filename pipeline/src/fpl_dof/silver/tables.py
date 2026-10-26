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
    ENTRY_GAMEWEEK = "entry_gameweek"
    LEAGUE_STANDING = "league_standing"
    LEAGUE_PICK = "league_pick"
    LEAGUE_TRANSFER = "league_transfer"
    LEAGUE_GAMEWEEK = "league_gameweek"
    PLAYER_CROSSWALK = "player_crosswalk"
    PLAYER_ADVANCED = "player_advanced"
    PLAYER_METRIC = "player_metric"
    TEAM_MATCH_EXPECTATION = "team_match_expectation"
    PLAYER_LIVE = "player_live"
    ENTRY_LIVE = "entry_live"


#: Advanced per-player measures a source may contribute, in canonical names and canonical units.
#: They are declared once here because two tables carry them — the per-source ledger and the
#: precedence-merged canonical view — and a column that existed in only one of them would be a
#: measurement that silently never reached a model.
ADVANCED_METRICS: tuple[str, ...] = (
    "minutes_played",
    "matches",
    "expected_goals",
    "non_penalty_expected_goals",
    "expected_assists",
    "shots",
    "shots_on_target",
    "key_passes",
    "shot_creating_actions",
    "goal_creating_actions",
    "progressive_carries",
    "progressive_passes",
    "touches_attacking_penalty_area",
    "tackles",
    "interceptions",
    "blocks",
    "clearances",
    "recoveries",
)

#: How a crosswalk row came to exist. ``unmatched`` is a first-class value, not an absence: a row
#: that resolution failed on must stay visible, because a silently dropped player is exactly the
#: failure R-10 describes.
MATCH_METHODS: tuple[str, ...] = ("deterministic", "fuzzy", "override", "unmatched")

#: How a source's rows arrived: captured live, or backdated from a timestamped match log or from
#: running-total snapshots after the source was added mid-season (DL-83).
INGRESS_METHODS: tuple[str, ...] = ("live", "match_log", "running_total")

#: Whether an advanced row describes one fixture or a season to date. Sources differ, and pretending
#: a season aggregate is a gameweek observation would leak the future into every backtest.
METRIC_SCOPES: tuple[str, ...] = ("gameweek", "season")


class TeamSchema(pa.DataFrameModel):
    team_id: Series[int] = pa.Field(unique=True, ge=1)
    code: Series[int] = pa.Field(unique=True, ge=1)
    """The club's permanent code: the id the archive uses in every season (D-26)."""
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
    """FPL's own flag: the match is over and its bonus is confirmed."""
    # Optional so a fixture table written before LIVE-01 still reads; absent means not known.
    finished_provisional: Series[bool] | None
    """Full time has been played; the bonus may not yet be confirmed."""
    started: Series[bool] | None

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
    # Optional so a gameweek table written before ORC-01 still reads; absent means not checked.
    data_checked: Series[bool] | None

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


class EntryGameweekSchema(pa.DataFrameModel):
    """The owner's score and standing per finished gameweek, as the game reports it (DL-69).

    The authoritative points figure — auto-substitutions, captain changes and hits already applied
    by the game itself — rather than one recomputed here from picks and scoring rules.
    """

    entry_id: Series[int] = pa.Field(ge=1)
    gameweek: Series[int] = pa.Field(ge=1, le=38)
    points: Series[int]
    total_points: Series[int]
    rank: Series[int] = pa.Field(ge=1, nullable=True)
    overall_rank: Series[int] = pa.Field(ge=1, nullable=True)
    bank: Series[float] = pa.Field(ge=0, nullable=True)
    squad_value: Series[float] = pa.Field(ge=0, nullable=True)
    transfers: Series[int] = pa.Field(ge=0)
    transfers_cost: Series[int] = pa.Field(ge=0)
    points_on_bench: Series[int] = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = True
        unique = ["entry_id", "gameweek"]  # noqa: RUF012 - pandera Config


class EntryChipSchema(pa.DataFrameModel):
    entry_id: Series[int] = pa.Field(ge=1)
    name: Series[str]
    gameweek: Series[int] = pa.Field(ge=1, le=38)

    class Config:
        strict = True
        coerce = True


class LeagueStandingSchema(pa.DataFrameModel):
    """One rival's position in a configured classic mini-league (E6-S10, FR-32).

    Everything here is what the standings themselves report. ``player_name`` and ``entry_name`` are
    public display names people chose for a public leaderboard, not personal data this project went
    looking for — and no identifier here reaches the browser that is not already on the league's own
    public page (NFR-11, Invariant 10).
    """

    league_id: Series[int] = pa.Field(ge=1)
    league_name: Series[str]
    entry_id: Series[int] = pa.Field(ge=1)
    entry_name: Series[str]
    player_name: Series[str]
    rank: Series[int] = pa.Field(ge=1)
    last_rank: Series[int] = pa.Field(ge=0, nullable=True)
    event_total: Series[int] = pa.Field(nullable=True)
    total: Series[int]

    class Config:
        strict = True
        coerce = True
        unique = ["league_id", "entry_id"]  # noqa: RUF012 - pandera Config


class LeaguePickSchema(pa.DataFrameModel):
    """A rival's squad for one gameweek.

    **Deliberately not ``entry_pick``**, though the shape is nearly the same. That table is the
    owner's own squad and the weekly decision is loaded from it; letting a hundred rivals' rows into
    it would make every consumer's correctness depend on remembering to filter by ``entry_id``, and
    the failure would be a plausible-looking squad built from somebody else's players (DP-13).

    No ``purchase_price`` or ``selling_price``: the public picks endpoint carries neither for
    another manager, and there is no transfer history fetched here to reconstruct them from. Absent
    rather than zero — an unmeasured price is not a free player (DL-18).
    """

    entry_id: Series[int] = pa.Field(ge=1)
    gameweek: Series[int] = pa.Field(ge=1, le=38)
    player_id: Series[int] = pa.Field(ge=1)
    slot: Series[int] = pa.Field(ge=1, le=15, description="1-11 start, 12-15 bench, in order.")
    multiplier: Series[int] = pa.Field(ge=0, le=3)
    is_captain: Series[bool]
    is_vice_captain: Series[bool]

    class Config:
        strict = True
        coerce = True
        unique = ["entry_id", "gameweek", "slot"]  # noqa: RUF012 - pandera Config


class _AdvancedMetrics(pa.DataFrameModel):
    """The metric columns, as nullable floats, shared by the two tables that carry them.

    Nullable and never zero-filled: a source that does not measure something has not observed a
    zero, and the two are not the same claim (DL-18). Inherited rather than repeated so the
    per-source ledger and the merged canonical view cannot drift apart.
    """

    minutes_played: Series[float] = pa.Field(ge=0, nullable=True)
    matches: Series[float] = pa.Field(ge=0, nullable=True)
    expected_goals: Series[float] = pa.Field(ge=0, nullable=True)
    non_penalty_expected_goals: Series[float] = pa.Field(ge=0, nullable=True)
    expected_assists: Series[float] = pa.Field(ge=0, nullable=True)
    shots: Series[float] = pa.Field(ge=0, nullable=True)
    shots_on_target: Series[float] = pa.Field(ge=0, nullable=True)
    key_passes: Series[float] = pa.Field(ge=0, nullable=True)
    shot_creating_actions: Series[float] = pa.Field(ge=0, nullable=True)
    goal_creating_actions: Series[float] = pa.Field(ge=0, nullable=True)
    progressive_carries: Series[float] = pa.Field(ge=0, nullable=True)
    progressive_passes: Series[float] = pa.Field(ge=0, nullable=True)
    touches_attacking_penalty_area: Series[float] = pa.Field(ge=0, nullable=True)
    tackles: Series[float] = pa.Field(ge=0, nullable=True)
    interceptions: Series[float] = pa.Field(ge=0, nullable=True)
    blocks: Series[float] = pa.Field(ge=0, nullable=True)
    clearances: Series[float] = pa.Field(ge=0, nullable=True)
    recoveries: Series[float] = pa.Field(ge=0, nullable=True)

    class Config:
        strict = True
        coerce = True


class PlayerCrosswalkSchema(pa.DataFrameModel):
    """The identity map between a source's own player ids and the canonical ones (FR-07).

    One row per (season, source, source player). ``player_id`` is null exactly when resolution
    failed, and such rows are kept rather than dropped so the unmatched rate is measurable and the
    quality gate has something to measure it on.

    Keyed on season because resolution is re-run from scratch every season: club-based matching is
    invalidated by transfers, so last season's answer is evidence, not truth.
    """

    season: Series[str]
    source: Series[str]
    source_player_id: Series[str]
    source_name: Series[str]
    source_team: Series[str] = pa.Field(nullable=True)
    source_position: Series[str] = pa.Field(nullable=True)
    player_id: Series[int] = pa.Field(ge=1, nullable=True)
    player_code: Series[int] = pa.Field(ge=1, nullable=True)
    match_method: Series[str] = pa.Field(isin=MATCH_METHODS)
    confidence: Series[float] = pa.Field(ge=0, le=1)
    verified: Series[bool]
    """True only for a human-reviewed override. A fuzzy match at 0.97 is still a guess."""
    ingress: Series[str] = pa.Field(isin=INGRESS_METHODS)

    class Config:
        strict = True
        coerce = True
        unique = ["season", "source", "source_player_id"]  # noqa: RUF012 - pandera Config


class PlayerAdvancedSchema(_AdvancedMetrics):
    """Advanced measures as each source reports them, before precedence is applied.

    Kept per source rather than merged on arrival, because "two providers disagree about this
    player's expected goals" is information, and a table that has already picked a winner cannot
    show it.
    """

    season: Series[str]
    as_of_gameweek: Series[int] = pa.Field(ge=1, le=38, nullable=True)
    observed_at: Series[pd.DatetimeTZDtype] = pa.Field(dtype_kwargs={"unit": "ns", "tz": "UTC"})
    """When the row's content became knowable: the capture, or a backdated row's latest event. The
    look-ahead gate holds it against the ``as_of_gameweek`` deadline (DL-83)."""
    source: Series[str]
    source_player_id: Series[str]
    player_id: Series[int] = pa.Field(ge=1, nullable=True)
    player_code: Series[int] = pa.Field(ge=1, nullable=True)
    scope: Series[str] = pa.Field(isin=METRIC_SCOPES)
    gameweek: Series[int] = pa.Field(ge=1, le=38, nullable=True)
    """Null when ``scope`` is ``season``: the row is a running total, not a fixture."""

    class Config:
        strict = True
        coerce = True
        unique = [  # noqa: RUF012 - pandera Config
            "season",
            "as_of_gameweek",
            "source",
            "source_player_id",
            "scope",
            "gameweek",
        ]


class PlayerMetricSchema(_AdvancedMetrics):
    """The canonical advanced view, after per-field source precedence (NFR-15).

    ``sources`` records which sources actually contributed to this row, because a number whose
    origin cannot be recovered is a number nobody can argue with (DP-09).
    """

    season: Series[str]
    as_of_gameweek: Series[int] = pa.Field(ge=1, le=38, nullable=True)
    observed_at: Series[pd.DatetimeTZDtype] = pa.Field(dtype_kwargs={"unit": "ns", "tz": "UTC"})
    """The latest ``observed_at`` of the rows merged into this one (DL-83)."""
    player_id: Series[int] = pa.Field(ge=1, nullable=True)
    player_code: Series[int] = pa.Field(ge=1)
    scope: Series[str] = pa.Field(isin=METRIC_SCOPES)
    gameweek: Series[int] = pa.Field(ge=1, le=38, nullable=True)
    sources: Series[str]

    class Config:
        strict = True
        coerce = True
        unique = [  # noqa: RUF012 - pandera Config
            "season",
            "as_of_gameweek",
            "player_code",
            "scope",
            "gameweek",
        ]


class TeamMatchExpectationSchema(pa.DataFrameModel):
    """Team-level goal expectations, however they were derived (FR-03).

    The market's view and a model's view have the same shape on purpose: the consumer asks for an
    expectation, not for a bookmaker.
    """

    season: Series[str]
    source: Series[str]
    captured_at: Series[pd.DatetimeTZDtype] = pa.Field(dtype_kwargs={"unit": "ns", "tz": "UTC"})
    kickoff_time: Series[pd.DatetimeTZDtype] = pa.Field(
        dtype_kwargs={"unit": "ns", "tz": "UTC"}, nullable=True
    )
    home_team: Series[str]
    away_team: Series[str]
    home_team_id: Series[int] = pa.Field(ge=1, nullable=True)
    away_team_id: Series[int] = pa.Field(ge=1, nullable=True)
    expected_goals_home: Series[float] = pa.Field(ge=0, le=10)
    expected_goals_away: Series[float] = pa.Field(ge=0, le=10)
    clean_sheet_probability_home: Series[float] = pa.Field(ge=0, le=1)
    clean_sheet_probability_away: Series[float] = pa.Field(ge=0, le=1)
    home_win_probability: Series[float] = pa.Field(ge=0, le=1)
    draw_probability: Series[float] = pa.Field(ge=0, le=1)
    away_win_probability: Series[float] = pa.Field(ge=0, le=1)
    """The three results, margin removed from the 1X2 prices; the fitted goals' outcome only where a
    source posts no result market (ORC-15)."""
    total_goals: Series[float] = pa.Field(ge=0, le=20)
    over_2_5_probability: Series[float] = pa.Field(ge=0, le=1, nullable=True)
    """P(more than 2.5 goals), margin removed from the over/under 2.5 prices. Null where the
    source posts no totals market (ORC-15)."""

    class Config:
        strict = True
        coerce = True


class LeagueTransferSchema(pa.DataFrameModel):
    """A rival's transfer in the published gameweek (ORC-14). Not ``entry_transfer``, for the same
    reason ``league_pick`` is not ``entry_pick``: that table is the owner's, and the decision reads
    it. No prices — the drill-down shows who moved, and the public endpoint is the only source."""

    entry_id: Series[int] = pa.Field(ge=1)
    gameweek: Series[int] = pa.Field(ge=1, le=38)
    player_in_id: Series[int] = pa.Field(ge=1)
    player_out_id: Series[int] = pa.Field(ge=1)

    class Config:
        strict = True
        coerce = True


class LeagueGameweekSchema(pa.DataFrameModel):
    """A rival's transfer count, hit cost, chip and season total per finished gameweek, from his
    history (ORC-14). The published gameweek's moves are read from its row; the total after the
    gameweek before the live one is what that team's live total stands on (LIVE-03)."""

    entry_id: Series[int] = pa.Field(ge=1)
    gameweek: Series[int] = pa.Field(ge=1, le=38)
    transfers: Series[int] = pa.Field(ge=0)
    transfers_cost: Series[int] = pa.Field(ge=0)
    chip: Series[str] = pa.Field(nullable=True)
    total_points: Series[int] = pa.Field(nullable=True)
    """The season total after the gameweek, net of every hit; null when his history has no row."""

    class Config:
        strict = True
        coerce = True
        unique = ["entry_id", "gameweek"]  # noqa: RUF012 - pandera Config


#: The column that marks a live row provisional: FPL had not data-checked its gameweek when the row
#: was captured. A frame carrying it is a live table, and the feature store refuses one (LIVE-01,
#: Invariant 5): provisional points are never features.
PROVISIONAL = "provisional"


class _LiveGameweek(pa.DataFrameModel):
    """What the two live tables share: one gameweek, past its deadline, and when it was seen.

    The gameweek is the latest whose deadline has passed: the gameweek in play until FPL
    data-checks it, then the same gameweek, final, until the next deadline (LIVE-01). Whether each
    row's deadline had passed when it was observed needs the gameweek table, which a schema cannot
    see, so :func:`require_past_deadline` checks it at transform.
    """

    gameweek: Series[int] = pa.Field(ge=1, le=38)
    observed_at: Series[pd.DatetimeTZDtype] = pa.Field(dtype_kwargs={"unit": "ns", "tz": "UTC"})
    """When the capture the row came from was fetched."""
    provisional: Series[bool]
    """True until a capture taken once FPL data-checked the gameweek: its figures can move."""

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def one_gameweek(cls, df: pd.DataFrame) -> Any:  # type: ignore[misc]  # noqa: N805
        return df["gameweek"].nunique() <= 1


class PlayerLiveSchema(_LiveGameweek):
    """The live gameweek's scores, one row per player per fixture of his club's (LIVE-01).

    Never ``player_gameweek``, and never a feature: these rows are what FPL showed at
    ``observed_at``, provisional until the gameweek is data-checked, and the feature store refuses a
    frame stamped ``provisional`` (Invariant 5). A fixture still to kick off, or one a player has no
    line in, is a row of zeros, so a player yet to play is never read as a blank (LIVE-03).
    """

    fixture_id: Series[int]
    player_id: Series[int] = pa.Field(ge=1)
    minutes: Series[int] = pa.Field(ge=0, le=120)
    points: Series[int]
    """The fixture's points as FPL explains them, bonus included."""
    bonus: Series[int] = pa.Field(ge=0)
    bps: Series[int] = pa.Field(nullable=True)
    """Null when FPL reports BPS only for the gameweek and the player has two fixtures in it."""
    finished: Series[bool]
    """Full time has been played: the minutes are final (the fixture's ``finished_provisional``).
    What the scorer substitutes on (LIVE-03)."""
    bonus_confirmed: Series[bool]
    """FPL has confirmed the fixture's bonus (the fixture's ``finished``): the points are final."""

    class Config:
        strict = True
        coerce = True
        unique = ["gameweek", "player_id", "fixture_id"]  # noqa: RUF012 - pandera Config


class EntryLiveSchema(_LiveGameweek):
    """FPL's own figures for each fetched team in the live gameweek, from its picks (LIVE-01).

    The owner's and each published rival's. Their hits and chip are fixed at the deadline; their
    ``points`` and ``total_points`` are as of ``observed_at``, final once ``provisional`` is false,
    which is what the scorer is checked against (LIVE-03). Not ``entry_gameweek``: the season log
    reads that, and it holds finished gameweeks only (DL-69).
    """

    entry_id: Series[int] = pa.Field(ge=1)
    points: Series[int]
    transfers_cost: Series[int] = pa.Field(ge=0)
    total_points: Series[int]
    chip: Series[str] = pa.Field(nullable=True)

    class Config:
        strict = True
        coerce = True
        unique = ["entry_id", "gameweek"]  # noqa: RUF012 - pandera Config


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
    Table.ENTRY_GAMEWEEK: EntryGameweekSchema,
    Table.LEAGUE_STANDING: LeagueStandingSchema,
    Table.LEAGUE_PICK: LeaguePickSchema,
    Table.LEAGUE_TRANSFER: LeagueTransferSchema,
    Table.LEAGUE_GAMEWEEK: LeagueGameweekSchema,
    Table.PLAYER_CROSSWALK: PlayerCrosswalkSchema,
    Table.PLAYER_ADVANCED: PlayerAdvancedSchema,
    Table.PLAYER_METRIC: PlayerMetricSchema,
    Table.TEAM_MATCH_EXPECTATION: TeamMatchExpectationSchema,
    Table.PLAYER_LIVE: PlayerLiveSchema,
    Table.ENTRY_LIVE: EntryLiveSchema,
}

#: Tables about the live gameweek only (LIVE-01). Rebuilt every transform, and removed when no
#: source produces them, so no run reads a gameweek that has passed as the live one.
LIVE_TABLES: frozenset[Table] = frozenset({Table.PLAYER_LIVE, Table.ENTRY_LIVE})

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
        Table.ENTRY_GAMEWEEK,
        # Only exist when a mini-league is configured, which it is not by default (E6-S10).
        Table.LEAGUE_STANDING,
        Table.LEAGUE_PICK,
        Table.LEAGUE_TRANSFER,
        Table.LEAGUE_GAMEWEEK,
        # Everything an external source contributes. Losing one of those sources removes the
        # fields it fed and nothing else, which is what DP-15 asks for in table form.
        Table.PLAYER_CROSSWALK,
        Table.PLAYER_ADVANCED,
        Table.PLAYER_METRIC,
        Table.TEAM_MATCH_EXPECTATION,
        # Only once a deadline has passed and its scores have been fetched (LIVE-01).
        *LIVE_TABLES,
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


def require_past_deadline(
    table: Table, frame: pd.DataFrame, gameweeks: pd.DataFrame, now: pd.Timestamp
) -> None:
    """Raise :class:`SchemaViolationError` if a live row's gameweek was not past its deadline.

    Past it both when the row was observed and at ``now``: a row for a gameweek whose deadline is
    still ahead, or captured before it, is the look-ahead Invariant 5 forbids (LIVE-01). Here, not
    in the schema, because the deadline is in the gameweek table.
    """
    if frame.empty:
        return
    deadlines = (
        dict(
            zip(
                gameweeks["gameweek"].astype(int),
                pd.to_datetime(gameweeks["deadline_time"], utc=True),
                strict=True,
            )
        )
        if "deadline_time" in gameweeks.columns
        else {}
    )
    moment = pd.Timestamp(now)
    moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
    for gameweek, observed in zip(
        frame["gameweek"].astype(int), pd.to_datetime(frame["observed_at"], utc=True), strict=True
    ):
        deadline = deadlines.get(gameweek)
        if deadline is None or observed < deadline or moment < deadline:
            raise SchemaViolationError(
                f"silver table {table.value!r} has a row for gameweek {gameweek} observed at "
                f"{observed}, before its deadline ({deadline}) had passed; a gameweek is live only "
                "once its deadline is behind both the capture and the run"
            )


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
