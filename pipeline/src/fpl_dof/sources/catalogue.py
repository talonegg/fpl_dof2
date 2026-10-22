"""What the data health page lists as a source, and how each one describes itself (T-003).

The adapter registry knows every source the pipeline can fetch (the football-data.co.uk odds and
the FPL archive are adapters now, DL-87), so the catalogue is the registry, each source a
:class:`SourceDescriptor`.

This module lives in ``sources/`` because it names sources, and only this package may (Invariant 1).
The publisher receives descriptors and renders them as data; it never branches on a key.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fpl_dof.config.models import SourcesConfig
from fpl_dof.sources.registry import is_enabled, known

LIVE = "live"
REFERENCE = "reference"
KINDS = (LIVE, REFERENCE)


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """One row of the data health page's Sources section, before this run's evidence is added."""

    key: str
    """The label the source is published under. A registered adapter's ``name``, or an external
    source's declared key. Opaque to everything downstream."""

    kind: str
    """``live`` or ``reference``."""

    label: str
    description: str

    enabled: bool
    """Whether configuration has this source switched on. External sources are always on: they are
    read by the prospective harness, which has no per-source switch."""

    registered: bool
    """True for a registry adapter, whose bronze snapshots are evidence that it was fetched."""

    not_configured: str | None = None
    """Set when the source is missing something it needs (a credential), with the reason."""

    disabled_reason: str | None = None
    note: str | None = None
    """The "Why" line for a reference source."""

    as_of: str | None = None
    """ISO date a fixed dataset is as of. Reference sources only."""


def _registered(config: SourcesConfig, environ: Mapping[str, str] | None) -> list[SourceDescriptor]:
    out: list[SourceDescriptor] = []
    for name, adapter_cls in sorted(known().items()):
        kind = adapter_cls.health_kind if adapter_cls.health_kind in KINDS else LIVE
        out.append(
            SourceDescriptor(
                key=name,
                kind=kind,
                label=adapter_cls.health_label or adapter_cls.summary,
                description=adapter_cls.health_description or adapter_cls.summary,
                enabled=is_enabled(name, adapter_cls, config),
                registered=True,
                not_configured=adapter_cls.configuration_problem(environ),
                disabled_reason=adapter_cls.health_disabled_reason or None,
                note=adapter_cls.health_note or None,
            )
        )
    return out


def describe(
    config: SourcesConfig, environ: Mapping[str, str] | None = None
) -> list[SourceDescriptor]:
    """Every source the page should list: the registry, by name.

    ``environ`` is only asked whether a credential is *present*; no value is ever carried out.
    """
    return _registered(config, environ)


__all__ = ["KINDS", "LIVE", "REFERENCE", "SourceDescriptor", "describe"]
