"""The change manifest: what moved between the bronze an ingest started from and the bronze it
left (ORC-02, DL-94 item 4).

CI restores the `data` branch before every ingest, so the latest capture of each watched resource
before the fetch is the one to compare with. Each source compares its own captures
(:meth:`SourceAdapter.changes`); what leaves this package is only the kinds, never a source name
(Invariant 1). There are no thresholds: any change of a kind starts a run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fpl_dof.sources.base import SourceAdapter, Window
from fpl_dof.sources.bronze import BronzeStore, Snapshot

#: Everything that starts a pipeline run: a price; a status or news line; a fixture's kick-off or
#: gameweek; a match of the Open gameweek priced for the first time.
KINDS: tuple[str, ...] = ("prices", "status", "fixtures", "odds")

Before = Mapping[tuple[str, str, str], Snapshot | None]


def before_ingest(bronze: BronzeStore, adapters: Sequence[SourceAdapter]) -> Before:
    """The latest capture of each watched resource, read before anything is fetched."""
    return {
        (adapter.name, resource, key): bronze.latest(adapter.name, resource, key)
        for adapter in adapters
        for resource, key in adapter.watched
    }


def changed_kinds(
    bronze: BronzeStore, adapters: Sequence[SourceAdapter], before: Before, window: Window
) -> list[str]:
    """The kinds that moved since ``before``, in :data:`KINDS` order.

    A resource with no earlier capture has nothing to compare with and moves nothing; one whose
    latest capture is the same bytes (a 304, a cache hit, a quarantined capture) moves nothing.
    """
    kinds: set[str] = set()
    for adapter in adapters:
        for resource, key in adapter.watched:
            old = before.get((adapter.name, resource, key))
            new = bronze.latest(adapter.name, resource, key)
            if old is None or new is None or new.meta.sha256 == old.meta.sha256:
                continue
            kinds |= adapter.changes(resource, old.read_bytes(), new.read_bytes(), window)
    return [kind for kind in KINDS if kind in kinds]


__all__ = ["KINDS", "Before", "before_ingest", "changed_kinds"]
