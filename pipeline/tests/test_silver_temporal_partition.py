"""Tests for PIPE-01: Silver tables partitioned by season and as_of_gameweek."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fpl_dof.config.models import SourcesConfig
from fpl_dof.silver.store import append_table, read_table
from fpl_dof.silver.tables import (
    SchemaViolationError,
    Table,
    columns_for,
    validate,
)
from fpl_dof.sources.enrich import canonicalise


def test_player_advanced_and_metric_schemas_accept_valid_as_of_gameweek() -> None:
    adv_row = dict.fromkeys(columns_for(Table.PLAYER_ADVANCED))
    adv_row.update(
        {
            "season": "2026/27",
            "as_of_gameweek": 5,
            "source": "understat",
            "source_player_id": "123",
            "player_id": 1,
            "player_code": 1001,
            "scope": "season",
            "gameweek": None,
        }
    )
    df_adv = pd.DataFrame([adv_row])
    validated_adv = validate(Table.PLAYER_ADVANCED, df_adv)
    assert validated_adv["as_of_gameweek"].iloc[0] == 5

    metric_row = dict.fromkeys(columns_for(Table.PLAYER_METRIC))
    metric_row.update(
        {
            "season": "2026/27",
            "as_of_gameweek": 5,
            "player_id": 1,
            "player_code": 1001,
            "scope": "season",
            "gameweek": None,
            "sources": "understat",
        }
    )
    df_metric = pd.DataFrame([metric_row])
    validated_metric = validate(Table.PLAYER_METRIC, df_metric)
    assert validated_metric["as_of_gameweek"].iloc[0] == 5


def test_schema_rejects_out_of_range_as_of_gameweek() -> None:
    row = dict.fromkeys(columns_for(Table.PLAYER_ADVANCED))
    row.update(
        {
            "season": "2026/27",
            "as_of_gameweek": 39,
            "source": "understat",
            "source_player_id": "123",
            "player_id": 1,
            "player_code": 1001,
            "scope": "season",
            "gameweek": None,
        }
    )
    with pytest.raises(SchemaViolationError):
        validate(Table.PLAYER_ADVANCED, pd.DataFrame([row]))


def test_canonicalise_populates_as_of_gameweek() -> None:
    cfg = SourcesConfig()
    players = pd.DataFrame(
        [
            {
                "player_id": 1,
                "code": 1001,
                "web_name": "Haaland",
                "full_name": "Erling Haaland",
                "position": "FWD",
                "team_id": 1,
                "price": 14.0,
                "status": "a",
                "chance_of_playing_next_round": 100.0,
                "selected_by_percent": 60.0,
                "news": "",
            }
        ]
    )
    teams = pd.DataFrame(
        [
            {
                "team_id": 1,
                "name": "Man City",
                "short_name": "MCI",
                "strength_overall_home": 5,
                "strength_overall_away": 5,
            }
        ]
    )
    crosswalk = pd.DataFrame(
        [
            {
                "season": "2026/27",
                "source": "understat",
                "source_player_id": "123",
                "source_name": "Erling Haaland",
                "source_team": "Man City",
                "source_position": "FWD",
                "player_id": 1,
                "player_code": 1001,
                "match_method": "deterministic",
                "confidence": 1.0,
                "verified": False,
            },
            {
                "season": "2025/26",
                "source": "understat",
                "source_player_id": "123",
                "source_name": "Erling Haaland",
                "source_team": "Man City",
                "source_position": "FWD",
                "player_id": 1,
                "player_code": 1001,
                "match_method": "deterministic",
                "confidence": 1.0,
                "verified": False,
            },
        ]
    )
    adv_row_curr = dict.fromkeys(columns_for(Table.PLAYER_ADVANCED))
    adv_row_curr.update(
        {
            "season": "2026/27",
            "as_of_gameweek": None,
            "source": "understat",
            "source_player_id": "123",
            "player_id": 1,
            "player_code": 1001,
            "scope": "season",
            "gameweek": None,
            "expected_goals": 2.5,
        }
    )
    adv_row_past = dict.fromkeys(columns_for(Table.PLAYER_ADVANCED))
    adv_row_past.update(
        {
            "season": "2025/26",
            "as_of_gameweek": None,
            "source": "understat",
            "source_player_id": "123",
            "player_id": 1,
            "player_code": 1001,
            "scope": "season",
            "gameweek": None,
            "expected_goals": 25.0,
        }
    )
    tables = {
        Table.PLAYER.value: players,
        Table.TEAM.value: teams,
        Table.PLAYER_CROSSWALK.value: crosswalk,
        Table.PLAYER_ADVANCED.value: pd.DataFrame([adv_row_curr, adv_row_past]),
    }
    produced, _ = canonicalise(tables, season="2026/27", config=cfg, as_of_gameweek=5)
    adv_res = produced[Table.PLAYER_ADVANCED.value]
    curr = adv_res[adv_res["season"] == "2026/27"].iloc[0]
    past = adv_res[adv_res["season"] == "2025/26"].iloc[0]
    assert curr["as_of_gameweek"] == 5
    assert past["as_of_gameweek"] == 38

    metric_res = produced[Table.PLAYER_METRIC.value]
    assert len(metric_res) == 2
    metric_curr = metric_res[metric_res["season"] == "2026/27"].iloc[0]
    metric_past = metric_res[metric_res["season"] == "2025/26"].iloc[0]
    assert metric_curr["as_of_gameweek"] == 5
    assert metric_past["as_of_gameweek"] == 38


def test_append_table_accumulates_across_as_of_gameweeks(tmp_path: Path) -> None:
    silver_root = tmp_path / "silver"
    row_gw1 = dict.fromkeys(columns_for(Table.PLAYER_METRIC))
    row_gw1.update(
        {
            "season": "2026/27",
            "as_of_gameweek": 1,
            "player_id": 1,
            "player_code": 1001,
            "scope": "season",
            "gameweek": None,
            "expected_goals": 0.8,
            "sources": "understat",
        }
    )
    df_gw1 = pd.DataFrame([row_gw1])
    append_table(silver_root, "2026/27", Table.PLAYER_METRIC, df_gw1)

    read_back = read_table(silver_root, "2026/27", Table.PLAYER_METRIC)
    assert len(read_back) == 1
    assert read_back["as_of_gameweek"].iloc[0] == 1

    row_gw2 = dict.fromkeys(columns_for(Table.PLAYER_METRIC))
    row_gw2.update(
        {
            "season": "2026/27",
            "as_of_gameweek": 2,
            "player_id": 1,
            "player_code": 1001,
            "scope": "season",
            "gameweek": None,
            "expected_goals": 1.5,
            "sources": "understat",
        }
    )
    df_gw2 = pd.DataFrame([row_gw2])
    append_table(silver_root, "2026/27", Table.PLAYER_METRIC, df_gw2)

    read_back_2 = read_table(silver_root, "2026/27", Table.PLAYER_METRIC)
    assert len(read_back_2) == 2
    assert set(read_back_2["as_of_gameweek"]) == {1, 2}
