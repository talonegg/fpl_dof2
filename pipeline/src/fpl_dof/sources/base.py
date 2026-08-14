"""The source adapter interface.

Everything a source needs to declare about itself is here. Nothing downstream of this package may
import, name or branch on a specific source (Invariant 1) — the ingest stage iterates the registry
and the transform stage reads the conformed silver model.

Adding a source means writing one module in this package and registering it. It means changing
nothing else.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import pandas as pd

from fpl_dof.config.models import SourceOverride
from fpl_dof.rules.models import ApiRules
from fpl_dof.sources.fetch import Fetcher


@dataclass(frozen=True, slots=True)
class Resource:
    """One fetchable thing a source offers."""

    name: str
    summary: str
    cache_ttl_seconds: int | None = None
    fast_path: bool = True
    """Whether this resource is cheap enough to refresh on the frequent ingest cadence.

    ``element-summary`` is ~700 requests and must never run on the fast path
    (Architecture §9). E0 has one cadence, but the declaration is made here now so the
    distinction exists before E7 needs it.
    """


@dataclass(frozen=True, slots=True)
class IngestRequest:
    """What the ingest stage passes an adapter. Deliberately not the pipeline's StageContext:
    a source adapter should not be able to see the whole run."""

    run_id: str
    force_refresh: bool = False
    offline: bool = False
    player_limit: int | None = None
    now: dt.datetime | None = None
    entry_id: int | None = None
    """The owner's team, when one is configured. A game concept, not a source concept — an adapter
    that cannot expose it simply ignores the field."""

    league_id: int | None = None
    seasons: tuple[str, ...] = ()
    """Historical seasons to backfill. Empty means current season only."""

    season: str | None = None
    """The season being run, as ``2026/27``. A source that derives its own from the data it fetches
    ignores this; a source whose URLs are season-shaped needs to be told, and guessing from the
    wall clock would quietly fetch the wrong year through every August."""

    def seasons_with_current(self) -> tuple[str, ...]:
        """Every season a season-shaped source should fetch: the backfill, then the current one.

        **Backfill adds to the current season; it never replaces it.** Reading ``seasons`` alone
        would mean that configuring a historical backfill silently switched off this season's
        enrichment — the run would still succeed, the fields would still be typed, and the only
        symptom would be a forecast quietly missing the source it was configured to use. Oldest
        first, so a later season's row wins any last-write-wins merge downstream.
        """
        ordered = [season for season in self.seasons if season != self.season]
        if self.season:
            ordered.append(self.season)
        return tuple(dict.fromkeys(ordered))


@dataclass
class IngestReport:
    """What an adapter did. Rolled into the manifest by the ingest stage."""

    source: str
    resources: dict[str, int] = field(default_factory=dict)
    network_calls: int = 0
    cache_hits: int = 0
    snapshots: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Conformed:
    """What a source contributes to the canonical model.

    Conformance lives in the source package, not in the transform stage: mapping *this* source's
    shape onto the canonical one is the one thing that is irreducibly source-specific, and putting
    it anywhere else is how the abstraction leaks (Invariant 1).
    """

    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    rules: ApiRules | None = None
    """Rules the source publishes, if it publishes any. Merged with configuration downstream."""

    rules_snapshot_sha256: str | None = None
    warnings: list[str] = field(default_factory=list)


class SourceAdapter(ABC):
    """Base class for every source.

    Subclasses declare identity and resources, and implement :meth:`ingest`. They do not implement
    rate limiting, retry, caching or snapshotting — those belong to the shared
    :class:`~fpl_dof.sources.fetch.Fetcher` and are not a per-source decision.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    summary: ClassVar[str]
    base_url: ClassVar[str]
    resources: ClassVar[tuple[Resource, ...]] = ()
    enabled_by_default: ClassVar[bool] = True

    essential: ClassVar[bool] = True
    """Whether the pipeline can produce a recommendation without this source.

    Exactly one source supplies the game itself; everything else enriches it. A non-essential
    source that fails is logged, recorded and skipped, because a slightly worse recommendation
    comfortably beats no recommendation at 03:30 (NFR-15, DP-15). Marking a source essential is a
    statement that its absence makes the output *wrong* rather than *poorer*.
    """

    attribution: ClassVar[str] = ""
    """How this source must be credited where its data is shown (NFR-10).

    Declared by the source because only the source knows its own terms, and carried downstream as
    data so no module outside this package has to name a provider to render the credit.
    """

    contributes: ClassVar[tuple[str, ...]] = ()
    """Canonical field names this source can supply. The input to per-field precedence (NFR-15),
    and the reason losing a source removes known fields rather than unknown ones."""

    def __init__(self, fetcher: Fetcher, options: SourceOverride | None = None) -> None:
        self.fetcher = fetcher
        self.options = options or SourceOverride()

    def url_for(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def resource(self, name: str) -> Resource:
        for declared in self.resources:
            if declared.name == name:
                return declared
        raise KeyError(f"{self.name} declares no resource named {name!r}")

    @abstractmethod
    def ingest(self, request: IngestRequest) -> IngestReport:
        """Fetch every resource this source provides, writing snapshots to bronze."""

    @abstractmethod
    def conform(self, request: IngestRequest) -> Conformed:
        """Map this source's bronze snapshots onto the canonical silver model.

        Abstract rather than defaulting to empty: a source that contributes no canonical table is
        a decision worth making explicitly, not one worth inheriting by accident.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} version={self.version!r}>"


def resource_names(adapters: Sequence[SourceAdapter]) -> list[str]:
    return [
        f"{adapter.name}.{resource.name}" for adapter in adapters for resource in adapter.resources
    ]
