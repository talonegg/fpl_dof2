"""The data health payload — E7-S6, FR-33, NFR-07, DL-41.

Every number on the health page already existed before this module did. The run manifest records
stage outcomes, timings and per-source metrics (DP-11); ``quality.json`` records the full gate
report; the bronze store's snapshot sidecars record when each source was last captured. None of it
was published, and the browser reads published static artefacts and nothing else (Invariant 8). So
this module is a **seam, not a measurement**.

That distinction is load-bearing. A health page that computed its own view of health would be a
second opinion, and a second opinion can disagree with the manifest. The whole value of the page is
that it *is* the manifest, rendered — so everything here is assembly, and anything it cannot
assemble is published as null rather than as a plausible-looking default (DP-15).

**No source is named here.** Source labels are read out of the manifest's own metric keys, which
``stages/ingest.py`` writes by asking the registry, and out of the source catalogue
(``sources/catalogue.py``), which the publish stage hands in: every registered adapter plus the
external sources the frozen harness reads, each with its own label, description and reason text.
They travel to the browser as opaque strings. Nothing in this module, and nothing in ``web/``,
branches on one (Invariant 1, DP-01).

Pure: no I/O, no clock, no config loading. The stage reads the files and hands the contents in
(DP-03), which is also what makes every state below testable without a filesystem.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from fpl_dof.obs.manifest import RunManifest, StageRecord
from fpl_dof.sources import LIVE, REFERENCE, SourceDescriptor

#: The stage whose metrics carry per-source fetch counts.
INGEST_STAGE = "ingest"
#: The stage whose metrics carry conformed row counts, and a second chance to record a degradation.
TRANSFORM_STAGE = "transform"
#: The stage whose metrics carry the solve time.
OPTIMISE_STAGE = "optimise"
#: The stage whose metrics carry the price-dependence diagnostic.
FORECAST_STAGE = "forecast"

#: Metric key prefix ``stages/ingest.py`` and ``stages/transform.py`` write a degradation under.
DEGRADED_PREFIX = "degraded."
#: Metric key suffixes that identify a key as belonging to a source rather than to the stage.
NETWORK_CALLS_SUFFIX = ".network_calls"
CACHE_HITS_SUFFIX = ".cache_hits"
#: Metric key prefix ``stages/transform.py`` writes conformed row counts under.
ROWS_PREFIX = "rows."

#: Where :func:`build_metrics_history` got its series. The shape is the contract; this is not
#: (DL-41) — a dedicated metrics store can replace the reader without a schema or app change.
MANIFEST_SERIES = "run-manifests"


def iso(moment: dt.datetime | None) -> str | None:
    """UTC, ``Z``-suffixed, or ``None``. The only timestamp format that crosses the seam (DL-11)."""
    if moment is None:
        return None
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _stage(manifest: RunManifest, name: str) -> StageRecord | None:
    return manifest.stage(name)


def _metrics(manifest: RunManifest, stage: str) -> dict[str, float | int | str]:
    record = _stage(manifest, stage)
    return dict(record.metrics) if record is not None else {}


def _as_int(value: object) -> int | None:
    """Manifest metrics are ``float | int | str``. Only the numeric ones become counts."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


# --- sources --------------------------------------------------------------------------------


def source_labels(manifest: RunManifest, observed: Mapping[str, dt.datetime]) -> list[str]:
    """Every source label this run knows about, from the manifest and from what is on disk.

    Three ways a label appears, and they are not the same thing:

    * it reported a fetch, so ``ingest`` recorded a ``<label>.network_calls`` metric;
    * it failed, so a stage recorded ``degraded.<label>``;
    * it has snapshots in bronze but this run recorded nothing about it — which is *not* the same
      as healthy, and must not be shown as healthy.

    A source is identified by ``.network_calls`` rather than by "any dotted key", because
    ``rows.player`` and ``resolved.<source>`` are dotted too and neither names a source in the
    position this needs.
    """
    labels: set[str] = set(observed)
    for stage in (INGEST_STAGE, TRANSFORM_STAGE):
        for key in _metrics(manifest, stage):
            if key.startswith(DEGRADED_PREFIX):
                labels.add(key.removeprefix(DEGRADED_PREFIX))
            elif key.endswith(NETWORK_CALLS_SUFFIX):
                labels.add(key[: -len(NETWORK_CALLS_SUFFIX)])
    return sorted(labels)


def _degradation(manifest: RunManifest, label: str) -> tuple[str, str] | None:
    """``(stage, detail)`` for the first stage that recorded this source as degraded."""
    for stage in (INGEST_STAGE, TRANSFORM_STAGE):
        detail = _metrics(manifest, stage).get(f"{DEGRADED_PREFIX}{label}")
        if detail is not None:
            return stage, str(detail)
    return None


def _resources(manifest: RunManifest, label: str) -> dict[str, int]:
    """Per-resource counts this source reported, minus the two book-keeping metrics."""
    prefix = f"{label}."
    resources: dict[str, int] = {}
    for key, value in _metrics(manifest, INGEST_STAGE).items():
        if not key.startswith(prefix):
            continue
        if key.endswith(NETWORK_CALLS_SUFFIX) or key.endswith(CACHE_HITS_SUFFIX):
            continue
        count = _as_int(value)
        if count is not None:
            resources[key.removeprefix(prefix)] = count
    return resources


#: Live rows first; within them, rows the run depends on, then not set up, then switched off.
_GROUP_ORDER = {
    "ok": 0,
    "stale": 0,
    "degraded": 0,
    "unknown": 0,
    "not_configured": 1,
    "disabled": 2,
}

NO_ACTIVITY = "this run recorded no activity for this source"


def _parse_time(value: object) -> dt.datetime | None:
    """A record timestamp (ISO, or pandas' ``2026-10-16 22:18:13+00:00``) as aware UTC."""
    if not isinstance(value, str) or not value or value in {"NaT", "None"}:
        return None
    try:
        moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def _age(generated_at: dt.datetime, moment: dt.datetime | None) -> float | None:
    if moment is None:
        return None
    return round(max(0.0, (generated_at - moment).total_seconds()), 1)


def _entry(
    key: str,
    status: str,
    detail: str | None,
    *,
    generated_at: dt.datetime,
    descriptor: SourceDescriptor | None = None,
    stage: str | None = None,
    moment: dt.datetime | None = None,
    resources: Mapping[str, int] | None = None,
    network_calls: int | None = None,
    cache_hits: int | None = None,
    check: str | None = None,
    checked_at: dt.datetime | None = None,
    quarantined: int = 0,
) -> dict[str, Any]:
    reference = descriptor is not None and descriptor.kind == REFERENCE
    return {
        "source": key,
        "kind": descriptor.kind if descriptor is not None else LIVE,
        "label": descriptor.label if descriptor is not None else None,
        "description": descriptor.description if descriptor is not None else None,
        "status": status,
        "detail": detail,
        "degraded_at_stage": stage,
        "observed_at": iso(moment),
        # A reference dataset has no freshness age: it is fixed, and an age would read as a feed
        # that has stopped updating. It carries an as-of date instead.
        "age_seconds": None if reference else _age(generated_at, moment),
        "as_of": descriptor.as_of if descriptor is not None else None,
        "check": check,
        "checked_at": iso(checked_at),
        "resources": dict(resources or {}),
        "network_calls": network_calls,
        "cache_hits": cache_hits,
        "quarantined": quarantined,
    }


def _reference_entry(
    descriptor: SourceDescriptor,
    degradation: tuple[str, str] | None,
    generated_at: dt.datetime,
    quarantined: int = 0,
) -> dict[str, Any]:
    """Fixed data: an as-of date and, where the harness pins it, a file check.

    ``status`` is ``ok`` unless something is known to be wrong with it (a failed file check, or a
    stage that recorded it degraded). The page shows such a row as *Reference*, not as *OK*.
    """
    status, detail, stage = "ok", descriptor.note, None
    if degradation is not None:
        status, stage, detail = "degraded", degradation[0], degradation[1]
    return _entry(
        descriptor.key,
        status,
        detail,
        generated_at=generated_at,
        descriptor=descriptor,
        stage=stage,
        quarantined=quarantined,
    )


def build_sources(
    *,
    manifest: RunManifest,
    observed: Mapping[str, dt.datetime],
    generated_at: dt.datetime,
    catalogue: Sequence[SourceDescriptor] = (),
    stale_after_seconds: float | None = None,
    quarantined: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Per-source status and freshness, for every catalogued source and anything else seen.

    Freshness is ``generated_at`` minus the source's newest snapshot time, computed here rather than
    in the browser. A published age is the age at publication; an age the browser computes keeps
    growing while a cached page sits open, which would make a stale artefact look like a stalled
    pipeline (DP-09).

    Evidence, strongest first, and never "no news" read as good news:

    * this run's own ingest recorded a degradation, or real activity (a request or a cache read);
    * the source is switched off by configuration → ``disabled``, with its reason;
    * it is missing a credential and has never been captured → ``not_configured``;
    * a registered source with a snapshot no older than ``stale_after_seconds`` → ``ok``, said to
      come from a scheduled ingest. A snapshot is only written after a successful fetch, so this is
      evidence of a working feed even when the publishing run did not fetch (the published run has
      no ingest stage; fetching is the ingest workflows' job). Older than that → ``stale``;
    * otherwise ``unknown``.

    A run that made zero requests and read nothing from cache has done nothing, so 0/0 is never
    ``ok``. A label that is not in the catalogue keeps the original rule: ``ok`` only on this run's
    own report, else ``unknown``.

    ``quarantined`` counts each source's captures held in quarantine for breaking its contract
    (ORC-10). It does not change the status: the run used the last valid capture, whose age the
    status already judges.
    """
    held = quarantined or {}
    ingest = _metrics(manifest, INGEST_STAGE)
    described = {descriptor.key: descriptor for descriptor in catalogue}
    keys = [descriptor.key for descriptor in catalogue]
    keys += [label for label in source_labels(manifest, observed) if label not in described]
    entries: list[dict[str, Any]] = []

    for label in keys:
        descriptor = described.get(label)
        degradation = _degradation(manifest, label)
        network_calls = _as_int(ingest.get(f"{label}{NETWORK_CALLS_SUFFIX}"))
        cache_hits = _as_int(ingest.get(f"{label}{CACHE_HITS_SUFFIX}"))
        resources = _resources(manifest, label)
        active = bool(network_calls or cache_hits or any(resources.values()))
        moment = observed.get(label)

        if descriptor is not None and descriptor.kind == REFERENCE:
            entries.append(
                _reference_entry(descriptor, degradation, generated_at, held.get(label, 0))
            )
            continue
        if descriptor is not None and not descriptor.enabled:
            status, detail, stage = "disabled", descriptor.disabled_reason, None
        elif degradation is not None:
            status, stage, detail = "degraded", degradation[0], degradation[1]
        elif active:
            status, stage, detail = "ok", None, None
        elif descriptor is not None and descriptor.not_configured and moment is None:
            status, stage, detail = "not_configured", None, descriptor.not_configured
        elif descriptor is not None and descriptor.registered and moment is not None:
            age = _age(generated_at, moment) or 0.0
            stage = None
            if stale_after_seconds is not None and age > stale_after_seconds:
                status = "stale"
                detail = (
                    f"Its newest data is {age / 3600:.0f} h old, and the limit is "
                    f"{stale_after_seconds / 3600:.0f} h."
                )
            else:
                status = "ok"
                detail = (
                    "Fetched by a scheduled ingest. This run used that saved data rather than "
                    "fetching it again."
                )
        else:
            status, stage, detail = "unknown", None, NO_ACTIVITY

        entries.append(
            _entry(
                label,
                status,
                detail,
                generated_at=generated_at,
                descriptor=descriptor,
                stage=stage,
                moment=moment,
                resources=resources,
                network_calls=network_calls,
                cache_hits=cache_hits,
                quarantined=held.get(label, 0),
            )
        )

    order = {key: index for index, key in enumerate(keys)}
    entries.sort(
        key=lambda e: (
            e["kind"] != LIVE,
            _GROUP_ORDER.get(e["status"], 0) if e["kind"] == LIVE else 0,
            order[e["source"]],
        )
    )
    return entries


# --- the run --------------------------------------------------------------------------------


def build_run(manifest: RunManifest) -> dict[str, Any]:
    """The manifest excerpt: identity, outcome, and every stage with its timing and its error.

    ``status`` is null for the run that writes this file — it is still in flight at publish time,
    and claiming success before the run has succeeded would be the one lie this page cannot afford.
    """
    duration = None
    if manifest.finished_at is not None:
        duration = round((manifest.finished_at - manifest.started_at).total_seconds(), 3)

    return {
        "run_id": manifest.run_id,
        "git_sha": manifest.git_sha,
        "git_dirty": manifest.git_dirty,
        "started_at": iso(manifest.started_at),
        "finished_at": iso(manifest.finished_at),
        "status": manifest.status.value if manifest.status is not None else None,
        "duration_seconds": duration,
        "stages": [
            {
                "name": record.name,
                "status": record.status.value,
                "started_at": iso(record.started_at),
                "finished_at": iso(record.finished_at),
                "duration_seconds": round(record.duration_seconds, 3),
                "error": record.error,
            }
            for record in manifest.stages
        ],
    }


# --- the gate report ------------------------------------------------------------------------


def build_gates(report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The gate report, narrowed to the fields the contract publishes.

    ``None`` in, ``None`` out. A missing report is published as missing, never as a pass: a gate
    that never ran has proved nothing, and an "all clear" assembled from an absent file is precisely
    the invisible wrongness the gates exist to catch (DP-13).

    ``observed`` is deliberately dropped. It is free-form per gate, it is the largest part of the
    report, and every gate already carries a ``message`` written to be read. The full report stays
    on disk in gold for anyone who needs the raw observation.
    """
    if report is None:
        return None

    counts = report.get("counts") or {}
    results = report.get("results") or []
    return {
        "passed": bool(report.get("passed", False)),
        "counts": {
            "passed": int(counts.get("passed", 0)),
            "failed": int(counts.get("failed", 0)),
            "skipped": int(counts.get("skipped", 0)),
        },
        "blocking": [str(name) for name in (report.get("blocking") or [])],
        "results": [
            {
                "gate": str(result.get("gate", "")),
                "class": str(result.get("class", "")),
                "severity": str(result.get("severity", "")),
                "outcome": str(result.get("outcome", "")),
                "message": str(result.get("message", "")),
                "requirement": str(result.get("requirement", "")),
            }
            for result in results
        ],
    }


# --- the rolling series ---------------------------------------------------------------------


def metrics_point(manifest: RunManifest) -> dict[str, Any]:
    """One run reduced to the handful of measurements worth watching move.

    Every field but the id is nullable, and a run that failed before a stage ran publishes null for
    that stage's measurement. A gap must draw as a gap: a zero solve time reads as a fast solve
    rather than as no solve at all, which is the chart equivalent of a silent failure.
    """
    transform = _metrics(manifest, TRANSFORM_STAGE)
    rows = {
        key.removeprefix(ROWS_PREFIX): count
        for key, value in transform.items()
        if key.startswith(ROWS_PREFIX) and (count := _as_int(value)) is not None
    }

    duration = None
    if manifest.finished_at is not None:
        duration = round((manifest.finished_at - manifest.started_at).total_seconds(), 3)

    quality = _metrics(manifest, "quality")
    return {
        "run_id": manifest.run_id,
        "finished_at": iso(manifest.finished_at),
        "status": manifest.status.value if manifest.status is not None else None,
        "duration_seconds": duration,
        "solve_seconds": _as_float(_metrics(manifest, OPTIMISE_STAGE).get("solve_seconds")),
        "rows_total": sum(rows.values()) if rows else None,
        "rows": rows,
        # Named for what it is. This is R-15's check that the forecast is not a repricing of the
        # price list — high is bad — and it is emphatically not a measure of skill. Skill is
        # measured against a baseline in the backtest and reported in the model card (DP-12).
        "r_squared_on_price": _as_float(
            _metrics(manifest, FORECAST_STAGE).get("r_squared_on_price")
        ),
        "gates_failed": _as_int(quality.get("gates.failed")),
    }


def build_metrics_history(
    manifests: Sequence[RunManifest],
    *,
    limit: int,
    derived_from: str = MANIFEST_SERIES,
) -> dict[str, Any] | None:
    """The rolling series, oldest first, or ``None`` when there is nothing to plot.

    ``None`` rather than an empty list, so the page can say "no history yet" instead of drawing an
    empty axis that looks like a measurement of zero.
    """
    # `limit <= 0` checked explicitly, not left to the slice: `xs[-0:]` is the whole list, not an
    # empty one, so a configured 0 would have published every run it was handed.
    if not manifests or limit <= 0:
        return None
    ordered = sorted(manifests, key=lambda m: (m.started_at, m.run_id))[-limit:]
    return {"derived_from": derived_from, "runs": [metrics_point(m) for m in ordered]}


# --- the whole payload ----------------------------------------------------------------------


def build_health(
    *,
    manifest: RunManifest,
    gate_report: Mapping[str, Any] | None,
    observed: Mapping[str, dt.datetime],
    recent: Sequence[RunManifest],
    generated_at: dt.datetime,
    history_limit: int,
    contract_version: int,
    catalogue: Sequence[SourceDescriptor] = (),
    stale_after_seconds: float | None = None,
    quarantined: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """The whole ``health.json`` payload. Pure (DP-03)."""
    return {
        "contract_version": contract_version,
        "generated_at": iso(generated_at),
        "run": build_run(manifest),
        "sources": build_sources(
            manifest=manifest,
            observed=observed,
            generated_at=generated_at,
            catalogue=catalogue,
            stale_after_seconds=stale_after_seconds,
            quarantined=quarantined,
        ),
        "gates": build_gates(gate_report),
        "metrics_history": build_metrics_history(recent, limit=history_limit),
    }


__all__ = [
    "MANIFEST_SERIES",
    "build_gates",
    "build_health",
    "build_metrics_history",
    "build_run",
    "build_sources",
    "metrics_point",
    "source_labels",
]
