"""The run manifest.

Every run records what it was given, what it did, and what it produced — including a checksum for
each artefact. This is the primitive DP-11 (reproducibility) and DP-09 (provenance) rest on, and it
is deliberately built in E0-S1 rather than retrofitted, because a manifest added later never covers
the runs you most want to explain.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import uuid
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_SCHEMA_VERSION = 1
_CHECKSUM_CHUNK_BYTES = 1 << 20


def utcnow() -> dt.datetime:
    """The only clock this codebase reads. UTC, always (DL-11)."""
    return dt.datetime.now(tz=dt.UTC)


def new_run_id(now: dt.datetime | None = None) -> str:
    """Sortable, unique, and readable at a glance: ``20260810T041530Z-a1b2c3d4``."""
    moment = now or utcnow()
    return f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHECKSUM_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha(repo: Path | None = None) -> str | None:
    """Best-effort commit SHA. ``None`` outside a checkout, or with git unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def git_dirty(repo: Path | None = None) -> bool | None:
    """Whether the working tree had uncommitted changes. A dirty run is not reproducible."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    return bool(result.stdout.strip()) if result.returncode == 0 else None


class StageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Artefact(BaseModel):
    """One file a stage produced, with enough detail to detect that it changed."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    bytes: int
    rows: int | None = None

    @classmethod
    def of(cls, path: Path, *, root: Path | None = None, rows: int | None = None) -> Artefact:
        relative = str(path.relative_to(root)) if root is not None else str(path)
        return cls(
            path=relative.replace("\\", "/"),
            sha256=sha256_file(path),
            bytes=path.stat().st_size,
            rows=rows,
        )


class StageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: StageStatus
    started_at: dt.datetime
    finished_at: dt.datetime
    duration_seconds: float
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    artefacts: list[Artefact] = Field(default_factory=list)
    error: str | None = None


class RunManifest(BaseModel):
    """The complete record of one pipeline run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = MANIFEST_SCHEMA_VERSION
    run_id: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    status: StageStatus | None = None
    git_sha: str | None = None
    git_dirty: bool | None = None
    config_digest: str
    requested_stages: list[str] = Field(default_factory=list)
    stages: list[StageRecord] = Field(default_factory=list)

    def stage(self, name: str) -> StageRecord | None:
        return next((record for record in self.stages if record.name == name), None)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class ManifestWriter:
    """Accumulates stage records and writes the manifest after every one.

    Written incrementally on purpose: a run that dies mid-stage still leaves a manifest saying how
    far it got.
    """

    def __init__(
        self,
        *,
        run_id: str,
        config_digest: str,
        runs_dir: Path,
        data_root: Path,
        requested_stages: list[str] | None = None,
        repo: Path | None = None,
    ) -> None:
        self.runs_dir = runs_dir
        self.data_root = data_root
        self.manifest = RunManifest(
            run_id=run_id,
            started_at=utcnow(),
            git_sha=git_sha(repo),
            git_dirty=git_dirty(repo),
            config_digest=config_digest,
            requested_stages=requested_stages or [],
        )
        self.flush()

    @property
    def path(self) -> Path:
        return self.runs_dir / self.manifest.run_id / "manifest.json"

    def record(self, record: StageRecord) -> None:
        self.manifest.stages.append(record)
        self.flush()

    def finish(self, status: StageStatus) -> RunManifest:
        self.manifest.finished_at = utcnow()
        self.manifest.status = status
        self.flush()
        return self.manifest

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.manifest.to_json(), encoding="utf-8")

    def artefact(self, path: Path, *, rows: int | None = None) -> Artefact:
        """Checksum an artefact, with its path recorded relative to the data root."""
        return Artefact.of(path, root=self.data_root, rows=rows)


def read_manifest(path: Path) -> RunManifest:
    return RunManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
