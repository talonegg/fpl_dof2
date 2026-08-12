"""Contract tests for the three external sources (E5-S2, E5-S3, E5-S4).

Every test here runs against a **recorded** artefact — a saved page, a saved API response — served
through respx. Nothing in this file touches a live site, and the odds provider in particular is
never called for real: it is credit-metered, it needs a key this project does not carry, and the
whole point of the adapter is that its absence is survivable.

The fixtures are shaped like the real thing rather than convenient: the page markup carries the
site's own ``data-stat`` attributes, one table is wrapped in an HTML comment because the real ones
are, and the embedded JSON is escaped byte by byte the way the real page escapes it. A convenient
fixture tests the test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import respx

from fpl_dof.config.models import HttpConfig, RateLimitConfig, RetryConfig, SourceOverride
from fpl_dof.silver.tables import ADVANCED_METRICS, SCHEMAS, Table, validate
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.errors import SourceContractError
from fpl_dof.sources.fbref.adapter import PAGES, FbrefAdapter
from fpl_dof.sources.fetch import REDACTED, Fetcher, redact
from fpl_dof.sources.oddsapi.adapter import (
    API_KEY_ENV,
    DEFAULT_CREDIT_BUDGET,
    CreditBudgetExhaustedError,
    OddsApiAdapter,
)
from fpl_dof.sources.oddsapi.market import devig, fit_goal_expectations, outcome_probabilities
from fpl_dof.sources.understat.adapter import REQUIRED_PLAYER_KEYS, UnderstatAdapter

FIXTURES = Path(__file__).parent / "fixtures"
SEASON = "2026/27"
REQUEST = IngestRequest(run_id="run-1", season=SEASON)


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


# --- Understat ----------------------------------------------------------------------------------


@pytest.fixture
def understat(fetcher: Fetcher) -> Iterator[UnderstatAdapter]:
    base = UnderstatAdapter.base_url
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{base}/league/EPL/2026").mock(
            return_value=httpx.Response(
                200,
                content=fixture("understat_league.html"),
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )
        yield UnderstatAdapter(fetcher)


def test_the_embedded_json_is_found_and_decoded(understat: UnderstatAdapter) -> None:
    """The fragile half, tested without any transport at all."""
    players = understat.parse_players(fixture("understat_league.html"), key="2026")
    assert len(players) == 4
    assert all(key in players[0] for key in REQUIRED_PLAYER_KEYS)


def test_byte_escaped_accents_survive_extraction(understat: UnderstatAdapter) -> None:
    """A mangled accent is an unmatched player, which is the failure this epic exists to avoid."""
    players = understat.parse_players(fixture("understat_league.html"), key="2026")
    names = {record["player_name"] for record in players}
    assert "Đorđe Petrović" in names


def test_a_page_that_has_stopped_carrying_the_data_is_a_contract_error(
    understat: UnderstatAdapter,
) -> None:
    with pytest.raises(SourceContractError, match="playersData"):
        understat.parse_players(b"<html><body>redesigned</body></html>", key="2026")


def test_conformed_expected_goals_land_in_the_canonical_columns(
    understat: UnderstatAdapter,
) -> None:
    conformed = understat.conform(REQUEST)
    advanced = conformed.tables[Table.PLAYER_ADVANCED.value]
    rice = advanced[advanced["source_player_id"] == "1001"].iloc[0]
    assert rice["expected_goals"] == pytest.approx(1.7431)
    assert rice["expected_assists"] == pytest.approx(1.2044)
    assert rice["key_passes"] == 9
    assert rice["scope"] == "season"
    # A running total is not a gameweek observation. Saying so is what keeps it out of a backtest's
    # past (Invariant 5).
    assert advanced["gameweek"].isna().all()


def test_it_emits_source_references_for_resolution(understat: UnderstatAdapter) -> None:
    refs = understat.conform(REQUEST).tables[Table.PLAYER_CROSSWALK.value]
    assert set(refs["source"]) == {"understat"}
    assert "Declan Rice" in set(refs["source_name"])
    assert refs[refs["source_player_id"] == "1001"].iloc[0]["source_position"] == "MID"


def test_it_is_off_by_default_and_off_the_fast_path() -> None:
    """Somebody else's website is not something a fresh clone should start reading on a schedule."""
    assert UnderstatAdapter.enabled_by_default is False
    assert UnderstatAdapter.essential is False
    assert all(not resource.fast_path for resource in UnderstatAdapter.resources)
    assert all((resource.cache_ttl_seconds or 0) >= 3600 for resource in UnderstatAdapter.resources)


def test_it_declares_the_attribution_the_interface_has_to_show() -> None:
    assert UnderstatAdapter.attribution


# --- FBref --------------------------------------------------------------------------------------


@contextmanager
def fbref_mock(
    *, allow: bool = True, pages: tuple[str, ...] = ("stats", "defense")
) -> Iterator[respx.MockRouter]:
    """Serve the recorded pages, and 404 the ones a test is not exercising.

    A page left out is routed to a 404 rather than left unrouted, so a test that removes one is
    exercising degradation rather than the suite's unmocked-network guard.
    """
    base = FbrefAdapter.base_url
    robots = fixture("fbref_robots.txt")
    if not allow:
        robots = b"User-agent: *\nDisallow: /\n"
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{base}/robots.txt").mock(return_value=httpx.Response(200, content=robots))
        for page in PAGES:
            url = f"{base}/{FbrefAdapter.page_path(SEASON, page)}"
            if page in pages:
                mock.get(url).mock(
                    return_value=httpx.Response(200, content=fixture(f"fbref_{page}.html"))
                )
            else:
                mock.get(url).mock(return_value=httpx.Response(404, text="not found"))
        yield mock


@pytest.fixture
def fbref(fetcher: Fetcher) -> Iterator[FbrefAdapter]:
    with fbref_mock():
        yield FbrefAdapter(fetcher)


def test_defensive_action_counts_are_read_from_a_commented_table(fbref: FbrefAdapter) -> None:
    """The counts model M4 needs, out of a table the site ships inside an HTML comment."""
    rows = fbref.parse_page(fixture("fbref_defense.html"), page="defense", key="2026-2027")
    rice = next(row for row in rows if row["player_id"] == "aa000001")
    assert rice["tackles"] == "11"
    assert rice["interceptions"] == "6"
    assert rice["blocks"] == "5"
    assert rice["clearances"] == "4"


def test_a_layout_change_is_a_contract_error_not_a_silent_empty_table(fbref: FbrefAdapter) -> None:
    with pytest.raises(SourceContractError, match="layout has changed"):
        fbref.parse_page(
            b"<html><body><table id='other'></table></body></html>", page="defense", key="2026-2027"
        )


def test_conformance_merges_the_pages_into_one_row_per_player(fbref: FbrefAdapter) -> None:
    conformed = fbref.conform(REQUEST)
    advanced = conformed.tables[Table.PLAYER_ADVANCED.value]
    rice = advanced[advanced["source_player_id"] == "aa000001"].iloc[0]
    assert rice["tackles"] == 11  # from the defence page
    assert rice["progressive_passes"] == 39  # from the standard page
    assert rice["expected_goals"] == pytest.approx(1.6)


def test_a_page_that_fails_removes_its_own_columns_and_nothing_else(fetcher: Fetcher) -> None:
    """Per-request degradation. The defence page is out; the standard page still arrives (DP-15)."""
    with fbref_mock(pages=("stats",)):
        conformed = FbrefAdapter(fetcher).conform(REQUEST)
    advanced = conformed.tables[Table.PLAYER_ADVANCED.value]
    rice = advanced[advanced["source_player_id"] == "aa000001"].iloc[0]
    assert rice["progressive_passes"] == 39
    assert rice["tackles"] is None or rice["tackles"] != rice["tackles"]
    assert any("defense" in warning for warning in conformed.warnings)


def test_robots_txt_is_evaluated_before_anything_is_fetched(fetcher: Fetcher) -> None:
    """Compliance is a check, not a comment. A disallowing site is simply not read."""
    with fbref_mock(allow=False):
        adapter = FbrefAdapter(fetcher)
        report = adapter.ingest(REQUEST)
    assert report.resources.get("robots") == 1
    assert not [name for name in report.resources if name.startswith("league_")]
    assert any("robots.txt disallows" in warning for warning in report.warnings)


def test_pages_are_weekly_at_most_and_never_on_the_fast_path() -> None:
    """E5-S3 sets the cadence; the TTL is what enforces it."""
    week = 7 * 24 * 3600
    for resource in FbrefAdapter.resources:
        assert resource.fast_path is False
        assert (resource.cache_ttl_seconds or 0) >= week


def test_the_season_slug_is_derived_not_written_down() -> None:
    assert FbrefAdapter.season_slug("2026/27") == "2026-2027"
    assert FbrefAdapter.season_slug("2025/26") == "2025-2026"


# --- odds: the market arithmetic ------------------------------------------------------------------


def test_devigging_removes_the_margin() -> None:
    prices = {"home": 1.62, "draw": 4.20, "away": 5.50}
    raw = sum(1 / price for price in prices.values())
    assert raw > 1.0
    fair = devig(prices)
    assert sum(fair.values()) == pytest.approx(1.0)
    assert fair["home"] > fair["draw"] > fair["away"]


def test_a_fitted_pair_reproduces_the_market_it_was_fitted_to() -> None:
    """The property that matters: the conversion is not merely plausible, it is invertible."""
    market = devig({"home": 1.62, "draw": 4.20, "away": 5.50})
    fitted = fit_goal_expectations(result=market, over=0.52, line=2.5)
    home, draw, away = outcome_probabilities(fitted.expected_goals_home, fitted.expected_goals_away)
    assert home == pytest.approx(market["home"], abs=0.03)
    assert draw == pytest.approx(market["draw"], abs=0.03)
    assert away == pytest.approx(market["away"], abs=0.03)
    assert fitted.residual < 0.05


def test_the_favourite_gets_the_higher_goal_expectation() -> None:
    strong = fit_goal_expectations(result=devig({"home": 1.30, "draw": 5.50, "away": 9.00}))
    assert strong.expected_goals_home > strong.expected_goals_away
    assert strong.clean_sheet_probability_home > strong.clean_sheet_probability_away


def test_a_totals_market_alone_fixes_the_total() -> None:
    fitted = fit_goal_expectations(over=0.75, line=2.5)
    assert fitted.total_goals > 3.0


def test_the_fit_is_deterministic() -> None:
    """DP-11: identical inputs, identical published numbers, every time."""
    market = devig({"home": 2.60, "draw": 3.50, "away": 2.70})
    first = fit_goal_expectations(result=market, over=0.55)
    second = fit_goal_expectations(result=market, over=0.55)
    assert first == second


# --- odds: the adapter ----------------------------------------------------------------------------


@pytest.fixture
def odds_mock() -> Iterator[respx.MockRouter]:
    payload = json.loads((FIXTURES / "odds_epl.json").read_text(encoding="utf-8"))
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://api\.the-odds-api\.com/v4/sports/soccer_epl/odds.*").mock(
            return_value=httpx.Response(200, json=payload)
        )
        yield mock


def test_no_key_configured_degrades_instead_of_failing(fetcher: Fetcher) -> None:
    """The normal state of this project until an owner signs up. It must be uneventful."""
    adapter = OddsApiAdapter(fetcher)
    assert adapter.api_key({}) is None
    conformed = adapter.conform(IngestRequest(run_id="r", season=SEASON))
    assert conformed.tables == {}
    assert any(API_KEY_ENV in warning for warning in conformed.warnings)


def test_no_key_means_no_request_is_even_attempted(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    adapter = OddsApiAdapter(fetcher)
    report = adapter.ingest(IngestRequest(run_id="r", season=SEASON))
    assert report.network_calls == 0
    assert report.warnings


def test_prices_become_team_goal_expectations(
    fetcher: Fetcher, odds_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "test-key-not-a-real-one")
    conformed = OddsApiAdapter(fetcher).conform(IngestRequest(run_id="r", season=SEASON))
    frame = conformed.tables[Table.TEAM_MATCH_EXPECTATION.value]
    assert len(frame) == 2
    arsenal = frame[frame["home_team"] == "Arsenal"].iloc[0]
    assert arsenal["expected_goals_home"] > arsenal["expected_goals_away"]
    assert 0.0 < arsenal["clean_sheet_probability_home"] < 1.0
    assert arsenal["total_goals"] == pytest.approx(
        arsenal["expected_goals_home"] + arsenal["expected_goals_away"]
    )
    validate(Table.TEAM_MATCH_EXPECTATION, frame)


def test_the_key_never_reaches_the_snapshot_metadata(
    fetcher: Fetcher, odds_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invariant 10, mechanically. Every request is written down; this one carries a secret."""
    sensitive_value = "this-value-must-never-be-written-to-a-snapshot"
    monkeypatch.setenv(API_KEY_ENV, sensitive_value)
    adapter = OddsApiAdapter(fetcher)
    adapter.ingest(IngestRequest(run_id="r", season=SEASON))
    written = [
        path.read_text(encoding="utf-8") for path in fetcher.bronze.root.rglob("*.meta.json")
    ]
    assert written
    assert not any(sensitive_value in text for text in written)
    assert any(REDACTED in text for text in written)


def test_redaction_leaves_everything_else_alone() -> None:
    url = "https://example.test/v4/odds?apiKey=secret&regions=uk"
    assert redact(url, ("apiKey",)) == f"https://example.test/v4/odds?apiKey={REDACTED}&regions=uk"
    assert redact(url, ()) == url


def test_the_credit_budget_is_enforced_in_the_adapter(
    fetcher: Fetcher, odds_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CON-7, R-08: a schedule is a promise, a ledger is a mechanism."""
    monkeypatch.setenv(API_KEY_ENV, "test-key-not-a-real-one")
    adapter = OddsApiAdapter(fetcher, SourceOverride(credit_budget=1))
    request = IngestRequest(run_id="r", season=SEASON)

    adapter.fetch_odds(request)
    month = adapter.month_of(None)
    assert adapter.credits_used(month) == 1

    with pytest.raises(CreditBudgetExhaustedError):
        adapter.fetch_odds(IngestRequest(run_id="r", season=SEASON, force_refresh=True))


def test_an_exhausted_budget_degrades_the_run_rather_than_stopping_it(
    fetcher: Fetcher, odds_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "test-key-not-a-real-one")
    adapter = OddsApiAdapter(fetcher, SourceOverride(credit_budget=0))
    conformed = adapter.conform(IngestRequest(run_id="r", season=SEASON))
    assert conformed.tables == {}
    assert any("spent" in warning for warning in conformed.warnings)


def test_the_budget_comes_from_configuration_then_environment_then_the_free_tier(
    fetcher: Fetcher,
) -> None:
    assert OddsApiAdapter(fetcher).credit_budget({}) == DEFAULT_CREDIT_BUDGET
    assert OddsApiAdapter(fetcher).credit_budget({"FPL_DOF_ODDS_CREDIT_BUDGET": "12"}) == 12
    configured = OddsApiAdapter(fetcher, SourceOverride(credit_budget=7))
    assert configured.credit_budget({"FPL_DOF_ODDS_CREDIT_BUDGET": "12"}) == 7


# --- the shape of what they all produce -----------------------------------------------------------


def test_every_conformed_advanced_table_validates(
    fetcher: Fetcher, understat: UnderstatAdapter
) -> None:
    frame = understat.conform(REQUEST).tables[Table.PLAYER_ADVANCED.value]
    validate(Table.PLAYER_ADVANCED, frame)


def test_the_metric_vocabulary_is_declared_in_one_place() -> None:
    """The tuple adapters fill in and the schemas that store it cannot drift apart."""
    for table in (Table.PLAYER_ADVANCED, Table.PLAYER_METRIC):
        columns = set(SCHEMAS[table].to_schema().columns)
        assert set(ADVANCED_METRICS) <= columns


def test_each_source_declares_which_fields_it_contributes() -> None:
    """DP-15: losing a source removes known fields, not unknown ones."""
    for adapter in (UnderstatAdapter, FbrefAdapter):
        assert adapter.contributes
        assert set(adapter.contributes) <= set(ADVANCED_METRICS)
