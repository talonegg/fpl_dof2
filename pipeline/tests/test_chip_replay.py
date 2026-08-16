"""D-18 — does the simulation re-rank change a chip decision on a *real* historical deadline?

The fast tests here cover the two reconstructions the replay rests on. The measurement itself is
marked ``slow``: it refits the component models and solves the multi-gameweek MILP twice for every
sampled deadline, which is minutes, and it needs the archive backfill present in silver.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from fpl_dof.config import Config
from fpl_dof.config.models import BacktestConfig, ChipReplayConfig
from fpl_dof.optimise.replay import (
    attach_team_ids,
    replay_chip_decisions,
    sample_deadlines,
)
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import read_table_optional
from fpl_dof.silver.tables import Table

REPO_ROOT = Path(__file__).resolve().parents[2]
SILVER = REPO_ROOT / "data" / "silver"
REPORT = REPO_ROOT / "data" / "gold" / "chip-replay.json"


def _history() -> pd.DataFrame:
    rows = []
    fixture_id = 1
    for gameweek in (1, 2):
        for home, away in ((10, 20), (30, 40)):
            for team, opponent, was_home in ((home, away, True), (away, home, False)):
                rows.append(
                    {
                        "season": "2024/25",
                        "gameweek": gameweek,
                        "fixture_id": fixture_id,
                        "player_code": team * 100 + gameweek,
                        "opponent_team_id": opponent,
                        "was_home": was_home,
                        "kickoff_time": pd.Timestamp(f"2024-08-{gameweek:02d}", tz="UTC"),
                    }
                )
            fixture_id += 1
    return pd.DataFrame(rows)


def test_the_club_the_archive_does_not_carry_is_reconstructed_from_the_fixture() -> None:
    """A fixture has two clubs; a player's is the one that is not his opponent.

    Without this the replay has no club cap, no fixture-varying forecast and no within-match
    correlation — which is precisely the tied case the constructed unit test already covers.
    """
    frame = attach_team_ids(_history())
    home_row = frame[(frame["opponent_team_id"] == 20) & (frame["gameweek"] == 1)].iloc[0]
    away_row = frame[(frame["opponent_team_id"] == 10) & (frame["gameweek"] == 1)].iloc[0]
    assert int(home_row["team_id"]) == 10
    assert int(away_row["team_id"]) == 20


def test_a_fixture_that_does_not_resolve_to_two_clubs_stays_null() -> None:
    """Guessed rather than null would break the club limit silently, which is the worst outcome."""
    broken = _history()
    broken.loc[broken["fixture_id"] == 1, "opponent_team_id"] = 20
    frame = attach_team_ids(broken)
    assert frame[frame["fixture_id"] == 1]["team_id"].isna().all()


def test_the_sample_is_bounded_by_configuration_not_by_a_literal() -> None:
    """DP-06. Every bound on the replay is named, defaulted and justified in the config."""
    history = pd.DataFrame(
        {
            "season": "2024/25",
            "gameweek": list(range(1, 39)),
            "kickoff_time": pd.to_datetime(["2024-08-01T12:00:00Z"] * 38, utc=True)
            + pd.to_timedelta(range(38), unit="D"),
        }
    )
    config = BacktestConfig(
        chip_replay=ChipReplayConfig(
            first_gameweek=6, last_gameweek=32, deadline_stride=6, max_deadlines=3
        )
    )
    sampled = sample_deadlines(history, config)
    assert [entry[1] for entry in sampled] == [6, 12, 18]


@pytest.mark.slow
def test_the_re_rank_against_real_historical_deadlines(game_rules: GameRules) -> None:
    """E4-S4a's real acceptance criterion, and it is allowed to come back negative.

    This asserts only that the replay *ran* and that both arms produced a decision. Whether the
    re-rank changed anything is the finding, and the finding is written to
    ``data/gold/chip-replay.json`` rather than encoded as an assertion — a test that fails when
    real data says "no change" would be a test that pressures the answer.
    """
    config = Config()
    history = read_table_optional(SILVER, config.rules.season, Table.PLAYER_GAMEWEEK)
    chips = read_table_optional(SILVER, config.rules.season, Table.CHIP)
    if history is None or history.empty or chips is None or chips.empty:
        pytest.skip("no archive backfill in silver; run `fpl-dof ingest` and `fpl-dof transform`")

    result = replay_chip_decisions(
        history,
        rules=game_rules,
        chips=chips,
        forecast_config=config.forecast,
        backtest_config=config.backtest,
        decision=config.decision,
        optimiser=config.optimiser,
    )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result.as_dict(), indent=2), encoding="utf-8")

    assert result.folds, "the replay measured nothing"
    for fold in result.folds:
        assert fold.with_label and fold.without_label
    print(result.verdict())
