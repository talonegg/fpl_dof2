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

**Cross-season *club* identity, which is the same failure again and went unnoticed for longer.**
This adapter wrote ``team_id: None`` on every row for the whole of E9 and E10, so the backtest's
fixture calendar was empty and every historical observation was scored against league-average
opposition while the code read as though it were using real fixtures (D-26, DL-51). FPL renumbers
clubs every season exactly as it renumbers players, so the repair is keyed on the stable club
``code`` and the test that matters is, again, the one that compares across two seasons.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx

from fpl_dof.config.models import HttpConfig, RateLimitConfig
from fpl_dof.forecast.backtest import fixture_calendar
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
                (f"{slug}/teams.csv", "teams"),
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
    assert first.network_calls == 6  # three files for each of two seasons
    second = adapter.ingest(REQUEST)
    assert second.network_calls == 0
    assert second.cache_hits == 6


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


def _club_table(slug: str) -> list[dict[str, str]]:
    with (FIXTURES / f"{slug}_teams.csv").open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_every_row_names_the_club_it_was_played_for(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    """D-26, the regression guard. ``team_id: None`` on every row is what this exists to catch.

    It is a null column that breaks nothing loudly: ``fixture_calendar`` drops rows with no club,
    so it returns an empty calendar, ``attach_fixtures`` takes its stated-absence branch, and the
    entire backtest scores against league-average opposition while every line of code involved
    reads as though it were consuming real fixtures. Nothing goes red — DP-13's case exactly.
    """
    adapter.ingest(REQUEST)
    frame = adapter.conform(REQUEST).tables[Table.PLAYER_GAMEWEEK.value]

    assert frame["team_id"].notna().all(), "a row that does not know its club has no fixture"
    assert frame["opponent_team_id"].notna().all()
    assert (frame["team_id"] != frame["opponent_team_id"]).all(), "a club cannot play itself"


def test_the_club_key_is_stable_across_seasons_like_the_player_key(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    """The club half of DL-19, and the reason a season-local id would not do.

    Promotion and relegation reshuffle an alphabetical ordering, so between two seasons roughly
    half of the twenty season-local ids point at a different club. Pooling team form on one would
    hand Liverpool's record to Leicester. This fixture pair contains a club that appears in both
    seasons **under a different season-local id**, which is the only condition under which the
    mistake is visible at all.
    """
    adapter.ingest(REQUEST)
    frame = adapter.conform(REQUEST).tables[Table.PLAYER_GAMEWEEK.value]

    early = {row["name"]: row for row in _club_table("2022-23")}
    late = {row["name"]: row for row in _club_table("2025-26")}

    # A club with rows in both seasons *and renumbered between them*. Without both properties, a
    # season-local id would pass this test and the bug would stay invisible.
    resolved = frame.dropna(subset=["team_id"])
    seen_in = {int(str(code)): set(group["season"]) for code, group in resolved.groupby("team_id")}
    renumbered = sorted(
        name
        for name in set(early) & set(late)
        if int(early[name]["id"]) != int(late[name]["id"])
        and seen_in.get(int(early[name]["code"])) == set(SEASONS)
    )
    assert renumbered, "this fixture pair cannot demonstrate the bug it guards against"

    for name in renumbered:
        code = int(early[name]["code"])
        assert code == int(late[name]["code"])
        seasons = set(frame.loc[frame["team_id"] == code, "season"])
        assert seasons == set(SEASONS), (
            f"{name} is not the same club in both seasons under id {code}"
        )
        # And the number written is the stable code, not either season's local id.
        assert code not in {int(early[name]["id"]), int(late[name]["id"])}

    written = set(frame["team_id"].dropna().astype(int))
    codes = {int(row["code"]) for row in early.values()} | {
        int(row["code"]) for row in late.values()
    }
    assert written <= codes, "a club id reached silver that is not a stable FPL club code"


def test_a_club_and_its_opponent_are_expressed_in_one_id_space(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    """Both sides of a fixture must be the same kind of number, or the join pairs strangers.

    ``team_id`` comes from a club *name* and ``opponent_team_id`` from a season-local *integer*.
    They are resolved through the same club list precisely so that the fixture self-join — which
    matches one row's club against another row's opponent — means what it says.
    """
    adapter.ingest(REQUEST)
    frame = adapter.conform(REQUEST).tables[Table.PLAYER_GAMEWEEK.value]

    for season, group in frame.groupby("season"):
        teams = set(group["team_id"].dropna().astype(int))
        opponents = set(group["opponent_team_id"].dropna().astype(int))
        assert opponents & teams, f"{season}: no opponent is anybody's club, so the spaces differ"


def test_the_fixture_calendar_is_no_longer_empty(
    recorded_archive: respx.MockRouter, adapter: ArchiveAdapter
) -> None:
    """The consumer, not the column. D-26's cost was paid here, so it is checked here.

    Asserting on ``team_id`` alone would not have caught the original defect being *harmless*; the
    thing that mattered is that the harness's calendar was empty for every gameweek it ever ran.
    """
    adapter.ingest(REQUEST)
    frame = adapter.conform(REQUEST).tables[Table.PLAYER_GAMEWEEK.value]

    built = 0
    for key, _ in frame.groupby(["season", "gameweek"]):
        season, gameweek = key
        built += len(fixture_calendar(frame, str(season), int(str(gameweek))))
    assert built > 0, "every fold would score against league-average opposition (D-26)"


def test_a_missing_club_list_costs_the_fixtures_and_not_the_season(
    adapter: ArchiveAdapter,
) -> None:
    """DP-15, in the honest direction.

    Without the club list the rows are still worth having for per-90 rates, so the season is kept.
    What it must not do is fall back to the season-local id: that number would be silently wrong
    rather than visibly absent, and would pool one club's form into another's. Null, and said.
    """
    slug = "2025-26"
    with respx.mock(assert_all_called=False) as mock:
        for path, name in (
            (f"{slug}/gws/merged_gw.csv", "merged_gw"),
            (f"{slug}/players_raw.csv", "players_raw"),
        ):
            body = (FIXTURES / f"{slug}_{name}.csv").read_text(encoding="utf-8")
            mock.get(f"{BASE}/{path}").mock(return_value=httpx.Response(200, text=body))
        mock.get(f"{BASE}/{slug}/teams.csv").mock(return_value=httpx.Response(404))

        request = IngestRequest(run_id="run-1", seasons=("2025/26",))
        adapter.ingest(request)
        conformed = adapter.conform(request)

    frame = conformed.tables[Table.PLAYER_GAMEWEEK.value]
    assert len(frame) > 0, "the season's player rows are still evidence for a per-90 rate"
    assert frame["team_id"].isna().all()
    assert frame["opponent_team_id"].isna().all(), "a season-local id here would be silently wrong"
    assert any("no club list" in warning for warning in conformed.warnings)


def test_a_club_list_without_the_stable_code_refuses_rather_than_guessing(
    adapter: ArchiveAdapter,
) -> None:
    """The club analogue of the ``code`` refusal above, and for the same reason."""
    body = (FIXTURES / "2025-26_teams.csv").read_text(encoding="utf-8")
    lines = body.splitlines()
    header = lines[0].split(",")
    index = header.index("code")
    stripped = "\n".join(
        ",".join(part for position, part in enumerate(line.split(",")) if position != index)
        for line in lines
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/2025-26/teams.csv").mock(return_value=httpx.Response(200, text=stripped))
        with pytest.raises(SourceContractError, match="cross-season identity"):
            adapter.fetch_teams("2025/26", IngestRequest(run_id="run-1"))


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
