"""Bronze snapshot store.

Bronze is immutable, gzipped, exactly as received, and doubles as the fetch cache: re-running
inside a resource's TTL reads the most recent snapshot and makes no network call. There is no
second cache tier to fall out of sync with what was actually ingested.

Layout::

    bronze/<source>/<resource>/<YYYY-MM-DD>/<key>__<UTC timestamp>.json.gz
    bronze/<source>/<resource>/<YYYY-MM-DD>/<key>__<UTC timestamp>.json.gz.meta.json

The sidecar is the lineage record: where the bytes came from, when, what the response said, and
the checksum of what was written.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from fpl_dof.obs.manifest import utcnow

SNAPSHOT_SUFFIX = ".json.gz"
"""Default snapshot extension. Overridable per call, because not every source speaks JSON — the
archive source (DL-19) serves CSV, and a file named ``.json.gz`` that contains CSV is a small lie
that costs someone an afternoon later."""

META_SUFFIX = ".meta.json"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_key(key: str) -> str:
    """Make an arbitrary resource key safe as a single filename component."""
    cleaned = _UNSAFE.sub("-", key).strip("-")
    return cleaned or "_"


class SnapshotMeta(BaseModel):
    """The lineage sidecar written next to every snapshot."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_version: str
    resource: str
    key: str
    url: str
    http_status: int
    fetched_at: dt.datetime
    sha256: str
    bytes: int
    content_encoding: str | None = None
    run_id: str | None = None
    immutable: bool = False
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A snapshot on disk, plus its lineage."""

    path: Path
    meta: SnapshotMeta

    def read_bytes(self) -> bytes:
        with gzip.open(self.path, "rb") as handle:
            return handle.read()

    def age_seconds(self, now: dt.datetime | None = None) -> float:
        return ((now or utcnow()) - self.meta.fetched_at).total_seconds()


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    path: Path
    kind: str
    detail: str


@dataclass(slots=True)
class VerifyReport:
    total_snapshots: int = 0
    passed: int = 0
    failed: int = 0
    issues: list[IntegrityIssue] = field(default_factory=list)
    pruned: list[Path] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.failed == 0 and len(self.issues) == 0


class BronzeStore:
    """Writes and finds snapshots. Knows nothing about HTTP or about any particular source."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resource_dir(self, source: str, resource: str) -> Path:
        return self.root / source / resource

    def write(
        self,
        payload: bytes,
        *,
        source: str,
        source_version: str,
        resource: str,
        key: str,
        url: str,
        http_status: int,
        run_id: str | None = None,
        content_encoding: str | None = None,
        now: dt.datetime | None = None,
        suffix: str = SNAPSHOT_SUFFIX,
        immutable: bool = False,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> Snapshot:
        moment = now or utcnow()
        directory = self.resource_dir(source, resource) / moment.strftime("%Y-%m-%d")
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{safe_key(key)}__{moment.strftime(_TIMESTAMP_FORMAT)}"
        path = directory / f"{stem}{suffix}"

        # mtime=0 and an empty embedded filename, so identical bytes produce byte-identical files.
        # gzip stores both the modification time and the original filename in its header; leaving
        # either in place would make every snapshot differ from every other one and defeat
        # content-addressed comparison between runs (DP-11). The real timestamp lives in the
        # sidecar, where it belongs.
        with (
            path.open("wb") as raw,
            gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as handle,
        ):
            handle.write(payload)

        meta = SnapshotMeta(
            source=source,
            source_version=source_version,
            resource=resource,
            key=key,
            url=url,
            http_status=http_status,
            fetched_at=moment,
            sha256=hashlib.sha256(payload).hexdigest(),
            bytes=len(payload),
            content_encoding=content_encoding,
            run_id=run_id,
            immutable=immutable,
            etag=etag,
            last_modified=last_modified,
        )
        path.with_name(path.name + META_SUFFIX).write_text(
            meta.model_dump_json(indent=2), encoding="utf-8"
        )
        return Snapshot(path=path, meta=meta)

    def touch(
        self,
        snapshot: Snapshot,
        *,
        now: dt.datetime | None = None,
        run_id: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> Snapshot:
        """Revalidate an existing snapshot without duplicating payload bytes (PIPE-07).

        Used when upstream returns HTTP 304 Not Modified. If the verification happens on a
        different UTC calendar day, hardlinks (or copies) the payload to today's date directory
        so date-based retention and globbing recognise the snapshot at the tip.
        """
        moment = now or utcnow()
        day_dir = snapshot.path.parent.parent / moment.strftime("%Y-%m-%d")
        if day_dir != snapshot.path.parent:
            day_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{safe_key(snapshot.meta.key)}__{moment.strftime(_TIMESTAMP_FORMAT)}"
            idx = snapshot.path.name.find(".")
            ext = snapshot.path.name[idx:] if idx != -1 else SNAPSHOT_SUFFIX
            new_path = day_dir / f"{stem}{ext}"
            try:
                os.link(snapshot.path, new_path)
            except OSError:
                shutil.copy2(snapshot.path, new_path)
            path = new_path
        else:
            path = snapshot.path

        meta = snapshot.meta.model_copy(
            update={
                "fetched_at": moment,
                "run_id": run_id or snapshot.meta.run_id,
                "etag": etag or snapshot.meta.etag,
                "last_modified": last_modified or snapshot.meta.last_modified,
            }
        )
        meta_path = path.with_name(path.name + META_SUFFIX)
        meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
        return Snapshot(path=path, meta=meta)

    def latest(
        self, source: str, resource: str, key: str, *, suffix: str = SNAPSHOT_SUFFIX
    ) -> Snapshot | None:
        """The most recent snapshot for this key, or ``None``.

        Filenames embed a sortable UTC timestamp, so lexical maximum is chronological maximum.
        """
        directory = self.resource_dir(source, resource)
        if not directory.is_dir():
            return None
        pattern = f"*/{safe_key(key)}__*{suffix}"
        candidates = sorted(directory.glob(pattern))
        for path in reversed(candidates):
            meta_path = path.with_name(path.name + META_SUFFIX)
            if not meta_path.exists():
                continue  # a torn write; skip it rather than trust it
            return Snapshot(
                path=path,
                meta=SnapshotMeta.model_validate_json(meta_path.read_text(encoding="utf-8")),
            )
        return None

    def verify(self, *, prune_orphans: bool = False) -> VerifyReport:
        """Inspect the Bronze store for corruption, torn writes, and orphaned files (PIPE-11)."""
        report = VerifyReport()
        if not self.root.is_dir():
            return report

        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        for source_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            for resource_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
                for day_dir in sorted(p for p in resource_dir.iterdir() if p.is_dir()):
                    if not date_pattern.match(day_dir.name):
                        report.issues.append(
                            IntegrityIssue(
                                path=day_dir,
                                kind="invalid_directory",
                                detail=f"directory {day_dir.name} is not in YYYY-MM-DD format",
                            )
                        )
                        report.failed += 1

                    all_files = [f for f in day_dir.iterdir() if f.is_file()]
                    meta_files = {f for f in all_files if f.name.endswith(META_SUFFIX)}
                    payload_files = {f for f in all_files if not f.name.endswith(META_SUFFIX)}

                    for payload in sorted(payload_files):
                        meta_path = payload.with_name(payload.name + META_SUFFIX)
                        if meta_path not in meta_files:
                            report.issues.append(
                                IntegrityIssue(
                                    path=payload,
                                    kind="missing_metadata",
                                    detail="payload has no accompanying .meta.json sidecar",
                                )
                            )
                            report.failed += 1
                            if prune_orphans:
                                payload.unlink(missing_ok=True)
                                report.pruned.append(payload)

                    for meta_file in sorted(meta_files):
                        payload_path = meta_file.with_name(meta_file.name[: -len(META_SUFFIX)])
                        if payload_path not in payload_files:
                            report.issues.append(
                                IntegrityIssue(
                                    path=meta_file,
                                    kind="missing_payload",
                                    detail="metadata sidecar has no accompanying payload file",
                                )
                            )
                            report.failed += 1
                            if prune_orphans:
                                meta_file.unlink(missing_ok=True)
                                report.pruned.append(meta_file)

                    for payload in sorted(payload_files):
                        meta_path = payload.with_name(payload.name + META_SUFFIX)
                        if meta_path not in meta_files:
                            continue

                        report.total_snapshots += 1
                        try:
                            meta = SnapshotMeta.model_validate_json(
                                meta_path.read_text(encoding="utf-8")
                            )
                            with gzip.open(payload, "rb") as gz:
                                uncompressed = gz.read()
                            actual_sha = hashlib.sha256(uncompressed).hexdigest()
                            if actual_sha != meta.sha256:
                                raise ValueError(
                                    f"checksum mismatch: expected {meta.sha256}, got {actual_sha}"
                                )
                            report.passed += 1
                        except (gzip.BadGzipFile, EOFError, OSError) as exc:
                            report.failed += 1
                            report.issues.append(
                                IntegrityIssue(
                                    path=payload,
                                    kind="corrupt_gzip",
                                    detail=f"decompression failed: {exc}",
                                )
                            )
                            if prune_orphans:
                                payload.unlink(missing_ok=True)
                                meta_path.unlink(missing_ok=True)
                                report.pruned.extend([payload, meta_path])
                        except Exception as exc:
                            report.failed += 1
                            kind = (
                                "checksum_mismatch"
                                if "checksum mismatch" in str(exc)
                                else "corrupt_metadata"
                            )
                            report.issues.append(
                                IntegrityIssue(
                                    path=payload,
                                    kind=kind,
                                    detail=str(exc),
                                )
                            )
                            if prune_orphans:
                                payload.unlink(missing_ok=True)
                                meta_path.unlink(missing_ok=True)
                                report.pruned.extend([payload, meta_path])
        return report
