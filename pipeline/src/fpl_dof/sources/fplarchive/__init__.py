"""Historical per-gameweek data, from the community mirror.

Registered like any other source and subject to Invariant 1 in full. See
:mod:`fpl_dof.sources.fplarchive.adapter` for why this source has to exist at all.
"""

from fpl_dof.sources.fplarchive.adapter import ArchiveAdapter

__all__ = ["ArchiveAdapter"]
