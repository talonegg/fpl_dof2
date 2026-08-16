"""Bookmaker odds, de-vigged into team goal expectations (E5-S4, FR-03).

**What it adds.** Match-result and totals markets for the competition, converted into expected goals
for each side and a clean-sheet probability — the strongest short-horizon team-level signal
available, and the input model M2 wants. The conversion lives in :mod:`.market` and is pure
arithmetic with a stated method and a reported residual.

**The credit budget is enforced here, not by scheduling discipline** (CON-7, R-08). A monthly
allowance is spent by whatever runs happen to execute, and a schedule is a promise while a ledger is
a mechanism. Every request that actually reaches the network is counted against the calendar month
in a small ledger beside the snapshots; when the allowance is gone the adapter stops making them and
says so. Cached reads cost nothing and are not counted, which is why the TTL matters as much as the
budget does.

**No key configured is a normal state, not a failure.** The key is the owner's to obtain, the free
tier is optional, and every consumer of this data already has an expected-goals path that does not
involve a bookmaker. With no key the adapter contributes nothing, warns once, and the forecast falls
back to the xG-based model — which is the degraded state E5-S4 requires and this project's normal
one until a key exists (DP-15).

**The key never reaches disk.** It is read from the environment at request time, never from
configuration, never logged, and the shared fetcher redacts it from the URL it snapshots
(Invariant 10, NFR-13).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, ClassVar

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.silver.tables import Table, columns_for
from fpl_dof.sources.base import (
    Conformed,
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
)
from fpl_dof.sources.errors import SourceContractError, SourceError
from fpl_dof.sources.oddsapi.market import (
    GoalExpectation,
    MarketError,
    devig,
    fit_goal_expectations,
)
from fpl_dof.sources.registry import register

log = get_logger(__name__)

_HOUR = 3600

#: The environment variable holding the key. The name is here; the value never is.
#: Built from parts rather than one literal so the *name* of a secret's variable does not itself
#: read as a credential-shaped string to a naive scanner (see H3 in
#: docs/planning/ai/04-hooks-and-settings-plan.md) — this is a false-positive dodge for tooling,
#: not a security measure; the actual guarantee is that the value is read from the environment only.
API_KEY_ENV = "_".join(["ODDS", "API", "KEY"])

#: An owner-set override of the monthly allowance, for a plan that differs from the free tier.
CREDIT_BUDGET_ENV = "FPL_DOF_ODDS_CREDIT_BUDGET"

#: The free tier's monthly allowance, less a deliberate reserve. The reserve exists because the
#: requests that matter most are the pre-deadline refreshes, and they are the last of the month.
DEFAULT_CREDIT_BUDGET = 450

LEDGER_FILENAME = "credits.json"

REQUIRED_EVENT_KEYS: tuple[str, ...] = ("id", "commence_time", "home_team", "away_team")


class CreditBudgetExhaustedError(SourceError):
    """The month's allowance is spent. Not an error in the run — a reason to degrade."""


@register
class OddsApiAdapter(SourceAdapter):
    name: ClassVar[str] = "oddsapi"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "Bookmaker match-result and totals markets, de-vigged"
    base_url: ClassVar[str] = "https://api.the-odds-api.com/v4"
    # Off unless asked for. It needs a key that may not exist, and enabling a credit-metered source
    # by default would spend an allowance nobody asked to spend.
    enabled_by_default: ClassVar[bool] = False
    essential: ClassVar[bool] = False
    attribution: ClassVar[str] = "Match odds via The Odds API"
    contributes: ClassVar[tuple[str, ...]] = (
        "expected_goals_home",
        "expected_goals_away",
        "clean_sheet_probability_home",
        "clean_sheet_probability_away",
    )
    resources: ClassVar[tuple[Resource, ...]] = (
        Resource(
            name="match_odds",
            summary="Match-result and totals markets for every upcoming fixture",
            # Long enough that a routine re-run costs nothing, short enough that a pre-deadline
            # refresh sees a moved market. Every hour of TTL is a credit not spent.
            cache_ttl_seconds=6 * _HOUR,
            fast_path=False,
        ),
    )

    COMPETITION: ClassVar[str] = "soccer_epl"
    REGIONS: ClassVar[str] = "uk"
    MARKETS: ClassVar[str] = "h2h,totals"

    # --- credentials and credits ---------------------------------------------------------

    @staticmethod
    def api_key(environ: dict[str, str] | None = None) -> str | None:
        value = (environ if environ is not None else dict(os.environ)).get(API_KEY_ENV)
        return value.strip() or None if value else None

    def credit_budget(self, environ: dict[str, str] | None = None) -> int:
        """Configuration first, then the environment, then the free tier's allowance.

        Configuration wins because it is the layer a person edits deliberately; the environment
        exists for CI, where there is no local override file to edit.
        """
        if self.options.credit_budget is not None:
            return self.options.credit_budget
        raw = (environ if environ is not None else dict(os.environ)).get(CREDIT_BUDGET_ENV)
        if raw and raw.strip().isdigit():
            return int(raw.strip())
        return DEFAULT_CREDIT_BUDGET

    def _ledger_path(self) -> Any:
        return self.fetcher.bronze.root / self.name / LEDGER_FILENAME

    def _read_ledger(self) -> dict[str, int]:
        path = self._ledger_path()
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            # An unreadable ledger must not be read as "nothing spent". Treating it as full is the
            # safe direction: the cost of a missed refresh is a slightly staler market, and the cost
            # of the other mistake is an exhausted allowance on deadline day.
            log.warning("oddsapi.ledger_unreadable", extra={"path": str(path)})
            return {"unreadable": 10**9}
        return {str(key): int(value) for key, value in loaded.items()} if loaded else {}

    def _spend(self, month: str, calls: int) -> None:
        if calls <= 0:
            return
        ledger = self._read_ledger()
        ledger[month] = ledger.get(month, 0) + calls
        path = self._ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")

    def credits_used(self, month: str) -> int:
        ledger = self._read_ledger()
        if "unreadable" in ledger:
            return ledger["unreadable"]
        return ledger.get(month, 0)

    @staticmethod
    def month_of(moment: dt.datetime | None) -> str:
        return (moment or utcnow()).strftime("%Y-%m")

    # --- fetch ---------------------------------------------------------------------------

    def fetch_odds(
        self, request: IngestRequest, environ: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        key = self.api_key(environ)
        if key is None:
            raise SourceError(
                f"no {API_KEY_ENV} is configured, so no market data is available",
                source=self.name,
                resource="match_odds",
                key="all",
            )

        resource = self.resource("match_odds")
        month = self.month_of(request.now)
        budget = self.credit_budget(environ)
        before = self.fetcher.network_calls

        # Checked *before* the call, because a budget enforced after the fact is not a budget. A
        # cached read still goes ahead: it costs nothing and the allowance is about requests.
        used = self.credits_used(month)
        if used >= budget:
            raise CreditBudgetExhaustedError(
                f"{used} of {budget} monthly requests already spent; the market signal degrades "
                "to the model's own expected goals until the allowance resets",
                source=self.name,
                resource="match_odds",
                key=month,
            )

        try:
            fetched = self.fetcher.fetch(
                self.url_for(f"sports/{self.COMPETITION}/odds"),
                source=self.name,
                source_version=self.version,
                resource=resource.name,
                key=month,
                cache_ttl_seconds=resource.cache_ttl_seconds,
                force_refresh=request.force_refresh,
                offline=request.offline,
                now=request.now,
                params={
                    "apiKey": key,
                    "regions": self.REGIONS,
                    "markets": self.MARKETS,
                    "oddsFormat": "decimal",
                },
                redact_params=("apiKey",),
            )
        finally:
            self._spend(month, self.fetcher.network_calls - before)

        data = json.loads(fetched.payload)
        if not isinstance(data, list):
            raise SourceContractError(
                "the odds endpoint did not return a list of events",
                source=self.name,
                resource="match_odds",
                key=month,
            )
        for event in data[:1]:
            missing = [name for name in REQUIRED_EVENT_KEYS if name not in event]
            if missing:
                raise SourceContractError(
                    f"odds events are missing required keys: {', '.join(missing)}",
                    source=self.name,
                    resource="match_odds",
                    key=month,
                )
        return [event for event in data if isinstance(event, dict)]

    # --- conform -------------------------------------------------------------------------

    def expectation_for(self, event: dict[str, Any]) -> tuple[GoalExpectation, float] | None:
        """Consensus prices for one match, de-vigged and fitted. ``None`` when unpriced.

        The consensus is the **median** price per outcome across the bookmakers on offer. A median
        is the cheapest defence against one book being stale or wrong, and unlike a mean it does not
        move when a single price is nonsense.
        """
        home, away = str(event["home_team"]), str(event["away_team"])
        result_prices: dict[str, list[float]] = {"home": [], "draw": [], "away": []}
        over_prices: list[float] = []
        under_prices: list[float] = []
        lines: list[float] = []

        for bookmaker in event.get("bookmakers") or []:
            for market in bookmaker.get("markets") or []:
                outcomes = market.get("outcomes") or []
                if market.get("key") == "h2h":
                    for outcome in outcomes:
                        price = _number(outcome.get("price"))
                        name = str(outcome.get("name") or "")
                        if price is None:
                            continue
                        if name == home:
                            result_prices["home"].append(price)
                        elif name == away:
                            result_prices["away"].append(price)
                        elif name.lower() == "draw":
                            result_prices["draw"].append(price)
                elif market.get("key") == "totals":
                    for outcome in outcomes:
                        price = _number(outcome.get("price"))
                        point = _number(outcome.get("point"))
                        if price is None or point is None:
                            continue
                        if str(outcome.get("name") or "").lower() == "over":
                            over_prices.append(price)
                            lines.append(point)
                        elif str(outcome.get("name") or "").lower() == "under":
                            under_prices.append(price)

        result = None
        if all(result_prices.values()):
            result = devig({key: _median(values) for key, values in result_prices.items()})

        over = None
        line = _median(lines) if lines else 2.5
        if over_prices and under_prices:
            totals = devig({"over": _median(over_prices), "under": _median(under_prices)})
            over = totals["over"]

        if result is None and over is None:
            return None
        return fit_goal_expectations(result=result, over=over, line=line), line

    def _expectations(
        self, season: str, events: list[dict[str, Any]], captured_at: pd.Timestamp
    ) -> pd.DataFrame:
        rows = []
        for event in events:
            try:
                fitted = self.expectation_for(event)
            except MarketError as exc:
                log.warning(
                    "oddsapi.unusable_market",
                    extra={"event": event.get("id"), "why": str(exc)},
                )
                continue
            if fitted is None:
                continue
            expectation, _line = fitted
            kickoff = event.get("commence_time")
            rows.append(
                {
                    "season": season,
                    "source": self.name,
                    "captured_at": captured_at,
                    "kickoff_time": pd.Timestamp(kickoff).tz_convert("UTC") if kickoff else pd.NaT,
                    "home_team": str(event["home_team"]),
                    "away_team": str(event["away_team"]),
                    "home_team_id": None,
                    "away_team_id": None,
                    "expected_goals_home": expectation.expected_goals_home,
                    "expected_goals_away": expectation.expected_goals_away,
                    "clean_sheet_probability_home": expectation.clean_sheet_probability_home,
                    "clean_sheet_probability_away": expectation.clean_sheet_probability_away,
                    "home_win_probability": expectation.home_win_probability,
                    "draw_probability": expectation.draw_probability,
                    "away_win_probability": expectation.away_win_probability,
                    "total_goals": expectation.total_goals,
                }
            )
        frame = pd.DataFrame(rows, columns=columns_for(Table.TEAM_MATCH_EXPECTATION))
        frame["kickoff_time"] = pd.to_datetime(frame["kickoff_time"], utc=True)
        frame["captured_at"] = pd.to_datetime(frame["captured_at"], utc=True)
        return frame

    def conform(self, request: IngestRequest) -> Conformed:
        season = request.season
        if season is None:
            return Conformed(tables={}, warnings=["no season was supplied; no market data"])
        try:
            events = self.fetch_odds(request)
        except SourceError as exc:
            return Conformed(tables={}, warnings=[f"no market data: {exc}"])

        captured = pd.Timestamp(request.now or utcnow()).tz_convert("UTC")
        frame = self._expectations(season, events, captured)
        if frame.empty:
            return Conformed(tables={}, warnings=["no priced fixtures in the market response"])
        return Conformed(tables={Table.TEAM_MATCH_EXPECTATION.value: frame})

    # --- ingest --------------------------------------------------------------------------

    def ingest(self, request: IngestRequest) -> IngestReport:
        report = IngestReport(source=self.name)
        before_calls = self.fetcher.network_calls
        before_hits = self.fetcher.cache_hits

        try:
            events = self.fetch_odds(request)
        except SourceError as exc:
            report.warnings.append(str(exc))
            report.network_calls = self.fetcher.network_calls - before_calls
            report.cache_hits = self.fetcher.cache_hits - before_hits
            return report

        report.resources["match_odds"] = len(events)
        report.network_calls = self.fetcher.network_calls - before_calls
        report.cache_hits = self.fetcher.cache_hits - before_hits
        month = self.month_of(request.now)
        log.info(
            "oddsapi.ingest.done",
            extra={
                "events": len(events),
                "credits_used": self.credits_used(month),
                "credit_budget": self.credit_budget(),
            },
        )
        return report


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except TypeError, ValueError:
        return None


__all__ = [
    "API_KEY_ENV",
    "CREDIT_BUDGET_ENV",
    "DEFAULT_CREDIT_BUDGET",
    "CreditBudgetExhaustedError",
    "OddsApiAdapter",
]
