"""Source adapters.

**This is the only package in the codebase permitted to know that a specific data source exists**
(Invariant 1, DP-01). Nothing outside it may import a source module, name a source in code, or
branch on which source a value came from. Downstream consumes the conformed silver model.

The rule is enforced by ``tests/test_source_isolation.py``, which fails the build if a source name
appears in a module outside this package.
"""

from fpl_dof.sources.base import (
    ChangeContext,
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
)
from fpl_dof.sources.bronze import META_SUFFIX, BronzeStore, Snapshot, SnapshotMeta
from fpl_dof.sources.catalogue import LIVE, REFERENCE, SourceDescriptor, describe, supplying
from fpl_dof.sources.changes import KINDS as CHANGE_KINDS
from fpl_dof.sources.changes import before_ingest, changed_kinds
from fpl_dof.sources.enrich import canonicalise
from fpl_dof.sources.errors import (
    OfflineWithoutSnapshotError,
    SourceContractError,
    SourceError,
    SourceNotFoundError,
    SourceRateLimitedError,
    SourceUnavailableError,
)
from fpl_dof.sources.feeds import LiveFeed
from fpl_dof.sources.fetch import Fetched, Fetcher, RateLimiter
from fpl_dof.sources.registry import build, known, register
from fpl_dof.sources.replay import extract_price_history_rows, gameweeks_from_bronze, replay_prices
from fpl_dof.sources.resolve import CLUB_ALIASES, resolve_team

__all__ = [
    "CHANGE_KINDS",
    "CLUB_ALIASES",
    "LIVE",
    "META_SUFFIX",
    "REFERENCE",
    "BronzeStore",
    "ChangeContext",
    "Fetched",
    "Fetcher",
    "IngestReport",
    "IngestRequest",
    "LiveFeed",
    "OfflineWithoutSnapshotError",
    "RateLimiter",
    "Resource",
    "Snapshot",
    "SnapshotMeta",
    "SourceAdapter",
    "SourceContractError",
    "SourceDescriptor",
    "SourceError",
    "SourceNotFoundError",
    "SourceRateLimitedError",
    "SourceUnavailableError",
    "before_ingest",
    "build",
    "canonicalise",
    "changed_kinds",
    "describe",
    "extract_price_history_rows",
    "gameweeks_from_bronze",
    "known",
    "register",
    "replay_prices",
    "resolve_team",
    "supplying",
]
