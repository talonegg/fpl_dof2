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
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from fpl_dof.obs.manifest import utcnow

SNAPSHOT_SUFFIX = ".json.gz"
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
    ) -> Snapshot:
        moment = now or utcnow()
        directory = self.resource_dir(source, resource) / moment.strftime("%Y-%m-%d")
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{safe_key(key)}__{moment.strftime(_TIMESTAMP_FORMAT)}"
        path = directory / f"{stem}{SNAPSHOT_SUFFIX}"

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
        )
        path.with_name(path.name + META_SUFFIX).write_text(
            meta.model_dump_json(indent=2), encoding="utf-8"
        )
        return Snapshot(path=path, meta=meta)

    def latest(self, source: str, resource: str, key: str) -> Snapshot | None:
        """The most recent snapshot for this key, or ``None``.

        Filenames embed a sortable UTC timestamp, so lexical maximum is chronological maximum.
        """
        directory = self.resource_dir(source, resource)
        if not directory.is_dir():
            return None
        pattern = f"*/{safe_key(key)}__*{SNAPSHOT_SUFFIX}"
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
