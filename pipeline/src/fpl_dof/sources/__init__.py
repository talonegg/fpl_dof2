"""Source adapters.

**This is the only package in the codebase permitted to know that a specific data source exists**
(Invariant 1, DP-01). Nothing outside it may import a source module, name a source in code, or
branch on which source a value came from. Downstream consumes the conformed silver model.

The rule is enforced by ``tests/test_source_isolation.py``, which fails the build if a source name
appears in a module outside this package.
"""

from fpl_dof.sources.base import (
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
)
from fpl_dof.sources.bronze import BronzeStore, Snapshot, SnapshotMeta
from fpl_dof.sources.enrich import canonicalise
from fpl_dof.sources.errors import (
    OfflineWithoutSnapshotError,
    SourceContractError,
    SourceError,
    SourceNotFoundError,
    SourceRateLimitedError,
    SourceUnavailableError,
)
from fpl_dof.sources.fetch import Fetched, Fetcher, RateLimiter
from fpl_dof.sources.registry import build, known, register

__all__ = [
    "BronzeStore",
    "Fetched",
    "Fetcher",
    "IngestReport",
    "IngestRequest",
    "OfflineWithoutSnapshotError",
    "RateLimiter",
    "Resource",
    "Snapshot",
    "SnapshotMeta",
    "SourceAdapter",
    "SourceContractError",
    "SourceError",
    "SourceNotFoundError",
    "SourceRateLimitedError",
    "SourceUnavailableError",
    "build",
    "canonicalise",
    "known",
    "register",
]
