"""Verify an extracted frozen bundle against its manifest, file by file (no git required).

The harness's own ``verify.py`` also checks the frozen worktree's git HEAD. CI has no checkout of
that commit (the tag is local-only), so this reproduces every *content* check instead: the manifest
body hash, every common/model/harness file hash, and each model's config hash, recomputed both from
the manifest and from the bundled ``models.py``. Content identity is what "unchanged" means here.
"""

from __future__ import annotations

import hashlib
import json
import runpy
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def canon(obj: Any) -> bytes:
    """The harness's canonical JSON (prospective/common.py ``canon``), reproduced exactly."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


@dataclass
class BundleReport:
    manifest_ok: bool
    common_mismatches: list[str] = field(default_factory=list)
    harness_mismatches: list[str] = field(default_factory=list)
    model_problems: dict[str, list[str]] = field(default_factory=dict)

    @property
    def shared_ok(self) -> bool:
        return self.manifest_ok and not self.common_mismatches and not self.harness_mismatches

    def model_ok(self, name: str) -> bool:
        return self.shared_ok and not self.model_problems.get(name)

    def reason(self, name: str) -> str | None:
        if not self.manifest_ok:
            return "frozen manifest was edited"
        if self.common_mismatches:
            return f"frozen code changed: {self.common_mismatches[0]}"
        if self.harness_mismatches:
            return f"frozen harness changed: {self.harness_mismatches[0]}"
        problems = self.model_problems.get(name)
        return problems[0] if problems else None


def manifest_body_ok(manifest: Mapping[str, Any]) -> bool:
    body = {k: v for k, v in manifest.items() if k not in ("frozen_at", "manifest_body_sha256")}
    return sha256_bytes(canon(body)) == manifest.get("manifest_body_sha256")


def bundled_model_configs(harness_root: Path) -> dict[str, Any]:
    """The MODELS registry from the bundled ``prospective/models.py`` (executed in isolation)."""
    ns = runpy.run_path(str(harness_root / "prospective" / "models.py"))
    return {name: m["config"] for name, m in ns["MODELS"].items()}


def verify_bundle(
    frozen_root: Path, harness_root: Path, manifest: Mapping[str, Any]
) -> BundleReport:
    """Every content check verify.py makes, minus the git ones. Never raises on a mismatch."""
    report = BundleReport(manifest_ok=manifest_body_ok(manifest))
    for rel, want in manifest.get("common_files_sha256", {}).items():
        if sha256_file(frozen_root / rel) != want:
            report.common_mismatches.append(rel)
    for rel, want in manifest.get("harness_files_sha256", {}).items():
        if sha256_file(harness_root / rel) != want:
            report.harness_mismatches.append(rel)
    try:
        bundled = bundled_model_configs(harness_root)
    except Exception as exc:  # a broken models.py fails every model, never the run
        bundled = {}
        report.harness_mismatches.append(f"prospective/models.py unreadable ({exc!r})")
    for name, m in manifest.get("models", {}).items():
        problems: list[str] = []
        if sha256_bytes(canon(m.get("config"))) != m.get("config_sha256"):
            problems.append(f"{name}: manifest config does not match its config_sha256")
        if name not in bundled or sha256_bytes(canon(bundled[name])) != m.get("config_sha256"):
            problems.append(f"{name}: bundled models.py config hash differs from the manifest")
        for rel, want in m.get("model_files_sha256", {}).items():
            got = sha256_file(frozen_root / rel)
            if got is None:
                problems.append(f"{name}: frozen input missing: {rel}")
            elif got != want:
                problems.append(f"{name}: frozen input changed: {rel}")
        report.model_problems[name] = problems
    return report
