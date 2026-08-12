"""Adapter registry.

The only place that knows which sources exist. Adapter classes register themselves at import
time; the ingest stage asks the registry for enabled adapters and never names one.

Enablement is a generic ``{source_name: {...}}`` map in configuration, not a set of named fields,
so admitting a source is a config edit and a new module — never a change to a downstream module.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from fpl_dof.config.models import SourcesConfig
from fpl_dof.obs.logging import get_logger
from fpl_dof.sources.base import SourceAdapter
from fpl_dof.sources.fetch import Fetcher

log = get_logger(__name__)

_REGISTRY: dict[str, type[SourceAdapter]] = {}
_DISCOVERED = False


class DuplicateSourceError(ValueError):
    """Two adapters claimed the same name."""


def register(adapter_cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Register an adapter class. Usable as a decorator."""
    name = adapter_cls.name
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not adapter_cls:
        raise DuplicateSourceError(f"source name {name!r} is already registered to {existing!r}")
    _REGISTRY[name] = adapter_cls
    return adapter_cls


def discover() -> None:
    """Import every submodule of this package so registrations happen. Idempotent."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    import fpl_dof.sources as package

    for module in pkgutil.walk_packages(package.__path__, prefix=f"{package.__name__}."):
        importlib.import_module(module.name)
    _DISCOVERED = True


def known() -> dict[str, type[SourceAdapter]]:
    discover()
    return dict(_REGISTRY)


def is_enabled(name: str, adapter_cls: type[SourceAdapter], config: SourcesConfig) -> bool:
    override = config.overrides.get(name)
    if override is not None and override.enabled is not None:
        return override.enabled
    return adapter_cls.enabled_by_default


def build(config: SourcesConfig, fetcher: Fetcher) -> list[SourceAdapter]:
    """Instantiate every enabled adapter, in a stable order."""
    unknown = set(config.overrides) - set(known())
    if unknown:
        raise KeyError(
            f"configuration names unknown source(s): {', '.join(sorted(unknown))}; "
            f"known sources are {', '.join(sorted(known()))}"
        )
    adapters = [
        adapter_cls(fetcher, config.overrides.get(name))
        for name, adapter_cls in sorted(known().items())
        if is_enabled(name, adapter_cls, config)
    ]
    log.info(
        "sources.built",
        extra={"enabled": [a.name for a in adapters], "known": sorted(known())},
    )
    return adapters


@contextmanager
def temporary_registry(adapters: Iterable[type[SourceAdapter]]) -> Iterator[None]:
    """Replace the registry contents for the duration of the block, then restore them.

    Tests only. Restoring matters: the registry is process-global, and a test that leaves a stub
    adapter behind silently changes what every later test ingests.
    """
    global _DISCOVERED
    discover()
    saved, saved_discovered = dict(_REGISTRY), _DISCOVERED
    _REGISTRY.clear()
    for adapter_cls in adapters:
        _REGISTRY[adapter_cls.name] = adapter_cls
    _DISCOVERED = True
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)
        _DISCOVERED = saved_discovered
