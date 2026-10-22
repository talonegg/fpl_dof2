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
import zlib
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
    retain: bool = False
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


def _write_sidecar(payload: Path, meta: SnapshotMeta) -> None:
    """Write the lineage record whole or not at all (REM-10).

    :meth:`BronzeStore.touch` rewrites an existing snapshot's sidecar; a write torn half-way would
    leave a good payload with unreadable lineage. A rename within one directory is atomic.
    """
    sidecar = payload.with_name(payload.name + META_SUFFIX)
    partial = sidecar.with_name(sidecar.name + ".partial")
    partial.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    partial.replace(sidecar)


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
    quarantined: list[Path] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.failed == 0 and len(self.issues) == 0

    @property
    def unresolved(self) -> list[IntegrityIssue]:
        """Issues still in bronze: everything not quarantined. Non-empty fails the command."""
        return [issue for issue in self.issues if issue.path not in self.quarantined]


class BronzeStore:
    """Writes and finds snapshots. Knows nothing about HTTP or about any particular source."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.quarantine_root = root.parent / "quarantine" / root.name
        """Where :meth:`verify` moves what it cannot trust, mirroring bronze's own layout."""

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
        retain: bool = False,
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
            retain=retain,
            etag=etag,
            last_modified=last_modified,
        )
        _write_sidecar(path, meta)
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
        _write_sidecar(path, meta)
        return Snapshot(path=path, meta=meta)

    def latest(
        self,
        source: str,
        resource: str,
        key: str,
        *,
        suffix: str = SNAPSHOT_SUFFIX,
        as_of: dt.datetime | None = None,
    ) -> Snapshot | None:
        """The most recent snapshot for this key fetched no later than ``as_of``, or ``None``.

        Filenames embed a sortable UTC timestamp, so lexical maximum is chronological maximum.
        ``as_of`` keeps a run evaluated in the past from reading what was fetched after it
        (Invariant 5).
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
            meta = SnapshotMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
            if as_of is not None and meta.fetched_at > as_of:
                continue
            return Snapshot(path=path, meta=meta)
        return None

    def verify(self, *, quarantine: bool = False) -> VerifyReport:
        """Inspect the Bronze store for corruption, torn writes, and orphaned files (PIPE-11).

        ``quarantine`` moves each bad file to :attr:`quarantine_root`, beside bronze rather than in
        it: out of every read, but kept as evidence of what went wrong (REM-10).
        """
        report = VerifyReport()
        if not self.root.is_dir():
            return report

        def flag(path: Path, kind: str, detail: str, *files: Path) -> None:
            report.issues.append(IntegrityIssue(path=path, kind=kind, detail=detail))
            report.failed += 1
            if quarantine and files:
                for bad in files:
                    if bad.exists():
                        target = self.quarantine_root / bad.relative_to(self.root)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        bad.replace(target)
                report.quarantined.extend(files)

        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        for source_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            for resource_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
                for day_dir in sorted(p for p in resource_dir.iterdir() if p.is_dir()):
                    if not date_pattern.match(day_dir.name):
                        flag(
                            day_dir,
                            "invalid_directory",
                            f"directory {day_dir.name} is not in YYYY-MM-DD format",
                        )

                    all_files = [f for f in day_dir.iterdir() if f.is_file()]
                    meta_files = {f for f in all_files if f.name.endswith(META_SUFFIX)}
                    payload_files = {f for f in all_files if not f.name.endswith(META_SUFFIX)}

                    for meta_file in sorted(meta_files):
                        payload_path = meta_file.with_name(meta_file.name[: -len(META_SUFFIX)])
                        if payload_path not in payload_files:
                            flag(
                                meta_file,
                                "missing_payload",
                                "metadata sidecar has no accompanying payload file",
                                meta_file,
                            )

                    for payload in sorted(payload_files):
                        meta_path = payload.with_name(payload.name + META_SUFFIX)
                        if meta_path not in meta_files:
                            flag(
                                payload,
                                "missing_metadata",
                                "payload has no accompanying .meta.json sidecar",
                                payload,
                            )
                            continue

                        report.total_snapshots += 1
                        try:
                            meta = SnapshotMeta.model_validate_json(
                                meta_path.read_text(encoding="utf-8")
                            )
                        except (OSError, ValueError) as exc:
                            flag(payload, "corrupt_metadata", str(exc), payload, meta_path)
                            continue
                        try:
                            with gzip.open(payload, "rb") as gz:
                                uncompressed = gz.read()
                        except (OSError, EOFError, zlib.error) as exc:
                            # zlib.error is not an OSError: a damaged deflate stream raises it.
                            flag(
                                payload,
                                "corrupt_gzip",
                                f"decompression failed: {exc}",
                                payload,
                                meta_path,
                            )
                            continue
                        actual_sha = hashlib.sha256(uncompressed).hexdigest()
                        if actual_sha != meta.sha256:
                            flag(
                                payload,
                                "checksum_mismatch",
                                f"checksum mismatch: expected {meta.sha256}, got {actual_sha}",
                                payload,
                                meta_path,
                            )
                            continue
                        report.passed += 1
        return report
