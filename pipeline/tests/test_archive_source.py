"""E2-S3 — the historical backfill source (DL-19).

Two things here are worth more than the rest combined.

**Cross-season identity.** FPL reassigns element IDs every season. Joining history on ``element``
gives one player another player's past, and the result is a model that is *most* confident about
exactly the players it has most corrupted. Nothing in a single-season test can see this, which is
why the test that matters compares the same footballer across two seasons.

**Absence of measurement.** Defensive Contribution did not exist in 2022/23. It must arrive as
null, never zero, because zero is a claim that the player did no defending — the trap DL-18
records, and the one that systematically underrates the players the model is supposed to beat
intuition on.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx

from fpl_dof.config.models import HttpConfig, RateLimitConfig
from fpl_dof.silver.tables import Table, columns_for, validate
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.errors import SourceContractError
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fplarchive.adapter import ArchiveAdapter, season_slug

FIXTURES = Path(__file__).parent / "fixtures" / "archive"
BASE = ArchiveAdapter.base_url
SEASONS = ("2022/23", "2025/26")
REQUEST = IngestRequest(run_id="run-1", seasons=SEASONS)


@pytest.fixture
def recorded_archive() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        for season in SEASONS:
            slug = season_slug(season)
            for path, name in (
                (f"{slug}/gws/merged_gw.csv", "merged_gw"),
                (f"{slug}/players_raw.csv", "players_raw"),
            ):
                body = (FIXTURES / f"{slug}_{name}.csv").read_text(encoding="utf-8")
                mock.get(f"{BASE}/{path}").mock(return_value=httpx.Response(200, text=body))
        yield mock


@pytest.fixture
def adapter(tmp_path: Path) -> Iterator[ArchiveAdapter]:
    config = HttpConfig(rate_limit=RateLimitConfig(requests_per_second=1000.0))
    with Fetcher(config=config, bronze=BronzeStore(tmp_path / "bronze"), run_id="run-1") as fetcher:
        yield ArchiveAdapter(fetcher)


def test_the_source_is_off_unless_asked_for() -> None:
    """A once-a-season, multi-megabyte ingest must not run on every routine invocation."""
    assert ArchiveAdapter.enabled_by_default is False


def test_snapshots_are_named_for_what_they_contain(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter, tmp_path: Path
) -> None:
    """This source serves CSV. A file called ``.json.gz`` holding CSV costs someone an afternoon."""
    adapter.ingest(REQUEST)
    snapshots = list((tmp_path / "bronze").rglob("*.csv.gz"))
    assert snapshots
    assert not list((tmp_path / "bronze").rglob("*.json.gz"))


def test_a_finished_season_is_cached_for_a_year(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    """A completed season is immutable; re-fetching it cannot produce a different answer."""
    first = adapter.ingest(REQUEST)
    assert first.network_calls == 4  # two files for each of two seasons
    second = adapter.ingest(REQUEST)
    assert second.network_calls == 0
    assert second.cache_hits == 4


def test_conformance_produces_a_valid_per_gameweek_table(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    adapter.ingest(REQUEST)
    conformed = adapter.conform(REQUEST)
    frame = conformed.tables[Table.PLAYER_GAMEWEEK.value]

    assert set(frame.columns) == set(columns_for(Table.PLAYER_GAMEWEEK))
    validate(Table.PLAYER_GAMEWEEK, frame)  # raises if the schema is not satisfied
    assert set(frame["season"]) == set(SEASONS)


def test_the_join_key_is_the_stable_code_not_the_season_local_id(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    """The failure this source could most easily cause, and the one nothing else would catch.

    ``player_id`` is reassigned between seasons, so the same integer means different people. If any
    code appears against two different players, or a player's history is split across two codes,
    every rolling feature computed from it is quietly wrong.
    """
    adapter.ingest(REQUEST)
    frame = adapter.conform(REQUEST).tables[Table.PLAYER_GAMEWEEK.value]

    # A code identifies exactly one person, so within a season it maps to exactly one element id.
    per_season = frame.groupby(["season", "player_code"])["player_id"].nunique()
    assert (per_season == 1).all(), "a code resolved to more than one player within a season"

    # And a code carries one position for a given season.
    positions = frame.groupby(["season", "player_code"])["position"].nunique()
    assert (positions == 1).all()

    # The codes are real FPL codes, not row numbers dressed up as identity.
    assert frame["player_code"].min() > 1000


def test_defensive_contribution_is_null_before_it_existed(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    """Null means "not measured". Zero would mean "did no defending", which is a different claim.

    2022/23 predates the component entirely; 2025/26 is the season it was introduced.
    """
    adapter.ingest(REQUEST)
    frame = adapter.conform(REQUEST).tables[Table.PLAYER_GAMEWEEK.value]

    old = frame[frame["season"] == "2022/23"]
    new = frame[frame["season"] == "2025/26"]

    assert old["defensive_contribution"].isna().all(), (
        "a season before Defensive Contribution existed must not report zero for it"
    )
    assert not new["defensive_contribution"].isna().all()


def test_prices_are_converted_out_of_tenths(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    adapter.ingest(REQUEST)
    frame = adapter.conform(REQUEST).tables[Table.PLAYER_GAMEWEEK.value]
    assert frame["price"].between(3.0, 20.0).all(), frame["price"].describe()


def test_kickoff_time_is_utc_and_present(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    """The knowability boundary (Invariant 5). Without it the backtest cannot enforce anything."""
    adapter.ingest(REQUEST)
    frame = adapter.conform(REQUEST).tables[Table.PLAYER_GAMEWEEK.value]

    assert isinstance(frame["kickoff_time"].dtype, pd.DatetimeTZDtype)
    assert str(frame["kickoff_time"].dt.tz) == "UTC"
    assert frame["kickoff_time"].notna().all()


def test_a_missing_identity_column_refuses_rather_than_inventing_one(
    adapter: ArchiveAdapter,
) -> None:
    """Without ``code`` there is no cross-season identity, and a synthetic one merges people."""
    body = (FIXTURES / "2025-26_players_raw.csv").read_text(encoding="utf-8")
    lines = body.splitlines()
    header = lines[0].split(",")
    index = header.index("code")
    stripped = "\n".join(
        ",".join(part for position, part in enumerate(line.split(",")) if position != index)
        for line in lines
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/2025-26/players_raw.csv").mock(
            return_value=httpx.Response(200, text=stripped)
        )
        with pytest.raises(SourceContractError, match="cross-season identity"):
            adapter.fetch_players("2025/26", IngestRequest(run_id="run-1"))


def test_a_season_the_mirror_does_not_have_degrades_rather_than_fails(
    adapter: ArchiveAdapter,
) -> None:
    """DP-15. A missing mirror costs the backtest its evidence; it must not stop the pipeline."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(404))
        report = adapter.ingest(IngestRequest(run_id="run-1", seasons=("1999/00",)))

    assert report.resources["merged_gameweeks"] == 0
    assert any("1999/00" in warning for warning in report.warnings)
