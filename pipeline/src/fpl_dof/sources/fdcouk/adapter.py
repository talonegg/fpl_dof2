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
from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

if TYPE_CHECKING:
    from pandas._libs.tslibs.nattype import NaTType

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

#: football-data.co.uk's club names (lower case, letters and digits only) -> FPL's permanent club
#: code. The source's own naming, mapped once at the boundary: past seasons' rows carry the code,
#: as the archive's do (D-26); the current season's are resolved to season-local ids downstream.
CLUB_CODES: dict[str, int] = {
    "arsenal": 3,
    "astonvilla": 7,
    "bournemouth": 91,
    "brentford": 94,
    "brighton": 36,
    "chelsea": 8,
    "coventry": 9,
    "coventrycity": 9,
    "crystalpalace": 31,
    "everton": 11,
    "fulham": 54,
    "hull": 88,
    "hullcity": 88,
    "ipswich": 40,
    "ipswichtown": 40,
    "leeds": 2,
    "leedsunited": 2,
    "liverpool": 14,
    "mancity": 43,
    "manchestercity": 43,
    "manutd": 1,
    "manunited": 1,
    "manchesterunited": 1,
    "newcastle": 4,
    "newcastleunited": 4,
    "nottinghamforest": 17,
    "nottmforest": 17,
    "spurs": 6,
    "tottenham": 6,
    "tottenhamhotspur": 6,
    "sunderland": 56,
    "sheffieldutd": 49,
    "sheffieldunited": 49,
    "burnley": 90,
    "luton": 102,
    "lutontown": 102,
    "wolves": 39,
    "wolverhampton": 39,
    "wolverhamptonwanderers": 39,
    "westham": 21,
    "westhamunited": 21,
    "leicester": 13,
    "leicestercity": 13,
    "southampton": 20,
}


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


@register
class FdcoukAdapter(SourceAdapter):
    name: ClassVar[str] = "fdcouk"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "Match odds and expectations from football-data.co.uk"
    base_url: ClassVar[str] = BASE_URL
    enabled_by_default: ClassVar[bool] = False
    essential: ClassVar[bool] = False
    attribution: ClassVar[str] = "Match odds via football-data.co.uk"
    health_label: ClassVar[str] = "Match odds in the pipeline run (football-data.co.uk)"
    health_description: ClassVar[str] = (
        "Bookmaker odds for upcoming fixtures, de-vigged into team goal expectations."
    )
    health_disabled_reason: ClassVar[str] = (
        "Off in the pipeline run. The prospective harness fetches upcoming odds through it in "
        "the hours before each deadline, and those are shown under Upcoming match odds."
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
        # football-data.co.uk serves Latin-1, decoded as prospective/timing.py does.
        return fetched.payload.decode("latin-1")

    def parse_fixtures_csv(
        self, text: str, season: str, captured_at: pd.Timestamp | None
    ) -> pd.DataFrame:
        """Parse a football-data CSV into conformed TeamMatchExpectation rows.

        ``captured_at=None`` marks a completed season's file: each row is stamped with its kickoff,
        the latest moment its pre-match prices can have been taken, and carries permanent club
        codes, since its clubs are not the current season's.
        """
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

            # Read 1X2 odds: prefer Bet365, fall back to Market Average / Max. The CSV gives
            # strings, so a missing price is "" and falls through.
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

            past = captured_at is None
            rows.append(
                {
                    "season": season,
                    "source": self.name,
                    "captured_at": kickoff if past else captured_at,
                    "kickoff_time": kickoff,
                    "home_team": home,
                    "away_team": away,
                    "home_team_id": _club_code(home) if past else None,
                    "away_team_id": _club_code(away) if past else None,
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
        for season in _past_seasons(request):
            try:
                report.resources[f"season_odds/{season}"] = len(
                    self.fetch_season_csv(season, request)
                )
            except Exception as exc:
                report.warnings.append(f"{season}: {exc}")

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

        frames: list[pd.DataFrame] = []
        warnings: list[str] = []
        try:
            text = self.fetch_fixtures_csv(request)
            snapshot = self.fetcher.bronze.latest(
                self.name, "fixtures", "upcoming", as_of=request.now
            )
            # When the prices were fetched, never when the run happened (as price history, REM-02).
            captured = pd.Timestamp(
                snapshot.meta.fetched_at if snapshot else (request.now or utcnow())
            ).tz_convert("UTC")
            frames.append(self.parse_fixtures_csv(text, season, captured))
        except Exception as exc:
            warnings.append(f"no fixtures odds: {exc}")
        for past in _past_seasons(request):
            try:
                text = self.fetch_season_csv(past, request)
                frames.append(self.parse_fixtures_csv(text, past, None))
            except Exception as exc:
                warnings.append(f"no {past} season odds: {exc}")

        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return Conformed(tables={}, warnings=[*warnings, "no priced fixtures"])
        frame = pd.concat(frames, ignore_index=True)
        return Conformed(tables={Table.TEAM_MATCH_EXPECTATION.value: frame}, warnings=warnings)

    def fetch_season_csv(self, season: str, request: IngestRequest) -> str:
        """A completed season's match file (E0.csv), fetched once and kept (PIPE-03)."""
        res = self.resource("season_odds")
        code = _season_code(season)
        fetched = self.fetcher.fetch(
            SEASONS[code],
            source=self.name,
            source_version=self.version,
            resource=res.name,
            key=code,
            cache_ttl_seconds=res.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            offline=request.offline,
            now=request.now,
            immutable=True,
            rebackfill=request.rebackfill,
        )
        return fetched.payload.decode("latin-1")


def _season_code(season: str) -> str:
    """``"2024/25"`` -> ``"2425"``, football-data's folder name."""
    return season[2:4] + season[5:7]


def _past_seasons(request: IngestRequest) -> list[str]:
    """The completed seasons asked for that football-data publishes a match file for."""
    return [
        s for s in (request.seasons or ()) if s != request.season and _season_code(s) in SEASONS
    ]


def _club_code(name: str) -> int | None:
    return CLUB_CODES.get("".join(ch for ch in name.lower() if ch.isalnum()))


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        val = float(str(value).strip())
        return val if val > 0 else None
    except TypeError, ValueError:
        return None


def _parse_kickoff(date_str: str, time_str: str) -> pd.Timestamp | NaTType:
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
    "CLUB_CODES",
    "HISTORY",
    "MMZ_BASE",
    "SEASONS",
    "FdcoukAdapter",
    "fetch_history",
]
