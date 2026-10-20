"""PIPE-01, REM-09: backdating a source added mid-season, proven on a recorded match log (DL-83).

No live source needs backdating yet, so the recorded 2025/26 archive stands in for one. Its rows are
a timestamped match log; cumulated at chosen moments, they are also the running-total snapshots a
source without match logs would have published.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fpl_dof.config.models import EntityResolutionConfig
from fpl_dof.quality.rules import _temporal_monotonicity_and_containment
from fpl_dof.silver.tables import Table, validate
from fpl_dof.sources.resolve import resolve
from fpl_dof.sources.retrospective import from_match_log, from_running_totals

ARCHIVE = Path(__file__).parent / "fixtures" / "archive" / "2025-26_merged_gw.csv"
SEASON = "2025/26"


@pytest.fixture(scope="module")
def match_log() -> pd.DataFrame:
    raw = pd.read_csv(ARCHIVE)
    return pd.DataFrame(
        {
            "season": SEASON,
            "source": "recorded",
            "source_player_id": raw["element"].astype(str),
            "event_time": pd.to_datetime(raw["kickoff_time"], utc=True),
            "round": raw["round"],
            "minutes_played": raw["minutes"].astype(float),
            "expected_goals": raw["expected_goals"].astype(float),
        }
    )


@pytest.fixture(scope="module")
def gameweeks(match_log: pd.DataFrame) -> pd.DataFrame:
    """FPL's rule: each deadline is 90 minutes before the gameweek's first kickoff."""
    first = match_log.groupby("round")["event_time"].min()
    return pd.DataFrame(
        {"gameweek": first.index.astype(int), "deadline_time": first - pd.Timedelta(minutes=90)}
    )


def _gate(advanced: pd.DataFrame, gameweeks: pd.DataFrame) -> tuple[bool, str]:
    tables = {Table.GAMEWEEK.value: gameweeks, Table.PLAYER_ADVANCED.value: advanced}
    ok, message, _ = _temporal_monotonicity_and_containment(
        gameweeks, {"season": SEASON, "tables": tables}
    )
    return ok, message


def test_a_match_log_rebuilds_each_deadlines_totals(
    match_log: pd.DataFrame, gameweeks: pd.DataFrame
) -> None:
    through = int(gameweeks["gameweek"].max())
    rows = validate(Table.PLAYER_ADVANCED, from_match_log(match_log, gameweeks, through=through))

    assert 1 not in set(rows["as_of_gameweek"])  # nothing was played before the first deadline
    deadlines = dict(zip(gameweeks["gameweek"], gameweeks["deadline_time"], strict=True))
    assert (rows["observed_at"] < rows["as_of_gameweek"].map(deadlines)).all()

    for gameweek in range(2, through + 1):
        before = match_log[match_log["event_time"] < deadlines[gameweek]]
        expected = before.groupby("source_player_id")["minutes_played"].sum()
        got = rows[rows["as_of_gameweek"] == gameweek].set_index("source_player_id")
        pd.testing.assert_series_equal(
            got["minutes_played"].sort_index(), expected.sort_index(), check_names=False
        )
        assert (got["matches"] == before.groupby("source_player_id").size()).all()

    assert _gate(rows, gameweeks)[0]


def test_running_totals_carry_the_latest_snapshot_forward_and_never_back(
    match_log: pd.DataFrame, gameweeks: pd.DataFrame
) -> None:
    """One snapshot, an hour before the GW2 deadline: GW1 gets nothing, GW2 and GW3 get it."""
    deadlines = dict(zip(gameweeks["gameweek"], gameweeks["deadline_time"], strict=True))
    by_log = from_match_log(match_log, gameweeks, through=3).set_index(
        ["as_of_gameweek", "source_player_id"]
    )
    taken = deadlines[2] - pd.Timedelta(hours=1)
    known = match_log[match_log["event_time"] < taken]
    snapshot = (
        known.groupby(["season", "source", "source_player_id"])[
            ["minutes_played", "expected_goals"]
        ]
        .sum()
        .reset_index()
        .assign(observed_at=taken)
    )
    rows = validate(Table.PLAYER_ADVANCED, from_running_totals(snapshot, gameweeks, through=3))

    assert sorted(set(rows["as_of_gameweek"])) == [2, 3]
    shown = rows.set_index(["as_of_gameweek", "source_player_id"])["minutes_played"]
    logged = by_log["minutes_played"]
    for gameweek in (2, 3):  # GW3 is stale, not scaled up from anything later
        pd.testing.assert_series_equal(
            shown.xs(gameweek).sort_index(), logged.xs(2).sort_index(), check_names=False
        )
    assert not logged.xs(3).equals(logged.xs(2))
    assert _gate(rows, gameweeks)[0]


def test_a_backdate_that_looks_ahead_is_blocked(
    match_log: pd.DataFrame, gameweeks: pd.DataFrame
) -> None:
    """The defence the method relies on: label GW3's totals as GW2's and the gate fails."""
    rows = from_match_log(match_log, gameweeks, through=3)
    leaky = rows[rows["as_of_gameweek"] == 3].assign(as_of_gameweek=2)
    ok, message = _gate(leaky, gameweeks)
    assert not ok
    assert "after the GW2 deadline" in message


def test_the_crosswalk_records_how_a_sources_rows_arrived() -> None:
    players = pd.DataFrame(
        {
            "player_id": [1],
            "code": [101],
            "web_name": ["Saka"],
            "first_name": ["Bukayo"],
            "second_name": ["Saka"],
            "full_name": ["Bukayo Saka"],
            "team_id": [1],
            "position": ["MID"],
        }
    )
    teams = pd.DataFrame({"team_id": [1], "name": ["Arsenal"], "short_name": ["ARS"]})
    refs = pd.DataFrame(
        {
            "season": [SEASON, SEASON],
            "source": ["late", "live"],
            "source_player_id": ["9", "9"],
            "source_name": ["Bukayo Saka", "Bukayo Saka"],
            "source_team": ["Arsenal", "Arsenal"],
            "source_position": ["MID", "MID"],
            "ingress": ["match_log", None],
        }
    )
    crosswalk, _ = resolve(
        refs, players, teams, season=SEASON, config=EntityResolutionConfig(), overrides={}
    )
    validate(Table.PLAYER_CROSSWALK, crosswalk)
    assert dict(zip(crosswalk["source"], crosswalk["ingress"], strict=True)) == {
        "late": "match_log",
        "live": "live",
    }
