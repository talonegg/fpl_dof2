"""The silver layer, and the transform stage that fills it.

The recurring theme: a schema violation must stop the run. Bad data that validates is worse than no
data, because it produces a squad that looks entirely reasonable.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx

from fpl_dof.config import Config
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.silver.store import read_table, read_table_optional, table_path, write_table
from fpl_dof.silver.tables import OPTIONAL_TABLES, SchemaViolationError, Table, validate
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fpl.adapter import FplApiAdapter
from fpl_dof.stages import transform

FIXTURES = Path(__file__).parent / "fixtures"
BASE = FplApiAdapter.base_url


@pytest.fixture
def populated_bronze(config: Config, layout: DataLayout) -> Iterator[DataLayout]:
    """Ingest the recorded fixtures into a real bronze store, so transform has something to read."""
    bootstrap = json.loads((FIXTURES / "bootstrap_static.json").read_text(encoding="utf-8"))
    fixtures = json.loads((FIXTURES / "fixtures.json").read_text(encoding="utf-8"))
    summaries = json.loads((FIXTURES / "element_summary.json").read_text(encoding="utf-8"))
    set_piece = json.loads((FIXTURES / "set_piece_notes.json").read_text(encoding="utf-8"))

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/bootstrap-static/").mock(return_value=httpx.Response(200, json=bootstrap))
        mock.get(f"{BASE}/fixtures/").mock(return_value=httpx.Response(200, json=fixtures))
        mock.get(f"{BASE}/team/set-piece-notes/").mock(
            return_value=httpx.Response(200, json=set_piece)
        )
        mock.get(url__regex=rf"{BASE}/event/\d+/live/").mock(
            return_value=httpx.Response(200, json={"elements": []})
        )
        for element_id, summary in summaries.items():
            mock.get(f"{BASE}/element-summary/{element_id}/").mock(
                return_value=httpx.Response(200, json=summary)
            )
        with Fetcher(
            config=config.http,
            bronze=BronzeStore(layout.bronze),
            run_id="run-1",
            sleep=lambda _s: None,
        ) as fetcher:
            FplApiAdapter(fetcher).ingest(IngestRequest(run_id="run-1"))
    yield layout


def _ctx(config: Config, layout: DataLayout) -> StageContext:
    return StageContext(config=config, layout=layout, run_id="run-1")


# --- schemas -------------------------------------------------------------------------------


def _player_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": 1,
                "code": 100,
                "web_name": "Someone",
                "full_name": "Some One",
                "position": "MID",
                "team_id": 1,
                "price": 5.5,
                "status": "a",
                "chance_of_playing_next_round": None,
                "selected_by_percent": 10.0,
                "news": "",
            }
        ]
    )


def test_a_valid_player_frame_passes() -> None:
    assert len(validate(Table.PLAYER, _player_frame())) == 1


def test_an_unknown_position_is_rejected() -> None:
    frame = _player_frame()
    frame.loc[0, "position"] = "STRIKER"
    with pytest.raises(SchemaViolationError, match="player"):
        validate(Table.PLAYER, frame)


def test_a_negative_price_is_rejected() -> None:
    frame = _player_frame()
    frame.loc[0, "price"] = -1.0
    with pytest.raises(SchemaViolationError):
        validate(Table.PLAYER, frame)


def test_an_unexpected_column_is_rejected() -> None:
    """strict=True: a source sending a new field must be a decision, not a surprise."""
    frame = _player_frame()
    frame["surprise"] = 1
    with pytest.raises(SchemaViolationError):
        validate(Table.PLAYER, frame)


def test_duplicate_players_are_rejected() -> None:
    frame = pd.concat([_player_frame(), _player_frame()], ignore_index=True)
    with pytest.raises(SchemaViolationError):
        validate(Table.PLAYER, frame)


def test_a_fixture_cannot_be_a_team_against_itself() -> None:
    frame = pd.DataFrame(
        [
            {
                "fixture_id": 1,
                "gameweek": 1,
                "kickoff_time": pd.Timestamp("2026-08-21T19:00:00Z"),
                "home_team_id": 3,
                "away_team_id": 3,
                "home_difficulty": 2,
                "away_difficulty": 4,
                "finished": False,
            }
        ]
    )
    with pytest.raises(SchemaViolationError):
        validate(Table.FIXTURE, frame)


# --- store ---------------------------------------------------------------------------------


def test_round_trip_through_parquet(tmp_path: Path) -> None:
    path = write_table(tmp_path, "2026/27", Table.PLAYER, _player_frame())
    assert path == table_path(tmp_path, "2026/27", Table.PLAYER)
    assert "season=2026-27" in str(path), "the season slash must not become a directory separator"
    back = read_table(tmp_path, "2026/27", Table.PLAYER)
    assert back.loc[0, "web_name"] == "Someone"


def test_writing_an_invalid_frame_fails_before_anything_is_written(tmp_path: Path) -> None:
    frame = _player_frame()
    frame.loc[0, "position"] = "nonsense"
    with pytest.raises(SchemaViolationError):
        write_table(tmp_path, "2026/27", Table.PLAYER, frame)
    assert not table_path(tmp_path, "2026/27", Table.PLAYER).exists()


def test_reading_a_missing_table_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="fpl-dof transform"):
        read_table(tmp_path, "2026/27", Table.PLAYER)


# --- the transform stage -------------------------------------------------------------------


def test_transform_without_bronze_says_to_ingest_first(config: Config, layout: DataLayout) -> None:
    with pytest.raises(transform.NoBronzeError, match="fpl-dof ingest"):
        transform.run(_ctx(config, layout))


def test_transform_produces_every_table(config: Config, populated_bronze: DataLayout) -> None:
    result = transform.run(_ctx(config, populated_bronze))

    assert result.metrics["rows.player"] == 92
    assert result.metrics["rows.team"] == 8
    assert result.metrics["season"] == "2026/27"

    # Required tables must exist and carry rows. Optional ones legitimately do not: no team ID is
    # configured here, and preseason there are no played gameweeks, so entry and per-gameweek
    # tables are absent by design (DP-15) rather than by failure.
    for table in Table:
        if table in OPTIONAL_TABLES:
            continue
        frame = read_table(populated_bronze.silver, "2026/27", table)
        assert not frame.empty, table.value


def test_optional_tables_are_absent_rather_than_empty_in_preseason(
    config: Config, populated_bronze: DataLayout
) -> None:
    """DL-20: no configured team ID and no played gameweeks is the normal August state.

    Absent and empty are different answers, and only absent is honest here — an empty entry table
    would claim the squad was read and found to hold nobody.
    """
    transform.run(_ctx(config, populated_bronze))

    for table in (Table.ENTRY, Table.ENTRY_PICK, Table.PLAYER_GAMEWEEK):
        assert read_table_optional(populated_bronze.silver, "2026/27", table) is None, table.value

    # Chips and price history are published year-round, so those are present.
    chips = read_table(populated_bronze.silver, "2026/27", Table.CHIP)
    assert not chips.empty
    assert set(chips["name"]) >= {"wildcard", "freehit", "bboost", "3xc"}


def test_transform_makes_no_network_calls(config: Config, populated_bronze: DataLayout) -> None:
    """Reproducibility (DP-11): the same bronze must always give the same silver.

    The socket guard in conftest would already fail an unmocked call; running transform entirely
    outside a respx mock proves it never even tries.
    """
    transform.run(_ctx(config, populated_bronze))


def test_prices_are_in_millions_not_tenths(config: Config, populated_bronze: DataLayout) -> None:
    transform.run(_ctx(config, populated_bronze))
    players = read_table(populated_bronze.silver, "2026/27", Table.PLAYER)
    assert players["price"].between(3.0, 20.0).all()
    assert players["price"].max() < 25.0


def test_positions_are_canonical(config: Config, populated_bronze: DataLayout) -> None:
    transform.run(_ctx(config, populated_bronze))
    players = read_table(populated_bronze.silver, "2026/27", Table.PLAYER)
    assert set(players["position"]) <= {p.value for p in Position}


def test_times_are_utc(config: Config, populated_bronze: DataLayout) -> None:
    """DL-11: stored and computed in UTC; local time is a rendering concern only."""
    transform.run(_ctx(config, populated_bronze))
    gameweeks = read_table(populated_bronze.silver, "2026/27", Table.GAMEWEEK)
    assert str(gameweeks["deadline_time"].dtype) == "datetime64[ns, UTC]"
    gw1 = gameweeks[gameweeks["gameweek"] == 1].iloc[0]
    assert gw1["deadline_time"] == pd.Timestamp("2026-08-21T17:30:00Z")


def test_defensive_contribution_survives_into_silver(
    config: Config, populated_bronze: DataLayout
) -> None:
    """E0-S3's whole reason for existing: DefCon must reach the model."""
    transform.run(_ctx(config, populated_bronze))
    history = read_table(populated_bronze.silver, "2026/27", Table.PLAYER_SEASON_HISTORY)
    recent = history[history["season_name"] == "2025/26"]
    assert not recent.empty
    assert (recent["defensive_contribution"] > 0).any()


def test_rules_are_written_alongside_the_tables(
    config: Config, populated_bronze: DataLayout
) -> None:
    transform.run(_ctx(config, populated_bronze))
    rules = transform.read_rules(_ctx(config, populated_bronze), "2026/27")
    assert isinstance(rules, GameRules)
    assert rules.squad.budget == 100.0
    assert rules.source_snapshot_sha256 is not None, "rules must be traceable to a snapshot"


def test_reading_rules_before_transform_is_an_error(config: Config, layout: DataLayout) -> None:
    with pytest.raises(transform.NoBronzeError, match="transform"):
        transform.read_rules(_ctx(config, layout), "2026/27")
