"""Live reads for the operational scripts (REM-06, REM-07; Invariant 1).

The CI scripts — the day-before gate, the prospective harness driver and the xP scorer — need the
game's current state, its fixtures, a gameweek's live scores and the upcoming match odds. They get
them here, through the adapters and the bronze store like every other read (DP-11), so no script
outside this package names a source, an endpoint or a source's file format.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from fpl_dof.config import load_config
from fpl_dof.obs.manifest import new_run_id, utcnow
from fpl_dof.sources.base import IngestRequest
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.fdcouk.adapter import FdcoukAdapter, fetch_history
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.fpl.adapter import FplApiAdapter

#: Where the frozen prospective harness reads a decision's upcoming odds, relative to its root.
#: Its contract, frozen with it; the bytes are the odds snapshot exactly as fetched.
UPCOMING_ODDS_RECORD = "data/bronze/fdcouk"


class LiveFeed:
    """One script run's live reads, each fetched fresh and kept in ``<data_dir>/bronze``."""

    def __init__(self, data_dir: Path = Path("data")) -> None:
        config, _ = load_config()
        run_id = new_run_id()
        self._season = config.rules.season
        self._fetcher = Fetcher(
            config=config.http, bronze=BronzeStore(data_dir / "bronze"), run_id=run_id
        )
        self._game = FplApiAdapter(self._fetcher)
        self._odds = FdcoukAdapter(self._fetcher)
        self._request = IngestRequest(
            run_id=run_id, force_refresh=True, now=utcnow(), season=self._season
        )

    def __enter__(self) -> LiveFeed:
        return self

    def __exit__(self, *exc: object) -> None:
        self._fetcher.close()

    def state(self) -> dict[str, Any]:
        """The game's current state: events (gameweeks), teams and players."""
        return self._game.fetch_bootstrap(self._request)

    def fixtures(self) -> list[dict[str, Any]]:
        return self._game.fetch_fixtures(self._request)

    def gameweek_live(self, gameweek: int) -> dict[str, Any]:
        """Every player's live points and minutes in ``gameweek``."""
        return self._game.fetch_event_live(gameweek, self._request)

    def upcoming_odds(self) -> tuple[pd.DataFrame, bytes]:
        """The upcoming fixtures' match odds, conformed, and the snapshot's bytes as fetched."""
        text = self._odds.fetch_fixtures_csv(self._request)
        captured = pd.Timestamp(utcnow())
        return self._odds.parse_fixtures_csv(text, self._season, captured), text.encode("latin-1")

    def place_odds_history(
        self, frozen_root: Path, expected: Mapping[str, str]
    ) -> dict[str, str | None]:
        """The frozen harness's pinned past-season odds, placed under ``frozen_root``.

        Path -> problem (``None`` when the file matches its pinned hash). Each file is fetched once
        into bronze as an immutable snapshot (PIPE-03), so later runs make no request for it.
        """
        resource = self._odds.resource("season_odds")

        def get(url: str) -> bytes:
            fetched = self._fetcher.fetch(
                url,
                source=self._odds.name,
                source_version=self._odds.version,
                resource=resource.name,
                key=url.rsplit("/", 2)[-2],
                cache_ttl_seconds=resource.cache_ttl_seconds,
                now=self._request.now,
                immutable=True,
            )
            return fetched.payload

        return fetch_history(frozen_root, expected, get)


__all__ = ["UPCOMING_ODDS_RECORD", "LiveFeed"]
