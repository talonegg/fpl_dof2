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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import pandas as pd

from fpl_dof.config.models import ScheduleConfig, SourceOverride
from fpl_dof.rules.models import ApiRules
from fpl_dof.sources.bronze import Snapshot
from fpl_dof.sources.fetch import Fetched, Fetcher

#: When the Open gameweek's matches can kick off: its deadline, then the next deadline or ``None``.
Window = tuple[dt.datetime, dt.datetime | None] | None


@dataclass(frozen=True, slots=True)
class ChangeContext:
    """What a source reads the change between two captures against (ORC-02, LIVE-02)."""

    window: Window
    """When the Open gameweek's matches can kick off, or ``None`` when no gameweek is Open."""
    matchday_zone: str
    """The zone whose date groups a gameweek's fixtures into matchdays."""
    settle: dt.timedelta
    """How long after a matchday's last kick-off it counts as done, bonus confirmed or not."""

    @classmethod
    def of(cls, window: Window, schedule: ScheduleConfig) -> ChangeContext:
        """The context for ``window``, with the matchday rule's tunables from config (DP-06)."""
        return cls(
            window, schedule.matchday_zone, dt.timedelta(hours=schedule.matchday_settle_hours)
        )


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
    immutable: bool = False
    """Whether this resource represents finalized historical data that never changes.

    Completed prior seasons (PIPE-03) are immutable: once cached in bronze, they are never
    re-fetched regardless of age unless explicit rebackfill or force-refresh is requested.
    """
    retain: bool = False
    """Whether every capture is kept on the `data` branch whatever its age.

    Distinct from ``immutable``: a retained resource is still re-fetched after its TTL (upcoming
    odds move), but each capture is evidence the backtest and the prospective record cannot recover.
    """


@dataclass(frozen=True, slots=True)
class IngestRequest:
    """What the ingest stage passes an adapter. Deliberately not the pipeline's StageContext:
    a source adapter should not be able to see the whole run."""

    run_id: str
    force_refresh: bool = False
    rebackfill: bool = False
    offline: bool = False
    player_limit: int | None = None
    fast_path_only: bool = False
    """Fetch only resources declared ``fast_path``. Set by the frequent cadence (E7-S1).

    Adapters should ask :meth:`SourceAdapter.wants` rather than read this directly, so the rule is
    written once and a new resource inherits it by declaring ``fast_path`` and nothing else.
    """

    now: dt.datetime | None = None
    entry_id: int | None = None
    """The owner's team, when one is configured. A game concept, not a source concept — an adapter
    that cannot expose it simply ignores the field."""

    league_id: int | None = None
    """A classic mini-league to read standings for, when one is configured. As with ``entry_id``, a
    game concept rather than a source concept; an adapter with no notion of a league ignores it."""

    league_rival_limit: int = 0
    """How many of that league's entries to fetch squads for, from the top of the table down.

    Defaults to **none**: standings are a single request, and squads are one request per entry per
    gameweek. An adapter asked for a league without being given a budget fetches the cheap half and
    stops, rather than inferring permission to make hundreds of requests.
    """

    seasons: tuple[str, ...] = ()
    """Historical seasons to backfill. Empty means current season only."""

    season: str | None = None
    """The season being run, as ``2026/27``. A source that derives its own from the data it fetches
    ignores this; a source whose URLs are season-shaped needs to be told, and guessing from the
    wall clock would quietly fetch the wrong year through every August."""

    as_of_gameweek: int | None = None
    """The gameweek whose deadline governs this run (PIPE-01, PIPE-12)."""

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

    # --- how the data health page describes this source (T-003) --------------------------------
    # Declared here, next to the source, for the same reason as ``attribution``: the page and the
    # publisher render these strings as data and never name a source themselves (Invariant 1).

    health_kind: ClassVar[str] = "live"
    """``live`` (fetched on a schedule, so it has a freshness age) or ``reference`` (fixed data,
    shown with an as-of date instead of an age)."""

    health_label: ClassVar[str] = ""
    """Plain-English name on the data health page. Empty falls back to ``summary``."""

    health_description: ClassVar[str] = ""
    """One line on what the source is for, shown under its label."""

    health_disabled_reason: ClassVar[str] = ""
    """Why this source is switched off, in words, for when configuration leaves it disabled."""

    health_note: ClassVar[str] = ""
    """The "Why" line for a ``reference`` source: what kind of fixed data it is and where it is
    used."""

    @classmethod
    def configuration_problem(cls, environ: Mapping[str, str] | None = None) -> str | None:
        """What this source is missing before it can collect anything, or ``None``.

        A source that needs a credential says so here, so "switched on but missing its key" can be
        published as *not set up* rather than inferred as healthy from a run that made no request
        at all. Never a secret: only whether one is present.
        """
        return None

    def __init__(self, fetcher: Fetcher, options: SourceOverride | None = None) -> None:
        self.fetcher = fetcher
        self.options = options or SourceOverride()
        self.observed: dict[str, dt.datetime] = {}
        """The latest snapshot time read per key: what stamps ``observed_at`` (DL-83)."""
        fetcher.contracts[self.name] = self.check

    def check(self, resource: str, key: str, payload: bytes) -> None:
        """Raise :class:`~fpl_dof.sources.errors.SourceContractError` if one capture breaks this
        source's contract, with the same parser conformance uses.

        The fetcher calls it on every new capture before it is kept, and ``bronze verify
        --contract`` on every capture already kept (ORC-10). One malformed row makes the whole
        capture malformed (DL-94). The default accepts everything: a source whose captures carry
        no contract of their own, such as a robots file, need not override it.
        """
        return None

    watched: ClassVar[tuple[tuple[str, str], ...]] = ()
    """The ``(resource, key)`` captures the change manifest compares across an ingest (ORC-02)."""

    def changes(
        self, resource: str, before: Snapshot, after: Snapshot, context: ChangeContext
    ) -> set[str]:
        """The change kinds (:data:`~fpl_dof.sources.changes.KINDS`) between two captures of one
        watched resource, the earlier first. Each capture carries its bytes and when it was taken,
        which a rule that counts time since a kick-off reads (LIVE-02's settle cap); ``context``
        carries the Open gameweek's kick-off window and the matchday rule's tunables. The default
        sees none: a source changes nothing that starts a run unless it says so."""
        return set()

    def note_observed(self, key: str, fetched: Fetched) -> None:
        """Remember when the bytes just read were captured, keeping the latest per key."""
        moment = fetched.snapshot.meta.fetched_at
        self.observed[key] = max(self.observed.get(key, moment), moment)

    def url_for(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def resource(self, name: str) -> Resource:
        for declared in self.resources:
            if declared.name == name:
                return declared
        raise KeyError(f"{self.name} declares no resource named {name!r}")

    def wants(self, name: str, request: IngestRequest) -> bool:
        """Whether ``name`` should be fetched under this request's cadence.

        Adapters guard their expensive resources with this rather than branching on
        ``request.fast_path_only`` themselves, so the cadence rule exists in exactly one place and
        a resource opts out by declaring ``fast_path=False`` — a fact about the resource, stated
        next to its TTL, rather than a condition buried in an ingest method.
        """
        return not request.fast_path_only or self.resource(name).fast_path

    def has_fast_path(self) -> bool:
        """Whether any of this source's resources belong on the frequent cadence at all.

        A source where nothing is fast — scrapers, odds, the historical archive — is skipped whole
        by the ingest stage rather than being built and then asked to fetch nothing.
        """
        return any(resource.fast_path for resource in self.resources)

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
