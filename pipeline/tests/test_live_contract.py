"""E2-S4 — a contract test for every endpoint the pipeline reads.

These run against the **live** API and are skipped unless ``--network`` is given. Their purpose is
to catch upstream drift in CI, on a schedule, rather than at 03:00 on a deadline — which is the
only other time anyone would find out.

Two rules keep them useful rather than flaky:

*Assert on structure, never on values.* ``len(elements) > 400`` is a contract. ``Haaland costs
£15.0m`` is a fact about today and will fail for a reason that is nobody's fault.

*Assert on what the pipeline actually depends on.* A contract test that checks fields nothing reads
generates false alarms; one that misses a field the forecast needs generates silence. Each
assertion here maps to a real consumer, named in the test.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fpl_dof.config.models import HttpConfig
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.errors import SourceNotFoundError
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fpl.adapter import (
    REQUIRED_BOOTSTRAP_KEYS,
    REQUIRED_ELEMENT_KEYS,
    REQUIRED_HISTORY_PAST_KEYS,
    FplApiAdapter,
)
from fpl_dof.sources.fplarchive.adapter import (
    REQUIRED_GAMEWEEK_COLUMNS,
    ArchiveAdapter,
)

pytestmark = pytest.mark.network

REQUEST = IngestRequest(run_id="contract")

#: A publicly readable entry that has existed since the game began. Used read-only, and nothing
#: about a third party's team is asserted or recorded — this repository is public (Invariant 10).
PUBLIC_ENTRY_ID = 1

#: FPL's own "Overall" league. Public and permanent.
OVERALL_LEAGUE_ID = 314


@pytest.fixture
def adapter(tmp_path: Path) -> Iterator[FplApiAdapter]:
    with Fetcher(
        config=HttpConfig(), bronze=BronzeStore(tmp_path / "bronze"), run_id="contract"
    ) as fetcher:
        yield FplApiAdapter(fetcher)


@pytest.fixture
def archive(tmp_path: Path) -> Iterator[ArchiveAdapter]:
    with Fetcher(
        config=HttpConfig(), bronze=BronzeStore(tmp_path / "bronze"), run_id="contract"
    ) as fetcher:
        yield ArchiveAdapter(fetcher)


def test_bootstrap_static(adapter: FplApiAdapter) -> None:
    """Consumers: the rules module, every silver table, the chip tracker."""
    data = adapter.fetch_bootstrap(REQUEST)

    for key in REQUIRED_BOOTSTRAP_KEYS:
        assert key in data
    assert len(data["elements"]) > 400
    assert len(data["teams"]) == 20
    assert len(data["events"]) == 38
    for key in REQUIRED_ELEMENT_KEYS:
        assert key in data["elements"][0]

    # Invariant 2: the scoring table and squad rules are read, never transcribed.
    scoring = data["game_config"]["scoring"]
    assert set(scoring["goals_scored"]) == {"GKP", "DEF", "MID", "FWD"}
    assert set(scoring["defensive_contribution"]) == {"GKP", "DEF", "MID", "FWD"}
    for field in ("squad_squadsize", "squad_squadplay", "squad_total_spend", "squad_team_limit"):
        assert field in data["game_settings"]

    # E2-S7 reads chip expiry from here rather than writing "GW19" down.
    chips = data.get("chips")
    assert chips, "chips are how the expiry tracker knows when a chip is lost"
    assert {"name", "start_event", "stop_event"} <= set(chips[0])

    # E2-S5 price history needs these, and they are easy to lose in a redesign.
    for field in ("transfers_in_event", "transfers_out_event", "cost_change_event"):
        assert field in data["elements"][0]


def test_fixtures(adapter: FplApiAdapter) -> None:
    """Consumer: the fixture-difficulty term in the v0 forecast."""
    fixtures = adapter.fetch_fixtures(REQUEST)
    assert len(fixtures) == 380
    first = fixtures[0]
    assert {"id", "event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty"} <= set(
        first
    )


def test_element_summary(adapter: FplApiAdapter) -> None:
    """Consumers: the cold-start forecast (``history_past``) and per-gameweek silver (``history``).

    The DefCon fields in ``history_past`` are the entire reason DL-18 could close route 1. If they
    vanish, the model quietly loses its best signal.
    """
    bootstrap = adapter.fetch_bootstrap(REQUEST)
    element_id = int(bootstrap["elements"][0]["id"])
    summary = adapter.fetch_element_summary(element_id, REQUEST)

    assert {"fixtures", "history", "history_past"} <= set(summary)
    if summary["history_past"]:
        for key in REQUIRED_HISTORY_PAST_KEYS:
            assert key in summary["history_past"][0]
    if summary["history"]:
        # The knowability stamp (Invariant 5) and the per-gameweek price.
        assert {"round", "kickoff_time", "value", "minutes", "total_points"} <= set(
            summary["history"][0]
        )


def test_set_piece_notes_is_where_the_adapter_says_it_is(adapter: FplApiAdapter) -> None:
    """The path moved. A bare ``set-piece-notes/`` returns 404; it lives under ``team/``.

    Worth its own test precisely because the failure is a 404 on a path that used to work, which
    reads like an outage rather than a move.
    """
    data = adapter.fetch_set_piece_notes(REQUEST)
    assert len(data["teams"]) == 20
    assert "id" in data["teams"][0]


def test_the_old_set_piece_path_is_still_gone(adapter: FplApiAdapter) -> None:
    """If this ever starts passing, the catalogue was right and the adapter should move back."""
    with pytest.raises(SourceNotFoundError):
        adapter._fetch_resource("set_piece_notes", "set-piece-notes/", "legacy", REQUEST)


def test_event_live(adapter: FplApiAdapter) -> None:
    """Consumer: per-gameweek actuals, including BPS for the bonus model.

    Empty before a gameweek is played, which is a valid contract and not a failure.
    """
    data = adapter.fetch_event_live(1, REQUEST)
    assert "elements" in data
    if data["elements"]:
        assert {"id", "stats"} <= set(data["elements"][0])
        assert "bps" in data["elements"][0]["stats"]


def test_league_standings(adapter: FplApiAdapter) -> None:
    """Consumer: rival analysis (FR-32). Empty in preseason; the shape still has to hold."""
    data = adapter.fetch_league_standings(OVERALL_LEAGUE_ID, REQUEST)
    assert {"league", "standings"} <= set(data)
    assert "results" in data["standings"]


def test_entry(adapter: FplApiAdapter) -> None:
    """Consumer: the squad state service. Public endpoint only — there is no auth here (Inv. 4)."""
    data = adapter.fetch_entry(PUBLIC_ENTRY_ID, REQUEST)
    assert data["id"] == PUBLIC_ENTRY_ID
    for field in ("last_deadline_bank", "last_deadline_value", "started_event", "current_event"):
        assert field in data, f"squad reconstruction reads {field}"


def test_entry_history_and_transfers(adapter: FplApiAdapter) -> None:
    """Consumers: the free-transfer recomputation and the chips-used list."""
    history = adapter.fetch_entry_history(PUBLIC_ENTRY_ID, REQUEST)
    assert {"current", "past", "chips"} <= set(history)

    transfers = adapter.fetch_entry_transfers(PUBLIC_ENTRY_ID, REQUEST)
    assert isinstance(transfers, list)
    if transfers:
        assert {"element_in", "element_in_cost", "element_out", "event"} <= set(transfers[0])


def test_picks_are_absent_until_a_gameweek_has_been_scored(adapter: FplApiAdapter) -> None:
    """DL-20, asserted rather than assumed.

    Before GW1 is scored this 404s, which is why a declared squad is the primary input and not a
    fallback. Once it starts returning data the service prefers it with no code change — and this
    test is how that transition gets noticed.
    """
    bootstrap = adapter.fetch_bootstrap(REQUEST)
    finished = [event for event in bootstrap["events"] if event.get("finished")]

    picks = adapter.fetch_entry_picks(PUBLIC_ENTRY_ID, 1, REQUEST)
    if not finished:
        assert picks is None, "no gameweek has finished, so no picks should exist yet"
        return

    assert picks is not None
    assert {"element", "position", "multiplier", "is_captain"} <= set(picks["picks"][0])
    # Purchase price is authenticated-only, which is why it is reconstructed (Invariant 4).
    assert "purchase_price" not in picks["picks"][0]


def test_the_official_api_still_has_no_prior_season_gameweek_data(adapter: FplApiAdapter) -> None:
    """The premise of DL-19, retested every time this runs.

    If the API ever starts publishing per-gameweek history for past seasons, the archive source
    becomes unnecessary and should be retired. Asserting the gap keeps that decision live rather
    than letting a second source persist out of habit.
    """
    bootstrap = adapter.fetch_bootstrap(REQUEST)
    element_id = int(bootstrap["elements"][0]["id"])
    summary = adapter.fetch_element_summary(element_id, REQUEST)

    seasons_in_history = {str(row.get("season_name", "")) for row in summary["history"]}
    assert not seasons_in_history - {""}, (
        "element-summary.history now carries a season label; check whether prior seasons are "
        "included, and retire the archive source (DL-19) if they are"
    )
    if summary["history_past"]:
        # Season totals only: no gameweek granularity anywhere in here.
        assert "round" not in summary["history_past"][0]
        assert "kickoff_time" not in summary["history_past"][0]


def test_archive_still_serves_the_seasons_the_backtest_needs(archive: ArchiveAdapter) -> None:
    """DL-19's dependency, checked rather than hoped for.

    The mirror carries no licence and no availability promise. If it disappears, E3's evidence base
    goes with it, and that is worth finding out from CI rather than from a backtest that silently
    trains on one season.
    """
    rows = archive.fetch_gameweeks("2025/26", REQUEST)
    for column in REQUIRED_GAMEWEEK_COLUMNS:
        assert column in rows[0]

    assert "defensive_contribution" in rows[0], (
        "2025/26 is the only season with Defensive Contribution; without it D-11 cannot be "
        "narrowed at all"
    )
    players = archive.fetch_players("2025/26", REQUEST)
    assert "code" in players[0], "cross-season identity depends on the stable code"


def test_defensive_contribution_is_still_confined_to_one_season(archive: ArchiveAdapter) -> None:
    """The scoring-regime caveat in E2-S3's usability table, kept honest.

    If an earlier season ever gains the column, D-11 can be re-scoped — and if this test is
    deleted, nobody will notice that it could have been.
    """
    old = archive.fetch_gameweeks("2022/23", REQUEST)
    assert "defensive_contribution" not in old[0]
