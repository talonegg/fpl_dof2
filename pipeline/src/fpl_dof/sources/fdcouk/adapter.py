"""Match odds and goal expectations from football-data.co.uk (PIPE-04, FR-03).

Provides pre-deadline fixture odds (fixtures.csv) and completed historical season match
results and odds (mmz4281/{season}/E0.csv).
Conforms raw bookmaker prices (Bet365 / consensus) into de-vigged team-level goal
expectations matching TeamMatchExpectationSchema.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.prospective.bundle import sha256_bytes, sha256_file
from fpl_dof.silver.tables import Table, columns_for
from fpl_dof.sources.base import (
    Conformed,
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
)
from fpl_dof.sources.errors import SourceContractError
from fpl_dof.sources.oddsapi.market import (
    MarketError,
    devig,
    fit_goal_expectations,
)
from fpl_dof.sources.registry import register

log = get_logger(__name__)

BASE_URL = "https://www.football-data.co.uk"
MMZ_BASE = f"{BASE_URL}/mmz4281"

#: Bundle-relative path -> source URL for historical frozen seasons.
HISTORY: dict[str, str] = {
    "backtest/fdcouk/E0_2324.csv": f"{MMZ_BASE}/2324/E0.csv",
    "backtest/fdcouk/E0_2425.csv": f"{MMZ_BASE}/2425/E0.csv",
    "backtest/fdcouk/E0_2526.csv": f"{MMZ_BASE}/2526/E0.csv",
}

#: Season code -> E0.csv URL for all seasons the replay/backtest tooling reads.
SEASONS: dict[str, str] = {
    "2324": f"{MMZ_BASE}/2324/E0.csv",
    "2425": f"{MMZ_BASE}/2425/E0.csv",
    "2526": f"{MMZ_BASE}/2526/E0.csv",
    "2627": f"{MMZ_BASE}/2627/E0.csv",
}

Getter = Callable[[str], bytes]


def fetch_history(
    frozen_root: Path, expected: Mapping[str, str], get: Getter
) -> dict[str, str | None]:
    """Place each history CSV under ``frozen_root``; return path -> problem (None when ok).

    A file already present with the frozen hash is not re-downloaded.
    """
    out: dict[str, str | None] = {}
    for rel, url in HISTORY.items():
        want = expected.get(rel)
        if want is None:
            out[rel] = "no frozen hash recorded"
            continue
        dest = frozen_root / rel
        if sha256_file(dest) == want:
            out[rel] = None
            continue
        try:
            data = get(url)
        except Exception as exc:
            out[rel] = f"download failed ({type(exc).__name__})"
            continue
        if sha256_bytes(data) != want:
            out[rel] = "upstream file differs from the frozen copy"
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        out[rel] = None
    return out


def latest_fixtures_csv(data_dir: Path | None = None) -> bytes:
    """Read the latest fixtures CSV snapshot from Bronze, if one exists."""
    from fpl_dof.sources.bronze import BronzeStore, Snapshot, SnapshotMeta

    root = data_dir or Path("data")
    store = BronzeStore(root / "bronze" if (root / "bronze").is_dir() else root)
    directory = store.resource_dir("fdcouk", "fixtures")
    if not directory.is_dir():
        return b""
    candidates = sorted(directory.glob("*/*"))
    for path in reversed(candidates):
        if path.name.endswith(".meta.json"):
            continue
        meta_path = path.with_name(path.name + ".meta.json")
        if meta_path.exists():
            snap = Snapshot(
                path=path,
                meta=SnapshotMeta.model_validate_json(meta_path.read_text(encoding="utf-8")),
            )
            return snap.read_bytes()
    return b""


@register
class FdcoukAdapter(SourceAdapter):
    name: ClassVar[str] = "fdcouk"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "Match odds and expectations from football-data.co.uk"
    base_url: ClassVar[str] = BASE_URL
    enabled_by_default: ClassVar[bool] = False
    essential: ClassVar[bool] = False
    attribution: ClassVar[str] = "Match odds via football-data.co.uk"
    health_label: ClassVar[str] = "Upcoming match odds (football-data.co.uk)"
    health_description: ClassVar[str] = (
        "Bookmaker odds for upcoming fixtures, de-vigged into team goal expectations."
    )
    health_disabled_reason: ClassVar[str] = (
        "Switched off by default; upcoming match odds are fetched on-demand "
        "during the pre-deadline window."
    )
    contributes: ClassVar[tuple[str, ...]] = (
        "expected_goals_home",
        "expected_goals_away",
        "clean_sheet_probability_home",
        "clean_sheet_probability_away",
    )
    resources: ClassVar[tuple[Resource, ...]] = (
        Resource(
            name="fixtures",
            summary="Upcoming gameweek fixture odds (fixtures.csv)",
            cache_ttl_seconds=3600,
            fast_path=True,
        ),
        Resource(
            name="season_odds",
            summary="Completed season match odds (E0.csv)",
            cache_ttl_seconds=365 * 24 * 3600,
            fast_path=False,
        ),
    )

    def fetch_fixtures_csv(self, request: IngestRequest) -> str:
        """Fetch the latest upcoming fixtures CSV."""
        res = self.resource("fixtures")
        url = self.url_for("fixtures.csv")
        fetched = self.fetcher.fetch(
            url,
            source=self.name,
            source_version=self.version,
            resource=res.name,
            key="upcoming",
            cache_ttl_seconds=res.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            offline=request.offline,
            now=request.now,
        )
        return fetched.payload

    def parse_fixtures_csv(self, text: str, season: str, captured_at: pd.Timestamp) -> pd.DataFrame:
        """Parse raw fixtures.csv into conformed TeamMatchExpectation rows."""
        cleaned = text.lstrip("\ufeff").replace("ï»¿", "", 1)
        try:
            reader = list(csv.DictReader(io.StringIO(cleaned)))
        except csv.Error as exc:
            raise SourceContractError(
                f"fixtures.csv could not be parsed as CSV: {exc}",
                source=self.name,
                resource="fixtures",
            ) from exc

        rows: list[dict[str, Any]] = []
        for r in reader:
            if r.get("Div") != "E0":
                continue
            home = str(r.get("HomeTeam") or "").strip()
            away = str(r.get("AwayTeam") or "").strip()
            if not home or not away:
                continue

            # Read 1X2 odds: prefer Bet365, fall back to Market Average / Max
            h_odds = _number(r.get("B365H") or r.get("AvgH") or r.get("MaxH"))
            d_odds = _number(r.get("B365D") or r.get("AvgD") or r.get("MaxD"))
            a_odds = _number(r.get("B365A") or r.get("AvgA") or r.get("MaxA"))
            if not (h_odds and d_odds and a_odds):
                continue

            # Over/under 2.5 if available
            over_odds = _number(r.get("B365>2.5") or r.get("Avg>2.5") or r.get("P>2.5"))
            under_odds = _number(r.get("B365<2.5") or r.get("Avg<2.5") or r.get("P<2.5"))

            try:
                result = devig({"home": h_odds, "draw": d_odds, "away": a_odds})
                over = None
                if over_odds and under_odds:
                    totals = devig({"over": over_odds, "under": under_odds})
                    over = totals["over"]
                fitted = fit_goal_expectations(result=result, over=over, line=2.5)
            except (MarketError, ValueError) as exc:
                log.warning(
                    "fdcouk.unusable_odds",
                    extra={"home": home, "away": away, "why": str(exc)},
                )
                continue

            # Parse kickoff time if present
            date_str = r.get("Date", "").strip()
            time_str = r.get("Time", "").strip()
            kickoff = _parse_kickoff(date_str, time_str)

            rows.append(
                {
                    "season": season,
                    "source": self.name,
                    "captured_at": captured_at,
                    "kickoff_time": kickoff,
                    "home_team": home,
                    "away_team": away,
                    "home_team_id": None,
                    "away_team_id": None,
                    "expected_goals_home": fitted.expected_goals_home,
                    "expected_goals_away": fitted.expected_goals_away,
                    "clean_sheet_probability_home": fitted.clean_sheet_probability_home,
                    "clean_sheet_probability_away": fitted.clean_sheet_probability_away,
                    "home_win_probability": fitted.home_win_probability,
                    "draw_probability": fitted.draw_probability,
                    "away_win_probability": fitted.away_win_probability,
                    "total_goals": fitted.total_goals,
                }
            )

        frame = pd.DataFrame(rows, columns=columns_for(Table.TEAM_MATCH_EXPECTATION))
        frame["kickoff_time"] = pd.to_datetime(frame["kickoff_time"], utc=True)
        frame["captured_at"] = pd.to_datetime(frame["captured_at"], utc=True)
        return frame

    def ingest(self, request: IngestRequest) -> IngestReport:
        report = IngestReport(source=self.name)
        before_calls = self.fetcher.network_calls
        before_hits = self.fetcher.cache_hits

        try:
            payload = self.fetch_fixtures_csv(request)
            report.resources["fixtures"] = len(payload)
        except Exception as exc:
            report.warnings.append(str(exc))

        report.network_calls = self.fetcher.network_calls - before_calls
        report.cache_hits = self.fetcher.cache_hits - before_hits
        log.info(
            "fdcouk.ingest.done",
            extra={"network_calls": report.network_calls, "cache_hits": report.cache_hits},
        )
        return report

    def conform(self, request: IngestRequest) -> Conformed:
        season = request.season
        if season is None:
            return Conformed(tables={}, warnings=["no season supplied; no fdcouk data"])

        try:
            text = self.fetch_fixtures_csv(request)
        except Exception as exc:
            return Conformed(tables={}, warnings=[f"no fixtures odds: {exc}"])

        captured = pd.Timestamp(request.now or utcnow()).tz_convert("UTC")
        frame = self.parse_fixtures_csv(text, season, captured)
        if frame.empty:
            return Conformed(tables={}, warnings=["no priced fixtures in fixtures.csv"])
        return Conformed(tables={Table.TEAM_MATCH_EXPECTATION.value: frame})


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        val = float(str(value).strip())
        return val if val > 0 else None
    except TypeError, ValueError:
        return None


def _parse_kickoff(date_str: str, time_str: str) -> pd.Timestamp:
    """Parse date like '18/10/2026' and time like '15:00' into UTC Timestamp."""
    if not date_str:
        return pd.NaT
    combo = f"{date_str} {time_str}".strip() if time_str else date_str
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%y %H:%M", "%d/%m/%Y", "%d/%m/%y"):
        try:
            parsed = dt.datetime.strptime(combo, fmt)
            return pd.Timestamp(parsed, tz="UTC")
        except ValueError:
            continue
    return pd.NaT


__all__ = [
    "BASE_URL",
    "HISTORY",
    "MMZ_BASE",
    "SEASONS",
    "FdcoukAdapter",
    "fetch_history",
]
