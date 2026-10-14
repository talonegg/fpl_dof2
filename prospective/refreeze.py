#!/usr/bin/env python3
"""Re-freeze the bundle after an approved *harness-only* fix. Deterministic and repeatable.

    python prospective/refreeze.py --reason "..." --at 2026-10-14T03:00:00+00:00

Takes the committed bundle, swaps in every file under ``prospective/harness_patches/`` (paths
relative to ``harness/``), recomputes the manifest exactly as the harness's ``freeze_lib.compute``
does (harness hashes, then each model's ``source_sha256`` over common + model + harness hashes),
records a ``refreezes`` entry (timestamp, reason, old/new hashes), and rewrites the tarball with
the same member order and metadata. Refuses if any model's ``config_sha256`` or
``model_files_sha256`` would change: a harness fix must not touch a model.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "bundle" / "frozen-2026-10-13.tar.gz"
MANIFEST = HERE / "bundle" / "manifest.json"
PATCHES = HERE / "harness_patches"


def canon(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dump(m: dict) -> bytes:
    return json.dumps(m, indent=2, sort_keys=True, default=str).encode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", required=True)
    ap.add_argument("--at", required=True, help="ISO-8601 timestamp recorded in the changelog")
    a = ap.parse_args()

    with tarfile.open(BUNDLE) as t:
        members = [(m, t.extractfile(m).read() if m.isfile() else None) for m in t.getmembers()]
    old = json.loads(MANIFEST.read_text())
    patches = {
        "harness/" + str(p.relative_to(PATCHES)): p.read_bytes()
        for p in sorted(PATCHES.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    new = copy.deepcopy(old)
    changed = {}
    for arc, data in patches.items():
        rel = arc.removeprefix("harness/")
        if rel not in new["harness_files_sha256"]:
            raise SystemExit(f"{rel} is not a manifest harness file")
        before = new["harness_files_sha256"][rel]
        new["harness_files_sha256"][rel] = sha(data)
        if before != sha(data):
            changed[rel] = {"old": before, "new": sha(data)}
    for name, m in new["models"].items():
        allh = {
            **{"repo:" + k: v for k, v in new["common_files_sha256"].items()},
            **{"repo:" + k: v for k, v in m["model_files_sha256"].items()},
            **{"harness:" + k: v for k, v in new["harness_files_sha256"].items()},
        }
        m["source_sha256"] = sha(canon(allh))
        o = old["models"][name]
        if (m["config_sha256"], m["model_files_sha256"]) != (
            o["config_sha256"],
            o["model_files_sha256"],
        ):
            raise SystemExit(f"{name}: model config/files changed; that is a new freeze, not a fix")
    old_body = old["manifest_body_sha256"]
    new.setdefault("refreezes", []).append(
        {
            "at": a.at,
            "reason": a.reason,
            "harness_files": changed,
            "manifest_body_sha256": {"old": old_body},
            "source_sha256": {
                k: {"old": old["models"][k]["source_sha256"], "new": v["source_sha256"]}
                for k, v in new["models"].items()
            },
        }
    )
    body = {k: v for k, v in new.items() if k not in ("frozen_at", "manifest_body_sha256")}
    new["manifest_body_sha256"] = sha(canon(body))
    manifest_bytes = dump(new) + b"\n" if MANIFEST.read_bytes().endswith(b"\n") else dump(new)
    patches["harness/manifest.json"] = manifest_bytes

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as out:
        for m, data in members:
            if m.isfile() and m.name in patches:
                data = patches.pop(m.name)
                m = copy.copy(m)
                m.size = len(data)
            out.addfile(m, io.BytesIO(data) if data is not None else None)
    if patches:
        raise SystemExit(f"patched files not in the bundle: {sorted(patches)}")
    with (
        BUNDLE.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz,
    ):
        gz.write(buf.getvalue())
    MANIFEST.write_bytes(manifest_bytes)
    print(f"manifest_body_sha256 {old_body} -> {new['manifest_body_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
