"""Historical-season backfill for the two scraped sources. Narrows D-20.

D-20 records that "no season-backfill path exists for any of" E5's three sources. For Understat and
FBref that turned out to be half wrong: both already loop over ``request.seasons``, and both ingest
and transform already pass ``sources.backfill_seasons`` into it. What was missing was coverage — and
underneath the missing coverage, a defect: ``request.seasons or (request.season,)`` made a
configured backfill **replace** the current season rather than add to it, so switching a backfill on
silently switched this season's enrichment off.

These tests pin both halves against recorded historical pages. Nothing here touches a live site.

The part of D-20 they do **not** close is the part that matters most, and it is recorded in DL-29
and D-22 rather than papered over here: the conformed `player_metric` table is written to silver and
read by nothing, so a backfill cannot move a backtest metric until a consumer exists.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import respx

from fpl_dof.config.models import HttpConfig, RateLimitConfig, RetryConfig
from fpl_dof.silver.tables import Table
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.fbref.adapter import PAGES, FbrefAdapter
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.understat.adapter import UnderstatAdapter

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = "2026/27"
HISTORIC = "2024/25"

#: What a configured backfill looks like: one prior season plus the season being run.
BACKFILL = IngestRequest(run_id="run-1", season=CURRENT, seasons=(HISTORIC,))


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def fetcher(tmp_path: Path) -> Iterator[Fetcher]:
    config = HttpConfig(
        rate_limit=RateLimitConfig(requests_per_second=1000.0),
        retry=RetryConfig(max_attempts=2, backoff_base_seconds=0.001),
    )
    with Fetcher(
        config=config,
        bronze=BronzeStore(tmp_path / "bronze"),
        run_id="run-1",
        sleep=lambda _s: None,
    ) as built:
        yield built


# --- the request contract -------------------------------------------------------------------


def test_a_backfill_adds_to_the_current_season_rather_than_replacing_it() -> None:
    """The defect underneath D-20's Understat/FBref half.

    Replacing would have meant that turning a backfill on turned this season's enrichment off, with
    no error and no missing column — only a forecast quietly missing the source it was told to use.
    """
    assert BACKFILL.seasons_with_current() == (HISTORIC, CURRENT)


def test_the_current_season_is_not_fetched_twice_when_it_is_also_in_the_backfill() -> None:
    request = IngestRequest(run_id="run-1", season=CURRENT, seasons=(HISTORIC, CURRENT))
    assert request.seasons_with_current() == (HISTORIC, CURRENT)


def test_no_backfill_still_fetches_the_current_season() -> None:
    assert IngestRequest(run_id="run-1", season=CURRENT).seasons_with_current() == (CURRENT,)


# --- Understat ------------------------------------------------------------------------------


@contextmanager
def understat_mock() -> Iterator[respx.MockRouter]:
    base = UnderstatAdapter.base_url
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{base}/robots.txt").mock(
            return_value=httpx.Response(200, content=fixture("understat_robots.txt"))
        )
        for season, page in (
            (CURRENT, "understat_league.html"),
            (HISTORIC, "understat_league_2024.html"),
        ):
            mock.get(f"{base}/league/EPL/{UnderstatAdapter.season_year(season)}").mock(
                return_value=httpx.Response(
                    200,
                    content=fixture(page),
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            )
        yield mock


def test_understat_conforms_a_historical_season_alongside_the_current_one(
    fetcher: Fetcher,
) -> None:
    """Both seasons arrive, each labelled with its own — which is what makes them joinable."""
    with understat_mock():
        conformed = UnderstatAdapter(fetcher).conform(BACKFILL)

    advanced = conformed.tables[Table.PLAYER_ADVANCED.value]
    assert set(advanced["season"]) == {HISTORIC, CURRENT}

    historic = advanced[
        (advanced["season"] == HISTORIC) & (advanced["source_player_id"] == "1001")
    ].iloc[0]
    current = advanced[
        (advanced["season"] == CURRENT) & (advanced["source_player_id"] == "1001")
    ].iloc[0]
    # A finished season and five gameweeks of one, not the same number twice.
    assert historic["minutes_played"] == 3210
    assert current["minutes_played"] == 430
    assert historic["expected_goals"] == pytest.approx(4.8812)


def test_a_historical_season_keeps_the_club_a_player_finished_at(fetcher: Fetcher) -> None:
    """A mid-season transfer leaves two clubs in one field, and only one of them is joinable."""
    with understat_mock():
        conformed = UnderstatAdapter(fetcher).conform(BACKFILL)
    crosswalk = conformed.tables[Table.PLAYER_CROSSWALK.value]
    moved = crosswalk[
        (crosswalk["season"] == HISTORIC) & (crosswalk["source_player_id"] == "2001")
    ].iloc[0]
    assert moved["source_team"] == "Leicester"


def test_the_historical_page_is_fetched_from_that_seasons_own_url(fetcher: Fetcher) -> None:
    """The URL is season-shaped, so a wrong year is a silently wrong season of data."""
    with understat_mock() as mock:
        UnderstatAdapter(fetcher).ingest(BACKFILL)
        requested = {str(call.request.url) for call in mock.calls}
    assert f"{UnderstatAdapter.base_url}/league/EPL/2024" in requested
    assert f"{UnderstatAdapter.base_url}/league/EPL/2026" in requested


# --- FBref ----------------------------------------------------------------------------------


@contextmanager
def fbref_mock() -> Iterator[respx.MockRouter]:
    """Only the standard page is recorded per season; the rest 404 and degrade to a warning.

    That is deliberately the same shape E5's own tests use — a page that fails removes its own
    columns and nothing else (DP-15) — and it keeps the fixture set to what a reader can check.
    """
    base = FbrefAdapter.base_url
    recorded = {CURRENT: "fbref_stats.html", HISTORIC: "fbref_stats_2024_2025.html"}
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{base}/robots.txt").mock(
            return_value=httpx.Response(200, content=fixture("fbref_robots.txt"))
        )
        for season in (CURRENT, HISTORIC):
            for page in PAGES:
                url = f"{base}/{FbrefAdapter.page_path(season, page)}"
                if page == "stats":
                    mock.get(url).mock(
                        return_value=httpx.Response(200, content=fixture(recorded[season]))
                    )
                else:
                    mock.get(url).mock(return_value=httpx.Response(404, text="not found"))
        yield mock


def test_fbref_conforms_a_historical_season_alongside_the_current_one(fetcher: Fetcher) -> None:
    with fbref_mock():
        conformed = FbrefAdapter(fetcher).conform(BACKFILL)

    advanced = conformed.tables[Table.PLAYER_ADVANCED.value]
    assert set(advanced["season"]) == {HISTORIC, CURRENT}

    historic = advanced[
        (advanced["season"] == HISTORIC) & (advanced["source_player_id"] == "aa000001")
    ].iloc[0]
    assert historic["minutes_played"] == 3210
    assert historic["progressive_passes"] == 311


def test_a_player_who_only_exists_in_the_historical_season_survives(fetcher: Fetcher) -> None:
    """Relegated and departed players are most of what a backfill adds, and they are the point."""
    with fbref_mock():
        conformed = FbrefAdapter(fetcher).conform(BACKFILL)
    crosswalk = conformed.tables[Table.PLAYER_CROSSWALK.value]
    relegated = crosswalk[crosswalk["source_player_id"] == "aa000009"]
    assert list(relegated["season"]) == [HISTORIC]


def test_each_season_is_fetched_from_its_own_slugged_path(fetcher: Fetcher) -> None:
    with fbref_mock() as mock:
        FbrefAdapter(fetcher).ingest(BACKFILL)
        requested = {str(call.request.url) for call in mock.calls}
    assert f"{FbrefAdapter.base_url}/{FbrefAdapter.page_path(HISTORIC, 'stats')}" in requested
    assert f"{FbrefAdapter.base_url}/{FbrefAdapter.page_path(CURRENT, 'stats')}" in requested


def test_robots_is_read_once_for_the_whole_backfill_not_once_per_season(fetcher: Fetcher) -> None:
    """A backfill is many more pages, so it must be gentler rather than louder."""
    with fbref_mock() as mock:
        report = FbrefAdapter(fetcher).ingest(BACKFILL)
        robots = [call for call in mock.calls if str(call.request.url).endswith("/robots.txt")]
    assert len(robots) == 1
    assert report.resources["robots"] == 1


def test_a_backfilled_season_is_never_refetched(fetcher: Fetcher) -> None:
    """A finished season's totals cannot change, so the week-long TTL settles it for good.

    Counted over the pages that *succeeded*: a 404 is not cached, and caching a failure would be
    the more dangerous behaviour of the two.
    """
    stats_pages = {
        f"{FbrefAdapter.base_url}/{FbrefAdapter.page_path(season, 'stats')}"
        for season in (CURRENT, HISTORIC)
    }
    with fbref_mock() as mock:
        adapter = FbrefAdapter(fetcher)
        adapter.ingest(BACKFILL)
        after_first = sum(1 for call in mock.calls if str(call.request.url) in stats_pages)
        adapter.ingest(BACKFILL)
        after_second = sum(1 for call in mock.calls if str(call.request.url) in stats_pages)
    assert after_first == 2
    assert after_second == 2, "the second pass must be served entirely from the cache"
