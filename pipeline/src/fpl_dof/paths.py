"""Where things live on disk.

The data root is resolved once, at config load, and every stage takes its directories from the
resulting :class:`DataLayout`. Nothing else in the codebase constructs a data path by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_ROOT_MARKERS = (".git", "CLAUDE.md")


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward from ``start`` looking for a repository marker.

    Returns ``None`` when nothing is found, which is the normal case for an installed package
    running outside a checkout. Callers must have a fallback.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate
    return None


def default_data_dir() -> Path:
    """The data root used when neither config nor environment names one."""
    root = find_repo_root()
    return (root / "data") if root is not None else (Path.cwd() / "data")


@dataclass(frozen=True, slots=True)
class DataLayout:
    """The four medallion tiers plus run metadata, rooted at a single directory."""

    root: Path

    @property
    def bronze(self) -> Path:
        """Raw, immutable source snapshots exactly as received."""
        return self.root / "bronze"

    @property
    def silver(self) -> Path:
        """Conformed canonical tables. Source-agnostic by construction."""
        return self.root / "silver"

    @property
    def gold(self) -> Path:
        """Decision-ready outputs: forecasts, squads, explanations."""
        return self.root / "gold"

    @property
    def web(self) -> Path:
        """The published web contract, versioned by subdirectory."""
        return self.root / "web"

    @property
    def runs(self) -> Path:
        """Run manifests, one directory per ``run_id``."""
        return self.root / "runs"

    def all_tiers(self) -> tuple[Path, ...]:
        return (self.bronze, self.silver, self.gold, self.web, self.runs)

    def ensure(self) -> None:
        """Create every tier directory. Idempotent."""
        for tier in self.all_tiers():
            tier.mkdir(parents=True, exist_ok=True)
